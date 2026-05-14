#!/usr/bin/env python3
"""
McNeillium_AI — AssemblyAI Caption Verifier (Phase 11)

Sends the generated narration to AssemblyAI for ground-truth ASR, then
reconciles AssemblyAI's word timestamps against ElevenLabs' (or Edge
TTS') reported timings. Where the alignment is confident AND the drift
exceeds 100ms, AssemblyAI's reading wins — it actually heard the audio.

Output: output/audio/latest_words_verified.json — the new canonical
captions source consumed by captions_v2.py and captions.py via the
existing load_verified_words() helper.

Sanity bounds (carried over from the Whisper validator):
  - require ≥30% aligned word coverage before applying any replacements
  - cap per-word drift correction at 1500ms (anything bigger is almost
    certainly an alignment error, not real drift)

Cost: AssemblyAI Universal Speech runs ~$0.37/hour audio. A 6-minute
narration costs ~$0.04. Logged to the cost tracker.
"""

import argparse
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
from difflib import SequenceMatcher
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower().replace("-", "") != "utf8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8",
                                  errors="replace")

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from utils import cost_tracker  # noqa: E402

AUDIO_DIR = PROJECT_ROOT / "output" / "audio"
DEFAULT_AUDIO = AUDIO_DIR / "latest.mp3"
DEFAULT_ELEVEN_WORDS = AUDIO_DIR / "latest_words_elevenlabs.json"
DEFAULT_VERIFIED_OUT = AUDIO_DIR / "latest_words_verified.json"
REPORT_DIR = PROJECT_ROOT / "knowledge_base" / "reviews"

API_KEY = os.getenv("ASSEMBLYAI_API_KEY", "")

DRIFT_THRESHOLD_MS = 100
DRIFT_MAX_TRUSTED_MS = 1500
MIN_ALIGNMENT_RATIO = 0.30


def _normalise(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def _align(tts_words, asr_words):
    """Greedy alignment via SequenceMatcher on normalised tokens."""
    tts_norm = [_normalise(w["text"]) for w in tts_words]
    asr_norm = [_normalise(w["text"]) for w in asr_words]
    sm = SequenceMatcher(a=tts_norm, b=asr_norm, autojunk=False)
    pairs = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                pairs.append((i1 + k, j1 + k))
    return pairs


def _ffprobe_duration_s(path):
    cmd = ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
           "-of", "csv=p=0", str(path)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except Exception:
        return 0.0


def _transcribe(audio_path):
    """Run AssemblyAI ASR. Returns word list with offset_ms / duration_ms."""
    import assemblyai as aai

    aai.settings.api_key = API_KEY
    config = aai.TranscriptionConfig(
        speech_model=aai.SpeechModel.universal,
        punctuate=True,
        format_text=True,
    )
    transcriber = aai.Transcriber(config=config)
    print(f"    🎧 AssemblyAI transcribing {audio_path}...")
    t0 = time.time()
    transcript = transcriber.transcribe(str(audio_path))
    elapsed = time.time() - t0

    if transcript.status == aai.TranscriptStatus.error:
        raise RuntimeError(f"AssemblyAI error: {transcript.error}")

    words = []
    for w in transcript.words or []:
        words.append({
            "text": w.text,
            "offset_ms": float(w.start),
            "duration_ms": float(w.end - w.start),
            "confidence": float(getattr(w, "confidence", 1.0)),
        })
    print(f"    ✅ {len(words)} words in {elapsed:.1f}s wall time")
    return words


def run(audio_path, eleven_words_path, out_path,
        drift_ms=DRIFT_THRESHOLD_MS):
    if not API_KEY:
        print("⏭  ASSEMBLYAI_API_KEY missing — skipping verification")
        return False
    audio_path = Path(audio_path)
    if not audio_path.exists():
        print(f"❌ Audio missing: {audio_path}")
        return False
    if not Path(eleven_words_path).exists():
        print(f"❌ ElevenLabs words missing: {eleven_words_path}")
        return False

    with open(eleven_words_path, encoding="utf-8") as f:
        eleven_data = json.load(f)
    title = eleven_data.get("title", "(untitled)")
    tts_words = eleven_data.get("words", [])
    if not tts_words:
        print("❌ No TTS words to verify against")
        return False

    print(f"🔉 AssemblyAI Verifier — {len(tts_words)} TTS words to check")

    try:
        asr_words = _transcribe(audio_path)
    except Exception as e:
        print(f"❌ AssemblyAI transcription failed: {e}")
        return False

    audio_dur_s = _ffprobe_duration_s(audio_path)
    cost_tracker.record_assemblyai_seconds(title, audio_dur_s)

    verified = [dict(w) for w in tts_words]
    pairs = _align(tts_words, asr_words)
    alignment_ratio = len(pairs) / max(1, len(tts_words))
    print(f"    🔗 aligned {len(pairs)} of {len(tts_words)} TTS words "
          f"({alignment_ratio:.0%})")

    drift_count = 0
    replaced = 0
    bogus = 0
    report_lines = ["# AssemblyAI Sync Verification", ""]
    notes = []

    if alignment_ratio < MIN_ALIGNMENT_RATIO:
        print(f"    ⏭  alignment too sparse — passing TTS through unchanged")
        score = 6
        notes.append(
            f"Alignment ratio {alignment_ratio:.0%} below threshold; "
            "no replacements made."
        )
    else:
        for tts_i, asr_i in pairs:
            tts_t = tts_words[tts_i]["offset_ms"]
            asr_t = asr_words[asr_i]["offset_ms"]
            drift = abs(tts_t - asr_t)
            if drift > drift_ms and drift <= DRIFT_MAX_TRUSTED_MS:
                drift_count += 1
                verified[tts_i]["offset_ms"] = asr_t
                verified[tts_i]["duration_ms"] = (
                    asr_words[asr_i]["duration_ms"]
                )
                verified[tts_i]["verified_by"] = "assemblyai"
                replaced += 1
                if drift_count <= 10:
                    notes.append(
                        f"- drift {drift:.0f}ms on `{tts_words[tts_i]['text']}` "
                        f"(eleven {tts_t:.0f} → asr {asr_t:.0f})"
                    )
            elif drift > DRIFT_MAX_TRUSTED_MS:
                bogus += 1
            else:
                verified[tts_i]["verified_by"] = "elevenlabs"
        score = max(0, 10 - int(10 * drift_count / max(1, len(pairs))))
        if bogus:
            notes.append(
                f"Ignored {bogus} aligned word(s) with drift > "
                f"{DRIFT_MAX_TRUSTED_MS}ms (likely alignment errors)."
            )

    report_lines.append(
        f"Total TTS words: {len(tts_words)} | "
        f"Drift events: {drift_count} | Replaced: {replaced} | "
        f"Sync score: {score}/10\n"
    )
    report_lines.extend(notes)

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_DIR / "assemblyai_verification.md"
    report_path.write_text("\n".join(report_lines), encoding="utf-8")
    print(f"    📝 Report: {report_path}")

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "sync_score": score,
            "drift_count": drift_count,
            "replaced": replaced,
            "asr_source": "assemblyai",
            "words": verified,
        }, f, indent=2)
    print(f"    💾 Verified: {out_path}  (sync_score={score}/10)")
    return True


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--audio", default=str(DEFAULT_AUDIO))
    p.add_argument("--eleven-words", default=str(DEFAULT_ELEVEN_WORDS))
    p.add_argument("--out", default=str(DEFAULT_VERIFIED_OUT))
    p.add_argument("--drift-ms", type=int, default=DRIFT_THRESHOLD_MS)
    args = p.parse_args()
    ok = run(args.audio, args.eleven_words, args.out,
             drift_ms=args.drift_ms)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
