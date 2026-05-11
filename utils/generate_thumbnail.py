#!/usr/bin/env python3
"""
McNeillium_AI — Thumbnail Generator
Creates eye-catching 1280x720 YouTube thumbnails with:
  - Bold text overlay (max 4 words)
  - Gradient or image background
  - Channel branding
  - High contrast for mobile visibility
"""

import argparse
import json
import os
import re
import sys
import textwrap
import urllib.parse
import urllib.request
from pathlib import Path

import yaml
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.yaml"
THUMB_DIR = PROJECT_ROOT / "output" / "thumbnails"
CACHE_DIR = PROJECT_ROOT / "output" / "_image_cache"


def load_config():
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def get_font(size, bold=True):
    if bold:
        paths = [
            "C:/Windows/Fonts/arialbd.ttf",
            "C:/Windows/Fonts/segoeui.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        ]
    else:
        paths = [
            "C:/Windows/Fonts/arial.ttf",
            "C:/Windows/Fonts/segoeui.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        ]
    for fp in paths:
        if os.path.exists(fp):
            return ImageFont.truetype(fp, size)
    return ImageFont.load_default()


def fetch_background(query, width=1280, height=720):
    """Fetch a background image from Pexels."""
    api_key = os.getenv("PEXELS_API_KEY", "")
    if not api_key:
        return None

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    safe_q = re.sub(r'[^a-zA-Z0-9]', '_', query)[:40]
    cache_path = CACHE_DIR / f"thumb_{safe_q}.jpg"

    if cache_path.exists():
        try:
            return Image.open(cache_path).convert("RGB")
        except Exception:
            pass

    try:
        encoded = urllib.parse.quote(query)
        url = f"https://api.pexels.com/v1/search?query={encoded}&per_page=3&orientation=landscape"
        req = urllib.request.Request(url, headers={"Authorization": api_key})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())

        photos = data.get("photos", [])
        if not photos:
            return None

        photo_url = photos[0]["src"]["large2x"]
        urllib.request.urlretrieve(photo_url, str(cache_path))
        return Image.open(cache_path).convert("RGB")
    except Exception as e:
        print(f"  ⚠️  Thumbnail image fetch failed: {e}")
        return None


def generate_thumbnail(
    title_text: str,
    subtitle_text: str = "",
    background_query: str = "artificial intelligence technology",
    output_path: str = None,
) -> Path:
    """Generate a YouTube thumbnail."""
    WIDTH, HEIGHT = 1280, 720
    THUMB_DIR.mkdir(parents=True, exist_ok=True)

    # ── Background ──
    bg_image = fetch_background(background_query, WIDTH, HEIGHT)

    if bg_image:
        # Resize to cover
        ratio = max(WIDTH / bg_image.width, HEIGHT / bg_image.height)
        new_size = (int(bg_image.width * ratio), int(bg_image.height * ratio))
        bg_image = bg_image.resize(new_size, Image.LANCZOS)
        left = (bg_image.width - WIDTH) // 2
        top = (bg_image.height - HEIGHT) // 2
        bg_image = bg_image.crop((left, top, left + WIDTH, top + HEIGHT))
        bg_image = bg_image.filter(ImageFilter.GaussianBlur(radius=4))
        bg_image = ImageEnhance.Brightness(bg_image).enhance(0.3)
        img = bg_image
    else:
        # Gradient fallback
        img = Image.new("RGB", (WIDTH, HEIGHT))
        for y in range(HEIGHT):
            r = int(10 + (25 * y / HEIGHT))
            g = int(12 + (20 * y / HEIGHT))
            b = int(30 + (40 * y / HEIGHT))
            for x in range(WIDTH):
                img.putpixel((x, y), (r, g, b))

    draw = ImageDraw.Draw(img)

    # ── Accent bar (left side) ──
    draw.rectangle([0, 0, 12, HEIGHT], fill=(88, 166, 255))

    # ── Dark overlay panel for text area ──
    overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    ov_draw = ImageDraw.Draw(overlay)
    ov_draw.rounded_rectangle(
        [40, 80, WIDTH - 40, HEIGHT - 80],
        radius=20, fill=(8, 12, 20, 180)
    )
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(img)

    # ── Title text (large, bold, white with accent) ──
    # Split into max 2 lines
    words = title_text.split()
    if len(words) <= 3:
        lines = [title_text]
        font_size = 96
    elif len(words) <= 6:
        mid = len(words) // 2
        lines = [" ".join(words[:mid]), " ".join(words[mid:])]
        font_size = 82
    else:
        mid = len(words) // 2
        lines = [" ".join(words[:mid]), " ".join(words[mid:])]
        font_size = 68

    title_font = get_font(font_size, bold=True)

    # Check if text fits, reduce if needed
    for line in lines:
        while title_font.getlength(line) > WIDTH - 140 and font_size > 40:
            font_size -= 4
            title_font = get_font(font_size, bold=True)

    y_start = HEIGHT // 2 - (len(lines) * (font_size + 10)) // 2 - 20

    for i, line in enumerate(lines):
        y = y_start + i * (font_size + 16)
        # Shadow
        draw.text((WIDTH // 2 + 3, y + 3), line, font=title_font,
                   fill=(0, 0, 0), anchor="mm")
        # Main text - first line white, second line accent blue
        colour = (255, 255, 255) if i == 0 else (88, 166, 255)
        draw.text((WIDTH // 2, y), line, font=title_font,
                   fill=colour, anchor="mm")

    # ── Subtitle ──
    if subtitle_text:
        sub_font = get_font(32, bold=False)
        sub_y = y_start + len(lines) * (font_size + 16) + 10
        draw.text((WIDTH // 2 + 2, sub_y + 2), subtitle_text,
                   font=sub_font, fill=(0, 0, 0), anchor="mm")
        draw.text((WIDTH // 2, sub_y), subtitle_text,
                   font=sub_font, fill=(180, 190, 210), anchor="mm")

    # ── Channel branding (bottom right) ──
    brand_font = get_font(28, bold=True)
    draw.text((WIDTH - 60, HEIGHT - 50), "McNeillium AI",
              font=brand_font, fill=(88, 166, 255), anchor="rm")

    # ── Save ──
    if output_path is None:
        safe = re.sub(r'[^a-zA-Z0-9 _-]', '', title_text).replace(' ', '_')[:50]
        output_path = THUMB_DIR / f"{safe}.jpg"
    else:
        output_path = Path(output_path)

    img.save(str(output_path), "JPEG", quality=95)

    # Also save as latest
    latest = THUMB_DIR / "latest.jpg"
    img.save(str(latest), "JPEG", quality=95)

    print(f"  ✅ Thumbnail saved: {output_path}")
    return output_path


def main():
    parser = argparse.ArgumentParser(description="Generate YouTube thumbnail")
    parser.add_argument("--title", "-t", required=True, help="Main title text (max ~6 words)")
    parser.add_argument("--subtitle", "-s", default="", help="Optional subtitle")
    parser.add_argument("--query", "-q", default="artificial intelligence",
                        help="Image search query for background")
    parser.add_argument("--output", "-o", default=None, help="Output file path")
    args = parser.parse_args()

    generate_thumbnail(args.title, args.subtitle, args.query, args.output)


if __name__ == "__main__":
    main()
