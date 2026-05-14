#!/usr/bin/env python3
"""
McNeillium AI — Thumbnail Generator (Phase 15)

Six viral thumbnail templates rendered with Pillow. Reads inputs from
the script + news asset manifest, generates 3 variants per video
(picked from the 6 templates based on content fit), saves to
output/thumbnails/<slug>_variant_<1..3>.png.

Templates:
  A) FACE_TEXT       Big face left, bold headline right
  B) VS_BATTLE       Two faces or logos with VS in the middle
  C) BIG_NUMBER      Massive stat dominates thumbnail
  D) RED_ARROW       Photo + thick red arrow pointing at something
  E) BREAKING_TAG    Red "BREAKING" badge + headline
  F) EMOTIONAL_FACE  Reaction face + question mark accent

After upload, the channel owner promotes the winning variant via
YouTube Studio's native A/B test feature. This module logs picks +
performance to knowledge_base/thumbnail_performance.csv so the
template chooser learns over time.

YouTube Data API does NOT expose A/B testing programmatically as of
2026. We upload the chosen variant as the active thumbnail and the
remaining two land in output/thumbnails/ for manual swap-in via
Studio.
"""

import argparse
import csv
import datetime
import io
import json
import re
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower().replace("-", "") != "utf8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8",
                                  errors="replace")

from PIL import Image, ImageDraw, ImageFilter, ImageFont

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = PROJECT_ROOT / "output" / "scripts" / "latest.json"
ASSETS_MANIFEST = PROJECT_ROOT / "output" / "_news_assets" / "manifest.json"
THUMB_DIR = PROJECT_ROOT / "output" / "thumbnails"
PERF_CSV = PROJECT_ROOT / "knowledge_base" / "thumbnail_performance.csv"

W, H = 1280, 720   # standard YouTube thumbnail
BG_DARK = (10, 14, 24)
ACCENT_BLUE = (91, 163, 245)
ACCENT_ORANGE = (255, 107, 53)
ACCENT_RED = (220, 60, 50)
ACCENT_YELLOW = (255, 220, 60)
TEXT_PRIMARY = (255, 255, 255)
TEXT_DIM = (180, 188, 200)


def _font(size, bold=False, impact=False):
    candidates = []
    if impact:
        candidates.append("C:/Windows/Fonts/impact.ttf")
    if bold:
        candidates += [
            "C:/Windows/Fonts/arialbd.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ]
    candidates += [
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for fp in candidates:
        if Path(fp).exists():
            return ImageFont.truetype(fp, size)
    return ImageFont.load_default()


def _gradient_bg():
    img = Image.new("RGB", (W, H), BG_DARK)
    d = ImageDraw.Draw(img)
    for y in range(0, H, 2):
        shade = int(2 + 18 * (y / H))
        d.rectangle([0, y, W, y + 2],
                    fill=(BG_DARK[0] + shade // 2,
                          BG_DARK[1] + shade // 2,
                          BG_DARK[2] + shade))
    return img


def _wrap_text(text, font, max_w, draw):
    """Greedy word-wrap to fit within max_w pixels."""
    words = text.split()
    lines = []
    cur = []
    for w in words:
        test = " ".join(cur + [w])
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] <= max_w:
            cur.append(w)
        else:
            if cur:
                lines.append(" ".join(cur))
            cur = [w]
    if cur:
        lines.append(" ".join(cur))
    return lines


def _fit_photo_card(photo_path, target_w, target_h, radius=24):
    """Cover-fit a photo into rounded-corner card."""
    photo = Image.open(photo_path).convert("RGB")
    src_ratio = photo.width / photo.height
    dst_ratio = target_w / target_h
    if src_ratio > dst_ratio:
        scale = target_h / photo.height
        new_w = int(photo.width * scale)
        photo = photo.resize((new_w, target_h), Image.LANCZOS)
        left = (new_w - target_w) // 2
        photo = photo.crop((left, 0, left + target_w, target_h))
    else:
        scale = target_w / photo.width
        new_h = int(photo.height * scale)
        photo = photo.resize((target_w, new_h), Image.LANCZOS)
        top = (new_h - target_h) // 2
        photo = photo.crop((0, top, target_w, top + target_h))
    # rounded mask
    mask = Image.new("L", (target_w, target_h), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle([0, 0, target_w - 1, target_h - 1],
                          radius=radius, fill=255)
    photo_rgba = photo.convert("RGBA")
    photo_rgba.putalpha(mask)
    return photo_rgba


def _drop_shadow(size, blur=20, alpha=200):
    sh = Image.new("RGBA", (size[0] + blur * 2, size[1] + blur * 2),
                    (0, 0, 0, 0))
    d = ImageDraw.Draw(sh)
    d.rounded_rectangle(
        [blur, blur, blur + size[0], blur + size[1]],
        radius=28, fill=(0, 0, 0, alpha),
    )
    return sh.filter(ImageFilter.GaussianBlur(blur))


# ─── Template A: FACE_TEXT ────────────────────────────────────

def render_face_text(headline, photo_path, out_path,
                     accent=ACCENT_BLUE):
    bg = _gradient_bg().convert("RGBA")
    d = ImageDraw.Draw(bg)

    # Big face on left
    if photo_path and Path(photo_path).exists():
        card_w, card_h = 540, 620
        card = _fit_photo_card(photo_path, card_w, card_h, radius=28)
        sh = _drop_shadow((card_w, card_h), blur=24, alpha=220)
        bg.alpha_composite(sh, (40 - 24, 50 - 24 + 12))
        bg.alpha_composite(card, (40, 50))

    # Headline on right
    text_x = 620
    text_w = W - text_x - 40
    font = _font(82, bold=True, impact=True)
    lines = _wrap_text(headline.upper(), font, text_w, d)
    line_h = 96
    total_h = len(lines) * line_h
    start_y = (H - total_h) // 2
    for i, line in enumerate(lines):
        y = start_y + i * line_h
        # Thick outline
        for dx in (-3, 3):
            for dy in (-3, 3):
                d.text((text_x + dx, y + dy), line, font=font,
                       fill=(0, 0, 0))
        d.text((text_x, y), line, font=font, fill=TEXT_PRIMARY)
    # accent bar under text
    d.rectangle([text_x, start_y + total_h + 12,
                 text_x + 200, start_y + total_h + 22],
                fill=accent)
    bg.convert("RGB").save(str(out_path), "PNG")
    return str(out_path)


# ─── Template B: VS_BATTLE ────────────────────────────────────

def render_vs_battle(headline, left_image, right_image, out_path,
                     left_label="", right_label=""):
    bg = _gradient_bg().convert("RGBA")
    d = ImageDraw.Draw(bg)
    card_w, card_h = 430, 430
    pad = 30
    left_x = pad
    right_x = W - pad - card_w
    cy = (H - card_h) // 2 + 30

    if left_image and Path(left_image).exists():
        card = _fit_photo_card(left_image, card_w, card_h, radius=26)
        sh = _drop_shadow((card_w, card_h), blur=20, alpha=200)
        bg.alpha_composite(sh, (left_x - 20 + 6, cy - 20 + 10))
        bg.alpha_composite(card, (left_x, cy))
    if right_image and Path(right_image).exists():
        card = _fit_photo_card(right_image, card_w, card_h, radius=26)
        sh = _drop_shadow((card_w, card_h), blur=20, alpha=200)
        bg.alpha_composite(sh, (right_x - 20 + 6, cy - 20 + 10))
        bg.alpha_composite(card, (right_x, cy))

    # VS badge centred
    badge_r = 80
    d.ellipse([W // 2 - badge_r, H // 2 - badge_r + 30,
               W // 2 + badge_r, H // 2 + badge_r + 30],
              fill=ACCENT_RED, outline=TEXT_PRIMARY, width=5)
    f_vs = _font(72, bold=True, impact=True)
    d.text((W // 2, H // 2 + 30), "VS", font=f_vs,
           fill=TEXT_PRIMARY, anchor="mm")

    # Headline at top
    f_head = _font(56, bold=True, impact=True)
    head_lines = _wrap_text(headline.upper(), f_head, W - 120, d)
    for i, line in enumerate(head_lines[:2]):
        y = 30 + i * 62
        for dx in (-3, 3):
            for dy in (-3, 3):
                d.text((W // 2 + dx, y + dy), line, font=f_head,
                       fill=(0, 0, 0), anchor="ma")
        d.text((W // 2, y), line, font=f_head, fill=TEXT_PRIMARY,
               anchor="ma")

    # Labels under each
    f_lab = _font(36, bold=True)
    if left_label:
        d.text((left_x + card_w // 2, cy + card_h + 28),
               left_label.upper(), font=f_lab, fill=TEXT_PRIMARY,
               anchor="ma")
    if right_label:
        d.text((right_x + card_w // 2, cy + card_h + 28),
               right_label.upper(), font=f_lab, fill=TEXT_PRIMARY,
               anchor="ma")
    bg.convert("RGB").save(str(out_path), "PNG")
    return str(out_path)


# ─── Template C: BIG_NUMBER ───────────────────────────────────

def render_big_number(stat, sub_label, out_path,
                      accent=ACCENT_ORANGE):
    bg = _gradient_bg().convert("RGBA")
    d = ImageDraw.Draw(bg)
    # Massive stat
    f_big = _font(300, bold=True, impact=True)
    cx, cy = W // 2, H // 2 - 30
    # Outline + main
    for dx in (-5, 5):
        for dy in (-5, 5):
            d.text((cx + dx, cy + dy), stat, font=f_big,
                   fill=(0, 0, 0), anchor="mm")
    d.text((cx, cy), stat, font=f_big, fill=accent, anchor="mm")
    # Accent bar
    d.rectangle([cx - 220, cy + 170, cx + 220, cy + 184],
                fill=ACCENT_BLUE)
    # Sub-label
    f_sub = _font(50, bold=True)
    d.text((cx, cy + 230), sub_label.upper(), font=f_sub,
           fill=TEXT_PRIMARY, anchor="mm")
    bg.convert("RGB").save(str(out_path), "PNG")
    return str(out_path)


# ─── Template D: RED_ARROW ────────────────────────────────────

def render_red_arrow(headline, photo_path, out_path):
    bg = _gradient_bg().convert("RGBA")
    d = ImageDraw.Draw(bg)
    # Photo on right
    if photo_path and Path(photo_path).exists():
        card_w, card_h = 580, 620
        card = _fit_photo_card(photo_path, card_w, card_h, radius=24)
        sh = _drop_shadow((card_w, card_h), blur=22, alpha=200)
        right_x = W - 60 - card_w
        cy = (H - card_h) // 2
        bg.alpha_composite(sh, (right_x - 22 + 6, cy - 22 + 12))
        bg.alpha_composite(card, (right_x, cy))
        # Red arrow pointing at face
        arrow_color = ACCENT_RED
        ax, ay = 320, H // 2
        bx, by = right_x - 30, H // 2
        # Shaft
        for o in range(-16, 17, 2):
            d.line([(ax, ay + o), (bx - 30, by + o)],
                   fill=arrow_color, width=4)
        # Arrowhead
        d.polygon([(bx - 30, by - 36), (bx - 30, by + 36), (bx, by)],
                  fill=arrow_color)

    # Headline on left side
    f_head = _font(64, bold=True, impact=True)
    lines = _wrap_text(headline.upper(), f_head, 260, d)
    total_h = len(lines) * 76
    start_y = (H - total_h) // 2
    for i, line in enumerate(lines):
        y = start_y + i * 76
        for dx in (-3, 3):
            for dy in (-3, 3):
                d.text((60 + dx, y + dy), line, font=f_head,
                       fill=(0, 0, 0))
        d.text((60, y), line, font=f_head, fill=TEXT_PRIMARY)
    bg.convert("RGB").save(str(out_path), "PNG")
    return str(out_path)


# ─── Template E: BREAKING_TAG ─────────────────────────────────

def render_breaking_tag(headline, photo_path, out_path):
    bg = _gradient_bg().convert("RGBA")
    d = ImageDraw.Draw(bg)
    # Optional photo in background, darkened
    if photo_path and Path(photo_path).exists():
        photo = Image.open(photo_path).convert("RGB").resize((W, H),
                                                              Image.LANCZOS)
        photo = photo.convert("RGBA")
        # Darken overlay
        dark = Image.new("RGBA", (W, H), (0, 0, 0, 140))
        photo.alpha_composite(dark)
        bg.alpha_composite(photo)
        d = ImageDraw.Draw(bg)

    # BREAKING badge top-left
    badge_w, badge_h = 360, 70
    d.rectangle([40, 40, 40 + badge_w, 40 + badge_h],
                fill=ACCENT_RED)
    f_break = _font(50, bold=True, impact=True)
    d.text((40 + badge_w // 2, 40 + badge_h // 2 - 2),
           "BREAKING", font=f_break, fill=TEXT_PRIMARY, anchor="mm")

    # Headline below
    f_head = _font(78, bold=True, impact=True)
    lines = _wrap_text(headline.upper(), f_head, W - 80, d)
    start_y = 160
    for i, line in enumerate(lines):
        y = start_y + i * 92
        for dx in (-3, 3):
            for dy in (-3, 3):
                d.text((40 + dx, y + dy), line, font=f_head,
                       fill=(0, 0, 0))
        d.text((40, y), line, font=f_head, fill=TEXT_PRIMARY)
    bg.convert("RGB").save(str(out_path), "PNG")
    return str(out_path)


# ─── Template F: EMOTIONAL_FACE ───────────────────────────────

def render_emotional_face(headline, photo_path, out_path):
    bg = _gradient_bg().convert("RGBA")
    d = ImageDraw.Draw(bg)
    # Photo on right with question-mark accent
    if photo_path and Path(photo_path).exists():
        card_w, card_h = 540, 620
        card = _fit_photo_card(photo_path, card_w, card_h, radius=28)
        sh = _drop_shadow((card_w, card_h), blur=22, alpha=210)
        right_x = W - 60 - card_w
        cy = (H - card_h) // 2
        bg.alpha_composite(sh, (right_x - 22 + 6, cy - 22 + 12))
        bg.alpha_composite(card, (right_x, cy))

    # Huge question mark on right edge in yellow
    f_q = _font(360, bold=True, impact=True)
    d.text((W - 80, 80), "?", font=f_q, fill=ACCENT_YELLOW, anchor="rt")

    # Headline left
    f_head = _font(60, bold=True, impact=True)
    lines = _wrap_text(headline.upper(), f_head, 540, d)
    start_y = (H - len(lines) * 72) // 2
    for i, line in enumerate(lines):
        y = start_y + i * 72
        for dx in (-3, 3):
            for dy in (-3, 3):
                d.text((60 + dx, y + dy), line, font=f_head,
                       fill=(0, 0, 0))
        d.text((60, y), line, font=f_head, fill=TEXT_PRIMARY)
    bg.convert("RGB").save(str(out_path), "PNG")
    return str(out_path)


# ─── Variant chooser ──────────────────────────────────────────

def choose_variants(script, manifest):
    """Pick 3 templates to render given what assets we have.

    Priority is data-driven: variants with the strongest available
    assets go first.
    """
    title = script.get("title", "AI News")
    thumb_text = (script.get("seo", {}) or {}).get(
        "thumbnail_text", title)[:30]

    people = manifest.get("people", {})
    logos = manifest.get("logos", {})
    charts = manifest.get("charts", [])

    primary_face = None
    if people:
        primary_face = list(people.values())[0]["path"]
    secondary_face = None
    if len(people) >= 2:
        secondary_face = list(people.values())[1]["path"]
    primary_logo = list(logos.values())[0]["path"] if logos else None
    secondary_logo = list(logos.values())[1]["path"] if len(logos) >= 2 else None

    plans = []
    # Always include a FACE_TEXT if we have a face, otherwise BREAKING
    if primary_face:
        plans.append({
            "template": "FACE_TEXT",
            "kwargs": {
                "headline": thumb_text,
                "photo_path": primary_face,
            },
        })
    else:
        plans.append({
            "template": "BREAKING_TAG",
            "kwargs": {"headline": thumb_text, "photo_path": None},
        })

    # Big number variant if any stat-heavy chart was generated
    if charts:
        plans.append({
            "template": "BIG_NUMBER",
            "kwargs": {
                "stat": charts[0]["value"],
                "sub_label": charts[0]["label"][:34],
            },
        })

    # VS battle if we have two people or two logos
    if secondary_face or secondary_logo:
        left = primary_face or primary_logo
        right = secondary_face or secondary_logo
        left_label = list(people.values())[0]["name"].split()[-1] if people else ""
        right_label = ""
        if secondary_face:
            right_label = list(people.values())[1]["name"].split()[-1]
        elif secondary_logo:
            right_label = list(logos.values())[1]["name"]
        plans.append({
            "template": "VS_BATTLE",
            "kwargs": {
                "headline": thumb_text,
                "left_image": left,
                "right_image": right,
                "left_label": left_label,
                "right_label": right_label,
            },
        })

    # Fillers if we don't yet have 3
    if len(plans) < 3:
        plans.append({
            "template": "RED_ARROW",
            "kwargs": {"headline": thumb_text,
                       "photo_path": primary_face},
        })
    if len(plans) < 3:
        plans.append({
            "template": "EMOTIONAL_FACE",
            "kwargs": {"headline": thumb_text,
                       "photo_path": primary_face},
        })

    return plans[:3]


TEMPLATE_DISPATCH = {
    "FACE_TEXT":       render_face_text,
    "VS_BATTLE":       render_vs_battle,
    "BIG_NUMBER":      render_big_number,
    "RED_ARROW":       render_red_arrow,
    "BREAKING_TAG":    render_breaking_tag,
    "EMOTIONAL_FACE":  render_emotional_face,
}


# ─── Main ─────────────────────────────────────────────────────

def run(script_path, manifest_path, out_dir):
    if not Path(script_path).exists():
        print(f"❌ Script not found: {script_path}")
        return False
    script = json.loads(Path(script_path).read_text(encoding="utf-8"))
    manifest = {}
    if Path(manifest_path).exists():
        try:
            manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        except Exception:
            pass

    title = script.get("title", "untitled")
    slug = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")[:60]
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    plans = choose_variants(script, manifest)
    print(f"🎨 Thumbnail generator — {len(plans)} variants for "
          f"'{title[:60]}…'")
    paths = []
    for i, plan in enumerate(plans, 1):
        tmpl = plan["template"]
        fn = TEMPLATE_DISPATCH[tmpl]
        target = out_dir / f"{slug}_variant_{i}_{tmpl.lower()}.png"
        try:
            fn(out_path=target, **plan["kwargs"])
            print(f"  ✅ Variant {i}: {tmpl} → {target.name}")
            paths.append({"template": tmpl, "path": str(target)})
        except Exception as e:
            print(f"  ⚠️  Variant {i} ({tmpl}) failed: {e}")

    # Log to performance CSV for later A/B feedback
    PERF_CSV.parent.mkdir(parents=True, exist_ok=True)
    new_file = not PERF_CSV.exists()
    with open(PERF_CSV, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["date", "video_slug", "template",
                         "variant_path", "views", "ctr_pct", "winner"])
        today = datetime.date.today().isoformat()
        for p in paths:
            w.writerow([today, slug, p["template"], p["path"], "", "", ""])

    # Save a small manifest right next to the thumbnails
    (out_dir / f"{slug}_variants.json").write_text(
        json.dumps({"title": title, "variants": paths}, indent=2),
        encoding="utf-8",
    )
    return len(paths) >= 2


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--script", default=str(SCRIPT_PATH))
    p.add_argument("--manifest", default=str(ASSETS_MANIFEST))
    p.add_argument("--out-dir", default=str(THUMB_DIR))
    args = p.parse_args()
    ok = run(args.script, args.manifest, args.out_dir)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
