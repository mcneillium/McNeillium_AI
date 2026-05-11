#!/usr/bin/env python3
"""
McNeillium_AI — Voice Generator
Uses Edge TTS to convert script narration into natural-sounding audio.
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

# Resolve paths relative to project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.yaml"
SCRIPT_DIR = PROJECT_ROOT / "output" / "scripts"
AUDIO_DIR = PROJECT_ROOT / "output" / "audio"


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


async def generate_audio_segments(
    script_data: dict, config: dict, output_dir: Path
) -> list[Path]:
    """Generate individual audio segments for each section."""
    voice_config = config.get("voice", {})
    voice_id = voice_config.get("voice_id", "en-GB-RyanNeural")
    rate = voice_config.get("rate", "+0%")
    pitch = voice_config.get("pitch", "+0Hz")
    volume = voice_config.get("volume", "+0%")

    sections = script_data.get("sections", [])
    segment_paths = []

    for i, section in enumerate(sections):
        narration = section.get("narration", "").strip()
        if not narration:
            continue

        section_id = section.get("id", f"section_{i}")
        segment_file = output_dir / f"segment_{i:02d}_{section_id}.mp3"

        if segment_file.exists() and segment_file.stat().st_size > 1000:
            print(f"    ✅  Skipping (already exists): {section_id}")
            segment_paths.append(segment_file)
            continue

        print(f"    🎙  Generating audio for: {section_id}")

        for attempt in range(MAX_RETRIES):
            try:
                communicate = edge_tts.Communicate(
                    text=narration,
                    voice=voice_id,
                    rate=rate,
                    pitch=pitch,
                    volume=volume,
                )
                await communicate.save(str(segment_file))
                break
            except (ConnectionResetError, OSError, Exception) as e:
                if attempt < MAX_RETRIES - 1:
                    wait = RETRY_DELAY * (attempt + 1)
                    print(f"    ⚠  Connection error, retrying in {wait}s... ({e.__class__.__name__})")
                    await asyncio.sleep(wait)
                else:
                    raise

        segment_paths.append(segment_file)
        await asyncio.sleep(SEGMENT_DELAY)

    return segment_paths


async def generate_full_audio(script_data: dict, config: dict) -> Path:
    """Generate the complete narration audio file."""
    voice_config = config.get("voice", {})
    voice_id = voice_config.get("voice_id", "en-GB-RyanNeural")
    rate = voice_config.get("rate", "+0%")
    pitch = voice_config.get("pitch", "+0Hz")
    volume = voice_config.get("volume", "+0%")

    AUDIO_DIR.mkdir(parents=True, exist_ok=True)

    # Build full narration with pauses between sections
    full_narration = build_narration_text(script_data)

    # Generate the combined audio
    title = script_data.get("title", "untitled")
    safe_title = "".join(c if c.isalnum() or c in " -_" else "" for c in title)
    safe_title = safe_title.strip().replace(" ", "_")[:60]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    output_file = AUDIO_DIR / f"{timestamp}_{safe_title}.mp3"
    latest_file = AUDIO_DIR / "latest.mp3"

    print(f"    🎙  Voice: {voice_id}")
    print(f"    📢  Rate: {rate} | Pitch: {pitch}")

    # Also generate individual segments for video sync
    segments_dir = AUDIO_DIR / "segments"
    segments_dir.mkdir(parents=True, exist_ok=True)
    segment_paths = await generate_audio_segments(script_data, config, segments_dir)

    # Generate full combined audio
    print(f"    🎙  Generating full narration audio...")
    await asyncio.sleep(SEGMENT_DELAY)
    for attempt in range(MAX_RETRIES):
        try:
            communicate = edge_tts.Communicate(
                text=full_narration,
                voice=voice_id,
                rate=rate,
                pitch=pitch,
                volume=volume,
            )
            await communicate.save(str(output_file))
            break
        except (ConnectionResetError, OSError, Exception) as e:
            if attempt < MAX_RETRIES - 1:
                wait = RETRY_DELAY * (attempt + 1)
                print(f"    ⚠  Connection error, retrying in {wait}s... ({e.__class__.__name__})")
                await asyncio.sleep(wait)
            else:
                raise

    # Copy as latest
    import shutil
    shutil.copy2(output_file, latest_file)

    # Save segment manifest for video assembly
    manifest = {
        "full_audio": str(output_file),
        "segments": [
            {
                "index": i,
                "section_id": script_data["sections"][i].get("id", f"section_{i}"),
                "path": str(p),
            }
            for i, p in enumerate(segment_paths)
        ],
        "voice": voice_id,
        "generated_at": datetime.now().isoformat(),
    }
    manifest_path = AUDIO_DIR / "manifest.json"
    with open(manifest_path, "w") as f:
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
