#!/usr/bin/env python3
"""
McNeillium_AI — Phase 21.6: Composite Layouts

Six layout templates the Visual Director can pick from based on
context. Each renders a static 1920×1080 PNG (no scale ramp / no
animated reveals — per the v19b/Phase 20 "news-anchor static"
preference confirmed in Phase 21).

Layouts
───────
  A. logo_hero      — single logo big-centered on a dark card
  B. logo_photo     — person photo (60% left), company logo (top-right card)
  C. vs_battle      — two logos side-by-side with "VS" in the middle
  D. illo_caption   — concept illustration centered + caption strip below
  E. news_anchor    — person photo in a circle frame + lower-third name/title
  F. stat_card      — massive number/percentage + label + optional small logo

Public API
──────────
  render_layout(layout, output_path, **kwargs) -> Path
      Dispatch by layout name. Returns the saved PNG path.
"""

import argparse
import io
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageFilter

if sys.stdout.encoding and sys.stdout.encoding.lower().replace("-", "") != "utf8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8",
                                  errors="replace")


PROJECT_ROOT = Path(__file__).resolve().parent.parent

PALETTE = {
    "primary":   (0, 212, 170),
    "secondary": (255, 107, 53),
    "ink":       (230, 237, 243),
    "muted":     (149, 163, 182),
    "bg":        (10, 14, 24),
    "panel":     (19, 24, 38),
    "panel2":    (24, 32, 50),
}

W_DEFAULT, H_DEFAULT = 1920, 1080


def _font(size, bold=True):
    candidates = [
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    for f in candidates:
        if Path(f).exists():
            try:
                return ImageFont.truetype(f, size)
            except Exception:
                pass
    return ImageFont.load_default()


def _gradient_bg(w, h):
    img = Image.new("RGB", (w, h), PALETTE["bg"])
    d = ImageDraw.Draw(img)
    for y in range(0, h, 2):
        t = y / h
        r = int(PALETTE["bg"][0] + 12 * t)
        g = int(PALETTE["bg"][1] + 18 * t)
        b = int(PALETTE["bg"][2] + 25 * t)
        d.rectangle([0, y, w, y + 2], fill=(r, g, b))
    return img


def _fit_image(src, max_w, max_h):
    """Resize keeping aspect ratio so it fits inside (max_w, max_h)."""
    src = src.convert("RGBA")
    sw, sh = src.size
    ratio = min(max_w / sw, max_h / sh)
    nw, nh = int(sw * ratio), int(sh * ratio)
    return src.resize((nw, nh), Image.LANCZOS)


def _draw_text_centered(draw, text, font, x_center, y, color):
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    draw.text((x_center - tw // 2, y), text, fill=color, font=font)


def _circular_crop(src, size):
    """Return src cropped to a circle of `size` (with padding)."""
    src = src.convert("RGBA")
    src.thumbnail((size, size), Image.LANCZOS)
    sq = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    sx = (size - src.width) // 2
    sy = (size - src.height) // 2
    sq.paste(src, (sx, sy), src)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, size, size], fill=255)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(sq, (0, 0), mask)
    return out


# ───────────────────────────── A. LOGO HERO ────────────────────────────

def logo_hero(logo_path, label="", *, w=W_DEFAULT, h=H_DEFAULT):
    """Single logo, centered on a dark card."""
    canvas = _gradient_bg(w, h)
    if logo_path:
        logo = _fit_image(Image.open(logo_path),
                          int(w * 0.45), int(h * 0.55))
        cx = (w - logo.width) // 2
        cy = (h - logo.height) // 2 - (60 if label else 0)
        canvas.paste(logo, (cx, cy), logo)
    if label:
        d = ImageDraw.Draw(canvas)
        font = _font(int(h * 0.06), bold=True)
        _draw_text_centered(d, label, font, w // 2,
                            int(h * 0.78), PALETTE["ink"])
    return canvas


# ───────────────────────────── B. LOGO + PHOTO ─────────────────────────

def logo_photo(person_photo_path, logo_path, name="", title="",
               *, w=W_DEFAULT, h=H_DEFAULT):
    """Person 60% left; company logo card top-right."""
    canvas = _gradient_bg(w, h)
    # Person panel (left)
    if person_photo_path and Path(person_photo_path).exists():
        person = Image.open(person_photo_path).convert("RGBA")
        # Fit into ~60% of width
        max_w = int(w * 0.55)
        max_h = int(h * 0.85)
        person = _fit_image(person, max_w, max_h)
        # Anchor to left, vertically centered
        px = int(w * 0.06)
        py = (h - person.height) // 2
        canvas.paste(person, (px, py), person)
    # Company logo card (top-right)
    if logo_path and Path(logo_path).exists():
        logo = _fit_image(Image.open(logo_path),
                          int(w * 0.22), int(h * 0.22))
        # Card behind it
        cx = int(w * 0.72)
        cy = int(h * 0.10)
        cw, ch = int(w * 0.24), int(h * 0.26)
        d = ImageDraw.Draw(canvas)
        d.rounded_rectangle([cx, cy, cx + cw, cy + ch], radius=18,
                            fill=PALETTE["panel"])
        lx = cx + (cw - logo.width) // 2
        ly = cy + (ch - logo.height) // 2
        canvas.paste(logo, (lx, ly), logo)
    # Lower-third (name + title)
    if name:
        d = ImageDraw.Draw(canvas)
        font_n = _font(int(h * 0.06), bold=True)
        font_t = _font(int(h * 0.025), bold=False)
        nx = int(w * 0.06)
        ny = int(h * 0.78)
        d.rectangle([nx - 12, ny - 8, nx + int(w * 0.50), ny + int(h * 0.10)],
                    fill=PALETTE["panel"])
        d.rectangle([nx - 12, ny - 8, nx, ny + int(h * 0.10)],
                    fill=PALETTE["primary"])
        d.text((nx + 8, ny), name, fill=PALETTE["ink"], font=font_n)
        if title:
            d.text((nx + 8, ny + int(h * 0.07)), title,
                   fill=PALETTE["muted"], font=font_t)
    return canvas


# ───────────────────────────── C. VS BATTLE ────────────────────────────

def vs_battle(left_path, right_path, left_label="", right_label="",
              *, w=W_DEFAULT, h=H_DEFAULT):
    """Two logos/photos side-by-side, VS in the middle."""
    canvas = _gradient_bg(w, h)
    d = ImageDraw.Draw(canvas)
    # Soft divider
    d.line([(w // 2, int(h * 0.15)), (w // 2, int(h * 0.85))],
           fill=PALETTE["panel2"], width=2)

    # Left
    if left_path and Path(left_path).exists():
        left = _fit_image(Image.open(left_path),
                          int(w * 0.32), int(h * 0.5))
        lx = int(w * 0.25 - left.width // 2)
        ly = (h - left.height) // 2
        canvas.paste(left, (lx, ly), left)
    # Right
    if right_path and Path(right_path).exists():
        right = _fit_image(Image.open(right_path),
                           int(w * 0.32), int(h * 0.5))
        rx = int(w * 0.75 - right.width // 2)
        ry = (h - right.height) // 2
        canvas.paste(right, (rx, ry), right)

    # Center "VS"
    font_vs = _font(int(h * 0.18), bold=True)
    _draw_text_centered(d, "VS", font_vs, w // 2,
                        int(h * 0.42), PALETTE["secondary"])

    # Labels under each
    if left_label:
        font_l = _font(int(h * 0.04), bold=True)
        _draw_text_centered(d, left_label, font_l,
                            int(w * 0.25), int(h * 0.85), PALETTE["ink"])
    if right_label:
        font_l = _font(int(h * 0.04), bold=True)
        _draw_text_centered(d, right_label, font_l,
                            int(w * 0.75), int(h * 0.85), PALETTE["ink"])
    return canvas


# ───────────────────────── D. ILLUSTRATION + CAPTION ───────────────────

def illo_caption(illustration_path, caption, *,
                 w=W_DEFAULT, h=H_DEFAULT):
    """Concept illustration centered + bold caption strip below."""
    canvas = _gradient_bg(w, h)
    if illustration_path and Path(illustration_path).exists():
        illo = _fit_image(Image.open(illustration_path),
                          int(w * 0.55), int(h * 0.55))
        ix = (w - illo.width) // 2
        iy = int(h * 0.18)
        canvas.paste(illo, (ix, iy), illo)
    # Caption strip
    if caption:
        d = ImageDraw.Draw(canvas)
        strip_h = int(h * 0.15)
        strip_y = int(h * 0.78)
        d.rectangle([0, strip_y, w, strip_y + strip_h],
                    fill=PALETTE["panel"])
        d.rectangle([0, strip_y, w, strip_y + 6],
                    fill=PALETTE["primary"])
        font = _font(int(h * 0.07), bold=True)
        _draw_text_centered(d, caption.upper(), font,
                            w // 2, strip_y + int(strip_h * 0.25),
                            PALETTE["ink"])
    return canvas


# ───────────────────────────── E. NEWS ANCHOR ──────────────────────────

def news_anchor(person_photo_path, name, title="", company_logo_path=None,
                *, w=W_DEFAULT, h=H_DEFAULT):
    """Circular person photo + lower-third name/title + corner logo."""
    canvas = _gradient_bg(w, h)
    d = ImageDraw.Draw(canvas)
    # Circular person photo, large, slightly left of center
    if person_photo_path and Path(person_photo_path).exists():
        circ_size = int(min(w, h) * 0.58)
        circ = _circular_crop(Image.open(person_photo_path), circ_size)
        cx = (w - circ.width) // 2
        cy = int(h * 0.10)
        # Accent ring around the circle
        ring_pad = 8
        d.ellipse([cx - ring_pad, cy - ring_pad,
                   cx + circ.width + ring_pad, cy + circ.height + ring_pad],
                  outline=PALETTE["primary"], width=ring_pad)
        canvas.paste(circ, (cx, cy), circ)
    # Lower third
    nx = int(w * 0.10)
    ny = int(h * 0.80)
    nh = int(h * 0.13)
    nw = int(w * 0.55)
    d.rectangle([nx, ny, nx + nw, ny + nh], fill=PALETTE["panel"])
    d.rectangle([nx, ny, nx + 12, ny + nh], fill=PALETTE["primary"])
    font_n = _font(int(h * 0.07), bold=True)
    font_t = _font(int(h * 0.03), bold=False)
    d.text((nx + 30, ny + int(h * 0.015)), name,
           fill=PALETTE["ink"], font=font_n)
    if title:
        d.text((nx + 30, ny + int(h * 0.085)), title,
               fill=PALETTE["muted"], font=font_t)
    # Corner logo
    if company_logo_path and Path(company_logo_path).exists():
        logo = _fit_image(Image.open(company_logo_path),
                          int(w * 0.10), int(h * 0.10))
        lx = int(w * 0.85)
        ly = int(h * 0.82)
        # background card
        d.rounded_rectangle([lx - 18, ly - 18,
                             lx + logo.width + 18, ly + logo.height + 18],
                            radius=12, fill=PALETTE["panel2"])
        canvas.paste(logo, (lx, ly), logo)
    return canvas


# ───────────────────────────── F. STAT CARD ────────────────────────────

def stat_card(stat, label="", source="", company_logo_path=None,
              *, w=W_DEFAULT, h=H_DEFAULT):
    """Massive stat number, smaller label, optional company logo corner."""
    canvas = _gradient_bg(w, h)
    d = ImageDraw.Draw(canvas)
    # Big number
    big_font = _font(int(h * 0.32), bold=True)
    _draw_text_centered(d, stat, big_font, w // 2,
                        int(h * 0.20), PALETTE["primary"])
    if label:
        lbl_font = _font(int(h * 0.07), bold=True)
        _draw_text_centered(d, label.upper(), lbl_font, w // 2,
                            int(h * 0.62), PALETTE["ink"])
    if source:
        src_font = _font(int(h * 0.025), bold=False)
        _draw_text_centered(d, f"source: {source}", src_font, w // 2,
                            int(h * 0.74), PALETTE["muted"])
    if company_logo_path and Path(company_logo_path).exists():
        logo = _fit_image(Image.open(company_logo_path),
                          int(w * 0.08), int(h * 0.08))
        lx = int(w * 0.05)
        ly = int(h * 0.85)
        d.rounded_rectangle([lx - 14, ly - 14,
                             lx + logo.width + 14, ly + logo.height + 14],
                            radius=10, fill=PALETTE["panel2"])
        canvas.paste(logo, (lx, ly), logo)
    return canvas


# ──────────────────────────── dispatcher ───────────────────────────────

LAYOUTS = {
    "logo_hero":    logo_hero,
    "logo_photo":   logo_photo,
    "vs_battle":    vs_battle,
    "illo_caption": illo_caption,
    "news_anchor":  news_anchor,
    "stat_card":    stat_card,
}


def render_layout(layout, output_path, **kwargs):
    if layout not in LAYOUTS:
        raise ValueError(f"unknown layout {layout!r}; "
                         f"choose from {list(LAYOUTS)}")
    img = LAYOUTS[layout](**kwargs)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG")
    return out


def main():
    p = argparse.ArgumentParser(description="Phase 21.6 composite layouts")
    p.add_argument("layout", choices=list(LAYOUTS))
    p.add_argument("output")
    p.add_argument("--logo-path")
    p.add_argument("--photo-path")
    p.add_argument("--left-path")
    p.add_argument("--right-path")
    p.add_argument("--illo-path")
    p.add_argument("--label", default="")
    p.add_argument("--name", default="")
    p.add_argument("--title", default="")
    p.add_argument("--caption", default="")
    p.add_argument("--stat", default="")
    p.add_argument("--source", default="")
    p.add_argument("--left-label", default="")
    p.add_argument("--right-label", default="")
    args = p.parse_args()

    # Translate flat CLI args into the right kwargs per layout
    if args.layout == "logo_hero":
        out = render_layout("logo_hero", args.output,
                            logo_path=args.logo_path, label=args.label)
    elif args.layout == "logo_photo":
        out = render_layout("logo_photo", args.output,
                            person_photo_path=args.photo_path,
                            logo_path=args.logo_path,
                            name=args.name, title=args.title)
    elif args.layout == "vs_battle":
        out = render_layout("vs_battle", args.output,
                            left_path=args.left_path,
                            right_path=args.right_path,
                            left_label=args.left_label,
                            right_label=args.right_label)
    elif args.layout == "illo_caption":
        out = render_layout("illo_caption", args.output,
                            illustration_path=args.illo_path,
                            caption=args.caption)
    elif args.layout == "news_anchor":
        out = render_layout("news_anchor", args.output,
                            person_photo_path=args.photo_path, name=args.name,
                            title=args.title,
                            company_logo_path=args.logo_path)
    elif args.layout == "stat_card":
        out = render_layout("stat_card", args.output, stat=args.stat,
                            label=args.label, source=args.source,
                            company_logo_path=args.logo_path)
    print(f"✅ {args.layout} → {out}")


if __name__ == "__main__":
    main()
