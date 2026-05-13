#!/usr/bin/env python3
"""
McNeillium_AI — Video Generator v4 (Stock Footage)
====================================================
Uses REAL stock video clips from Pexels as section backgrounds.
No more static slides — every section has motion.

Pipeline:
  1. For each script section, fetch a relevant HD stock video from Pexels
  2. Trim/loop the clip to match section duration
  3. Darken + blur the footage for text readability
  4. Overlay branded text, headings, and bullets using Pillow
  5. Composite everything with FFmpeg
  6. Mix in background music at low volume
  7. Add fade transitions between sections
"""

import argparse
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
CLIP_CACHE = PROJECT_ROOT / "output" / "_clip_cache"
TEMP_DIR = PROJECT_ROOT / "output" / "_temp_v4"


def load_config():
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def load_script(path):
    with open(path) as f:
        return json.load(f)


def get_audio_duration(path):
    try:
        from mutagen.mp3 import MP3
        return MP3(path).info.length
    except ImportError:
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
# PEXELS VIDEO API
# ═══════════════════════════════════════════════════════════════

def fetch_pexels_video(query, min_duration=8, target_w=1920):
    """
    Fetch a stock video clip from Pexels. Returns path to downloaded MP4 or None.
    Uses the Pexels Video Search API (same API key as photos).
    """
    api_key = os.getenv("PEXELS_API_KEY", "")
    if not api_key:
        print(f"        ⚠️  No PEXELS_API_KEY — skipping video fetch")
        return None

    CLIP_CACHE.mkdir(parents=True, exist_ok=True)

    # Cache check
    safe_q = re.sub(r'[^a-zA-Z0-9]', '_', query)[:50]
    cache_path = CLIP_CACHE / f"{safe_q}.mp4"
    if cache_path.exists() and cache_path.stat().st_size > 10000:
        return str(cache_path)

    try:
        enc = urllib.parse.quote(query)
        url = (f"https://api.pexels.com/videos/search"
               f"?query={enc}&per_page=10&orientation=landscape"
               f"&size=medium&min_duration={min_duration}")

        req = urllib.request.Request(url, headers={"Authorization": api_key})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())

        videos = data.get("videos", [])
        if not videos:
            print(f"        ⚠️  No videos found for '{query}'")
            return None

        # Pick a random video from results for variety
        video = random.choice(videos[:min(5, len(videos))])

        # Find the best HD file (prefer 1920w or 1280w)
        best_file = None
        for vf in video.get("video_files", []):
            w = vf.get("width", 0)
            h = vf.get("height", 0)
            quality = vf.get("quality", "")
            ft = vf.get("file_type", "")

            if "mp4" not in ft:
                continue
            if w >= 1280 and h >= 720:
                if best_file is None or abs(w - target_w) < abs(best_file["width"] - target_w):
                    best_file = {"url": vf["link"], "width": w, "height": h}

        if not best_file:
            # Fall back to any mp4
            for vf in video.get("video_files", []):
                if "mp4" in vf.get("file_type", ""):
                    best_file = {"url": vf["link"], "width": vf.get("width", 0),
                                 "height": vf.get("height", 0)}
                    break

        if not best_file:
            return None

        print(f"        📥 Downloading {best_file['width']}x{best_file['height']} clip...")
        urllib.request.urlretrieve(best_file["url"], str(cache_path))
        time.sleep(0.5)  # Rate limit courtesy
        return str(cache_path)

    except Exception as e:
        print(f"        ⚠️  Video fetch failed for '{query}': {e}")
        return None


def fetch_pexels_photo(query):
    """Fallback: fetch a photo if video is unavailable."""
    api_key = os.getenv("PEXELS_API_KEY", "")
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
        url = f"https://api.pexels.com/v1/search?query={enc}&per_page=5&orientation=landscape"
        req = urllib.request.Request(url, headers={"Authorization": api_key})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        photos = data.get("photos", [])
        if not photos:
            return None
        photo = random.choice(photos[:min(5, len(photos))])
        urllib.request.urlretrieve(photo["src"]["landscape"], str(cache_path))
        time.sleep(0.3)
        return Image.open(cache_path).convert("RGB")
    except Exception:
        return None


def section_search_query(section):
    """Generate a search query for stock footage based on section content."""
    sid = section.get("id", "")
    heading = section.get("heading", "")
    narration = section.get("narration", "")[:300].lower()

    # Map section types to cinematic footage queries
    video_queries = {
        "hook": "futuristic technology abstract lights",
        "intro": "artificial intelligence neural network visualization",
        "outro": "technology social media community hands",
        "summary": "innovation future city technology",
        "demo": "computer programming code screen typing",
    }

    if sid in video_queries:
        return video_queries[sid]

    # Extract keywords from heading/narration for relevant footage
    tech_keywords = {
        "agent": "robot artificial intelligence autonomous",
        "privacy": "security surveillance data protection",
        "google": "technology data center server room",
        "openai": "artificial intelligence neural network",
        "chatgpt": "chatbot conversation artificial intelligence",
        "code": "programming computer code screen",
        "data": "data visualization analytics dashboard",
        "brain": "neural network brain science",
        "robot": "robot automation industry",
        "cloud": "cloud computing server data center",
        "phone": "smartphone mobile technology",
        "search": "internet search technology browsing",
        "money": "business finance technology digital",
        "ad": "digital advertising marketing online",
        "learn": "education technology classroom digital",
    }

    combined = f"{heading} {narration}".lower()
    for keyword, footage_query in tech_keywords.items():
        if keyword in combined:
            return footage_query

    # Default: use heading + technology
    return f"{heading} technology" if heading else "technology innovation future"


# ═══════════════════════════════════════════════════════════════
# VIDEO CLIP PROCESSING (via FFmpeg)
# ═══════════════════════════════════════════════════════════════

def prepare_clip_segment(clip_path, duration, output_path, w=1920, h=1080,
                         darken=0.3, blur_strength="8:8"):
    """
    Use FFmpeg to:
    - Loop/trim the clip to exact duration
    - Scale + crop to target resolution
    - Apply blur + darken for text readability
    - Output as raw frames or an intermediate clip
    """
    cmd = [
        FFMPEG, "-y",
        "-stream_loop", "-1",  # Loop if shorter than duration
        "-i", clip_path,
        "-t", str(duration),
        "-vf", (
            f"scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h},"
            f"boxblur={blur_strength},"
            f"eq=brightness=-{1 - darken:.2f}:saturation=0.7"
        ),
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-an",  # No audio from stock clips
        "-r", "30",
        str(output_path),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"        ⚠️  FFmpeg clip prep failed: {result.stderr[-300:]}")
        return False
    return True


def create_static_clip(image, duration, output_path, w=1920, h=1080):
    """Create a video clip from a static image (photo or gradient fallback)."""
    if image is None:
        # Generate gradient
        arr = np.zeros((h, w, 3), dtype=np.uint8)
        for ch_idx in range(3):
            start = [10, 14, 30][ch_idx]
            end = [25, 35, 60][ch_idx]
            arr[:, :, ch_idx] = np.linspace(start, end, h, dtype=np.uint8)[:, np.newaxis]
        image = Image.fromarray(arr)

    # Resize/crop
    ratio = max(w / image.width, h / image.height)
    nw, nh = int(image.width * ratio), int(image.height * ratio)
    image = image.resize((nw, nh), Image.LANCZOS)
    left, top = (nw - w) // 2, (nh - h) // 2
    image = image.crop((left, top, left + w, top + h))
    image = image.filter(ImageFilter.GaussianBlur(radius=6))
    image = ImageEnhance.Brightness(image).enhance(0.3)

    # Save as temp image and convert to clip
    temp_img = output_path.parent / f"{output_path.stem}_bg.png"
    image.save(str(temp_img), "PNG")

    cmd = [
        FFMPEG, "-y",
        "-loop", "1",
        "-i", str(temp_img),
        "-t", str(duration),
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
# TEXT OVERLAY GENERATION
# ═══════════════════════════════════════════════════════════════

def create_text_overlay_frames(
    heading, lines, duration, w, h, fps, section_num, total_sections,
    channel_name, accent, layout="bullets"
):
    """
    Generate transparent PNG overlay frames with text that animates.
    Text fades/slides in progressively.
    """
    frames_dir = TEMP_DIR / f"overlay_{section_num}"
    frames_dir.mkdir(parents=True, exist_ok=True)

    total_frames = int(duration * fps)
    pad = 80

    for f_idx in range(total_frames):
        fp = f_idx / max(1, total_frames - 1)

        # RGBA for transparency
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # ── Top bar (semi-transparent) ──
        draw.rectangle([0, 0, w, 50], fill=(0, 0, 0, 180))

        # Channel name
        draw.text((pad, 17), channel_name, font=font_small(18),
                  fill=(88, 166, 255, 255), anchor="lm")

        # Section counter
        counter = f"{section_num}/{total_sections}"
        draw.text((w - pad, 17), counter, font=font_small(16),
                  fill=(140, 150, 165, 230), anchor="rm")

        # Progress bar
        draw.rectangle([0, 50, w, 53], fill=(30, 30, 30, 200))
        prog = (section_num - 1 + fp) / total_sections
        draw.rectangle([0, 50, int(w * prog), 53], fill=(*accent, 255))

        # ── Content panel ──
        panel_top = 70
        panel_bottom = h - 50
        panel_left = pad - 25
        panel_right = w - pad + 25

        draw.rounded_rectangle(
            [panel_left, panel_top, panel_right, panel_bottom],
            radius=16, fill=(8, 12, 18, 190)
        )

        # ── Heading (slides in from left) ──
        head_y = panel_top + 28
        if heading:
            # Slide-in: starts offset, settles at 0
            slide_offset = max(0, int(60 * (1 - min(1.0, fp * 4))))
            head_alpha = min(255, int(255 * min(1.0, fp * 4)))
            hf = font_heading(44)

            # Accent bar
            draw.rectangle([pad - slide_offset, head_y, pad + 5 - slide_offset,
                           head_y + 38], fill=(*accent, head_alpha))
            # Heading text shadow
            draw.text((pad + 20 - slide_offset + 2, head_y + 2), heading,
                      font=hf, fill=(0, 0, 0, head_alpha // 2))
            draw.text((pad + 20 - slide_offset, head_y), heading,
                      font=hf, fill=(230, 237, 243, head_alpha))

            head_y += 60

        # Divider
        div_alpha = min(180, int(180 * min(1.0, fp * 3)))
        draw.rectangle([pad, head_y, w - pad, head_y + 1],
                       fill=(*accent, div_alpha))
        head_y += 18

        # ── Content lines (fade in one by one) ──
        bf = font_body(28)
        line_h = 48
        n_lines = len(lines)

        for i, line in enumerate(lines):
            y = head_y + i * line_h
            if y + line_h > panel_bottom - 35:
                break

            # Each line fades in with a stagger
            line_start = 0.08 + (i * 0.06)  # Stagger start time
            if fp < line_start:
                continue

            line_progress = min(1.0, (fp - line_start) / 0.15)
            line_alpha = int(255 * line_progress)
            slide_up = int(15 * (1 - line_progress))

            if layout == "numbered":
                # Number badge
                draw.rounded_rectangle(
                    [pad, y + slide_up, pad + 32, y + 32 + slide_up],
                    radius=5, fill=(*accent, line_alpha)
                )
                draw.text((pad + 16, y + 16 + slide_up), str(i + 1),
                          font=font_small(16), fill=(0, 0, 0, line_alpha), anchor="mm")
                text_x = pad + 44
            elif layout == "code":
                # Line number
                draw.text((pad + 8, y + slide_up), str(i + 1).rjust(2),
                          font=font_small(16), fill=(80, 90, 100, line_alpha))
                text_x = pad + 40
            else:
                # Bullet dot
                dot_y = y + 14 + slide_up
                draw.ellipse([pad + 4, dot_y - 4, pad + 14, dot_y + 4],
                             fill=(*accent, line_alpha))
                text_x = pad + 26

            # Text shadow + text
            draw.text((text_x + 1, y + slide_up + 1), line,
                      font=bf, fill=(0, 0, 0, line_alpha // 2))
            draw.text((text_x, y + slide_up), line,
                      font=bf, fill=(220, 228, 236, line_alpha))

        # ── Blinking cursor ──
        visible_count = sum(1 for i in range(n_lines)
                           if fp >= 0.08 + i * 0.06
                           and head_y + i * line_h + line_h <= panel_bottom - 35)
        if visible_count > 0 and int(fp * 60) % 2 == 0:
            last_visible = min(visible_count - 1, n_lines - 1)
            last_y = head_y + last_visible * line_h
            cursor_x = pad + 26 + bf.getlength(lines[last_visible]) + 8
            draw.rectangle([cursor_x, last_y, cursor_x + 12, last_y + 30],
                           fill=(*accent, 200))

        # Save overlay frame
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


def generate_outro_clip(channel_name, duration, w, h, fps, output_path):
    """Generate branded outro clip."""
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

    # Clean temp
    if TEMP_DIR.exists():
        shutil.rmtree(TEMP_DIR)
    TEMP_DIR.mkdir(parents=True)

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
    # STEP 1: Fetch stock video clips
    # ════════════════════════════════════════════
    print(f"\n    📹 STEP 1: Fetching stock video clips for {n_secs} sections...")
    clip_paths = []
    for i, sec in enumerate(sections):
        query = section_search_query(sec)
        print(f"      [{i+1}/{n_secs}] Searching: {query}")

        clip_path = fetch_pexels_video(query, min_duration=int(sec_durs[i]) + 2)

        if clip_path is None:
            # Fallback to photo
            print(f"        📷 Trying photo fallback...")
            photo = fetch_pexels_photo(query)
            clip_paths.append(("photo", photo))
        else:
            clip_paths.append(("video", clip_path))

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
        screen_text = sec.get("screen_text", sec.get("narration", ""))
        accent = ACCENTS[i % len(ACCENTS)]
        layout = "numbered" if i % 3 == 0 else ("code" if sid == "demo" else "bullets")

        # Chapter marker
        mins = int(current_time) // 60
        secs = int(current_time) % 60
        chapters.append({"time": f"{mins}:{secs:02d}", "label": heading or sid})
        current_time += dur

        max_chars = max(45, int((W - 200) / 16))
        wrapped = textwrap.wrap(screen_text, width=max_chars)

        print(f"      [{i+1}/{n_secs}] {sid} ({dur:.1f}s) — ", end="")

        # Prepare background clip
        bg_clip_path = TEMP_DIR / f"bg_{i:02d}.mp4"
        clip_type, clip_data = clip_paths[i]

        if clip_type == "video":
            print("video bg ", end="")
            ok = prepare_clip_segment(clip_data, dur, bg_clip_path, W, H,
                                       darken=0.35, blur_strength="6:6")
            if not ok:
                print("→ fallback ", end="")
                create_static_clip(None, dur, bg_clip_path, W, H)
        else:
            print("photo bg ", end="")
            create_static_clip(clip_data, dur, bg_clip_path, W, H)

        # Generate text overlay frames
        overlay_pattern, n_frames = create_text_overlay_frames(
            heading, wrapped, dur, W, H, FPS,
            i + 1, n_secs, ch_name, accent, layout
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

    if has_music:
        print(f"    🎵 Mixing narration + background music...")
        cmd = [
            FFMPEG, "-y",
            "-i", str(concat_path),
            "-i", str(audio_path),
            "-i", str(bg_music),
            "-filter_complex",
            "[1:a]volume=1.0[narr];"
            "[2:a]volume=0.10,afade=t=in:st=0:d=3,"
            f"afade=t=out:st={max(0, audio_dur - 3)}:d=3[music];"
            "[narr][music]amix=inputs=2:duration=first[aout]",
            "-map", "0:v",
            "-map", "[aout]",
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            "-movflags", "+faststart",
            str(output_file),
        ]
    else:
        print(f"    🎵 Adding narration audio...")
        cmd = [
            FFMPEG, "-y",
            "-i", str(concat_path),
            "-i", str(audio_path),
            "-map", "0:v",
            "-map", "1:a",
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            "-movflags", "+faststart",
            str(output_file),
        ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ERROR final: {result.stderr[-500:]}")
        sys.exit(1)

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
    print("\n🎬 McNeillium_AI — Stock Footage Video Generator v4")
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
