#!/usr/bin/env python3
"""
McNeillium AI — Asset Renderers (Phase 12.3)

Renders styled PNG composites from real assets. The video generator
then plays these as static clips with Ken Burns motion.

  render_person_card_png(photo, name, role, out, w, h)
  render_logo_card_png(logo, name, out, w, h)
  render_article_card_png(screenshot, source, date, out, w, h)

These are composited frames — single PNG output per asset. The
animation (scale-in, fade-in, slow zoom) is added by the video
generator's create_static_clip + Ken Burns crop, so we don't have to
re-render frame sequences here.
"""

import io
import os
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

PROJECT_ROOT = Path(__file__).resolve().parent.parent

BG_DARK = (10, 14, 24, 255)
ACCENT_BLUE = (91, 163, 245, 255)
ACCENT_ORANGE = (255, 107, 53, 255)
TEXT_PRIMARY = (230, 237, 243, 255)
TEXT_DIM = (140, 150, 165, 255)


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


def _gradient_bg(w, h):
    """Subtle vertical gradient on the dark navy bg."""
    img = Image.new("RGB", (w, h), BG_DARK[:3])
    d = ImageDraw.Draw(img)
    for y in range(0, h, 2):
        shade = int(2 + 14 * (y / h))
        d.rectangle([0, y, w, y + 2],
                    fill=(BG_DARK[0] + shade // 2,
                          BG_DARK[1] + shade // 2,
                          BG_DARK[2] + shade))
    return img


def _rounded_mask(size, radius):
    mask = Image.new("L", size, 0)
    d = ImageDraw.Draw(mask)
    d.rounded_rectangle([0, 0, size[0] - 1, size[1] - 1],
                        radius=radius, fill=255)
    return mask


def _drop_shadow(size, blur=18, alpha=180):
    """Drop shadow image for an element of `size`."""
    sh = Image.new("RGBA", (size[0] + blur * 2, size[1] + blur * 2),
                   (0, 0, 0, 0))
    d = ImageDraw.Draw(sh)
    d.rounded_rectangle(
        [blur, blur, blur + size[0], blur + size[1]],
        radius=24, fill=(0, 0, 0, alpha),
    )
    return sh.filter(ImageFilter.GaussianBlur(blur))


# ─── PEOPLE CARDS ────────────────────────────────────────────────

def render_person_card_png(photo_path, name, role, output_png,
                            w=1920, h=1080):
    """Dark gradient bg, photo card centred-ish, name + role caption below."""
    bg = _gradient_bg(w, h).convert("RGBA")
    if not photo_path or not Path(photo_path).exists():
        return None

    photo = Image.open(photo_path).convert("RGB")

    # Frame the photo in a tall portrait card (3:4 aspect)
    card_w = int(h * 0.55)        # narrower than tall
    card_h = int(card_w * 4 / 3)
    if card_h > h - 240:
        card_h = h - 240
        card_w = int(card_h * 3 / 4)

    # Cover-fit the source photo into the card
    src_ratio = photo.width / photo.height
    dst_ratio = card_w / card_h
    if src_ratio > dst_ratio:
        # source is wider — crop sides
        scale = card_h / photo.height
        new_w = int(photo.width * scale)
        photo = photo.resize((new_w, card_h), Image.LANCZOS)
        left = (new_w - card_w) // 2
        photo = photo.crop((left, 0, left + card_w, card_h))
    else:
        scale = card_w / photo.width
        new_h = int(photo.height * scale)
        photo = photo.resize((card_w, new_h), Image.LANCZOS)
        top = (new_h - card_h) // 2
        photo = photo.crop((0, top, card_w, top + card_h))

    # Rounded corners
    mask = _rounded_mask((card_w, card_h), 28)
    photo_rgba = photo.convert("RGBA")
    photo_rgba.putalpha(mask)

    # Drop shadow
    sh = _drop_shadow((card_w, card_h), blur=22, alpha=220)
    # Position
    cx, cy = w // 2, int(h * 0.46)
    sh_x = cx - sh.width // 2 + 4
    sh_y = cy - sh.height // 2 + 12
    bg.alpha_composite(sh, (sh_x, sh_y))
    bg.alpha_composite(photo_rgba,
                       (cx - card_w // 2, cy - card_h // 2))

    # Accent bar above caption
    d = ImageDraw.Draw(bg)
    d.rectangle([cx - 140, cy + card_h // 2 + 30,
                 cx + 140, cy + card_h // 2 + 35],
                fill=ACCENT_BLUE)

    # Name (Impact / bold) and role caption
    f_name = _font(64, bold=True, impact=True)
    f_role = _font(28)
    d.text((cx + 2, cy + card_h // 2 + 70 + 2), name.upper(),
           font=f_name, fill=(0, 0, 0), anchor="mm")
    d.text((cx, cy + card_h // 2 + 70), name.upper(),
           font=f_name, fill=TEXT_PRIMARY, anchor="mm")
    if role:
        d.text((cx, cy + card_h // 2 + 122), role,
               font=f_role, fill=TEXT_DIM, anchor="mm")

    output_png = Path(output_png)
    output_png.parent.mkdir(parents=True, exist_ok=True)
    bg.convert("RGB").save(str(output_png), "PNG")
    return str(output_png)


# ─── LOGO CARDS ──────────────────────────────────────────────────

def render_logo_card_png(logo_path, company_name, output_png,
                          w=1920, h=1080):
    """Dark gradient bg with logo centred on a subtle inner card."""
    bg = _gradient_bg(w, h).convert("RGBA")
    if not logo_path or not Path(logo_path).exists():
        return None
    logo = Image.open(logo_path).convert("RGBA")

    # Inner card
    card_w = int(w * 0.55)
    card_h = int(h * 0.6)
    cx, cy = w // 2, h // 2
    card_box = [cx - card_w // 2, cy - card_h // 2,
                cx + card_w // 2, cy + card_h // 2]
    d = ImageDraw.Draw(bg)
    d.rounded_rectangle(card_box, radius=32,
                         fill=(20, 26, 40, 255),
                         outline=(50, 60, 84, 255), width=2)

    # Resize logo to fit inside card with generous padding
    pad = 80
    max_w = card_w - pad * 2
    max_h = card_h - pad * 2 - 80  # room for caption below
    src_ratio = logo.width / logo.height
    if src_ratio > max_w / max_h:
        new_w = max_w
        new_h = int(max_w / src_ratio)
    else:
        new_h = max_h
        new_w = int(max_h * src_ratio)
    logo = logo.resize((new_w, new_h), Image.LANCZOS)
    bg.alpha_composite(logo,
                       (cx - new_w // 2, cy - new_h // 2 - 30))

    # Company name beneath
    f_name = _font(48, bold=True, impact=True)
    d.text((cx, cy + card_h // 2 - 60), company_name.upper(),
           font=f_name, fill=TEXT_PRIMARY, anchor="mm")
    # Accent bar
    d.rectangle([cx - 80, cy + card_h // 2 - 30,
                 cx + 80, cy + card_h // 2 - 26],
                fill=ACCENT_BLUE)

    output_png = Path(output_png)
    output_png.parent.mkdir(parents=True, exist_ok=True)
    bg.convert("RGB").save(str(output_png), "PNG")
    return str(output_png)


# ─── ARTICLE CARDS (browser chrome around a screenshot) ─────────

def render_article_card_png(screenshot_path, source, date,
                              output_png, w=1920, h=1080):
    if not screenshot_path or not Path(screenshot_path).exists():
        return None
    bg = _gradient_bg(w, h).convert("RGBA")
    shot = Image.open(screenshot_path).convert("RGB")

    # Frame size — leave 80px margins, top 120px for source bar
    inner_w = w - 160
    inner_h = h - 240
    # Fit screenshot into inner area
    src_ratio = shot.width / shot.height
    dst_ratio = inner_w / inner_h
    if src_ratio > dst_ratio:
        scale = inner_w / shot.width
        new_w = inner_w
        new_h = int(shot.height * scale)
    else:
        scale = inner_h / shot.height
        new_w = int(shot.width * scale)
        new_h = inner_h
    shot = shot.resize((new_w, new_h), Image.LANCZOS)

    cx, cy = w // 2, h // 2 + 50
    chrome_x = cx - new_w // 2
    chrome_y = cy - new_h // 2

    # Browser-chrome header strip
    header_h = 56
    d = ImageDraw.Draw(bg)
    d.rounded_rectangle(
        [chrome_x - 4, chrome_y - header_h - 4,
         chrome_x + new_w + 4, chrome_y + new_h + 4],
        radius=18, fill=(20, 26, 40, 255),
        outline=(60, 72, 96, 255), width=2,
    )
    d.rectangle(
        [chrome_x, chrome_y - header_h,
         chrome_x + new_w, chrome_y],
        fill=(30, 38, 56, 255),
    )
    # Traffic-light dots
    for i, col in enumerate([(255, 95, 86, 255),
                              (255, 189, 46, 255),
                              (39, 201, 63, 255)]):
        d.ellipse([chrome_x + 20 + i * 28, chrome_y - header_h // 2 - 10,
                   chrome_x + 38 + i * 28, chrome_y - header_h // 2 + 8],
                  fill=col)
    # URL bar
    d.rounded_rectangle(
        [chrome_x + 130, chrome_y - header_h // 2 - 12,
         chrome_x + new_w - 130, chrome_y - header_h // 2 + 12],
        radius=8, fill=(12, 18, 28, 255),
    )
    f_url = _font(20)
    d.text((chrome_x + 150, chrome_y - header_h // 2),
           source.lower() + " — " + date, font=f_url,
           fill=TEXT_DIM, anchor="lm")

    # Drop shadow + paste the screenshot
    sh = _drop_shadow((new_w, new_h), blur=20, alpha=180)
    bg.alpha_composite(sh, (chrome_x - 20 + 8, chrome_y - 20 + 14))
    bg.paste(shot, (chrome_x, chrome_y))

    # Title banner at top
    f_title = _font(42, bold=True, impact=True)
    d.text((cx + 2, 70 + 2), source.upper(), font=f_title,
           fill=(0, 0, 0), anchor="mm")
    d.text((cx, 70), source.upper(), font=f_title,
           fill=TEXT_PRIMARY, anchor="mm")
    d.rectangle([cx - 100, 100, cx + 100, 104],
                fill=ACCENT_ORANGE)
    f_date = _font(24)
    d.text((cx, 132), date, font=f_date, fill=TEXT_DIM, anchor="mm")

    output_png = Path(output_png)
    output_png.parent.mkdir(parents=True, exist_ok=True)
    bg.convert("RGB").save(str(output_png), "PNG")
    return str(output_png)
