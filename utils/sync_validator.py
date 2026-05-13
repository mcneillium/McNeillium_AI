#!/usr/bin/env python3
"""
McNeillium_AI — Agent 26: Audio-Visual Sync Validator

Re-transcribes the generated narration audio with whisper-timestamped and
compares the word timestamps to Edge TTS's stored timestamps. If drift on
any aligned word exceeds 200ms, the Whisper timestamps replace the TTS
ones for that word and the captions burn against the verified file.

Output: output/audio/latest_words_verified.json

GRACEFUL DEGRADATION:
  If whisper-timestamped (or its torch backend) is unavailable, the
  validator copies the merged Edge TTS timestamps through unchanged and
  records that no verification was performed. The pipeline continues
  with the TTS-only captions, so a missing whisper install does not
  break video production.
"""

import argparse
import json
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
AUDIO_DIR = PROJECT_ROOT / "output" / "audio"
CAPTIONS_DIR = AUDIO_DIR / "captions"
SCRIPT_PATH = PROJECT_ROOT / "output" / "scripts" / "latest.json"
VERIFIED_OUT = AUDIO_DIR / "latest_words_verified.json"
REPORT_DIR = PROJECT_ROOT / "knowledge_base" / "reviews"

DRIFT_THRESHOLD_MS = 200


def _whisper_available():
    try:
        import whisper_timestamped  # noqa: F401
        return True
    except Exception:
        return False


def _load_edge_tts_words(script_path, captions_dir):
    """Merge per-section Edge TTS caption JSONs into one absolute-timestamped list.

    Returns the merged words with offset_ms expressed relative to the start
    of the narration audio (NOT the final video — the video adds intro/logo).
    """
    if not Path(script_path).exists():
        return []
    with open(script_path, encoding="utf-8") as f:
        script = json.load(f)

    sections = script.get("sections", [])
    cap_dir = Path(captions_dir)
    if not cap_dir.exists():
        return []

    merged = []
    running_offset = 0.0
    for idx, sec in enumerate(sections):
        sid = sec.get("id", f"section_{idx}")
        cap_file = cap_dir / f"segment_{idx:02d}_{sid}.json"
        if not cap_file.exists():
            continue
        try:
            with open(cap_file, encoding="utf-8") as f:
                words = json.load(f)
        except Exception:
            continue
        if not words:
            continue

        for w in words:
            merged.append({
                "text": w["text"],
                "offset_ms": float(w["offset_ms"]) + running_offset,
                "duration_ms": float(w["duration_ms"]),
                "section_id": sid,
            })
        if merged:
            last = merged[-1]
            running_offset = last["offset_ms"] + last["duration_ms"]

    return merged


def _normalise(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def _align_words(tts_words, whisper_words):
    """Greedy alignment using normalised tokens and SequenceMatcher.

    Returns a list of (tts_idx, whisper_idx) tuples for matched words.
    """
    tts_norm = [_normalise(w["text"]) for w in tts_words]
    wh_norm = [_normalise(w["text"]) for w in whisper_words]
    sm = SequenceMatcher(a=tts_norm, b=wh_norm, autojunk=False)
    pairs = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                pairs.append((i1 + k, j1 + k))
    return pairs


def _run_whisper(audio_path):
    """Return Whisper's word list as [{"text", "offset_ms", "duration_ms"}, ...]."""
    import whisper_timestamped as whisper
    model_name = "tiny"
    print(f"    🧠 Loading Whisper model: {model_name}")
    model = whisper.load_model(model_name)
    print(f"    🎧 Transcribing {audio_path} ...")
    result = whisper.transcribe(model, str(audio_path), language="en")
    words = []
    for seg in result.get("segments", []):
        for w in seg.get("words", []):
            text = (w.get("text") or "").strip()
            if not text:
                continue
            start = float(w.get("start", 0.0)) * 1000.0
            end = float(w.get("end", start / 1000.0)) * 1000.0
            words.append({
                "text": text,
                "offset_ms": start,
                "duration_ms": max(10.0, end - start),
            })
    return words


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

def run(audio_path, script_path, captions_dir, out_path,
        drift_ms=DRIFT_THRESHOLD_MS):
    audio_path = Path(audio_path)
    if not audio_path.exists():
        print(f"❌ Audio not found: {audio_path}")
        return False

    tts_words = _load_edge_tts_words(script_path, captions_dir)
    if not tts_words:
        print(f"❌ No Edge TTS word timestamps found in {captions_dir}")
        return False

    has_whisper = _whisper_available()
    print(f"🔉 Sync Validator — Whisper available: {has_whisper}")

    report_lines = ["# Sync Validation Report", ""]
    drift_count = 0
    replaced_count = 0

    verified_words = [dict(w) for w in tts_words]

    if has_whisper:
        try:
            wh_words = _run_whisper(audio_path)
        except Exception as e:
            print(f"    ⚠️  Whisper transcription failed: {e}")
            wh_words = []
            report_lines.append(f"Whisper failed: {e}")

        if wh_words:
            pairs = _align_words(tts_words, wh_words)
            print(f"    🔗 Aligned {len(pairs)} of "
                  f"{min(len(tts_words), len(wh_words))} candidate words")
            for tts_i, wh_i in pairs:
                tts_t = tts_words[tts_i]["offset_ms"]
                wh_t = wh_words[wh_i]["offset_ms"]
                drift = abs(tts_t - wh_t)
                if drift > drift_ms:
                    drift_count += 1
                    verified_words[tts_i]["offset_ms"] = wh_t
                    verified_words[tts_i]["duration_ms"] = (
                        wh_words[wh_i]["duration_ms"]
                    )
                    verified_words[tts_i]["verified_by"] = "whisper"
                    replaced_count += 1
                    if drift_count <= 8:
                        report_lines.append(
                            f"- drift {drift:.0f}ms on "
                            f"`{tts_words[tts_i]['text']}` "
                            f"(tts {tts_t:.0f} → wh {wh_t:.0f})"
                        )
                else:
                    verified_words[tts_i]["verified_by"] = "tts"

            score = max(
                0,
                10 - int(10 * drift_count / max(1, len(pairs))),
            )
        else:
            score = 7
            report_lines.append("No Whisper transcript — using TTS as-is.")
    else:
        score = 7
        report_lines.append(
            "whisper-timestamped not installed; sync validation skipped. "
            "Edge TTS timestamps passed through unchanged."
        )
        print("    ⏭  Whisper unavailable — passing TTS timestamps through.")

    report_lines.insert(1, (
        f"Total TTS words: {len(tts_words)} | "
        f"Drift events: {drift_count} | "
        f"Replaced: {replaced_count} | "
        f"Sync score: {score}/10\n"
    ))

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_DIR / "sync_validation.md"
    report_path.write_text("\n".join(report_lines), encoding="utf-8")
    print(f"📝 Report: {report_path}")

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "sync_score": score,
            "drift_count": drift_count,
            "replaced": replaced_count,
            "whisper_used": has_whisper,
            "words": verified_words,
        }, f, indent=2)
    print(f"💾 Verified timestamps → {out_path}")
    return True


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--audio", default=str(AUDIO_DIR / "latest.mp3"))
    p.add_argument("--script", default=str(SCRIPT_PATH))
    p.add_argument("--captions-dir", default=str(CAPTIONS_DIR))
    p.add_argument("--out", default=str(VERIFIED_OUT))
    p.add_argument("--drift-ms", type=int, default=DRIFT_THRESHOLD_MS)
    args = p.parse_args()
    ok = run(args.audio, args.script, args.captions_dir, args.out,
             drift_ms=args.drift_ms)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
