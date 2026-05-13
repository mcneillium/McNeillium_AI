#!/usr/bin/env python3
"""
McNeillium_AI — Voice Generator v2
Edge TTS narration with word-level timestamps for animated captions.
"""

import argparse
import asyncio
import io
import json
import sys
from datetime import datetime
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower().replace("-", "") != "utf8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import edge_tts
import yaml

MAX_RETRIES = 15
RETRY_DELAY = 15
SEGMENT_DELAY = 8

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.yaml"
SCRIPT_DIR = PROJECT_ROOT / "output" / "scripts"
AUDIO_DIR = PROJECT_ROOT / "output" / "audio"
CAPTIONS_DIR = AUDIO_DIR / "captions"


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def load_script(script_path: str) -> dict:
    """Load a script JSON file."""
    with open(script_path, encoding="utf-8") as f:
        return json.load(f)


def build_narration_text(script_data: dict) -> str:
    """Extract and combine all narration text from script sections."""
    sections = script_data.get("sections", [])
    narration_parts = []

    for section in sections:
        narration = section.get("narration", "").strip()
        if narration:
            narration_parts.append(narration)

    return "\n\n".join(narration_parts)


CAPTION_STREAM_RETRIES = 3
CAPTION_RETRY_DELAY = 5


async def _stream_with_captions(communicate, audio_path: Path) -> list[dict]:
    """Stream TTS audio to file and capture word-level timestamps."""
    words = []
    with open(audio_path, "wb") as f:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                words.append({
                    "text": chunk["text"],
                    "offset_ms": chunk["offset"] / 10_000,
                    "duration_ms": chunk["duration"] / 10_000,
                })
    return words


def _whisper_fallback(audio_path: str) -> list[dict]:
    """Extract word-level timestamps from audio using whisper-timestamped."""
    try:
        import whisper_timestamped as whisper
    except ImportError:
        print("        ⚠  whisper-timestamped not installed, skipping caption fallback")
        return []

    print("        🔄 Whisper fallback: transcribing audio for word timestamps...")
    try:
        model = whisper.load_model("base", device="cpu")
        result = whisper.transcribe(model, audio_path)
        words = []
        for seg in result.get("segments", []):
            for w in seg.get("words", []):
                words.append({
                    "text": w["text"].strip(),
                    "offset_ms": w["start"] * 1000,
                    "duration_ms": (w["end"] - w["start"]) * 1000,
                })
        print(f"        ✅ Whisper extracted {len(words)} word timestamps")
        return words
    except Exception as e:
        print(f"        ⚠  Whisper fallback failed: {e}")
        return []


async def _generate_segment_with_captions(
    text: str, voice_id: str, rate: str, pitch: str, volume: str,
    segment_file: Path, section_id: str
) -> tuple[Path, list[dict]]:
    """Generate a single audio segment with robust caption capture."""
    words = []

    for attempt in range(MAX_RETRIES):
        try:
            communicate = edge_tts.Communicate(
                text=text, voice=voice_id, rate=rate, pitch=pitch, volume=volume,
            )
            words = await _stream_with_captions(communicate, segment_file)
            break
        except (ConnectionResetError, OSError, Exception) as e:
            if attempt < MAX_RETRIES - 1:
                wait = RETRY_DELAY * (attempt + 1)
                print(f"    ⚠  Connection error, retrying in {wait}s... ({e.__class__.__name__})")
                await asyncio.sleep(wait)
            else:
                raise

    if not words and segment_file.exists() and segment_file.stat().st_size > 1000:
        print(f"        ⚠  Audio OK but 0 word timestamps — retrying stream for captions...")
        for cap_attempt in range(CAPTION_STREAM_RETRIES):
            try:
                await asyncio.sleep(CAPTION_RETRY_DELAY * (cap_attempt + 1))
                communicate = edge_tts.Communicate(
                    text=text, voice=voice_id, rate=rate, pitch=pitch, volume=volume,
                )
                temp_audio = segment_file.parent / f"_cap_retry_{section_id}.mp3"
                words = await _stream_with_captions(communicate, temp_audio)
                temp_audio.unlink(missing_ok=True)
                if words:
                    print(f"        ✅ Caption retry {cap_attempt + 1} got {len(words)} words")
                    break
            except Exception:
                continue

    if not words and segment_file.exists() and segment_file.stat().st_size > 1000:
        words = _whisper_fallback(str(segment_file))

    return segment_file, words


async def generate_audio_segments(
    script_data: dict, config: dict, output_dir: Path
) -> tuple[list[Path], list[list[dict]]]:
    """Generate audio segments with word-level caption data."""
    voice_config = config.get("voice", {})
    voice_id = voice_config.get("voice_id", "en-GB-RyanNeural")
    rate = voice_config.get("rate", "+0%")
    pitch = voice_config.get("pitch", "+0Hz")
    volume = voice_config.get("volume", "+0%")

    sections = script_data.get("sections", [])
    segment_paths = []
    all_captions = []

    CAPTIONS_DIR.mkdir(parents=True, exist_ok=True)

    for i, section in enumerate(sections):
        narration = section.get("narration", "").strip()
        if not narration:
            continue

        section_id = section.get("id", f"section_{i}")
        segment_file = output_dir / f"segment_{i:02d}_{section_id}.mp3"
        caption_file = CAPTIONS_DIR / f"segment_{i:02d}_{section_id}.json"

        if segment_file.exists() and segment_file.stat().st_size > 1000:
            if caption_file.exists():
                with open(caption_file, encoding="utf-8") as cf:
                    existing = json.load(cf)
                if existing:
                    print(f"    ✅  Skipping (already exists): {section_id}")
                    segment_paths.append(segment_file)
                    all_captions.append(existing)
                    continue

        print(f"    🎙  Generating audio + captions for: {section_id}")

        _, words = await _generate_segment_with_captions(
            narration, voice_id, rate, pitch, volume, segment_file, section_id
        )

        with open(caption_file, "w", encoding="utf-8") as cf:
            json.dump(words, cf, indent=2)
        print(f"        {len(words)} word timestamps captured")

        segment_paths.append(segment_file)
        all_captions.append(words)
        await asyncio.sleep(SEGMENT_DELAY)

    return segment_paths, all_captions


async def generate_full_audio(script_data: dict, config: dict) -> Path:
    """Generate narration audio with word-level caption data."""
    voice_config = config.get("voice", {})
    voice_id = voice_config.get("voice_id", "en-GB-RyanNeural")
    rate = voice_config.get("rate", "+0%")
    pitch = voice_config.get("pitch", "+0Hz")
    volume = voice_config.get("volume", "+0%")

    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    CAPTIONS_DIR.mkdir(parents=True, exist_ok=True)

    full_narration = build_narration_text(script_data)

    title = script_data.get("title", "untitled")
    safe_title = "".join(c if c.isalnum() or c in " -_" else "" for c in title)
    safe_title = safe_title.strip().replace(" ", "_")[:60]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    output_file = AUDIO_DIR / f"{timestamp}_{safe_title}.mp3"
    latest_file = AUDIO_DIR / "latest.mp3"

    print(f"    🎙  Voice: {voice_id}")
    print(f"    📢  Rate: {rate} | Pitch: {pitch}")

    segments_dir = AUDIO_DIR / "segments"
    segments_dir.mkdir(parents=True, exist_ok=True)
    segment_paths, segment_captions = await generate_audio_segments(
        script_data, config, segments_dir
    )

    print(f"    🎙  Generating full narration audio...")
    await asyncio.sleep(SEGMENT_DELAY)
    _, full_words = await _generate_segment_with_captions(
        full_narration, voice_id, rate, pitch, volume, output_file, "full"
    )

    import shutil
    shutil.copy2(output_file, latest_file)

    full_caption_file = CAPTIONS_DIR / "full_captions.json"
    with open(full_caption_file, "w", encoding="utf-8") as f:
        json.dump(full_words, f, indent=2)
    print(f"    📝  {len(full_words)} total word timestamps saved")

    manifest = {
        "full_audio": str(output_file),
        "full_captions": str(full_caption_file),
        "segments": [
            {
                "index": i,
                "section_id": script_data["sections"][i].get("id", f"section_{i}"),
                "path": str(p),
                "captions": str(CAPTIONS_DIR / f"segment_{i:02d}_{script_data['sections'][i].get('id', f'section_{i}')}.json"),
            }
            for i, p in enumerate(segment_paths)
        ],
        "voice": voice_id,
        "generated_at": datetime.now().isoformat(),
    }
    manifest_path = AUDIO_DIR / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    return output_file


def main():
    parser = argparse.ArgumentParser(description="Generate voice narration from script")
    parser.add_argument(
        "--script", "-s",
        default=str(SCRIPT_DIR / "latest.json"),
        help="Path to script JSON file",
    )
    args = parser.parse_args()

    config = load_config()
    script_data = load_script(args.script)

    print("\n🎤 McNeillium_AI — Voice Generator")
    print("=" * 50)
    print(f"  Script: {script_data.get('title', 'Untitled')}")

    output_file = asyncio.run(generate_full_audio(script_data, config))

    print(f"\n  ✅ Audio saved: {output_file}")
    return output_file


if __name__ == "__main__":
    main()
