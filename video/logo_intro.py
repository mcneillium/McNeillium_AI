#!/usr/bin/env python3
"""
McNeillium_AI — Logo Animation Intro Generator
3-second branded intro: typing effect + blue glow + tagline.
"""

import io
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower().replace("-", "") != "utf8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from PIL import Image, ImageDraw, ImageFont, ImageFilter

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ASSETS_DIR = PROJECT_ROOT / "assets" / "logo_intro"
TEMP_DIR = PROJECT_ROOT / "output" / "_temp_logo"
OUTPUT_PATH = ASSETS_DIR / "mcneillium_intro.mp4"

W, H, FPS, DURATION = 1920, 1080, 30, 3.0
TOTAL_FRAMES = int(DURATION * FPS)

BLUE = (88, 166, 255)
WHITE = (230, 237, 243)
GREY = (160, 170, 185)
BG = (6, 10, 18)


def _find_font(candidates, size):
    for fp in candidates:
        if os.path.exists(fp):
            return ImageFont.truetype(fp, size)
    return ImageFont.load_default()


def font_bold(sz):
    return _find_font([
        "C:/Windows/Fonts/arialbd.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ], sz)


def font_regular(sz):
    return _find_font([
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ], sz)


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


def _draw_glow(img, cx, cy, text, font, color, radius=20, alpha=80):
    """Draw a subtle glow effect behind text."""
    glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.text((cx, cy), text, font=font, fill=(*color, alpha), anchor="mm")
    glow = glow.filter(ImageFilter.GaussianBlur(radius=radius))
    return Image.alpha_composite(img, glow)


def generate_logo_intro():
    """Generate the 3-second logo animation."""
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)

    channel_text = "McNeillium"
    ai_text = "_AI"
    tagline = "AI & Emerging Tech"
    cx, cy = W // 2, H // 2

    main_font = font_bold(72)
    ai_font = font_bold(72)
    tag_font = font_regular(26)

    main_bbox = main_font.getbbox(channel_text)
    main_w = main_bbox[2] - main_bbox[0]
    ai_bbox = ai_font.getbbox(ai_text)
    ai_w = ai_bbox[2] - ai_bbox[0]
    total_w = main_w + ai_w
    start_x = cx - total_w // 2

    for f_idx in range(TOTAL_FRAMES):
        p = f_idx / max(1, TOTAL_FRAMES - 1)
        img = Image.new("RGBA", (W, H), (*BG, 255))
        draw = ImageDraw.Draw(img)

        # Gradient background
        for y in range(H):
            r = int(6 + 10 * (y / H))
            g = int(10 + 12 * (y / H))
            b = int(18 + 22 * (y / H))
            draw.line([(0, y), (W, y)], fill=(r, g, b, 255))

        # Phase 1 (0-0.17): Fade in from black
        # Phase 2 (0.17-0.50): "McNeillium" types out
        # Phase 3 (0.50-0.67): "_AI" appears with blue glow pulse
        # Phase 4 (0.67-0.83): Tagline fades in
        # Phase 5 (0.83-1.0): Hold + slight scale, fade out last 4 frames

        fade_in = min(1.0, p / 0.17) if p < 0.17 else 1.0

        # Type-out "McNeillium" (frames 5-45 ~ p 0.06-0.50)
        if p >= 0.06:
            type_p = min(1.0, (p - 0.06) / 0.44)
            chars_visible = max(1, int(type_p * len(channel_text)))
            visible = channel_text[:chars_visible]
            a = int(255 * fade_in)

            draw.text((start_x, cy - 20), visible,
                      font=main_font, fill=(*WHITE, a), anchor="lm")

            # Cursor blink during typing
            if type_p < 1.0 and (f_idx // 4) % 2 == 0:
                cursor_bbox = main_font.getbbox(visible)
                cursor_x = start_x + (cursor_bbox[2] - cursor_bbox[0])
                draw.rectangle([cursor_x + 4, cy - 44, cursor_x + 8, cy + 4],
                               fill=(*BLUE, a))

        # "_AI" appears with glow (p > 0.50)
        if p >= 0.50:
            ai_p = min(1.0, (p - 0.50) / 0.17)
            ai_a = int(255 * ai_p * fade_in)

            # Glow pulse
            glow_intensity = 0.5 + 0.5 * math.sin(ai_p * math.pi)
            glow_radius = int(15 + 10 * glow_intensity)
            glow_alpha = int(60 + 40 * glow_intensity)

            ai_x = start_x + main_w
            img = _draw_glow(img, ai_x + ai_w // 2, cy - 20,
                             ai_text, ai_font, BLUE, glow_radius, glow_alpha)
            draw = ImageDraw.Draw(img)

            draw.text((ai_x, cy - 20), ai_text,
                      font=ai_font, fill=(*BLUE, ai_a), anchor="lm")

        # Tagline (p > 0.67)
        if p >= 0.67:
            tag_p = min(1.0, (p - 0.67) / 0.16)
            tag_a = int(255 * tag_p * fade_in)
            offset = int(8 * (1 - tag_p))
            draw.text((cx, cy + 40 + offset), tagline,
                      font=tag_font, fill=(*GREY, tag_a), anchor="mm")

        # Accent lines (expand from center)
        if p >= 0.50:
            line_p = min(1.0, (p - 0.50) * 3)
            line_w = int(220 * line_p)
            line_a = int(180 * fade_in * line_p)
            draw.rectangle([cx - line_w, cy + 70, cx + line_w, cy + 72],
                           fill=(*BLUE, line_a))

        # Fade out last 4 frames
        if f_idx > TOTAL_FRAMES - 5:
            remaining = TOTAL_FRAMES - f_idx
            black = Image.new("RGBA", (W, H), (*BG, 255))
            img = Image.blend(img, black, 1 - remaining / 5)

        # Fade from black at start
        if f_idx < 5:
            black = Image.new("RGBA", (W, H), (*BG, 255))
            img = Image.blend(black, img, f_idx / 5)

        path = TEMP_DIR / f"logo_{f_idx:04d}.png"
        img.save(str(path), "PNG")

    # Encode to MP4
    cmd = [
        FFMPEG, "-y",
        "-framerate", str(FPS),
        "-i", str(TEMP_DIR / "logo_%04d.png"),
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "20",
        "-pix_fmt", "yuv420p",
        str(OUTPUT_PATH),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)

    shutil.rmtree(TEMP_DIR, ignore_errors=True)

    if result.returncode != 0:
        print(f"  ERROR encoding logo intro: {result.stderr[-300:]}")
        return None

    print(f"  ✅ Logo intro: {OUTPUT_PATH}")
    return str(OUTPUT_PATH)


if __name__ == "__main__":
    print("\n🎬 McNeillium_AI — Logo Intro Generator")
    print("=" * 40)
    generate_logo_intro()
