#!/usr/bin/env python3
"""
McNeillium_AI — Video Generator v6
====================================
Stock footage, Ken Burns, animated word-by-word captions,
shot list support, stat cards, voice ducking, loudness normalization.
"""

import argparse
import io
import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
import textwrap
import time
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
from captions import generate_ass, load_caption_words, load_verified_words

try:
    from captions_v2 import build_phrase_ass
except ImportError:
    build_phrase_ass = None

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.yaml"
SCRIPT_DIR = PROJECT_ROOT / "output" / "scripts"
AUDIO_DIR = PROJECT_ROOT / "output" / "audio"
VIDEO_DIR = PROJECT_ROOT / "output" / "videos"
MUSIC_DIR = PROJECT_ROOT / "assets" / "music"
CLIP_CACHE = PROJECT_ROOT / "output" / "_clip_cache"
TEMP_DIR = PROJECT_ROOT / "output" / "_temp_v4"


def load_config():
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def load_script(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def get_audio_duration(path):
    try:
        from mutagen.mp3 import MP3
        if path.lower().endswith(".mp3"):
            return MP3(path).info.length
    except Exception:
        pass
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", path], capture_output=True, text=True)
    return float(r.stdout.strip())


def find_ffmpeg():
    """Find ffmpeg binary."""
    # Check PATH first
    r = shutil.which("ffmpeg")
    if r:
        return r
    # Try imageio-ffmpeg
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        pass
    return "ffmpeg"


FFMPEG = find_ffmpeg()


# ═══════════════════════════════════════════════════════════════
# FONTS
# ═══════════════════════════════════════════════════════════════

def _find_font(candidates, size):
    for fp in candidates:
        if os.path.exists(fp):
            return ImageFont.truetype(fp, size)
    return ImageFont.load_default()


def font_heading(sz=48):
    return _find_font([
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
    ], sz)


def font_body(sz=30):
    return _find_font([
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ], sz)


def font_small(sz=18):
    return _find_font([
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ], sz)


# ═══════════════════════════════════════════════════════════════
# COLOURS
# ═══════════════════════════════════════════════════════════════

ACCENTS = [
    (88, 166, 255),    # Blue
    (126, 231, 135),   # Green
    (255, 166, 87),    # Orange
    (188, 140, 255),   # Purple
    (255, 123, 114),   # Red
    (99, 220, 220),    # Teal
]


# ═══════════════════════════════════════════════════════════════
# LAYOUT + KEN BURNS CONFIG
# ═══════════════════════════════════════════════════════════════

LAYOUT_MAP = {
    "hook": "A",
    "intro": "A",
    "main_point_1": "B",
    "main_point_2": "B",
    "main_point_3": "C",
    "demo": "D",
    "summary": "C",
    "outro": "A",
}

KB_SCALE = 1.25

LAYOUT_BG = {
    "A": {"blur": "0:0", "darken": 0.0},
    "B": {"blur": "1:1", "darken": 0.0},
    "C": {"blur": "1:1", "darken": 0.0},
    "D": {"blur": "3:3", "darken": 0.12},
}

COLOUR_GRADE = (
    "eq=brightness=-0.06:contrast=1.1:saturation=0.85,"
    "curves=m='0/0 0.3/0.25 0.7/0.75 1/1'"
    ":r='0/0 0.5/0.52 1/1':b='0/0 0.5/0.48 1/1'"
)


# ═══════════════════════════════════════════════════════════════
# PIXABAY VIDEO API
# ═══════════════════════════════════════════════════════════════

def fetch_stock_video(query, min_duration=8, target_w=1920):
    """
    Fetch a stock video clip from any of: Pexels, Pixabay, Pixabay AI.
    Phase 19 Step 3: delegates to utils.stock_fetcher.fetch_video which
    queries all three in parallel and picks the best-scoring result.
    Falls back to legacy Pixabay-only path if the new fetcher fails.
    """
    # Phase 19: try the multi-source fetcher first.
    # Ensure PROJECT_ROOT is on sys.path so the import resolves when
    # this module is invoked as `python video/generate_video.py`.
    try:
        if str(PROJECT_ROOT) not in sys.path:
            sys.path.insert(0, str(PROJECT_ROOT))
        from utils.stock_fetcher import fetch_video as _multi_fetch
        path = _multi_fetch(query, min_duration=min_duration)
        if path:
            return path
    except Exception as e:
        print(f"        ⚠️  multi-source fetcher errored ({e}); "
              f"falling back to Pixabay-only path")

    # Legacy Pixabay-only path (preserved as fallback)
    api_key = os.getenv("PIXABAY_API_KEY", "")
    if not api_key:
        print(f"        ⚠️  No PIXABAY_API_KEY — skipping video fetch")
        return None

    CLIP_CACHE.mkdir(parents=True, exist_ok=True)

    # Cache check
    safe_q = re.sub(r'[^a-zA-Z0-9]', '_', query)[:50]
    cache_path = CLIP_CACHE / f"{safe_q}.mp4"
    if cache_path.exists() and cache_path.stat().st_size > 10000:
        return str(cache_path)

    try:
        enc = urllib.parse.quote(query)
        url = (f"https://pixabay.com/api/videos/"
               f"?key={api_key}"
               f"&q={enc}"
               f"&video_type=film"
               f"&min_width=1280"
               f"&min_height=720"
               f"&per_page=10")

        with urllib.request.urlopen(url, timeout=15) as resp:
            data = json.loads(resp.read().decode())

        hits = data.get("hits", [])
        if not hits:
            print(f"        ⚠️  No videos found for '{query}'")
            return None

        # Pick a random video from top results for variety
        video = random.choice(hits[:min(5, len(hits))])

        # Prefer "large" (1920x1080), fall back to "medium" (1280x720)
        videos = video.get("videos", {})
        dl_url = None
        for quality in ["large", "medium", "small"]:
            entry = videos.get(quality, {})
            if entry.get("url"):
                dl_url = entry["url"]
                w = entry.get("width", 0)
                h = entry.get("height", 0)
                print(f"        📥 Downloading {w}x{h} clip ({quality})...")
                break

        if not dl_url:
            return None

        req = urllib.request.Request(dl_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            with open(cache_path, "wb") as f:
                f.write(resp.read())
        time.sleep(0.3)
        return str(cache_path)

    except Exception as e:
        print(f"        ⚠️  Video fetch failed for '{query}': {e}")
        return None


def fetch_stock_photo(query):
    """Fallback: fetch a photo from Pixabay if video unavailable."""
    api_key = os.getenv("PIXABAY_API_KEY", "")
    if not api_key:
        return None

    CLIP_CACHE.mkdir(parents=True, exist_ok=True)
    safe_q = re.sub(r'[^a-zA-Z0-9]', '_', query)[:50]
    cache_path = CLIP_CACHE / f"photo_{safe_q}.jpg"

    if cache_path.exists():
        try:
            return Image.open(cache_path).convert("RGB")
        except Exception:
            pass

    try:
        enc = urllib.parse.quote(query)
        url = (f"https://pixabay.com/api/"
               f"?key={api_key}"
               f"&q={enc}"
               f"&image_type=photo"
               f"&orientation=horizontal"
               f"&min_width=1280"
               f"&per_page=5")

        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode())

        hits = data.get("hits", [])
        if not hits:
            return None

        photo = random.choice(hits[:min(5, len(hits))])
        img_url = photo.get("largeImageURL", photo.get("webformatURL"))
        if not img_url:
            return None

        req = urllib.request.Request(img_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            with open(cache_path, "wb") as f:
                f.write(resp.read())
        time.sleep(0.2)
        return Image.open(cache_path).convert("RGB")
    except Exception:
        return None


def section_search_query(section):
    """Generate cinematic search queries for stock footage."""
    sid = section.get("id", "")
    heading = section.get("heading", "")
    narration = section.get("narration", "")[:300].lower()

    cinematic_queries = {
        "hook": "city night aerial drone lights",
        "intro": "server room blue lights close up",
        "outro": "sunset city skyline timelapse",
        "summary": "aerial city lights night drone",
        "demo": "hands typing keyboard dark room",
    }

    if sid in cinematic_queries:
        return cinematic_queries[sid]

    tech_keywords = {
        "agent": "robot arm factory automation close up",
        "privacy": "surveillance camera security dark",
        "google": "server room data center blue lights",
        "openai": "neural network visualization abstract blue",
        "chatgpt": "person using laptop dark room",
        "code": "hands typing keyboard dark room code",
        "data": "data visualization hologram blue light",
        "brain": "brain scan neural connections close up",
        "robot": "robot arm industry automation",
        "cloud": "cloud data center server room blue",
        "phone": "smartphone screen glow dark room",
        "search": "internet browsing screen close up",
        "money": "stock market digital finance display",
        "ad": "digital billboard advertising neon city",
        "learn": "student laptop education digital",
        "future": "futuristic city aerial night",
        "danger": "warning alert red light dark",
        "compete": "chess strategy game close up",
        "launch": "rocket launch technology space",
        "network": "fiber optic cables blue light",
    }

    combined = f"{heading} {narration}".lower()
    for keyword, footage_query in tech_keywords.items():
        if keyword in combined:
            return footage_query

    return f"{heading} technology cinematic" if heading else "technology innovation aerial"


# ═══════════════════════════════════════════════════════════════
# SHOT LIST + CAPTION DATA LOADING
# ═══════════════════════════════════════════════════════════════

SHOT_LIST_PATH = PROJECT_ROOT / "output" / "shot_list.json"
CAPTIONS_DIR = AUDIO_DIR / "captions"


def load_shot_list():
    """Load shot list from Visual Director if it exists."""
    if SHOT_LIST_PATH.exists():
        try:
            with open(SHOT_LIST_PATH, encoding="utf-8") as f:
                data = json.load(f)
            print(f"    📋 Shot list loaded ({len(data.get('sections', []))} sections)")
            return data
        except Exception as e:
            print(f"    ⚠️  Shot list load failed: {e}")
    return None


# ═══════════════════════════════════════════════════════════════
# STAT CARD OVERLAY
# ═══════════════════════════════════════════════════════════════

def _draw_stat_card(draw, w, h, fp, accent, overlay_data):
    """Draw an animated stat card overlay (big number + label + source)."""
    stat = overlay_data.get("stat", "")
    label = overlay_data.get("label", "")
    source = overlay_data.get("source", "")

    if not stat:
        return

    cx, cy = w // 2, h // 2

    if fp < 0.1:
        alpha = int(255 * (fp / 0.1))
        scale = 0.8 + 0.2 * (fp / 0.1)
    elif fp > 0.85:
        alpha = int(255 * ((1.0 - fp) / 0.15))
        scale = 1.0
    else:
        alpha = 255
        scale = 1.0

    card_w, card_h = 600, 300
    rx, ry = cx - card_w // 2, cy - card_h // 2
    draw.rounded_rectangle([rx, ry, rx + card_w, ry + card_h], radius=16,
                           fill=(10, 14, 24, min(220, alpha)))
    draw.rectangle([rx, ry, rx + 5, ry + card_h], fill=(*accent, alpha))

    sf = font_heading(int(72 * scale))
    draw.text((cx, cy - 30), stat, font=sf, fill=(*accent, alpha), anchor="mm")

    lf = font_body(int(26 * scale))
    draw.text((cx, cy + 40), label, font=lf, fill=(220, 228, 236, alpha), anchor="mm")

    if source:
        srf = font_small(14)
        draw.text((cx, cy + 80), source, font=srf, fill=(120, 130, 150, alpha), anchor="mm")


# ═══════════════════════════════════════════════════════════════
# VIDEO CLIP PROCESSING (via FFmpeg)
# ═══════════════════════════════════════════════════════════════

def _kb_crop(effect_idx, duration, w=1920, h=1080):
    """Phase 19b: Ken Burns disabled per aesthetic preference.

    Returns a STATIC centered crop. The KB_SCALE oversize is preserved
    upstream (so the source frame still has headroom for the centered
    crop to land cleanly), but the cursor never moves — the image holds
    still for the full beat duration. This gives a news-anchor feel,
    no zoom or pan.

    The (effect_idx, duration) args are kept in the signature so callers
    don't break, but ignored.
    """
    sw = int(w * KB_SCALE) + int(w * KB_SCALE) % 2
    sh = int(h * KB_SCALE) + int(h * KB_SCALE) % 2
    dx, dy = sw - w, sh - h
    # Centered static crop — Python integer division evaluated here,
    # not in the FFmpeg expression (FFmpeg has no // operator).
    return f"crop={w}:{h}:{dx // 2}:{dy // 2}"


def prepare_clip_segment(clip_path, duration, output_path, w=1920, h=1080,
                         darken=0.0, blur_strength="0:0", kb_effect=0):
    sw = int(w * KB_SCALE) + int(w * KB_SCALE) % 2
    sh = int(h * KB_SCALE) + int(h * KB_SCALE) % 2

    parts = [
        f"scale={sw}:{sh}:force_original_aspect_ratio=increase",
        f"crop={sw}:{sh}",
        _kb_crop(kb_effect, duration, w, h),
    ]
    if blur_strength and blur_strength != "0:0":
        parts.append(f"boxblur={blur_strength}")
    brightness = -0.06 - darken
    parts.append(f"eq=brightness={brightness:.2f}:contrast=1.1:saturation=0.85")
    parts.append(
        "curves=m='0/0 0.3/0.25 0.7/0.75 1/1'"
        ":r='0/0 0.5/0.52 1/1':b='0/0 0.5/0.48 1/1'"
    )
    vf = ",".join(parts)

    cmd = [
        FFMPEG, "-y",
        "-stream_loop", "-1",
        "-i", clip_path,
        "-t", str(duration),
        "-vf", vf,
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-an",
        "-r", "30",
        str(output_path),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"        ⚠️  FFmpeg clip prep failed: {result.stderr[-300:]}")
        return False
    return True


def create_static_clip(image, duration, output_path, w=1920, h=1080, kb_effect=0):
    """Create a video clip from a static image with Ken Burns + colour grade."""
    if image is None:
        arr = np.zeros((h, w, 3), dtype=np.uint8)
        for ch_idx in range(3):
            start = [10, 14, 30][ch_idx]
            end = [25, 35, 60][ch_idx]
            arr[:, :, ch_idx] = np.linspace(start, end, h, dtype=np.uint8)[:, np.newaxis]
        image = Image.fromarray(arr)

    sw = int(w * KB_SCALE) + int(w * KB_SCALE) % 2
    sh = int(h * KB_SCALE) + int(h * KB_SCALE) % 2
    ratio = max(sw / image.width, sh / image.height)
    nw, nh = int(image.width * ratio), int(image.height * ratio)
    image = image.resize((nw, nh), Image.LANCZOS)
    left, top = (nw - sw) // 2, (nh - sh) // 2
    image = image.crop((left, top, left + sw, top + sh))

    temp_img = output_path.parent / f"{output_path.stem}_bg.png"
    image.save(str(temp_img), "PNG")

    kb = _kb_crop(kb_effect, duration, w, h)
    vf = (
        f"{kb},"
        f"eq=brightness=-0.06:contrast=1.1:saturation=0.85,"
        f"curves=m='0/0 0.3/0.25 0.7/0.75 1/1'"
        f":r='0/0 0.5/0.52 1/1':b='0/0 0.5/0.48 1/1'"
    )

    cmd = [
        FFMPEG, "-y",
        "-loop", "1",
        "-i", str(temp_img),
        "-t", str(duration),
        "-vf", vf,
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-r", "30",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    temp_img.unlink(missing_ok=True)
    return result.returncode == 0


# ═══════════════════════════════════════════════════════════════
# BEAT-LEVEL ASSEMBLY (Phase 4)
# Visual Director produces a shot list with multiple "beats" per section
# (one every 5-8 seconds). The Video Producer fetches a clip per beat
# and concatenates them. Stat cards and text overlays become their own
# beats rather than section-wide overlays.
# ═══════════════════════════════════════════════════════════════

MOTION_MAP = {
    "ken_burns_in": 0,
    "ken_burns_out": 1,
    "slow_zoom_in": 0,
    "slow_zoom_out": 1,
    "pan_left": 2,
    "pan_right": 3,
    "diagonal": 4,
    "static": 0,
}


def _render_stat_card_clip(stat, label, source, duration, output_path,
                            w, h, fps, accent):
    """Render a stat card as a single beat clip (static image with fade)."""
    img = Image.new("RGB", (w, h), (6, 10, 20))
    draw = ImageDraw.Draw(img)
    for y in range(h):
        shade = int(6 + 14 * (y / h))
        draw.line([(0, y), (w, y)], fill=(shade, shade + 4, shade + 14))

    cx, cy = w // 2, h // 2
    if stat:
        sf = font_heading(180)
        draw.text((cx + 4, cy - 30 + 4), stat, font=sf,
                  fill=(0, 0, 0), anchor="mm")
        draw.text((cx, cy - 30), stat, font=sf, fill=accent, anchor="mm")
    if label:
        lf = font_body(36)
        draw.text((cx, cy + 80), label, font=lf,
                  fill=(220, 228, 236), anchor="mm")
    if source:
        sff = font_small(18)
        draw.text((cx, cy + 140), source, font=sff,
                  fill=(120, 130, 150), anchor="mm")
    draw.rectangle([cx - 120, cy - 130, cx + 120, cy - 128], fill=accent)

    temp_img = output_path.parent / f"{output_path.stem}_bg.png"
    img.save(str(temp_img), "PNG")
    fade_out_st = max(0.0, duration - 0.3)
    vf = f"fade=t=in:st=0:d=0.3,fade=t=out:st={fade_out_st:.2f}:d=0.3"

    cmd = [
        FFMPEG, "-y",
        "-loop", "1", "-i", str(temp_img),
        "-t", str(duration), "-vf", vf,
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-r", str(fps),
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    temp_img.unlink(missing_ok=True)
    return result.returncode == 0


def _render_text_overlay_clip(text, duration, output_path, w, h, fps, accent):
    """Render a text-overlay beat (title card) as a clip."""
    img = Image.new("RGB", (w, h), (4, 8, 16))
    draw = ImageDraw.Draw(img)
    for y in range(h):
        shade = int(4 + 10 * (y / h))
        draw.line([(0, y), (w, y)], fill=(shade, shade + 2, shade + 8))
    cx, cy = w // 2, h // 2
    sf = font_heading(96)
    draw.text((cx + 4, cy + 4), text, font=sf, fill=(0, 0, 0), anchor="mm")
    draw.text((cx, cy), text, font=sf, fill=accent, anchor="mm")
    draw.rectangle([cx - 200, cy + 75, cx + 200, cy + 78], fill=accent)

    temp_img = output_path.parent / f"{output_path.stem}_bg.png"
    img.save(str(temp_img), "PNG")
    fade_out_st = max(0.0, duration - 0.3)
    vf = f"fade=t=in:st=0:d=0.3,fade=t=out:st={fade_out_st:.2f}:d=0.3"
    cmd = [
        FFMPEG, "-y", "-loop", "1", "-i", str(temp_img),
        "-t", str(duration), "-vf", vf,
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-r", str(fps),
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    temp_img.unlink(missing_ok=True)
    return result.returncode == 0


def build_section_background(section_idx, section_dur, shots,
                              w, h, fps, blur_strength="0:0", darken=0.0):
    """
    Build the background video for a section by assembling beat clips.

    Each shot in `shots` becomes its own clip:
      - "footage"       → fetch a stock clip for shot["query"]
      - "illustration"  → use shot["path"] (pre-rendered Manim MP4)
      - "stat_card"     → render a static stat card image
      - "text_overlay"  → render a title card
      - anything else   → gradient fallback

    Returns the path to the concatenated section bg, or None on failure.
    """
    if not shots:
        return None

    durs = [max(1.0, float(s.get("duration", 5.0))) for s in shots]
    total_d = sum(durs)
    scaled = [d * section_dur / total_d for d in durs]

    beat_paths = []
    accent = ACCENTS[section_idx % len(ACCENTS)]

    for bi, shot in enumerate(shots):
        beat_dur = scaled[bi]
        shot_type = (shot.get("type") or shot.get("shot_type")
                     or "footage").lower()
        beat_path = TEMP_DIR / f"beat_{section_idx:02d}_{bi:02d}.mp4"
        motion = shot.get("motion", "ken_burns_in")
        kb_idx = MOTION_MAP.get(motion, (section_idx + bi) % 5)

        ok = False
        # Phase 12.3: real-asset shot types from the News Asset Collector
        if shot_type in ("person_photo", "company_logo",
                          "article_screenshot"):
            # These are pre-rendered PNGs (styled cards). Use as static
            # clip — Ken Burns is no-op'd in _kb_crop() per Phase 19b.
            asset_path = shot.get("path")
            if asset_path and Path(asset_path).exists():
                try:
                    image = Image.open(asset_path).convert("RGB")
                    ok = create_static_clip(image, beat_dur, beat_path,
                                            w, h, kb_effect=kb_idx)
                except Exception as e:
                    print(f"\n        ⚠️  asset render failed: {e}")

            # Phase 20.4 fallback: when the LLM Visual Director picks a
            # person/company that isn't in the pre-built news_asset
            # manifest, try the entity pack (people) or the stock fetcher
            # (companies) instead of skipping the beat.
            if not ok and shot_type == "person_photo" and shot.get("name"):
                try:
                    if str(PROJECT_ROOT) not in sys.path:
                        sys.path.insert(0, str(PROJECT_ROOT))
                    from utils.entity_pack_builder import (pick_pack_image,
                                                            build_pack, _slug as _eslug)
                    name = shot["name"]
                    slug = _eslug(name)
                    img_path = pick_pack_image(slug)
                    if not img_path:
                        # Build the pack on demand (Wikipedia fetch)
                        build_pack(name, max_images=2)
                        img_path = pick_pack_image(slug)
                    if img_path and img_path.exists():
                        image = Image.open(img_path).convert("RGB")
                        ok = create_static_clip(image, beat_dur, beat_path,
                                                w, h, kb_effect=kb_idx)
                except Exception as e:
                    print(f"\n        ⚠️  pack fallback failed: {e}")

            if not ok and shot_type == "company_logo" and shot.get("company"):
                # Phase 21.1: Simple Icons lookup before stock fallback.
                # 3,294 brand SVGs cover most named companies; for the
                # ~6 commonly-cited brands they exclude (Microsoft,
                # OpenAI, ChatGPT, AWS, Amazon, Cohere) we still fall
                # through to stock_fetcher.
                try:
                    if str(PROJECT_ROOT) not in sys.path:
                        sys.path.insert(0, str(PROJECT_ROOT))
                    from utils.logo_indexer import render_logo_png
                    logo_png = render_logo_png(
                        shot["company"], size=512, accent_bg=True)
                    if logo_png and logo_png.exists():
                        image = Image.open(logo_png).convert("RGB")
                        ok = create_static_clip(image, beat_dur, beat_path,
                                                w, h, kb_effect=0)
                        print("[+SI] ", end="")
                except Exception as e:
                    print(f"\n        ⚠️  Simple Icons fallback failed: {e}")

                # Last resort: stock footage with brand name as query
                if not ok:
                    query = f"{shot['company']} logo"
                    clip = fetch_stock_video(query, min_duration=beat_dur)
                    if clip:
                        ok = prepare_clip_segment(
                            clip, beat_dur, beat_path, w, h,
                            darken=0.0, blur_strength="0:0", kb_effect=0,
                        )

            label_map = {
                "person_photo": shot.get("name", "person"),
                "company_logo": shot.get("company", "logo"),
                "article_screenshot": shot.get("source", "article"),
            }
            print(f"          beat {bi+1}: {shot_type} "
                  f"({label_map[shot_type]}) ", end="")

            # Phase 19b: lower-third name card on person_photo beats.
            # Composites a slide-in label over the static photo. If the
            # overlay step fails, the unmodified beat survives — no
            # render-blocking risk.
            if ok and shot_type == "person_photo" and beat_dur >= 1.5:
                try:
                    sys.path.insert(0, str(PROJECT_ROOT))
                    from utils.motion_graphics import (lower_third as _lt,
                                                       composite as _cmp)
                    name = shot.get("name", "")
                    title = (shot.get("title") or shot.get("role")
                             or shot.get("company") or "")
                    if name:
                        lt_dur = min(4.0, max(2.0, beat_dur - 0.3))
                        lt_path = beat_path.parent / f"{beat_path.stem}_lt.mov"
                        comp_path = beat_path.parent / f"{beat_path.stem}_comp.mp4"
                        _lt(name, title, lt_path, duration=lt_dur)
                        _cmp(beat_path, lt_path, comp_path,
                             x=0, y=0, t_start=0.3)
                        beat_path.unlink()
                        comp_path.rename(beat_path)
                        lt_path.unlink(missing_ok=True)
                        print("[+lt] ", end="")
                except Exception as e:
                    print(f"\n        ⚠️  lower-third failed (kept plain): {e}")
        elif shot_type == "chart":
            # Animated chart MP4 produced by news_asset_collector
            chart_path = shot.get("path")
            if chart_path and Path(chart_path).exists():
                ok = prepare_clip_segment(
                    chart_path, beat_dur, beat_path, w, h,
                    darken=0.0, blur_strength="0:0", kb_effect=0,
                )
            print(f"          beat {bi+1}: chart "
                  f"({shot.get('stat', '?')}) ", end="")
        elif shot_type == "hero":
            # Phase 11: cinematic hero shot via Kling on fal.ai.
            # The shot list should provide either `path` (pre-fetched) or
            # `prompt` (we generate on demand and cache).
            hero_path = shot.get("path")
            if not hero_path or not Path(hero_path).exists():
                prompt = shot.get("prompt") or shot.get("query") or ""
                if prompt:
                    try:
                        sys.path.insert(0, str(PROJECT_ROOT))
                        from utils import kling_via_fal
                        hero_path = kling_via_fal.fetch_hero(
                            prompt, title="",
                        )
                    except Exception as e:
                        print(f"\n        ⚠️  hero fetch failed: {e}")
                        hero_path = None
            if hero_path and Path(hero_path).exists():
                ok = prepare_clip_segment(
                    hero_path, beat_dur, beat_path, w, h,
                    darken=0.0, blur_strength="0:0", kb_effect=kb_idx,
                )
            print(f"          beat {bi+1}: hero ", end="")
        elif shot_type == "illustration":
            ill_path = shot.get("path") or shot.get("illustration_path")
            if ill_path and Path(ill_path).exists():
                ok = prepare_clip_segment(
                    ill_path, beat_dur, beat_path, w, h,
                    darken=0.0, blur_strength="0:0", kb_effect=0,
                )
            print(f"          beat {bi+1}: illustration ", end="")
        elif shot_type in ("ai_image", "ai_image_animated"):
            img_path = shot.get("path") or shot.get("image_path")
            print(f"          beat {bi+1}: ai_image ", end="")
            if img_path and Path(img_path).exists():
                try:
                    image = Image.open(img_path).convert("RGB")
                    ok = create_static_clip(image, beat_dur, beat_path,
                                            w, h, kb_effect=kb_idx)
                except Exception as e:
                    print(f"(load failed: {e}) ", end="")
                    ok = create_static_clip(None, beat_dur, beat_path,
                                            w, h, kb_effect=kb_idx)
        elif shot_type == "concept_illustration":
            # Phase 20.2: render a static concept illustration from
            # utils.concept_illustrations. The LLM Visual Director (Step 1)
            # tags abstract narration moments with concept_illustration +
            # a concept slug. We map slug → drawing → static MP4.
            concept = (shot.get("concept") or shot.get("query") or "").strip()
            try:
                if str(PROJECT_ROOT) not in sys.path:
                    sys.path.insert(0, str(PROJECT_ROOT))
                from utils.concept_illustrations import (render_concept,
                                                          match_concept)
                slug = match_concept(concept)
                if slug:
                    out = render_concept(concept, beat_dur, beat_path,
                                         w=w, h=h)
                    ok = out is not None
                    print(f"          beat {bi+1}: concept ('{slug}') ", end="")
                else:
                    print(f"          beat {bi+1}: concept "
                          f"(no match for '{concept[:30]}', "
                          f"falling back to footage) ", end="")
                    ok = False
            except Exception as e:
                print(f"\n        ⚠️  concept render failed: {e}")
                ok = False
            # Fall back to stock footage if no concept match
            if not ok:
                query = shot.get("query") or concept or "abstract technology"
                clip = fetch_stock_video(query, min_duration=beat_dur)
                if clip:
                    ok = prepare_clip_segment(
                        clip, beat_dur, beat_path, w, h,
                        darken=0.0, blur_strength="0:0", kb_effect=0,
                    )
        elif shot_type == "stat_card":
            overlay = shot.get("overlay_data", {})
            stat = shot.get("stat") or overlay.get("stat", "")
            label = shot.get("label") or overlay.get("label", "")
            source = shot.get("source") or overlay.get("source", "")
            ok = _render_stat_card_clip(
                stat, label, source, beat_dur, beat_path,
                w, h, fps, accent,
            )
            print(f"          beat {bi+1}: stat_card '{stat}' ", end="")
        elif shot_type == "text_overlay":
            txt = shot.get("text") or shot.get("query") or "..."
            ok = _render_text_overlay_clip(
                txt, beat_dur, beat_path, w, h, fps, accent,
            )
            print(f"          beat {bi+1}: text '{txt[:24]}' ", end="")
        else:
            query = shot.get("query") or shot.get("footage_query") or ""
            print(f"          beat {bi+1}: '{query[:40]}' ", end="")
            if query:
                clip = fetch_stock_video(query, min_duration=int(beat_dur) + 2)
                if clip:
                    ok = prepare_clip_segment(
                        clip, beat_dur, beat_path, w, h,
                        darken=darken, blur_strength=blur_strength,
                        kb_effect=kb_idx,
                    )
                if not ok:
                    photo = fetch_stock_photo(query)
                    ok = create_static_clip(photo, beat_dur, beat_path,
                                            w, h, kb_effect=kb_idx)
            else:
                ok = create_static_clip(None, beat_dur, beat_path,
                                        w, h, kb_effect=kb_idx)

        if ok and beat_path.exists():
            beat_paths.append(str(beat_path))
            print("✅")
        else:
            print("⚠️  (skipped)")

    if not beat_paths:
        return None

    concat_list = TEMP_DIR / f"section_{section_idx:02d}_beats.txt"
    with open(concat_list, "w") as f:
        for bp in beat_paths:
            f.write(f"file '{bp}'\n")

    section_bg = TEMP_DIR / f"section_bg_{section_idx:02d}.mp4"
    cmd = [
        FFMPEG, "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(concat_list),
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-r", str(fps),
        str(section_bg),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"        ⚠️  Section concat failed: {result.stderr[-200:]}")
        return None
    return str(section_bg)


# ═══════════════════════════════════════════════════════════════
# OVERLAY GENERATION (Phase 4: minimal — progress bar + stat cards only)
# Word-by-word captions are rendered separately as ASS subtitles
# (see captions.py + STEP 6 below). This avoids the doubled-text issue.
# ═══════════════════════════════════════════════════════════════


def create_text_overlay_frames(
    duration, w, h, fps, section_num, total_sections,
    accent, stat_overlay=None
):
    """
    Generate transparent overlay frames containing only:
    - A thin 3px progress bar across the top of the frame
    - The animated stat card (when a beat declares one)

    Headings, bullets, and the channel-name bar were removed in Phase 4;
    word captions handle all text communication via the ASS overlay step.
    """
    frames_dir = TEMP_DIR / f"overlay_{section_num}"
    frames_dir.mkdir(parents=True, exist_ok=True)
    total_frames = int(duration * fps)

    for f_idx in range(total_frames):
        fp = f_idx / max(1, total_frames - 1)
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        draw.rectangle([0, 0, w, 3], fill=(30, 30, 30, 140))
        prog = (section_num - 1 + fp) / total_sections
        draw.rectangle([0, 0, int(w * prog), 3], fill=(*accent, 220))

        if stat_overlay:
            _draw_stat_card(draw, w, h, fp, accent, stat_overlay)

        frame_path = frames_dir / f"overlay_{f_idx:06d}.png"
        img.save(str(frame_path), "PNG")

    return str(frames_dir / "overlay_%06d.png"), total_frames


# ═══════════════════════════════════════════════════════════════
# INTRO / OUTRO GENERATORS
# ═══════════════════════════════════════════════════════════════

def generate_intro_clip(title, channel_name, tagline, duration, w, h, fps, output_path):
    """Generate a cinematic intro clip."""
    total_frames = int(duration * fps)
    frames_dir = TEMP_DIR / "intro_frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    for f_idx in range(total_frames):
        p = f_idx / max(1, total_frames - 1)
        img = Image.new("RGB", (w, h), (6, 10, 18))
        draw = ImageDraw.Draw(img)

        # Gradient
        for y in range(h):
            r = int(6 + 14 * (y / h))
            g = int(10 + 18 * (y / h))
            b = int(18 + 32 * (y / h))
            draw.line([(0, y), (w, y)], fill=(r, g, b))

        cx, cy = w // 2, h // 2

        # Expanding accent lines
        line_w = int(250 * min(1.0, p * 2.5))
        draw.rectangle([cx - line_w, cy - 48, cx + line_w, cy - 46],
                       fill=(88, 166, 255))
        draw.rectangle([cx - line_w, cy + 48, cx + line_w, cy + 50],
                       fill=(88, 166, 255))

        # Channel name
        if p > 0.08:
            a = min(1.0, (p - 0.08) * 5)
            c = tuple(int(v * a) for v in (88, 166, 255))
            draw.text((cx, cy - 80), channel_name, font=font_heading(60),
                      fill=c, anchor="mm")

        # Tagline
        if p > 0.2:
            a = min(1.0, (p - 0.2) * 5)
            c = tuple(int(v * a) for v in (160, 170, 185))
            draw.text((cx, cy - 22), tagline, font=font_body(24),
                      fill=c, anchor="mm")

        # Title
        if p > 0.35:
            a = min(1.0, (p - 0.35) * 3)
            offset = int(25 * (1 - a))
            c = tuple(int(v * a) for v in (230, 237, 243))
            f = font_heading(40)
            max_ch = (w - 200) // 22
            tlines = textwrap.wrap(title, width=max_ch)
            for j, tl in enumerate(tlines):
                draw.text((cx, cy + 70 + j * 50 + offset), tl,
                          font=f, fill=c, anchor="mm")

        # Fade from black
        if f_idx < 15:
            black = Image.new("RGB", (w, h), (0, 0, 0))
            img = Image.blend(black, img, f_idx / 15)

        path = frames_dir / f"frame_{f_idx:06d}.png"
        img.save(str(path), "PNG")

    # Encode to clip
    cmd = [FFMPEG, "-y", "-framerate", str(fps),
           "-i", str(frames_dir / "frame_%06d.png"),
           "-c:v", "libx264", "-preset", "ultrafast",
           "-crf", "23", "-pix_fmt", "yuv420p",
           str(output_path)]
    subprocess.run(cmd, capture_output=True, text=True)
    shutil.rmtree(frames_dir)


def generate_outro_clip(channel_name, duration, w, h, fps, output_path,
                        teaser_text=None):
    """Generate branded outro clip with optional end screen teaser."""
    total_frames = int(duration * fps)
    frames_dir = TEMP_DIR / "outro_frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    for f_idx in range(total_frames):
        p = f_idx / max(1, total_frames - 1)
        img = Image.new("RGB", (w, h), (6, 10, 18))
        draw = ImageDraw.Draw(img)

        for y in range(h):
            draw.line([(0, y), (w, y)],
                      fill=(int(6 + 10 * y / h), int(10 + 14 * y / h), int(18 + 28 * y / h)))

        cx, cy = w // 2, h // 2

        if p > 0.05:
            a = min(1.0, (p - 0.05) * 4)
            draw.text((cx, cy - 45), "LIKE & SUBSCRIBE",
                      font=font_heading(52), fill=tuple(int(v * a) for v in (88, 166, 255)),
                      anchor="mm")

        if p > 0.2:
            a = min(1.0, (p - 0.2) * 4)
            draw.text((cx, cy + 15), "for more AI content",
                      font=font_body(28), fill=tuple(int(v * a) for v in (160, 170, 185)),
                      anchor="mm")

        if p > 0.35:
            a = min(1.0, (p - 0.35) * 4)
            draw.text((cx, cy + 75), channel_name,
                      font=font_heading(30), fill=tuple(int(v * a) for v in (230, 237, 243)),
                      anchor="mm")

        lw = int(180 * min(1.0, p * 2))
        draw.rectangle([cx - lw, cy + 115, cx + lw, cy + 117], fill=(88, 166, 255))

        # Fade to black at end
        if f_idx > total_frames - 15:
            remaining = total_frames - f_idx
            black = Image.new("RGB", (w, h), (0, 0, 0))
            img = Image.blend(img, black, 1 - remaining / 15)

        path = frames_dir / f"frame_{f_idx:06d}.png"
        img.save(str(path), "PNG")

    cmd = [FFMPEG, "-y", "-framerate", str(fps),
           "-i", str(frames_dir / "frame_%06d.png"),
           "-c:v", "libx264", "-preset", "ultrafast",
           "-crf", "23", "-pix_fmt", "yuv420p",
           str(output_path)]
    subprocess.run(cmd, capture_output=True, text=True)
    shutil.rmtree(frames_dir)


def generate_end_screen_ass(total_duration_s, teaser_text, output_path,
                            width=1920, height=1080):
    """Generate ASS overlay for last 15 seconds: teaser card + subscribe nudge."""
    end_screen_dur = min(15.0, total_duration_s - 5.0)
    if end_screen_dur < 3.0:
        return None

    start_ms = (total_duration_s - end_screen_dur) * 1000
    end_ms = total_duration_s * 1000

    margin_r = int(width * 0.05)
    margin_top = int(height * 0.12)

    teaser_display = teaser_text[:50] if teaser_text else "Next video coming soon..."

    def _ts(ms):
        total_cs = int(ms / 10)
        cs = total_cs % 100
        total_s = total_cs // 100
        s = total_s % 60
        m = (total_s // 60) % 60
        h_val = total_s // 3600
        return f"{h_val}:{m:02d}:{s:02d}.{cs:02d}"

    ass = f"""[Script Info]
Title: McNeillium_AI End Screen
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Teaser,Arial Black,34,&H0000FFFF,&H000000FF,&H00000000,&HC8000000,-1,0,0,0,100,100,0,0,3,3,4,3,20,{margin_r},{margin_top},1
Style: TeaserLabel,Arial,22,&H00FFFFFF,&H000000FF,&H00000000,&HC8000000,0,0,0,0,100,100,0,0,3,2,3,3,20,{margin_r},{margin_top + 45},1
Style: SubNudge,Arial,24,&H4DFFFFFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,2,2,2,20,20,30,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 1,{_ts(start_ms + 500)},{_ts(end_ms - 2000)},TeaserLabel,,0,0,0,,{{\\fad(600,400)}}UP NEXT
Dialogue: 1,{_ts(start_ms + 800)},{_ts(end_ms - 2000)},Teaser,,0,0,0,,{{\\fad(700,400)}}{teaser_display}
Dialogue: 1,{_ts(start_ms + 1500)},{_ts(end_ms - 1000)},SubNudge,,0,0,0,,{{\\fad(500,500)}}Subscribe for more AI content
"""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8-sig") as f:
        f.write(ass)
    return str(out)


# ═══════════════════════════════════════════════════════════════
# SECTION CLIP ASSEMBLY
# ═══════════════════════════════════════════════════════════════

def assemble_section_clip(
    bg_clip_path, overlay_pattern, n_overlay_frames,
    duration, output_path, w, h, fps
):
    """
    Overlay transparent text PNGs onto a background video clip.
    This is where the magic happens — real video + animated text.
    """
    cmd = [
        FFMPEG, "-y",
        "-i", bg_clip_path,
        "-framerate", str(fps),
        "-i", overlay_pattern,
        "-filter_complex",
        f"[0:v]scale={w}:{h},setpts=PTS-STARTPTS[bg];"
        f"[1:v]format=rgba,setpts=PTS-STARTPTS[fg];"
        f"[bg][fg]overlay=0:0:shortest=1[out]",
        "-map", "[out]",
        "-t", str(duration),
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "22",
        "-pix_fmt", "yuv420p",
        "-r", str(fps),
        str(output_path),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"        ⚠️  Section assembly failed: {result.stderr[-400:]}")
        return False
    return True


# ═══════════════════════════════════════════════════════════════
# MAIN PIPELINE
# ═══════════════════════════════════════════════════════════════

def generate_video(script_path, audio_path, config):
    """Build the complete video with stock footage backgrounds."""
    vc = config.get("video", {})
    W = vc.get("width", 1920)
    H = vc.get("height", 1080)
    FPS = vc.get("fps", 30)
    ch = config.get("channel", {})
    ch_name = ch.get("name", "McNeillium_AI")
    ch_tag = ch.get("tagline", "AI & Emerging Tech")

    script = load_script(script_path)
    sections = script.get("sections", [])
    n_secs = len(sections)
    title = script.get("title", "Untitled")

    audio_dur = get_audio_duration(audio_path)
    print(f"    🎵 Audio: {audio_dur:.1f}s")

    shot_list = load_shot_list()

    # Clean temp
    if TEMP_DIR.exists():
        shutil.rmtree(TEMP_DIR)
    TEMP_DIR.mkdir(parents=True)

    # ── Logo intro ──
    LOGO_PATH = PROJECT_ROOT / "assets" / "logo_intro" / "mcneillium_intro.mp4"
    LOGO_DUR = 3.0 if LOGO_PATH.exists() else 0.0

    # ── Timing ──
    INTRO_DUR = 3.5
    OUTRO_DUR = 3.5
    FADE_DUR = 0.8
    content_dur = audio_dur - INTRO_DUR - OUTRO_DUR

    char_counts = [len(s.get("narration", "")) for s in sections]
    total_chars = sum(char_counts) or 1
    sec_durs = [(c / total_chars) * content_dur for c in char_counts]

    chapters = [{"time": "0:00", "label": "Intro"}]
    current_time = INTRO_DUR

    # ════════════════════════════════════════════
    # STEP 1: Index shot list by section
    # ════════════════════════════════════════════
    print(f"\n    📹 STEP 1: Indexing shot list for {n_secs} sections...")
    shot_section_data = {}
    if shot_list:
        for i, sec in enumerate(sections):
            sid = sec.get("id", f"section_{i}")
            for sl_s in shot_list.get("sections", []):
                if sl_s.get("section_id") == sid:
                    shot_section_data[i] = sl_s
                    break

    beat_counts = [
        len(shot_section_data.get(i, {}).get("shots", []))
        for i in range(n_secs)
    ]
    total_beats = sum(beat_counts)
    if total_beats:
        print(f"      📋 Total beats planned: {total_beats} "
              f"(avg {total_beats / n_secs:.1f}/section)")
    else:
        print(f"      ⚠️  No shot list — will fall back to section-level fetch")

    # ════════════════════════════════════════════
    # STEP 2: Generate intro
    # ════════════════════════════════════════════
    print(f"\n    🎬 STEP 2: Generating intro clip ({INTRO_DUR}s)...")
    intro_path = TEMP_DIR / "intro.mp4"
    generate_intro_clip(title, ch_name, ch_tag, INTRO_DUR, W, H, FPS, intro_path)

    # ════════════════════════════════════════════
    # STEP 3: Generate section clips
    # ════════════════════════════════════════════
    print(f"\n    🎞  STEP 3: Building {n_secs} section clips...")
    section_clip_paths = []

    for i, sec in enumerate(sections):
        sid = sec.get("id", f"section_{i}")
        dur = sec_durs[i]
        heading = sec.get("heading", "")
        accent = ACCENTS[i % len(ACCENTS)]
        layout = LAYOUT_MAP.get(sid, "B")
        bg_p = LAYOUT_BG.get(layout, {"blur": "0:0", "darken": 0.0})

        mins = int(current_time) // 60
        secs_t = int(current_time) % 60
        chapters.append({"time": f"{mins}:{secs_t:02d}", "label": heading or sid})
        current_time += dur

        shots = shot_section_data.get(i, {}).get("shots", [])
        bg_clip_path = TEMP_DIR / f"bg_{i:02d}.mp4"

        print(f"      [{i+1}/{n_secs}] {sid} ({dur:.1f}s) "
              f"— {len(shots) if shots else 1} beat(s)")

        section_bg = None
        if shots:
            section_bg = build_section_background(
                i, dur, shots, W, H, FPS,
                blur_strength=bg_p["blur"], darken=bg_p["darken"],
            )

        if section_bg:
            shutil.copy2(section_bg, bg_clip_path)
        else:
            # Fallback: single-clip section-level fetch
            query = section_search_query(sec)
            print(f"        📥 Section-level fallback: '{query}'")
            clip = fetch_stock_video(query, min_duration=int(dur) + 2)
            kb_idx = i % 5
            if clip:
                ok = prepare_clip_segment(
                    clip, dur, bg_clip_path, W, H,
                    darken=bg_p["darken"], blur_strength=bg_p["blur"],
                    kb_effect=kb_idx,
                )
                if not ok:
                    create_static_clip(None, dur, bg_clip_path, W, H,
                                       kb_effect=kb_idx)
            else:
                photo = fetch_stock_photo(query)
                create_static_clip(photo, dur, bg_clip_path, W, H,
                                   kb_effect=kb_idx)

        overlay_pattern, n_frames = create_text_overlay_frames(
            dur, W, H, FPS, i + 1, n_secs, accent,
            stat_overlay=None,
        )

        # Composite: video background + text overlay
        section_path = TEMP_DIR / f"section_{i:02d}.mp4"
        ok = assemble_section_clip(
            str(bg_clip_path), overlay_pattern, n_frames,
            dur, section_path, W, H, FPS
        )

        if ok:
            section_clip_paths.append(str(section_path))
            print("✅")
        else:
            # Fallback: use bg clip directly
            section_clip_paths.append(str(bg_clip_path))
            print("⚠️ (no overlay)")

        # Clean overlay frames
        overlay_dir = TEMP_DIR / f"overlay_{i + 1}"
        if overlay_dir.exists():
            shutil.rmtree(overlay_dir)

    # ════════════════════════════════════════════
    # STEP 4: Generate outro
    # ════════════════════════════════════════════
    print(f"\n    🎬 STEP 4: Generating outro clip ({OUTRO_DUR}s)...")
    outro_path = TEMP_DIR / "outro.mp4"
    generate_outro_clip(ch_name, OUTRO_DUR, W, H, FPS, outro_path)

    # ════════════════════════════════════════════
    # STEP 5: Concatenate all clips + add audio
    # ════════════════════════════════════════════
    print(f"\n    🔧 STEP 5: Final assembly...")

    # Write concat list
    concat_list = TEMP_DIR / "concat.txt"
    with open(concat_list, "w") as f:
        if LOGO_PATH.exists():
            f.write(f"file '{LOGO_PATH}'\n")
            print(f"    🎨 Logo intro prepended ({LOGO_DUR}s)")
        f.write(f"file '{intro_path}'\n")
        for sp in section_clip_paths:
            f.write(f"file '{sp}'\n")
        f.write(f"file '{outro_path}'\n")

    # Concat all video clips
    concat_path = TEMP_DIR / "concat.mp4"
    cmd = [
        FFMPEG, "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(concat_list),
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "22",
        "-pix_fmt", "yuv420p",
        str(concat_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ERROR concat: {result.stderr[-500:]}")
        sys.exit(1)

    # Add narration audio (and background music if available)
    VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    safe_title = re.sub(r'[^a-zA-Z0-9 _-]', '', title).replace(' ', '_')[:60]
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = VIDEO_DIR / f"{ts}_{safe_title}.mp4"
    latest = VIDEO_DIR / "latest.mp4"

    bg_music = MUSIC_DIR / "ambient_tech.mp3"
    has_music = bg_music.exists()

    # Phase 10.1: per-mode mix settings. Explainer: deeper ducking,
    # quieter base music, -16 LUFS so the voice sits forward.
    mode_cfg_path = PROJECT_ROOT / "output" / "mode_config.json"
    mix_mode = "fireship"
    if mode_cfg_path.exists():
        try:
            mix_mode = json.loads(mode_cfg_path.read_text(encoding="utf-8")).get("mode", "fireship")
        except Exception:
            pass
    if mix_mode == "explainer":
        # Voice sits far forward, music near-silent under speech, -16 LUFS
        music_vol = 0.08
        duck_ratio = 20
        target_lufs = -16
    elif mix_mode == "reaction":
        # Slightly hotter than explainer but voice still has to win — the
        # baseline music level is just below voice and ducking pulls it
        # ~10dB deeper when speech is active.
        music_vol = 0.10
        duck_ratio = 10
        target_lufs = -14
    else:
        # fireship / tutorial / default — energetic, music more present
        music_vol = 0.12
        duck_ratio = 6
        target_lufs = -14
    print(f"    🎚  Mix: mode={mix_mode}, music_vol={music_vol}, "
          f"duck_ratio={duck_ratio}, target {target_lufs} LUFS")

    if has_music:
        print(f"    🎵 Mixing narration + background music (voice ducking)...")
        cmd = [
            FFMPEG, "-y",
            "-i", str(concat_path),
            "-i", str(audio_path),
            "-i", str(bg_music),
            "-filter_complex",
            "[1:a]aformat=fltp:44100:stereo,asplit[narr][sc];"
            f"[2:a]aformat=fltp:44100:stereo,volume={music_vol},"
            f"afade=t=in:st=0:d=3,afade=t=out:st={max(0, audio_dur - 3)}:d=3[music];"
            f"[music][sc]sidechaincompress=threshold=0.02:ratio={duck_ratio}:attack=200:release=1000[ducked];"
            "[narr][ducked]amix=inputs=2:duration=first,"
            f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11[aout]",
            "-map", "0:v",
            "-map", "[aout]",
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            "-movflags", "+faststart",
            str(output_file),
        ]
    else:
        print(f"    🎵 Adding narration audio (normalized)...")
        cmd = [
            FFMPEG, "-y",
            "-i", str(concat_path),
            "-i", str(audio_path),
            "-map", "0:v",
            "-map", "1:a",
            "-c:v", "copy",
            "-af", f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            "-movflags", "+faststart",
            str(output_file),
        ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ERROR final: {result.stderr[-500:]}")
        sys.exit(1)

    # ════════════════════════════════════════════
    # STEP 6: Burn ASS captions (if word timestamps exist)
    # ════════════════════════════════════════════
    section_indices = [
        (i, sec.get("id", f"section_{i}")) for i, sec in enumerate(sections)
    ]
    section_offsets_ms = []
    offset = (LOGO_DUR + INTRO_DUR) * 1000
    for dur_s in sec_durs:
        section_offsets_ms.append(offset)
        offset += dur_s * 1000

    # Phase 12.1: be LOUD about which timestamp source is feeding captions.
    # The verified file is the ground truth (AssemblyAI in Phase 11+, or
    # Whisper in earlier runs). The ElevenLabs / Edge TTS per-section
    # fallback is much less accurate — surface that as a banner warning.
    verified_path = AUDIO_DIR / "latest_words_verified.json"
    audio_start_ms = (LOGO_DUR + INTRO_DUR) * 1000
    caption_words = load_verified_words(str(verified_path), audio_start_ms)

    # Inspect the verified file's asr_source metadata if present
    verified_source = "unknown"
    try:
        if verified_path.exists():
            _vdata = json.loads(verified_path.read_text(encoding="utf-8"))
            verified_source = (_vdata.get("asr_source")
                                or "verified (legacy format)")
    except Exception:
        pass

    if caption_words:
        print(f"\n    📝 CAPTION SOURCE: ✅ "
              f"{verified_path.name}  ({verified_source}, "
              f"{len(caption_words)} words)")
    else:
        # Fall back to the per-section ElevenLabs / Edge TTS captions.
        # This is much less accurate — flag it prominently.
        print(f"\n    📝 CAPTION SOURCE: ⚠️  ⚠️  ⚠️")
        print(f"    📝 CAPTION SOURCE: latest_words_verified.json "
              f"NOT FOUND at {verified_path}")
        print(f"    📝 CAPTION SOURCE: Falling back to per-section "
              f"TTS timestamps (ElevenLabs / Edge TTS).")
        print(f"    📝 CAPTION SOURCE: These are less accurate. "
              f"Run utils/assemblyai_verify.py before next render.")
        print(f"    📝 CAPTION SOURCE: ⚠️  ⚠️  ⚠️\n")
        caption_words = load_caption_words(
            str(CAPTIONS_DIR), section_indices, section_offsets_ms
        )

    # Build VF filter chain: captions + end screen overlay
    vf_filters = []
    TEMP_DIR.mkdir(parents=True, exist_ok=True)

    # Phase 12.2: caption_style="none" → skip the entire captions burn.
    # All long-form modes (reaction / explainer / tutorial / fireship)
    # are now caption-free; viewers toggle YouTube's auto-CC for
    # accessibility. Shorts get their own subtitle pass downstream.
    mode_cfg_path = PROJECT_ROOT / "output" / "mode_config.json"
    mode = "reaction"
    caption_style = "none"
    if mode_cfg_path.exists():
        try:
            cfg = json.loads(mode_cfg_path.read_text(encoding="utf-8"))
            mode = cfg.get("mode", "reaction")
            caption_style = cfg.get("caption_style", "none")
        except Exception:
            pass
    if caption_style == "none":
        print(f"\n    📝 STEP 6: captions DISABLED ({mode} mode, "
              f"long-form). YouTube auto-CC handles accessibility.")
        caption_words = []  # short-circuit the rest of the captions block

    if caption_words:
        palette_terms = {}
        palette_path = PROJECT_ROOT / "output" / "color_palette.json"
        if palette_path.exists():
            try:
                pdata = json.loads(palette_path.read_text(encoding="utf-8"))
                for term, hex_c in pdata.get("term_colours", {}).items():
                    h = hex_c.lstrip("#")
                    if len(h) == 6:
                        r, g, b = h[0:2], h[2:4], h[4:6]
                        palette_terms[term.lower()] = (
                            f"&H00{b}{g}{r}".upper()
                        )
            except Exception:
                pass

        ass_path = TEMP_DIR / "captions.ass"
        # Phase 11+: route every mode through the viral renderer. It
        # handles reaction (word-by-word, Impact 104pt) and explainer/
        # tutorial (3-word phrase groups, Impact 96pt) internally.
        if build_phrase_ass is not None:
            print(f"\n    📝 STEP 6: Burning viral captions "
                  f"({mode} mode, {len(caption_words)} words)...")
            _, n_lines = build_phrase_ass(
                caption_words, str(ass_path), W, H,
                palette=palette_terms, mode=mode,
            )
            print(f"        {n_lines} caption dialogue lines rendered")
        else:
            print(f"\n    📝 STEP 6: Burning "
                  f"{len(caption_words)} word captions (legacy)...")
            generate_ass(caption_words, str(ass_path), W, H)
        ass_escaped = str(ass_path).replace("\\", "/").replace(":", "\\:")
        vf_filters.append(f"ass='{ass_escaped}'")
    elif caption_style != "none":
        print(f"\n    ⚠️  No word timestamps available — skipping captions")

    # End screen teaser overlay (last 15 seconds)
    end_screen_meta = script.get("metadata", {}).get("end_screen", {})
    teaser_text = end_screen_meta.get("teaser_text", "")
    if not teaser_text:
        outro_section = next((s for s in sections if s.get("id") == "outro"), None)
        if outro_section:
            teaser_text = outro_section.get("end_screen_teaser", "")

    video_dur = get_audio_duration(str(output_file))
    if teaser_text and video_dur > 20:
        print(f"    🎬 End screen teaser: \"{teaser_text[:40]}...\"")
        endscreen_ass = TEMP_DIR / "endscreen.ass"
        es_path = generate_end_screen_ass(video_dur, teaser_text, str(endscreen_ass), W, H)
        if es_path:
            es_escaped = str(endscreen_ass).replace("\\", "/").replace(":", "\\:")
            vf_filters.append(f"ass='{es_escaped}'")

    if vf_filters:
        # Phase 19b: force a fully Windows-compatible final encode.
        # 8-bit yuv420p, BT.709 colorspace tags, main profile, faststart.
        # `format=yuv420p` is appended to the filter chain so any
        # upstream filter that promotes to yuv444p (color grade, lut3d)
        # is forced back down before encoding.
        vf_chain = ",".join(vf_filters) + ",format=yuv420p"
        captioned_file = output_file.parent / f"{output_file.stem}_captioned.mp4"
        cap_cmd = [
            FFMPEG, "-y",
            "-i", str(output_file),
            "-vf", vf_chain,
            "-c:v", "libx264",
            "-profile:v", "main",
            "-pix_fmt", "yuv420p",
            "-colorspace", "bt709",
            "-color_primaries", "bt709",
            "-color_trc", "bt709",
            "-preset", "medium",
            "-crf", "20",
            "-c:a", "copy",
            "-movflags", "+faststart",
            str(captioned_file),
        ]
        cap_result = subprocess.run(cap_cmd, capture_output=True, text=True)
        if cap_result.returncode == 0:
            output_file.unlink()
            captioned_file.rename(output_file)
            print(f"    ✅ Captions + end screen burned in successfully")
        else:
            print(f"    ⚠️  Overlay burn failed (video still usable)")
            print(f"        {cap_result.stderr[-300:]}")
            captioned_file.unlink(missing_ok=True)

    # ════════════════════════════════════════════
    # STEP 7: 2-pass loudnorm — single-pass leaves up to ~2 dB error
    # ════════════════════════════════════════════
    print(f"\n    🎚  STEP 7: 2-pass loudnorm targeting {target_lufs} LUFS...")
    measure_cmd = [
        FFMPEG, "-hide_banner", "-nostats",
        "-i", str(output_file),
        "-af", f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11:print_format=json",
        "-f", "null", "-",
    ]
    mres = subprocess.run(measure_cmd, capture_output=True, text=True)
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", mres.stderr, re.S)
    if m:
        try:
            stats = json.loads(m.group(0))
            normalized = output_file.with_name(output_file.stem + "_norm.mp4")
            apply_cmd = [
                FFMPEG, "-hide_banner", "-y", "-i", str(output_file),
                "-af",
                f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11:linear=true:"
                f"measured_I={stats['input_i']}:"
                f"measured_TP={stats['input_tp']}:"
                f"measured_LRA={stats['input_lra']}:"
                f"measured_thresh={stats['input_thresh']}:"
                f"offset={stats['target_offset']}",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                "-movflags", "+faststart",
                str(normalized),
            ]
            ar = subprocess.run(apply_cmd, capture_output=True, text=True)
            if ar.returncode == 0 and normalized.exists():
                output_file.unlink()
                normalized.rename(output_file)
                print(f"        ✅ measured {stats['input_i']} → corrected")
            else:
                normalized.unlink(missing_ok=True)
                print(f"        ⚠️  2-pass apply failed: {ar.stderr[-200:]}")
        except Exception as e:
            print(f"        ⚠️  2-pass parse failed: {e}")
    else:
        print(f"        ⚠️  Could not measure loudness — keeping single-pass result")

    shutil.copy2(output_file, latest)

    # Save chapters
    chap_file = VIDEO_DIR / "chapters.txt"
    with open(chap_file, "w") as f:
        for c in chapters:
            f.write(f"{c['time']} - {c['label']}\n")

    # Clean up
    shutil.rmtree(TEMP_DIR, ignore_errors=True)

    return output_file


def main():
    parser = argparse.ArgumentParser(description="Generate video with stock footage (v4)")
    parser.add_argument("--script", "-s", default=str(SCRIPT_DIR / "latest.json"))
    parser.add_argument("--audio", "-a", default=str(AUDIO_DIR / "latest.mp3"))
    args = parser.parse_args()

    config = load_config()
    print("\n🎬 McNeillium_AI — Professional Video Generator v6")
    print("=" * 55)

    output = generate_video(args.script, args.audio, config)
    size = output.stat().st_size / (1024 * 1024)
    dur = get_audio_duration(str(output))

    print(f"\n  ✅ Video: {output}")
    print(f"  📦 Size: {size:.1f} MB")
    print(f"  ⏱  Duration: {int(dur) // 60}m {int(dur) % 60}s")
    print(f"  🎵 Background music: {'Yes' if (MUSIC_DIR / 'ambient_tech.mp3').exists() else 'No'}")


if __name__ == "__main__":
    main()
