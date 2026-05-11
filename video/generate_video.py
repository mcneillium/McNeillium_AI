#!/usr/bin/env python3
"""
McNeillium_AI — Video Generator v2
Polished videos with Pexels image backgrounds, branded intro/outro cards,
crossfade transitions, and typing animations.
"""

import argparse
import io
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower().replace("-", "") != "utf8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import shutil as _shutil_mod

import yaml
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
from mutagen.mp3 import MP3


def _find_ffmpeg() -> str:
    if _shutil_mod.which("ffmpeg"):
        return "ffmpeg"
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return "ffmpeg"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.yaml"
SCRIPT_DIR = PROJECT_ROOT / "output" / "scripts"
AUDIO_DIR = PROJECT_ROOT / "output" / "audio"
VIDEO_DIR = PROJECT_ROOT / "output" / "videos"
CACHE_DIR = PROJECT_ROOT / "output" / "_image_cache"

CROSSFADE_SECONDS = 0.5
INTRO_SECONDS = 3.0
OUTRO_SECONDS = 3.0


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def load_script(script_path: str) -> dict:
    with open(script_path, encoding="utf-8") as f:
        return json.load(f)


def get_audio_duration(audio_path: str) -> float:
    return MP3(audio_path).info.length


# ── Fonts ──────────────────────────────────────────────────────────────

def get_mono_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    paths = (
        ["C:/Windows/Fonts/consolab.ttf", "C:/Windows/Fonts/courbd.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"]
        if bold else
        ["C:/Windows/Fonts/consola.ttf", "C:/Windows/Fonts/cour.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"]
    )
    for fp in paths:
        if os.path.exists(fp):
            return ImageFont.truetype(fp, size)
    return ImageFont.load_default()


def get_sans_font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    paths = (
        ["C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/segoeui.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
        if bold else
        ["C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/segoeui.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    )
    for fp in paths:
        if os.path.exists(fp):
            return ImageFont.truetype(fp, size)
    return ImageFont.load_default()


def hex_to_rgb(hex_colour: str) -> tuple:
    hex_colour = hex_colour.lstrip("#")
    return tuple(int(hex_colour[i : i + 2], 16) for i in (0, 2, 4))


# ── Image helpers ──────────────────────────────────────────────────────

def fetch_background(query: str) -> Image.Image | None:
    api_key = os.getenv("PEXELS_API_KEY", "")
    if not api_key:
        return None
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    safe_q = re.sub(r"[^a-zA-Z0-9]", "_", query)[:40]
    cache_path = CACHE_DIR / f"bg_{safe_q}.jpg"
    if cache_path.exists():
        try:
            return Image.open(cache_path).convert("RGB")
        except Exception:
            pass
    try:
        encoded = urllib.parse.quote(query)
        url = f"https://api.pexels.com/v1/search?query={encoded}&per_page=3&orientation=landscape"
        req = urllib.request.Request(url, headers={"Authorization": api_key})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
        photos = data.get("photos", [])
        if not photos:
            return None
        photo_url = photos[0]["src"]["large2x"]
        urllib.request.urlretrieve(photo_url, str(cache_path))
        return Image.open(cache_path).convert("RGB")
    except Exception as e:
        print(f"    ⚠  Background fetch failed ({query}): {e}")
        return None


def prepare_background(
    bg_image: Image.Image | None, width: int, height: int, brightness: float = 0.25
) -> Image.Image:
    if bg_image:
        ratio = max(width / bg_image.width, height / bg_image.height)
        new_size = (int(bg_image.width * ratio), int(bg_image.height * ratio))
        bg = bg_image.resize(new_size, Image.LANCZOS)
        left = (bg.width - width) // 2
        top = (bg.height - height) // 2
        bg = bg.crop((left, top, left + width, top + height))
        bg = bg.filter(ImageFilter.GaussianBlur(radius=6))
        return ImageEnhance.Brightness(bg).enhance(brightness)
    # Gradient fallback
    img = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(img)
    for y in range(height):
        r = int(10 + 15 * y / height)
        g = int(12 + 10 * y / height)
        b = int(25 + 35 * y / height)
        draw.line([(0, y), (width, y)], fill=(r, g, b))
    return img


def derive_query(section: dict) -> str:
    notes = section.get("visual_notes", "")
    if notes:
        words = notes.split(".")[0].split()[:4]
        return " ".join(words) + " technology"
    return section.get("heading", "technology") + " dark"


# ── Frame renderers ───────────────────────────────────────────────────

def add_overlay_panel(img: Image.Image, padding: int) -> Image.Image:
    width, height = img.size
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    ov_draw = ImageDraw.Draw(overlay)
    ov_draw.rounded_rectangle(
        [padding - 20, 55, width - padding + 20, height - 50],
        radius=16,
        fill=(8, 12, 20, 160),
    )
    return Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")


def apply_fade(img: Image.Image, alpha: float) -> Image.Image:
    if alpha >= 1.0:
        return img
    black = Image.new("RGB", img.size, (0, 0, 0))
    return Image.blend(black, img, max(0.0, alpha))


def render_intro_card(
    bg: Image.Image, config: dict, title: str, fade: float = 1.0
) -> Image.Image:
    vc = config.get("video", {})
    width, height = bg.size
    accent = hex_to_rgb(vc.get("accent_colour", "#58a6ff"))
    channel = config.get("channel", {}).get("name", "McNeillium_AI")

    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 140))
    img = Image.alpha_composite(bg.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(img)

    draw.rectangle([0, 0, 8, height], fill=accent)

    channel_font = get_sans_font(72)
    draw.text(
        (width // 2, height // 2 - 80),
        channel,
        fill=accent,
        font=channel_font,
        anchor="mm",
    )

    rule_y = height // 2 - 20
    draw.rectangle(
        [width // 4, rule_y, width * 3 // 4, rule_y + 3], fill=accent
    )

    title_font = get_sans_font(42)
    wrapped = textwrap.wrap(title, width=45)
    y = height // 2 + 20
    for line in wrapped[:3]:
        draw.text(
            (width // 2, y),
            line,
            fill=(230, 237, 243),
            font=title_font,
            anchor="mm",
        )
        y += 55

    tag_font = get_sans_font(24, bold=False)
    draw.text(
        (width // 2, height - 80),
        "AI & Emerging Tech — Explained",
        fill=(150, 160, 175),
        font=tag_font,
        anchor="mm",
    )

    return apply_fade(img, fade)


def render_outro_card(
    bg: Image.Image, config: dict, fade: float = 1.0
) -> Image.Image:
    vc = config.get("video", {})
    width, height = bg.size
    accent = hex_to_rgb(vc.get("accent_colour", "#58a6ff"))
    channel = config.get("channel", {}).get("name", "McNeillium_AI")

    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 160))
    img = Image.alpha_composite(bg.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(img)

    draw.rectangle([0, 0, 8, height], fill=accent)

    cta_font = get_sans_font(64)
    draw.text(
        (width // 2, height // 2 - 60),
        "Like & Subscribe",
        fill=(255, 255, 255),
        font=cta_font,
        anchor="mm",
    )

    name_font = get_sans_font(48)
    draw.text(
        (width // 2, height // 2 + 30),
        channel,
        fill=accent,
        font=name_font,
        anchor="mm",
    )

    tag_font = get_sans_font(28, bold=False)
    draw.text(
        (width // 2, height // 2 + 100),
        "New videos weekly — AI & Emerging Tech",
        fill=(180, 190, 210),
        font=tag_font,
        anchor="mm",
    )

    return apply_fade(img, fade)


def render_content_frame(
    bg: Image.Image,
    config: dict,
    heading: str,
    body_lines: list[str] | None,
    progress: float,
    show_cursor: bool,
    section_num: int,
    total_sections: int,
    channel_name: str,
) -> Image.Image:
    vc = config.get("video", {})
    width, height = bg.size
    text_colour = hex_to_rgb(vc.get("text_colour", "#e6edf3"))
    accent = hex_to_rgb(vc.get("accent_colour", "#58a6ff"))
    heading_colour = hex_to_rgb(vc.get("heading_colour", "#ff7b72"))
    code_colour = hex_to_rgb(vc.get("code_colour", "#7ee787"))
    padding = vc.get("padding", 80)
    font_size = vc.get("font_size", 36)

    img = add_overlay_panel(bg, padding)
    draw = ImageDraw.Draw(img)

    # Title bar
    title_bar_h = 40
    draw.rectangle([0, 0, width, title_bar_h], fill=(22, 27, 34))
    dot_y = title_bar_h // 2
    for i, c in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        draw.ellipse(
            [15 + i * 22, dot_y - 6, 15 + i * 22 + 12, dot_y + 6], fill=c
        )
    tf = get_mono_font(14)
    draw.text(
        (width // 2, dot_y),
        f"  {channel_name} — Terminal",
        fill=text_colour,
        font=tf,
        anchor="mm",
    )

    # Progress bar
    bar_y = title_bar_h
    draw.rectangle([0, bar_y, width, bar_y + 3], fill=(30, 30, 30))
    draw.rectangle(
        [0, bar_y, int(width * progress), bar_y + 3], fill=accent
    )

    # Section indicator
    sf = get_mono_font(16)
    draw.text(
        (width - padding, title_bar_h + 20),
        f"[{section_num}/{total_sections}]",
        fill=tuple(c // 2 for c in text_colour),
        font=sf,
    )

    # Heading
    content_top = title_bar_h + 3 + 40
    if heading:
        hf = get_sans_font(vc.get("heading_font_size", 52))
        draw.rectangle(
            [padding, content_top, padding + 4, content_top + 50], fill=accent
        )
        draw.text(
            (padding + 20, content_top), heading, fill=heading_colour, font=hf
        )
        content_top += 80

    # Body text
    if body_lines:
        bf = get_mono_font(font_size)
        lh = int(font_size * vc.get("line_spacing", 1.6))
        y = content_top + 20
        for line in body_lines:
            if y + lh > height - 70:
                break
            draw.text((padding, y), "> ", fill=code_colour, font=bf)
            draw.text((padding + 40, y), line, fill=text_colour, font=bf)
            y += lh
        if show_cursor:
            cx = padding + 40 + bf.getlength(body_lines[-1])
            cy = y - lh
            draw.rectangle(
                [cx + 4, cy, cx + 18, cy + font_size], fill=accent
            )

    # Footer
    ff = get_mono_font(16)
    draw.text(
        (padding, height - 35),
        "McNeillium_AI  •  AI & Emerging Tech",
        fill=tuple(c // 3 for c in text_colour),
        font=ff,
    )

    return img


# ── Main generator ─────────────────────────────────────────────────────

def generate_video(script_path: str, audio_path: str, config: dict) -> Path:
    vc = config.get("video", {})
    width = vc.get("width", 1920)
    height = vc.get("height", 1080)
    fps = vc.get("fps", 30)
    channel_name = config.get("channel", {}).get("name", "McNeillium_AI")

    script_data = load_script(script_path)
    title = script_data.get("title", "Untitled")
    sections = script_data.get("sections", [])
    total_sections = len(sections)

    audio_duration = get_audio_duration(audio_path)
    print(f"    Audio duration: {audio_duration:.1f}s")

    # Distribute time proportionally by narration length
    narration_lengths = [len(s.get("narration", "")) for s in sections]
    total_chars = sum(narration_lengths) or 1
    section_durations = [
        (n / total_chars) * audio_duration for n in narration_lengths
    ]

    # Fetch Pexels backgrounds for each section
    print(f"    Fetching backgrounds for {total_sections} sections...")
    backgrounds = []
    for section in sections:
        query = derive_query(section)
        raw = fetch_background(query)
        bg = prepare_background(raw, width, height)
        backgrounds.append(bg)
        sid = section.get("id", "?")
        status = "fetched" if raw else "gradient"
        print(f"      [{sid}] {status}")

    # Temp frames directory
    frames_dir = PROJECT_ROOT / "output" / "_temp_frames"
    if frames_dir.exists():
        shutil.rmtree(frames_dir)
    frames_dir.mkdir(parents=True)

    crossfade_n = int(CROSSFADE_SECONDS * fps)
    intro_n = int(INTRO_SECONDS * fps)
    outro_n = int(OUTRO_SECONDS * fps)

    print(f"    Rendering frames...")
    frame_counter = 0
    prev_bg = None

    for i, section in enumerate(sections):
        n_frames = max(1, int(section_durations[i] * fps))
        curr_bg = backgrounds[i]
        heading = section.get("heading", "")
        screen_text = section.get("screen_text", section.get("narration", ""))

        max_chars = max(
            40,
            int(
                (width - vc.get("padding", 80) * 2 - 60)
                / (vc.get("font_size", 36) * 0.6)
            ),
        )
        wrapped = textwrap.wrap(screen_text, width=max_chars)

        sid = section.get("id", f"section_{i}")
        print(
            f"      [{i+1}/{total_sections}] {sid} "
            f"({section_durations[i]:.1f}s, {n_frames} frames)"
        )

        for f_num in range(n_frames):
            progress = (i + f_num / n_frames) / total_sections
            f_progress = f_num / n_frames

            # Crossfade background between sections
            if f_num < crossfade_n and prev_bg is not None:
                alpha = f_num / crossfade_n
                bg = Image.blend(prev_bg, curr_bg, alpha)
            else:
                bg = curr_bg

            # Intro card (first section, first N seconds)
            if i == 0 and f_num < intro_n:
                fade = f_num / intro_n
                frame = render_intro_card(bg, config, title, fade)

            # Outro card (last section, last N seconds)
            elif i == total_sections - 1 and f_num >= n_frames - outro_n:
                remaining = n_frames - f_num
                fade = remaining / outro_n
                frame = render_outro_card(bg, config, fade)

            # Regular content frame
            else:
                lines_to_show = max(
                    1, int(len(wrapped) * min(1.0, f_progress * 1.5))
                )
                visible = wrapped[:lines_to_show]
                show_cursor = (f_num // max(1, fps // 2)) % 2 == 0
                frame = render_content_frame(
                    bg,
                    config,
                    heading,
                    visible,
                    progress,
                    show_cursor,
                    i + 1,
                    total_sections,
                    channel_name,
                )

            path = frames_dir / f"frame_{frame_counter:06d}.png"
            frame.save(str(path), "PNG")
            frame_counter += 1

        prev_bg = curr_bg

    print(f"    Total frames: {frame_counter}")

    # FFmpeg assembly
    VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    safe_title = (
        "".join(c if c.isalnum() or c in " -_" else "" for c in title)
        .strip()
        .replace(" ", "_")[:60]
    )
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = VIDEO_DIR / f"{timestamp}_{safe_title}.mp4"

    print(f"    Assembling with FFmpeg...")

    ffmpeg_cmd = [
        _find_ffmpeg(),
        "-y",
        "-framerate",
        str(fps),
        "-i",
        str(frames_dir / "frame_%06d.png"),
        "-i",
        str(audio_path),
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "23",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-shortest",
        "-movflags",
        "+faststart",
        str(output_file),
    ]

    result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ERROR: FFmpeg failed:\n{result.stderr[-500:]}")
        sys.exit(1)

    shutil.copy2(output_file, VIDEO_DIR / "latest.mp4")
    shutil.rmtree(frames_dir)

    return output_file


def main():
    parser = argparse.ArgumentParser(
        description="Generate video from script + audio (v2)"
    )
    parser.add_argument(
        "--script",
        "-s",
        default=str(SCRIPT_DIR / "latest.json"),
    )
    parser.add_argument(
        "--audio",
        "-a",
        default=str(AUDIO_DIR / "latest.mp3"),
    )
    args = parser.parse_args()

    config = load_config()

    print("\n McNeillium_AI — Video Generator v2")
    print("=" * 50)

    output_file = generate_video(args.script, args.audio, config)

    size_mb = output_file.stat().st_size / (1024 * 1024)
    print(f"\n  Video saved: {output_file}")
    print(f"  Size: {size_mb:.1f} MB")
    return output_file


if __name__ == "__main__":
    main()
