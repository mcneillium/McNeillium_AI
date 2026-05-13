#!/usr/bin/env python3
"""
McNeillium_AI — Video Generator v3 (Cinematic)
================================================
Professional YouTube video engine with:
  - Pexels image backgrounds (gradient fallback per section)
  - Multiple section layouts (bullets, numbered, code, quote, split)
  - Particle overlay and vignette effects
  - Crossfade + slide transitions (alternating)
  - Background music (auto-downloaded, mixed at 12%)
  - Branded intro/outro with animated elements
  - Auto-generated chapter timestamps
"""

import argparse
import io
import json
import math
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

import numpy as np
import yaml
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.yaml"
SCRIPT_DIR = PROJECT_ROOT / "output" / "scripts"
AUDIO_DIR = PROJECT_ROOT / "output" / "audio"
VIDEO_DIR = PROJECT_ROOT / "output" / "videos"
MUSIC_DIR = PROJECT_ROOT / "assets" / "music"
IMAGE_CACHE = PROJECT_ROOT / "output" / "_image_cache"


def load_config():
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def load_script(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def get_audio_duration(path):
    try:
        from mutagen.mp3 import MP3
        return MP3(path).info.length
    except ImportError:
        ffprobe = _find_ffprobe()
        result = subprocess.run(
            [ffprobe, "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", path],
            capture_output=True, text=True,
        )
        return float(result.stdout.strip())


def _find_ffmpeg():
    if shutil.which("ffmpeg"):
        return "ffmpeg"
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return "ffmpeg"


def _find_ffprobe():
    if shutil.which("ffprobe"):
        return "ffprobe"
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        probe = exe.replace("ffmpeg", "ffprobe")
        if os.path.exists(probe):
            return probe
    except ImportError:
        pass
    return "ffprobe"


# ═══════════════════════════════════════════════════════════════
# FONTS
# ═══════════════════════════════════════════════════════════════

def _find_font(candidates, size):
    for fp in candidates:
        if os.path.exists(fp):
            return ImageFont.truetype(fp, size)
    return ImageFont.load_default()


def font_heading(size=52):
    return _find_font([
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ], size)


def font_body(size=32):
    return _find_font([
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ], size)


def font_mono(size=28):
    return _find_font([
        "C:/Windows/Fonts/consola.ttf",
        "C:/Windows/Fonts/cour.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    ], size)


def font_brand(size=24):
    return _find_font([
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ], size)


# ═══════════════════════════════════════════════════════════════
# COLOUR PALETTE
# ═══════════════════════════════════════════════════════════════

PALETTE = {
    "bg_dark":       (10, 14, 20),
    "bg_card":       (16, 20, 30),
    "text_primary":  (230, 237, 243),
    "text_dim":      (140, 150, 165),
    "accent_blue":   (88, 166, 255),
    "accent_green":  (126, 231, 135),
    "accent_orange": (255, 166, 87),
    "accent_red":    (255, 123, 114),
    "accent_purple": (188, 140, 255),
}

ACCENT_CYCLE = [
    PALETTE["accent_blue"],
    PALETTE["accent_green"],
    PALETTE["accent_orange"],
    PALETTE["accent_red"],
    PALETTE["accent_purple"],
]

GRADIENTS = [
    ((8, 15, 35),  (18, 30, 60)),
    ((20, 8, 30),  (40, 18, 55)),
    ((8, 22, 22),  (16, 45, 45)),
    ((22, 12, 8),  (45, 28, 16)),
    ((12, 12, 22), (28, 28, 48)),
    ((8, 20, 12),  (18, 42, 28)),
    ((22, 8, 16),  (48, 18, 32)),
    ((14, 18, 28), (28, 36, 55)),
]


def hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


# ═══════════════════════════════════════════════════════════════
# IMAGE FETCHING (Pexels)
# ═══════════════════════════════════════════════════════════════

def fetch_pexels(query):
    api_key = os.getenv("PEXELS_API_KEY", "")
    if not api_key:
        return None
    IMAGE_CACHE.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^a-zA-Z0-9]", "_", query)[:50]
    cache = IMAGE_CACHE / f"{safe}.jpg"
    if cache.exists():
        try:
            return Image.open(cache).convert("RGB")
        except Exception:
            pass
    try:
        import time
        time.sleep(1)
        enc = urllib.parse.quote(query)
        url = f"https://api.pexels.com/v1/search?query={enc}&per_page=5&orientation=landscape"
        req = urllib.request.Request(url, headers={"Authorization": api_key})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        photos = data.get("photos", [])
        if not photos:
            return None
        import random
        photo = random.choice(photos[:min(5, len(photos))])
        urllib.request.urlretrieve(photo["src"]["landscape"], str(cache))
        return Image.open(cache).convert("RGB")
    except Exception as e:
        print(f"      Pexels fetch failed: {e}")
        return None


def section_image_query(section):
    sid = section.get("id", "")
    heading = section.get("heading", "")
    keywords = {
        "hook": "futuristic technology abstract",
        "intro": "artificial intelligence neural network",
        "outro": "social media community technology",
        "summary": "innovation future technology",
        "demo": "programming computer code screen",
    }
    base = keywords.get(sid, heading)
    if not any(w in base.lower() for w in ("ai", "tech", "computer", "robot", "code", "digital")):
        base += " technology"
    return base


# ═══════════════════════════════════════════════════════════════
# BACKGROUND GENERATION
# ═══════════════════════════════════════════════════════════════

def make_gradient(w, h, c1, c2):
    arr = np.zeros((h, w, 3), dtype=np.uint8)
    for ch in range(3):
        arr[:, :, ch] = np.linspace(c1[ch], c2[ch], h, dtype=np.uint8)[:, np.newaxis]
    return Image.fromarray(arr)


def prepare_bg(image, w, h, darken=0.28, blur=8, gradient_idx=0):
    if image is None:
        c1, c2 = GRADIENTS[gradient_idx % len(GRADIENTS)]
        return make_gradient(w, h, c1, c2)
    ratio = max(w / image.width, h / image.height)
    nw, nh = int(image.width * ratio), int(image.height * ratio)
    image = image.resize((nw, nh), Image.LANCZOS)
    left, top = (nw - w) // 2, (nh - h) // 2
    image = image.crop((left, top, left + w, top + h))
    image = image.filter(ImageFilter.GaussianBlur(radius=blur))
    return ImageEnhance.Brightness(image).enhance(darken)


# ═══════════════════════════════════════════════════════════════
# DRAWING UTILITIES (with overlay caching)
# ═══════════════════════════════════════════════════════════════

def draw_shadow_text(draw, pos, text, font, fill, shadow=2, anchor=None):
    x, y = pos
    draw.text((x + shadow, y + shadow), text, font=font, fill=(0, 0, 0), anchor=anchor)
    draw.text(pos, text, font=font, fill=fill, anchor=anchor)


_particle_cache = {}


def _make_particle_overlay(w, h, count, seed):
    rng = np.random.RandomState(seed)
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for _ in range(count):
        x = rng.randint(0, w)
        y = rng.randint(0, h)
        r = rng.randint(1, 3)
        alpha = rng.randint(20, 60)
        draw.ellipse([x - r, y - r, x + r, y + r], fill=(150, 180, 220, alpha))
    return overlay


def add_particle_overlay(img, count=30, seed=42):
    key = (img.width, img.height, count, seed)
    if key not in _particle_cache:
        _particle_cache[key] = _make_particle_overlay(img.width, img.height, count, seed)
    return Image.alpha_composite(img.convert("RGBA"), _particle_cache[key]).convert("RGB")


_vignette_cache = {}


def _make_vignette(w, h, strength):
    vignette = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(vignette)
    for i in range(40):
        alpha = int(strength * 255 * (i / 40) ** 2)
        margin = int(w * 0.05 * (40 - i) / 40)
        draw.rectangle(
            [margin, margin, w - margin, h - margin],
            outline=(0, 0, 0, alpha),
            width=max(1, w // 40),
        )
    return vignette


def add_vignette(img, strength=0.4):
    key = (img.width, img.height, strength)
    if key not in _vignette_cache:
        _vignette_cache[key] = _make_vignette(img.width, img.height, strength)
    return Image.alpha_composite(img.convert("RGBA"), _vignette_cache[key]).convert("RGB")


# ═══════════════════════════════════════════════════════════════
# FRAME RENDERERS
# ═══════════════════════════════════════════════════════════════

def render_intro_card(w, h, title, channel_name, tagline, progress=0.0):
    img = make_gradient(w, h, (6, 10, 18), (14, 22, 38))
    img = add_particle_overlay(img, count=50)
    draw = ImageDraw.Draw(img)

    cx, cy = w // 2, h // 2

    line_width = int(w * 0.4 * min(1.0, progress * 3))
    draw.rectangle([cx - line_width, cy - 45, cx + line_width, cy - 43],
                   fill=PALETTE["accent_blue"])
    draw.rectangle([cx - line_width, cy + 45, cx + line_width, cy + 47],
                   fill=PALETTE["accent_blue"])

    if progress > 0.1:
        a = min(1.0, (progress - 0.1) * 5)
        c = tuple(int(v * a) for v in PALETTE["accent_blue"])
        draw_shadow_text(draw, (cx, cy - 80), channel_name,
                         font_heading(64), c, 3, "mm")

    if progress > 0.2:
        a = min(1.0, (progress - 0.2) * 5)
        c = tuple(int(v * a) for v in PALETTE["text_dim"])
        draw_shadow_text(draw, (cx, cy - 25), tagline,
                         font_body(26), c, 2, "mm")

    if progress > 0.35:
        a = min(1.0, (progress - 0.35) * 4)
        offset = int(30 * (1 - a))
        c = tuple(int(v * a) for v in PALETTE["text_primary"])
        f = font_heading(44)
        max_ch = (w - 200) // 24
        lines = textwrap.wrap(title, width=max_ch)
        for i, line in enumerate(lines):
            draw_shadow_text(draw, (cx, cy + 70 + i * 54 + offset), line,
                             f, c, 2, "mm")

    return add_vignette(img, 0.3)


def render_outro_card(w, h, channel_name, progress=0.0):
    img = make_gradient(w, h, (6, 10, 18), (14, 22, 38))
    img = add_particle_overlay(img, count=40, seed=99)
    draw = ImageDraw.Draw(img)

    cx, cy = w // 2, h // 2

    if progress > 0.1:
        a = min(1.0, (progress - 0.1) * 4)
        c = tuple(int(v * a) for v in PALETTE["accent_blue"])
        draw_shadow_text(draw, (cx, cy - 50), "LIKE & SUBSCRIBE",
                         font_heading(56), c, 3, "mm")

    if progress > 0.25:
        a = min(1.0, (progress - 0.25) * 4)
        c = tuple(int(v * a) for v in PALETTE["text_dim"])
        draw_shadow_text(draw, (cx, cy + 15), "for more AI content",
                         font_body(30), c, 2, "mm")

    if progress > 0.4:
        a = min(1.0, (progress - 0.4) * 4)
        c = tuple(int(v * a) for v in PALETTE["text_primary"])
        draw_shadow_text(draw, (cx, cy + 80), channel_name,
                         font_heading(32), c, 2, "mm")

    line_w = int(200 * min(1.0, progress * 2.5))
    draw.rectangle([cx - line_w, cy + 120, cx + line_w, cy + 122],
                   fill=PALETTE["accent_blue"])

    return add_vignette(img, 0.3)


def render_content_frame(
    w, h, bg, heading, lines, lines_visible, progress,
    section_num, total_sections, channel_name,
    layout="bullets", accent_idx=0,
):
    frame = bg.copy()
    frame = add_particle_overlay(frame, count=20, seed=section_num * 7)

    draw = ImageDraw.Draw(frame)
    pad = 80
    accent = ACCENT_CYCLE[accent_idx % len(ACCENT_CYCLE)]
    dimmed_accent = tuple(c // 3 for c in accent)

    # ── Top bar ──
    bar = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    bar_draw = ImageDraw.Draw(bar)
    bar_draw.rectangle([0, 0, w, 52], fill=(0, 0, 0, 180))
    frame = Image.alpha_composite(frame.convert("RGBA"), bar).convert("RGB")
    draw = ImageDraw.Draw(frame)

    draw.text((pad, 18), channel_name, font=font_brand(18),
              fill=PALETTE["accent_blue"], anchor="lm")
    draw.text((w - pad, 18), f"{section_num}/{total_sections}",
              font=font_brand(16), fill=PALETTE["text_dim"], anchor="rm")

    draw.rectangle([0, 52, w, 55], fill=(30, 30, 30))
    draw.rectangle([0, 52, int(w * progress), 55], fill=accent)

    # ── Content panel ──
    panel_top = 75
    panel_bottom = h - 55
    panel_left = pad - 25
    panel_right = w - pad + 25

    panel = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    p_draw = ImageDraw.Draw(panel)
    p_draw.rounded_rectangle(
        [panel_left, panel_top, panel_right, panel_bottom],
        radius=18, fill=(10, 14, 22, 195),
    )
    frame = Image.alpha_composite(frame.convert("RGBA"), panel).convert("RGB")
    draw = ImageDraw.Draw(frame)

    # ── Heading ──
    head_y = panel_top + 30
    if heading:
        hf = font_heading(44)
        draw.rectangle([pad, head_y, pad + 5, head_y + 40], fill=accent)
        draw_shadow_text(draw, (pad + 20, head_y + 2), heading, hf,
                         PALETTE["text_primary"], shadow=2)
        head_y += 65

    # ── Divider ──
    draw.rectangle([pad, head_y, w - pad, head_y + 1], fill=dimmed_accent)
    head_y += 20

    # ── Content area ──
    visible = lines[:lines_visible]
    bf = font_body(30)
    line_h = 52

    if layout == "bullets":
        for i, line in enumerate(visible):
            y = head_y + i * line_h
            if y + line_h > panel_bottom - 40:
                break
            dot_y = y + 16
            draw.ellipse([pad + 6, dot_y - 5, pad + 16, dot_y + 5], fill=accent)
            draw_shadow_text(draw, (pad + 30, y), line, bf,
                             PALETTE["text_primary"], shadow=1)

    elif layout == "numbered":
        for i, line in enumerate(visible):
            y = head_y + i * line_h
            if y + line_h > panel_bottom - 40:
                break
            draw.rounded_rectangle([pad, y, pad + 34, y + 34],
                                   radius=6, fill=accent)
            draw.text((pad + 17, y + 17), str(i + 1), font=font_brand(18),
                      fill=(0, 0, 0), anchor="mm")
            draw_shadow_text(draw, (pad + 48, y + 2), line, bf,
                             PALETTE["text_primary"], shadow=1)

    elif layout == "code":
        mf = font_mono(26)
        code_line_h = 40
        code_bottom = min(panel_bottom - 30, head_y + len(visible) * code_line_h + 20)
        draw.rounded_rectangle(
            [pad + 5, head_y - 5, w - pad - 5, code_bottom],
            radius=10, fill=(5, 8, 14),
        )
        for i, line in enumerate(visible):
            y = head_y + i * code_line_h + 8
            if y + code_line_h > panel_bottom - 30:
                break
            draw.text((pad + 18, y), str(i + 1).rjust(2),
                      font=font_mono(20), fill=PALETTE["text_dim"])
            draw.text((pad + 55, y), line, font=mf, fill=PALETTE["accent_green"])

    elif layout == "quote":
        draw.text((pad + 10, head_y - 10), "“", font=font_heading(80),
                  fill=dimmed_accent)
        qf = font_body(34)
        q_line_h = 55
        for i, line in enumerate(visible):
            y = head_y + 50 + i * q_line_h
            if y + q_line_h > panel_bottom - 40:
                break
            draw_shadow_text(draw, (pad + 40, y), line, qf,
                             PALETTE["text_primary"], shadow=1)

    else:  # split
        for i, line in enumerate(visible):
            y = head_y + i * line_h
            if y + line_h > panel_bottom - 40:
                break
            draw_shadow_text(draw, (pad + 10, y), f"→ {line}", bf,
                             PALETTE["text_primary"], shadow=1)

    # ── Cursor blink ──
    if visible:
        max_lines = (panel_bottom - 40 - head_y) // line_h
        last_idx = min(len(visible), max_lines) - 1
        if last_idx >= 0:
            last_line = visible[last_idx]
            cursor_x = pad + 30 + bf.getlength(last_line) + 6
            cursor_y = head_y + last_idx * line_h
            if int(progress * 1000) % 2 == 0:
                draw.rectangle(
                    [cursor_x, cursor_y, cursor_x + 14, cursor_y + 32],
                    fill=accent,
                )

    # ── Section type badge ──
    sid = f"Section {section_num}"
    badge_w = len(sid) * 10 + 24
    draw.rounded_rectangle(
        [pad, panel_bottom - 32, pad + badge_w, panel_bottom - 8],
        radius=4, fill=accent,
    )
    draw.text((pad + badge_w // 2, panel_bottom - 20), sid,
              font=font_brand(14), fill=(0, 0, 0), anchor="mm")

    return add_vignette(frame, 0.2)


# ═══════════════════════════════════════════════════════════════
# TRANSITIONS
# ═══════════════════════════════════════════════════════════════

def crossfade_frames(frame_a, frame_b, n_frames):
    a = np.array(frame_a, dtype=np.float32)
    b = np.array(frame_b, dtype=np.float32)
    frames = []
    for i in range(n_frames):
        alpha = i / max(1, n_frames)
        blended = (a * (1 - alpha) + b * alpha).astype(np.uint8)
        frames.append(Image.fromarray(blended))
    return frames


def slide_transition(frame_a, frame_b, n_frames, direction="left"):
    w = frame_a.width
    frames = []
    for i in range(n_frames):
        t = i / max(1, n_frames)
        t = 1 - (1 - t) ** 3  # ease-out cubic
        offset = int(w * t)
        canvas = Image.new("RGB", frame_a.size, (0, 0, 0))
        if direction == "left":
            canvas.paste(frame_a, (-offset, 0))
            canvas.paste(frame_b, (w - offset, 0))
        else:
            canvas.paste(frame_a, (offset, 0))
            canvas.paste(frame_b, (offset - w, 0))
        frames.append(canvas)
    return frames


# ═══════════════════════════════════════════════════════════════
# BACKGROUND MUSIC
# ═══════════════════════════════════════════════════════════════

def download_bg_music():
    MUSIC_DIR.mkdir(parents=True, exist_ok=True)
    music_file = MUSIC_DIR / "ambient_tech.mp3"

    if music_file.exists() and music_file.stat().st_size > 10000:
        print("    Background music: using cached track")
        return str(music_file)

    sources = [
        "https://cdn.pixabay.com/audio/2024/11/28/audio_9adb5fa01a.mp3",
        "https://cdn.pixabay.com/audio/2024/01/10/audio_d8140db9eb.mp3",
    ]

    for url in sources:
        try:
            print(f"    Downloading background music...")
            urllib.request.urlretrieve(url, str(music_file))
            if music_file.stat().st_size > 10000:
                print(f"    Background music saved")
                return str(music_file)
        except Exception as e:
            print(f"      Music download failed: {e}")
            continue

    print("    No background music available — narration only")
    return None


# ═══════════════════════════════════════════════════════════════
# LAYOUT SELECTION
# ═══════════════════════════════════════════════════════════════

def pick_layout(section, idx):
    sid = section.get("id", "")
    narration = section.get("narration", "").lower()

    if sid in ("hook", "intro"):
        return "bullets"
    elif sid == "demo":
        return "code"
    elif "quote" in narration or "said" in narration or "exact words" in narration:
        return "quote"
    elif idx % 3 == 0:
        return "numbered"
    elif idx % 3 == 1:
        return "bullets"
    else:
        return "split"


# ═══════════════════════════════════════════════════════════════
# MAIN VIDEO GENERATION
# ═══════════════════════════════════════════════════════════════

def generate_video(script_path, audio_path, config):
    vc = config.get("video", {})
    W = vc.get("width", 1920)
    H = vc.get("height", 1080)
    FPS = vc.get("fps", 30)
    channel = config.get("channel", {})
    ch_name = channel.get("name", "McNeillium_AI")
    ch_tag = channel.get("tagline", "AI & Emerging Tech")

    script = load_script(script_path)
    sections = script.get("sections", [])
    n_sections = len(sections)
    title = script.get("title", "Untitled")

    audio_dur = get_audio_duration(audio_path)
    print(f"    Audio: {audio_dur:.1f}s")

    # ── Fetch backgrounds ──
    print(f"    Fetching images for {n_sections} sections...")
    bg_images = []
    for i, sec in enumerate(sections):
        q = section_image_query(sec)
        raw = fetch_pexels(q)
        bg = prepare_bg(raw, W, H, darken=0.25, blur=6, gradient_idx=i)
        bg_images.append(bg)
        status = "fetched" if raw else "gradient"
        print(f"      [{i + 1}/{n_sections}] {status}")

    # ── Background music ──
    bg_music_path = download_bg_music()

    # ── Timing ──
    INTRO_DUR = 3.5
    OUTRO_DUR = 3.5
    TRANSITION_DUR = 0.6

    n_transitions = n_sections + 1
    total_transition_time = n_transitions * TRANSITION_DUR
    content_dur = max(1.0, audio_dur - INTRO_DUR - OUTRO_DUR - total_transition_time)

    char_counts = [len(s.get("narration", "")) for s in sections]
    total_chars = sum(char_counts) or 1
    sec_durations = [(c / total_chars) * content_dur for c in char_counts]

    # ── Frame directory ──
    frames_dir = PROJECT_ROOT / "output" / "_temp_frames"
    if frames_dir.exists():
        shutil.rmtree(frames_dir)
    frames_dir.mkdir(parents=True)

    frame_num = 0
    trans_frames = int(TRANSITION_DUR * FPS)

    chapters = []
    current_time = 0.0

    def save_frame(img):
        nonlocal frame_num
        path = frames_dir / f"frame_{frame_num:06d}.png"
        img.save(str(path), "PNG")
        frame_num += 1

    # ════════════════════════════════════════════
    # INTRO
    # ════════════════════════════════════════════
    print(f"    Intro ({INTRO_DUR}s)...")
    chapters.append({"time": "0:00", "label": "Intro"})
    intro_n = int(INTRO_DUR * FPS)
    for f in range(intro_n):
        p = f / intro_n
        frame = render_intro_card(W, H, title, ch_name, ch_tag, p)
        if f < 15:
            black = Image.new("RGB", (W, H), (0, 0, 0))
            frame = Image.blend(black, frame, f / 15)
        save_frame(frame)
    current_time += INTRO_DUR

    prev_frame = render_intro_card(W, H, title, ch_name, ch_tag, 1.0)

    # ════════════════════════════════════════════
    # CONTENT SECTIONS
    # ════════════════════════════════════════════
    print(f"    Generating {n_sections} sections...")

    for i, sec in enumerate(sections):
        sid = sec.get("id", f"section_{i}")
        dur = sec_durations[i]
        heading = sec.get("heading", "")
        screen_text = sec.get("screen_text", sec.get("narration", ""))
        layout = pick_layout(sec, i)

        mins = int(current_time) // 60
        secs = int(current_time) % 60
        chapters.append({"time": f"{mins}:{secs:02d}", "label": heading or sid})

        print(f"      [{i + 1}/{n_sections}] {sid} ({dur:.1f}s) layout={layout}")

        max_chars = max(45, int((W - 200) / 17))
        wrapped = textwrap.wrap(screen_text, width=max_chars)

        total_sec_frames = max(1, int(dur * FPS))

        first_frame = render_content_frame(
            W, H, bg_images[i], heading, wrapped, 1, 0,
            i + 1, n_sections, ch_name, layout, i,
        )

        if i % 2 == 0:
            trans = crossfade_frames(prev_frame, first_frame, trans_frames)
        else:
            trans = slide_transition(prev_frame, first_frame, trans_frames, "left")
        for tf in trans:
            save_frame(tf)
        current_time += TRANSITION_DUR

        for f in range(total_sec_frames):
            fp = f / total_sec_frames
            global_p = (i + fp) / n_sections
            lines_vis = max(1, int(len(wrapped) * min(1.0, fp * 1.3)))
            frame = render_content_frame(
                W, H, bg_images[i], heading, wrapped, lines_vis, global_p,
                i + 1, n_sections, ch_name, layout, i,
            )
            save_frame(frame)

        current_time += dur

        prev_frame = render_content_frame(
            W, H, bg_images[i], heading, wrapped, len(wrapped), 1.0,
            i + 1, n_sections, ch_name, layout, i,
        )

    # ════════════════════════════════════════════
    # OUTRO
    # ════════════════════════════════════════════
    print(f"    Outro ({OUTRO_DUR}s)...")
    outro_n = int(OUTRO_DUR * FPS)

    outro_first = render_outro_card(W, H, ch_name, 0.3)
    trans = crossfade_frames(prev_frame, outro_first, trans_frames)
    for tf in trans:
        save_frame(tf)

    for f in range(outro_n):
        p = f / outro_n
        frame = render_outro_card(W, H, ch_name, p)
        if f > outro_n - 15:
            remaining = outro_n - f
            black = Image.new("RGB", (W, H), (0, 0, 0))
            frame = Image.blend(frame, black, 1 - remaining / 15)
        save_frame(frame)

    print(f"    Total frames: {frame_num}")

    # ════════════════════════════════════════════
    # FFMPEG ASSEMBLY
    # ════════════════════════════════════════════
    VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    safe_title = re.sub(r"[^a-zA-Z0-9 _-]", "", title).replace(" ", "_")[:60]
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = VIDEO_DIR / f"{ts}_{safe_title}.mp4"

    ffmpeg = _find_ffmpeg()
    print(f"    Assembling with FFmpeg...")

    if bg_music_path and os.path.exists(bg_music_path):
        fade_out_start = str(max(0, audio_dur - 3))
        ffmpeg_cmd = [
            ffmpeg, "-y",
            "-framerate", str(FPS),
            "-i", str(frames_dir / "frame_%06d.png"),
            "-i", str(audio_path),
            "-i", str(bg_music_path),
            "-filter_complex",
            "[1:a]volume=1.0[narration];"
            "[2:a]volume=0.12,afade=t=in:st=0:d=3,"
            f"afade=t=out:st={fade_out_start}:d=3[music];"
            "[narration][music]amix=inputs=2:duration=first[aout]",
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "libx264", "-preset", "medium", "-crf", "21",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest", "-movflags", "+faststart",
            str(output_file),
        ]
    else:
        ffmpeg_cmd = [
            ffmpeg, "-y",
            "-framerate", str(FPS),
            "-i", str(frames_dir / "frame_%06d.png"),
            "-i", str(audio_path),
            "-c:v", "libx264", "-preset", "medium", "-crf", "21",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest", "-movflags", "+faststart",
            str(output_file),
        ]

    result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ERROR: FFmpeg failed:\n{result.stderr[-800:]}")
        sys.exit(1)

    shutil.copy2(output_file, VIDEO_DIR / "latest.mp4")
    shutil.rmtree(frames_dir)

    chapters_file = VIDEO_DIR / "chapters.txt"
    with open(chapters_file, "w", encoding="utf-8") as f:
        for ch in chapters:
            f.write(f"{ch['time']} - {ch['label']}\n")
    print(f"    Chapters saved: {chapters_file}")

    return output_file


def main():
    parser = argparse.ArgumentParser(description="Generate cinematic video v3")
    parser.add_argument("--script", "-s", default=str(SCRIPT_DIR / "latest.json"))
    parser.add_argument("--audio", "-a", default=str(AUDIO_DIR / "latest.mp3"))
    args = parser.parse_args()

    config = load_config()
    print("\n McNeillium_AI — Cinematic Video Generator v3")
    print("=" * 55)

    output = generate_video(args.script, args.audio, config)
    size = output.stat().st_size / (1024 * 1024)
    print(f"\n  Video: {output}")
    print(f"  Size: {size:.1f} MB")


if __name__ == "__main__":
    main()
