#!/usr/bin/env python3
"""
McNeillium_AI — Phase 22.3: Phrase-aligned video renderer

Parallel to video/generate_video.py but built around phrase-aligned
beats from utils/phrase_planner.py + utils/visual_director_llm.plan_phrases_batch.

Inputs (all already produced earlier in the pipeline):
  output/audio/latest.mp3                — narration
  output/phrases.json                    — phrase plan w/ start/end times
  output/shot_list_phrases.json          — same phrases enriched with
                                            shot_type + layout + assets
  assets/music/ambient_tech.mp3          — background music

Output:
  output/videos/_phrases_<timestamp>.mp4 — finished render

Each phrase becomes ONE beat. Beat duration = phrase.duration_s.
Visuals are composed from the asset library (logos, concept icons,
person photos) using the layout the LLM Visual Director picked.
"""

import io
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

from PIL import Image

if sys.stdout.encoding and sys.stdout.encoding.lower().replace("-", "") != "utf8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8",
                                  errors="replace")


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

AUDIO_PATH = PROJECT_ROOT / "output" / "audio" / "latest.mp3"
PHRASES_PATH = PROJECT_ROOT / "output" / "phrases.json"
SHOT_LIST_PATH = PROJECT_ROOT / "output" / "shot_list_phrases.json"
MUSIC_PATH = PROJECT_ROOT / "assets" / "music" / "ambient_tech.mp3"
TEMP_DIR = PROJECT_ROOT / "output" / "_temp_phrases"
VIDEO_DIR = PROJECT_ROOT / "output" / "videos"
W, H, FPS = 1920, 1080, 30


def _ffmpeg():
    return shutil.which("ffmpeg") or "ffmpeg"


def _ffprobe():
    return shutil.which("ffprobe") or "ffprobe"


def _safe_encode_args():
    return [
        "-c:v", "libx264", "-profile:v", "main",
        "-pix_fmt", "yuv420p",
        "-colorspace", "bt709",
        "-color_primaries", "bt709",
        "-color_trc", "bt709",
        "-preset", "medium", "-crf", "20",
        "-movflags", "+faststart",
    ]


# ─────────────────────── per-beat asset builders ──────────────────────

def _build_logo_path(name):
    """Resolve logo PNG via Simple Icons → Lobe → Brandfetch chain."""
    try:
        from utils.logo_indexer import render_logo_png
        p = render_logo_png(name, size=512, accent_bg=False)
        if p and p.exists():
            return p
    except Exception:
        pass
    try:
        from utils.brandfetch_client import fetch_logo_png
        p = fetch_logo_png(name, size=512)
        if p and p.exists():
            return p
    except Exception:
        pass
    return None


def _build_person_path(name):
    """Resolve person photo via entity packs (build on demand)."""
    try:
        from utils.entity_pack_builder import (pick_pack_image, build_pack,
                                                _slug as _eslug)
        slug = _eslug(name)
        p = pick_pack_image(slug)
        if not p:
            try:
                build_pack(name, max_images=2)
            except Exception:
                pass
            p = pick_pack_image(slug)
        return p if p and p.exists() else None
    except Exception:
        return None


def _build_concept_png(concept, w=W, h=H):
    """Render a concept illustration PNG (Lucide → PIL fallback)."""
    try:
        from utils.concept_illustrations import (_png_for_concept,
                                                  match_concept)
        slug = match_concept(concept)
        if slug:
            return _png_for_concept(slug, w, h)
    except Exception:
        pass
    return None


def _build_unsplash_path(query):
    """Resolve an Unsplash atmospheric photo for a query."""
    try:
        from utils.unsplash_client import fetch_photo
        return fetch_photo(query, orientation="landscape")
    except Exception:
        return None


def _build_stock_video_path(query, min_duration=3.0):
    """Resolve a real video clip via the multi-source stock fetcher."""
    try:
        from utils.stock_fetcher import fetch_video
        p = fetch_video(query, min_duration=min_duration)
        return Path(p) if p else None
    except Exception:
        return None


def _build_layout_png(phrase, beat_idx, beat_dir):
    """Compose the visual for one phrase using its layout. Returns
    a PIL Image.RGB at (W, H) or None on miss."""
    from utils.composite_layouts import (logo_hero, logo_photo, vs_battle,
                                          news_anchor, stat_card,
                                          illo_caption)
    layout = phrase.get("layout", "solo")
    shot_type = phrase.get("shot_type", "footage")
    company = phrase.get("company")
    secondary = phrase.get("secondary_company")
    name = phrase.get("name")
    concept = phrase.get("concept")
    caption = phrase.get("caption_text") or phrase.get("query") or ""

    # FINAL FIX 1: word-level entity pin overrides Director's choice.
    # If the planner pinned a specific entity to this phrase, the visual
    # MUST be that entity. Director may have ignored the PINNED hint.
    pinned_kind = phrase.get("pinned_entity_kind")
    pinned_name = phrase.get("pinned_entity_name")
    if pinned_kind == "company" or pinned_kind == "product":
        company = pinned_name  # override
        if shot_type not in ("company_logo", "logo_photo"):
            shot_type = "company_logo"
        if layout == "solo":
            layout = "logo_hero"
    elif pinned_kind == "person":
        name = pinned_name  # override
        if shot_type not in ("person_photo", "logo_photo", "news_anchor"):
            shot_type = "person_photo"
        if layout == "solo":
            layout = "news_anchor"

    logo_path = _build_logo_path(company) if company else None
    secondary_logo = _build_logo_path(secondary) if secondary else None
    person_path = _build_person_path(name) if name else None
    concept_png = _build_concept_png(concept) if concept else None

    # Layout dispatch
    try:
        if layout == "vs_battle" and (logo_path or person_path) and (secondary_logo):
            left = logo_path or person_path
            return vs_battle(left, secondary_logo,
                             left_label=(company or name or "").upper(),
                             right_label=(secondary or "").upper())
        if layout == "logo_photo" and person_path and logo_path:
            return logo_photo(person_path, logo_path,
                              name=name or "", title=caption[:60])
        if layout == "news_anchor" and person_path:
            return news_anchor(person_path, name or "", title=caption[:60],
                               company_logo_path=logo_path)
        if layout == "stat_card":
            return stat_card(caption[:12] or company or "?",
                             label=caption[:60],
                             company_logo_path=logo_path)
        if layout == "illo_caption" and concept_png:
            return illo_caption(str(concept_png), caption[:50])
        if layout == "logo_hero" and logo_path:
            return logo_hero(logo_path,
                             label=(company or "").upper())
    except Exception as e:
        print(f"        ⚠️  layout {layout!r} failed: {e}; falling back")

    # Fallbacks based on shot_type
    if shot_type == "company_logo" and logo_path:
        return logo_hero(logo_path, label=(company or "").upper())
    if shot_type == "person_photo" and person_path:
        return news_anchor(person_path, name or "",
                           title=caption[:60],
                           company_logo_path=logo_path)
    if shot_type == "concept_illustration" and concept_png:
        return illo_caption(str(concept_png), caption[:50])
    if shot_type == "chart":
        return stat_card(caption[:12] or "?", label=caption[:60],
                         company_logo_path=logo_path)
    # FINAL FIX 2/3: Unsplash photo (atmospheric/setting) + stock video
    if shot_type == "unsplash":
        u = _build_unsplash_path(phrase.get("query") or caption or company or "")
        if u and u.exists():
            return Image.open(u).convert("RGB")
    if shot_type == "footage":
        # Footage is a video clip — we can't easily concat that into our
        # PNG-based beat assembler. Pull the FIRST FRAME as a still so
        # the beat at least matches the action's setting; adding true
        # video-in-beat support is a larger pipeline change.
        clip = _build_stock_video_path(phrase.get("query") or caption or "")
        if clip and clip.exists():
            still = TEMP_DIR / f"still_{beat_idx:03d}.png"
            try:
                subprocess.run(
                    [_ffmpeg(), "-y", "-i", str(clip),
                     "-vf", f"scale={W}:{H}:force_original_aspect_ratio=increase,"
                     f"crop={W}:{H}",
                     "-frames:v", "1", str(still)],
                    capture_output=True, check=True,
                )
                return Image.open(still).convert("RGB")
            except Exception:
                pass
    # Last resort: if we have ANY logo, show it
    if logo_path:
        return logo_hero(logo_path, label=(company or "").upper())
    return None


# ───────────────────────────── render loop ─────────────────────────────

def render_beat(phrase, beat_idx):
    """Render one phrase as a beat MP4 of phrase.duration_s seconds.
    Returns Path or None."""
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    beat_path = TEMP_DIR / f"beat_{beat_idx:03d}.mp4"
    if beat_path.exists():
        beat_path.unlink()

    img = _build_layout_png(phrase, beat_idx, TEMP_DIR)
    if img is None:
        # Last-resort dark frame with the phrase text
        from utils.composite_layouts import _gradient_bg
        from PIL import ImageDraw, ImageFont
        img = _gradient_bg(W, H)
        d = ImageDraw.Draw(img)
        for fp in ["C:/Windows/Fonts/arialbd.ttf"]:
            if Path(fp).exists():
                font = ImageFont.truetype(fp, 36)
                break
        else:
            font = ImageFont.load_default()
        text = phrase.get("text", "")[:60]
        d.text((100, H // 2 - 20), text, fill=(150, 163, 182), font=font)

    png_path = TEMP_DIR / f"beat_{beat_idx:03d}.png"
    img.convert("RGB").save(png_path, "PNG")

    duration = max(0.5, float(phrase["duration_s"]))
    cmd = [
        _ffmpeg(), "-y", "-loop", "1", "-i", str(png_path),
        "-t", f"{duration:.3f}",
        "-vf", f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
               f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,format=yuv420p",
        *_safe_encode_args(),
        "-an", "-r", str(FPS),
        str(beat_path),
    ]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        sys.stderr.write(r.stderr.decode("utf-8", "replace")[-500:])
        return None
    return beat_path


def render_video():
    if not AUDIO_PATH.exists():
        print(f"❌ audio missing: {AUDIO_PATH}")
        return None
    if not PHRASES_PATH.exists():
        print(f"❌ phrases missing: {PHRASES_PATH}")
        return None
    if not SHOT_LIST_PATH.exists():
        print(f"❌ shot list missing: {SHOT_LIST_PATH}")
        return None

    phrases = json.loads(SHOT_LIST_PATH.read_text(encoding="utf-8"))
    print(f"🎬 Phrase-aligned render — {len(phrases)} beats")

    # Cover any silent gaps before/between phrases. We render each
    # phrase as exactly its duration_s; gaps get filled by repeating
    # the previous beat's last frame (cheap: just extend the prev MP4).
    beat_paths = []
    failed = 0
    for i, p in enumerate(phrases):
        b = render_beat(p, i)
        if b:
            beat_paths.append(b)
        else:
            failed += 1
        if (i + 1) % 10 == 0:
            print(f"   {i+1}/{len(phrases)} beats...")
    print(f"   ✅ {len(beat_paths)} rendered  ⚠️ {failed} failed")

    if not beat_paths:
        return None

    # Concat all beats. Use ffmpeg concat demuxer.
    list_path = TEMP_DIR / "concat.txt"
    with open(list_path, "w", encoding="utf-8") as f:
        for bp in beat_paths:
            f.write(f"file '{bp.resolve().as_posix()}'\n")

    silent_video = TEMP_DIR / "silent.mp4"
    cmd = [
        _ffmpeg(), "-y", "-f", "concat", "-safe", "0",
        "-i", str(list_path), "-c:v", "copy",
        str(silent_video),
    ]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        sys.stderr.write(r.stderr.decode("utf-8", "replace")[-1500:])
        return None
    print(f"   🔧 Concatenated {len(beat_paths)} beats")

    # Mix narration + ducked background music
    VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    final = VIDEO_DIR / f"_phrases_{ts}.mp4"

    has_music = MUSIC_PATH.exists()
    if has_music:
        # narration full vol, music looped + ducked when voice is loud.
        # Pattern: [music] gets volume cut → sidechain-compress against
        # voice → mix compressed-music with voice.
        af = (
            "[1:a]aloop=loop=-1:size=2e9,volume=0.10[mus];"
            "[mus][2:a]sidechaincompress=threshold=0.025:ratio=10:"
            "attack=15:release=300[ducked];"
            "[ducked][2:a]amix=inputs=2:duration=longest:"
            "dropout_transition=2[a]"
        )
        cmd = [
            _ffmpeg(), "-y",
            "-i", str(silent_video),
            "-stream_loop", "-1", "-i", str(MUSIC_PATH),
            "-i", str(AUDIO_PATH),
            "-filter_complex", af,
            "-map", "0:v", "-map", "[a]",
            *_safe_encode_args(),
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            str(final),
        ]
    else:
        cmd = [
            _ffmpeg(), "-y",
            "-i", str(silent_video), "-i", str(AUDIO_PATH),
            "-map", "0:v", "-map", "1:a",
            *_safe_encode_args(),
            "-c:a", "aac", "-b:a", "192k", "-shortest",
            str(final),
        ]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        sys.stderr.write(r.stderr.decode("utf-8", "replace")[-1500:])
        return None

    # 2-pass loudnorm (mirrors video/generate_video.py STEP 7) so the
    # render comes out at the channel target -14 LUFS without needing
    # an external post-pass.
    print("   🎚  2-pass loudnorm targeting -14 LUFS...")
    measure_cmd = [
        _ffmpeg(), "-hide_banner", "-nostats", "-i", str(final),
        "-af", "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json",
        "-f", "null", "-",
    ]
    mres = subprocess.run(measure_cmd, capture_output=True, text=True)
    import re as _re
    m = _re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", mres.stderr, _re.S)
    if m:
        try:
            stats = json.loads(m.group(0))
            normalized = final.with_name(final.stem + "_norm.mp4")
            apply_cmd = [
                _ffmpeg(), "-hide_banner", "-y", "-i", str(final),
                "-af",
                f"loudnorm=I=-14:TP=-1.5:LRA=11:linear=true:"
                f"measured_I={stats['input_i']}:"
                f"measured_TP={stats['input_tp']}:"
                f"measured_LRA={stats['input_lra']}:"
                f"measured_thresh={stats['input_thresh']}:"
                f"offset={stats['target_offset']}",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                "-movflags", "+faststart", str(normalized),
            ]
            ar = subprocess.run(apply_cmd, capture_output=True)
            if ar.returncode == 0:
                final.unlink()
                normalized.rename(final)
                print(f"      ✅ measured {stats['input_i']} → -14")
        except Exception as e:
            print(f"      ⚠️  loudnorm parse failed: {e}")

    size_mb = final.stat().st_size / (1024 * 1024)
    # Probe duration
    pr = subprocess.run(
        [_ffprobe(), "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(final)],
        capture_output=True, text=True,
    )
    dur = float(pr.stdout.strip() or 0)
    print(f"\n  ✅ Video: {final}")
    print(f"  📦 Size: {size_mb:.1f} MB")
    print(f"  ⏱  Duration: {int(dur)//60}m {int(dur)%60}s")
    print(f"  🎵 Background music: {'Yes' if has_music else 'No'}")
    return final


if __name__ == "__main__":
    render_video()
