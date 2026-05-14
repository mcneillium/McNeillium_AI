#!/usr/bin/env python3
"""
McNeillium_AI — ElevenLabs Voice Generator (Phase 11 primary)

Replaces Edge TTS as the default narration engine. Uses the Brian voice
(or any voice configured in ELEVENLABS_VOICE_ID) with the multilingual
v2 model and the studio settings called out in the Phase 11 spec.

Process:
  1. Generate audio + character-level alignment per script section
  2. Convert character alignment to word-level timestamps
  3. Concat all section MP3s via FFmpeg
  4. Save:
       output/audio/latest.mp3
       output/audio/latest_words_elevenlabs.json
       output/audio/captions/segment_NN_<sid>.json (compat with old loader)
  5. Log character usage to the cost tracker

Falls back to Edge TTS only if ELEVENLABS_API_KEY is missing or every
section call fails — Phase 11 makes ElevenLabs the primary path.
"""

import argparse
import base64
import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower().replace("-", "") != "utf8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8",
                                  errors="replace")

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = PROJECT_ROOT / "output" / "scripts" / "latest.json"
AUDIO_DIR = PROJECT_ROOT / "output" / "audio"
CAPTIONS_DIR = AUDIO_DIR / "captions"

sys.path.insert(0, str(PROJECT_ROOT))
from utils import cost_tracker  # noqa: E402

API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "nPczCjzI2devNBz1zQrb")  # Brian
MODEL_ID = "eleven_multilingual_v2"

VOICE_SETTINGS = {
    "stability": 0.4,
    "similarity_boost": 0.75,
    "style": 0.35,
    "use_speaker_boost": True,
}


def _find_ffmpeg():
    r = shutil.which("ffmpeg")
    if r:
        return r
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return "ffmpeg"


FFMPEG = _find_ffmpeg()


def _chars_to_words(characters, starts, ends):
    """Convert ElevenLabs character alignment to word-level entries.

    Each entry: {"text": str, "offset_ms": float, "duration_ms": float}.
    Punctuation is attached to the word it follows (e.g. "word.").
    """
    words = []
    buf = []
    buf_start = None
    buf_end = None
    for ch, s, e in zip(characters, starts, ends):
        if ch.isspace():
            if buf:
                words.append({
                    "text": "".join(buf),
                    "offset_ms": (buf_start or 0.0) * 1000.0,
                    "duration_ms": ((buf_end or buf_start or 0.0)
                                    - (buf_start or 0.0)) * 1000.0,
                })
                buf = []
                buf_start = None
                buf_end = None
        else:
            if buf_start is None:
                buf_start = float(s)
            buf.append(ch)
            buf_end = float(e)
    if buf:
        words.append({
            "text": "".join(buf),
            "offset_ms": (buf_start or 0.0) * 1000.0,
            "duration_ms": ((buf_end or buf_start or 0.0)
                            - (buf_start or 0.0)) * 1000.0,
        })
    return words


def _section_clip(section_text, voice_id, model_id, settings, client):
    """Return (audio_bytes, words). words[].offset_ms is relative to section start."""
    from elevenlabs.types.voice_settings import VoiceSettings

    vs = VoiceSettings(
        stability=settings["stability"],
        similarity_boost=settings["similarity_boost"],
        style=settings["style"],
        use_speaker_boost=settings["use_speaker_boost"],
    )
    resp = client.text_to_speech.convert_with_timestamps(
        voice_id=voice_id,
        text=section_text,
        model_id=model_id,
        output_format="mp3_44100_128",
        voice_settings=vs,
    )
    audio = base64.b64decode(resp.audio_base_64)

    alignment = resp.normalized_alignment or resp.alignment
    if alignment is None:
        words = []
    else:
        words = _chars_to_words(
            alignment.characters,
            alignment.character_start_times_seconds,
            alignment.character_end_times_seconds,
        )
    return audio, words


def _ffprobe_duration_ms(path):
    cmd = ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
           "-of", "csv=p=0", str(path)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return float(r.stdout.strip()) * 1000.0
    except Exception:
        return 0.0


def run(script_path):
    if not API_KEY:
        print("❌ ELEVENLABS_API_KEY not set in .env")
        return False
    if not Path(script_path).exists():
        print(f"❌ Script not found: {script_path}")
        return False

    from elevenlabs.client import ElevenLabs
    client = ElevenLabs(api_key=API_KEY)

    with open(script_path, encoding="utf-8") as f:
        script = json.load(f)
    sections = script.get("sections", [])
    title = script.get("title", "(untitled)")
    if not sections:
        print("❌ No sections to narrate")
        return False

    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    CAPTIONS_DIR.mkdir(parents=True, exist_ok=True)
    temp_dir = AUDIO_DIR / "_eleven_temp"
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir(parents=True)

    section_mp3s = []
    merged_words = []
    running_offset_ms = 0.0
    total_chars = 0
    failures = []

    print(f"🎙  ElevenLabs voice: {VOICE_ID}  model={MODEL_ID}")

    for idx, sec in enumerate(sections):
        sid = sec.get("id", f"section_{idx}")
        text = sec.get("narration", "").strip()
        if not text:
            continue
        total_chars += len(text)
        print(f"  [{idx + 1}/{len(sections)}] {sid:14s} {len(text)} chars",
              end=" ")

        try:
            audio_bytes, words = _section_clip(
                text, VOICE_ID, MODEL_ID, VOICE_SETTINGS, client,
            )
        except Exception as e:
            print(f"❌ ({e})")
            failures.append((sid, str(e)))
            continue

        seg_path = temp_dir / f"section_{idx:02d}_{sid}.mp3"
        seg_path.write_bytes(audio_bytes)
        section_mp3s.append(seg_path)
        seg_dur_ms = _ffprobe_duration_ms(seg_path)
        print(f"→ {seg_dur_ms / 1000.0:5.1f}s  {len(words)} words")

        # Save per-section captions for backwards compat with the old loader
        per_section_words = [
            {
                "text": w["text"],
                "offset_ms": w["offset_ms"],
                "duration_ms": w["duration_ms"],
            }
            for w in words
        ]
        with open(CAPTIONS_DIR / f"segment_{idx:02d}_{sid}.json", "w",
                  encoding="utf-8") as f:
            json.dump(per_section_words, f, indent=2)

        # Merge into absolute timeline
        for w in words:
            merged_words.append({
                "text": w["text"],
                "offset_ms": w["offset_ms"] + running_offset_ms,
                "duration_ms": w["duration_ms"],
                "section_id": sid,
            })
        running_offset_ms += seg_dur_ms

    if not section_mp3s:
        print("❌ No sections produced audio")
        return False

    # Concat with ffmpeg concat demuxer
    concat_list = temp_dir / "concat.txt"
    with open(concat_list, "w") as f:
        for p in section_mp3s:
            f.write(f"file '{p.resolve()}'\n")

    final_mp3 = AUDIO_DIR / "latest.mp3"
    cmd = [
        FFMPEG, "-y", "-f", "concat", "-safe", "0",
        "-i", str(concat_list),
        "-c:a", "libmp3lame", "-q:a", "2",
        str(final_mp3),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"❌ Concat failed: {r.stderr[-300:]}")
        return False

    # Word timestamp dumps
    eleven_words_path = AUDIO_DIR / "latest_words_elevenlabs.json"
    with open(eleven_words_path, "w", encoding="utf-8") as f:
        json.dump({
            "title": title,
            "voice_id": VOICE_ID,
            "model_id": MODEL_ID,
            "total_words": len(merged_words),
            "words": merged_words,
        }, f, indent=2)

    shutil.rmtree(temp_dir, ignore_errors=True)

    print(f"  ✅ Audio:      {final_mp3}")
    print(f"  ✅ Timestamps: {eleven_words_path}  ({len(merged_words)} words)")
    print(f"  📝 Total characters narrated: {total_chars}")
    cost_tracker.record_eleven_chars(title, total_chars)

    if failures:
        print(f"  ⚠️  {len(failures)} section(s) failed:")
        for sid, err in failures:
            print(f"      - {sid}: {err[:80]}")
    return True


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--script", default=str(SCRIPT_PATH))
    args = p.parse_args()
    ok = run(args.script)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
