#!/usr/bin/env python3
"""
McNeillium_AI — Video Generator
Creates screen-recording style videos with typing animations and narration.
Uses Pillow for frame rendering and FFmpeg for assembly.
"""

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import textwrap
from datetime import datetime
from pathlib import Path

import yaml
from PIL import Image, ImageDraw, ImageFont
from mutagen.mp3 import MP3

# Resolve paths relative to project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.yaml"
SCRIPT_DIR = PROJECT_ROOT / "output" / "scripts"
AUDIO_DIR = PROJECT_ROOT / "output" / "audio"
VIDEO_DIR = PROJECT_ROOT / "output" / "videos"


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def load_script(script_path: str) -> dict:
    with open(script_path, encoding="utf-8") as f:
        return json.load(f)


def get_audio_duration(audio_path: str) -> float:
    """Get duration of an MP3 file in seconds."""
    audio = MP3(audio_path)
    return audio.info.length


def get_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Get a monospace font. Falls back to default if custom not found."""
    if bold:
        font_paths = [
            "C:/Windows/Fonts/consolab.ttf",
            "C:/Windows/Fonts/courbd.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf",
        ]
    else:
        font_paths = [
            "C:/Windows/Fonts/consola.ttf",
            "C:/Windows/Fonts/cour.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
        ]

    for fp in font_paths:
        if os.path.exists(fp):
            return ImageFont.truetype(fp, size)

    return ImageFont.load_default()


def hex_to_rgb(hex_colour: str) -> tuple:
    """Convert hex colour string to RGB tuple."""
    hex_colour = hex_colour.lstrip("#")
    return tuple(int(hex_colour[i : i + 2], 16) for i in (0, 2, 4))


def create_frame(
    width: int,
    height: int,
    config: dict,
    heading: str = "",
    body_lines: list[str] = None,
    progress: float = 0.0,
    show_cursor: bool = True,
    section_num: int = 0,
    total_sections: int = 1,
    channel_name: str = "McNeillium_AI",
) -> Image.Image:
    """Render a single video frame in screen-recording style."""
    vc = config.get("video", {})
    bg_colour = hex_to_rgb(vc.get("background_colour", "#0d1117"))
    text_colour = hex_to_rgb(vc.get("text_colour", "#e6edf3"))
    accent_colour = hex_to_rgb(vc.get("accent_colour", "#58a6ff"))
    heading_colour = hex_to_rgb(vc.get("heading_colour", "#ff7b72"))
    code_colour = hex_to_rgb(vc.get("code_colour", "#7ee787"))
    padding = vc.get("padding", 80)

    img = Image.new("RGB", (width, height), bg_colour)
    draw = ImageDraw.Draw(img)

    # ── Title bar (simulated window chrome) ──
    title_bar_height = 40
    title_bar_colour = tuple(min(c + 15, 255) for c in bg_colour)
    draw.rectangle([0, 0, width, title_bar_height], fill=title_bar_colour)

    # Window control dots
    dot_y = title_bar_height // 2
    for i, colour in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        draw.ellipse(
            [15 + i * 22, dot_y - 6, 15 + i * 22 + 12, dot_y + 6], fill=colour
        )

    # Window title
    title_font = get_font(14)
    draw.text(
        (width // 2, dot_y),
        f"  {channel_name} — Terminal",
        fill=text_colour,
        font=title_font,
        anchor="mm",
    )

    # ── Progress bar at top ──
    bar_y = title_bar_height
    bar_height = 3
    draw.rectangle([0, bar_y, width, bar_y + bar_height], fill=(30, 30, 30))
    draw.rectangle(
        [0, bar_y, int(width * progress), bar_y + bar_height], fill=accent_colour
    )

    # ── Section indicator (top right) ──
    indicator_font = get_font(16)
    section_text = f"[{section_num}/{total_sections}]"
    draw.text(
        (width - padding, title_bar_height + 20),
        section_text,
        fill=tuple(c // 2 for c in text_colour),
        font=indicator_font,
    )

    # ── Heading ──
    content_top = title_bar_height + bar_height + 40
    if heading:
        heading_font = get_font(vc.get("heading_font_size", 52), bold=True)
        # Draw a subtle accent line
        draw.rectangle(
            [padding, content_top, padding + 4, content_top + 50], fill=accent_colour
        )
        draw.text(
            (padding + 20, content_top),
            f"# {heading}",
            fill=heading_colour,
            font=heading_font,
        )
        content_top += 80

    # ── Body text (typing effect — lines appear based on progress) ──
    if body_lines:
        body_font = get_font(vc.get("font_size", 36))
        line_height = int(vc.get("font_size", 36) * vc.get("line_spacing", 1.6))
        y = content_top + 20

        # Terminal-style prompt prefix
        prompt = "❯ "

        for i, line in enumerate(body_lines):
            if y + line_height > height - 60:
                break

            # Dim bullet marker
            draw.text(
                (padding, y), prompt, fill=code_colour, font=body_font
            )

            # Draw the text line
            draw.text(
                (padding + 40, y),
                line,
                fill=text_colour,
                font=body_font,
            )
            y += line_height

        # Blinking cursor on last line
        if show_cursor and body_lines:
            cursor_x = padding + 40 + body_font.getlength(body_lines[-1])
            cursor_y = y - line_height
            draw.rectangle(
                [cursor_x + 4, cursor_y, cursor_x + 18, cursor_y + vc.get("font_size", 36)],
                fill=accent_colour,
            )

    # ── Footer ──
    footer_font = get_font(16)
    footer_text = f"McNeillium_AI  •  AI & Emerging Tech"
    draw.text(
        (padding, height - 35),
        footer_text,
        fill=tuple(c // 3 for c in text_colour),
        font=footer_font,
    )

    return img


def generate_section_frames(
    section: dict,
    section_idx: int,
    total_sections: int,
    section_duration: float,
    config: dict,
) -> list[Image.Image]:
    """Generate all frames for a single script section."""
    vc = config.get("video", {})
    width = vc.get("width", 1920)
    height = vc.get("height", 1080)
    fps = vc.get("fps", 30)
    channel_name = config.get("channel", {}).get("name", "McNeillium_AI")

    total_frames = max(1, int(section_duration * fps))

    heading = section.get("heading", "")
    screen_text = section.get("screen_text", section.get("narration", ""))

    # Wrap text into lines that fit the screen
    max_chars = (width - vc.get("padding", 80) * 2 - 60) // (vc.get("font_size", 36) * 0.6)
    max_chars = max(40, int(max_chars))
    wrapped_lines = textwrap.wrap(screen_text, width=max_chars)

    frames = []
    for frame_num in range(total_frames):
        progress_global = (section_idx + frame_num / total_frames) / total_sections
        frame_progress = frame_num / total_frames

        # Reveal lines progressively (typing effect)
        lines_to_show = max(1, int(len(wrapped_lines) * min(1.0, frame_progress * 1.5)))
        visible_lines = wrapped_lines[:lines_to_show]

        # Cursor blinks every 0.5 seconds
        show_cursor = (frame_num // (fps // 2)) % 2 == 0

        frame = create_frame(
            width=width,
            height=height,
            config=config,
            heading=heading,
            body_lines=visible_lines,
            progress=progress_global,
            show_cursor=show_cursor,
            section_num=section_idx + 1,
            total_sections=total_sections,
            channel_name=channel_name,
        )
        frames.append(frame)

    return frames


def generate_video(script_path: str, audio_path: str, config: dict) -> Path:
    """Generate the complete video from script + audio."""
    vc = config.get("video", {})
    fps = vc.get("fps", 30)

    script_data = load_script(script_path)
    sections = script_data.get("sections", [])
    total_sections = len(sections)

    # Get audio duration to sync video length
    audio_duration = get_audio_duration(audio_path)
    print(f"    🎵 Audio duration: {audio_duration:.1f}s")

    # Distribute time across sections proportionally by narration length
    narration_lengths = []
    for s in sections:
        narration_lengths.append(len(s.get("narration", "")))
    total_chars = sum(narration_lengths) or 1

    section_durations = [
        (length / total_chars) * audio_duration for length in narration_lengths
    ]

    # Create temp directory for frames
    frames_dir = PROJECT_ROOT / "output" / "_temp_frames"
    if frames_dir.exists():
        shutil.rmtree(frames_dir)
    frames_dir.mkdir(parents=True)

    print(f"    🎞  Generating frames for {total_sections} sections...")

    frame_counter = 0
    for i, section in enumerate(sections):
        section_id = section.get("id", f"section_{i}")
        duration = section_durations[i]
        print(f"      [{i+1}/{total_sections}] {section_id} ({duration:.1f}s)")

        section_frames = generate_section_frames(
            section=section,
            section_idx=i,
            total_sections=total_sections,
            section_duration=duration,
            config=config,
        )

        for frame in section_frames:
            frame_path = frames_dir / f"frame_{frame_counter:06d}.png"
            frame.save(str(frame_path), "PNG")
            frame_counter += 1

    print(f"    🎞  Total frames: {frame_counter}")

    # Assemble video with FFmpeg
    VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    title = script_data.get("title", "untitled")
    safe_title = "".join(c if c.isalnum() or c in " -_" else "" for c in title)
    safe_title = safe_title.strip().replace(" ", "_")[:60]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    output_file = VIDEO_DIR / f"{timestamp}_{safe_title}.mp4"
    latest_file = VIDEO_DIR / "latest.mp4"

    print(f"    🔧 Assembling video with FFmpeg...")

    ffmpeg_cmd = [
        "ffmpeg",
        "-y",
        "-framerate", str(fps),
        "-i", str(frames_dir / "frame_%06d.png"),
        "-i", str(audio_path),
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        "-movflags", "+faststart",
        str(output_file),
    ]

    result = subprocess.run(
        ffmpeg_cmd,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print(f"  ERROR: FFmpeg failed:\n{result.stderr[-500:]}")
        sys.exit(1)

    # Copy as latest
    shutil.copy2(output_file, latest_file)

    # Clean up temp frames
    shutil.rmtree(frames_dir)

    return output_file


def main():
    parser = argparse.ArgumentParser(description="Generate video from script + audio")
    parser.add_argument(
        "--script", "-s",
        default=str(SCRIPT_DIR / "latest.json"),
        help="Path to script JSON file",
    )
    parser.add_argument(
        "--audio", "-a",
        default=str(AUDIO_DIR / "latest.mp3"),
        help="Path to narration audio file",
    )
    args = parser.parse_args()

    config = load_config()

    print("\n🎬 McNeillium_AI — Video Generator")
    print("=" * 50)

    output_file = generate_video(args.script, args.audio, config)

    # Get file size
    size_mb = output_file.stat().st_size / (1024 * 1024)
    print(f"\n  ✅ Video saved: {output_file}")
    print(f"  📦 Size: {size_mb:.1f} MB")
    return output_file


if __name__ == "__main__":
    main()
