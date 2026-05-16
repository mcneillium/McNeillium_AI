#!/usr/bin/env python3
"""
McNeillium_AI — Phase 20.2: Concept Illustration Library

Renders simple, on-brand conceptual illustrations for abstract
narration moments (lost leverage, monopoly broken, growth, etc.).

Design choices
──────────────
- **Pillow-drawn, not scraped.** unDraw/Storyset/Open Doodles all
  require browser-based discovery and have ToS friction with bulk
  download. Drawing 10-15 clean icons in code gives full control
  over the channel palette and avoids licensing entanglement.
- **Static, not animated.** Per FIX 2A from v19b, the channel
  aesthetic is "no Ken Burns, no scale ramp." Each concept renders
  to a held PNG, which the renderer then loops to MP4.
- **One pass per concept.** Cached by (concept, w, h, accent) so
  re-renders are free.
- **Channel palette.** Pulls primary/secondary from niche_profile.yaml
  (teal #00D4AA + orange #FF6B35) and uses them consistently.

Public API
──────────
  list_concepts() -> list[str]
      All known concept slugs.

  match_concept(query) -> str | None
      Fuzzy-match a free-form concept word to a known slug.

  render_concept(concept, duration, output_path,
                 w=1920, h=1080) -> Path | None
      Renders the concept as a static MP4 of `duration` seconds.

CLI:
  python utils/concept_illustrations.py list
  python utils/concept_illustrations.py preview <concept>
  python utils/concept_illustrations.py render <concept> <out.mp4> [--duration 4]
"""

import argparse
import hashlib
import io
import math
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

if sys.stdout.encoding and sys.stdout.encoding.lower().replace("-", "") != "utf8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8",
                                  errors="replace")


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ASSETS_DIR = PROJECT_ROOT / "assets" / "illustrations"
CACHE_DIR = PROJECT_ROOT / "output" / "_concept_cache"

# Channel palette (matches niche_profile.yaml)
PALETTE = {
    "primary":   (0, 212, 170),    # #00D4AA teal
    "secondary": (255, 107, 53),   # #FF6B35 orange
    "ink":       (230, 237, 243),  # #E6EDF3 near-white
    "muted":     (149, 163, 182),  # #95A3B6 slate
    "bg":        (10, 14, 24),     # #0A0E18 deep navy
    "panel":     (19, 24, 38),     # #131826 panel
}


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


def _new_canvas(w, h):
    img = Image.new("RGB", (w, h), PALETTE["bg"])
    # Subtle vertical gradient for depth
    draw = ImageDraw.Draw(img)
    for y in range(0, h, 2):
        t = y / h
        r = int(PALETTE["bg"][0] + 12 * t)
        g = int(PALETTE["bg"][1] + 18 * t)
        b = int(PALETTE["bg"][2] + 25 * t)
        draw.rectangle([0, y, w, y + 2], fill=(r, g, b))
    return img


def _label(img, text, *, anchor_y=None):
    """Draw caption text below the icon area."""
    draw = ImageDraw.Draw(img)
    w, h = img.size
    if anchor_y is None:
        anchor_y = int(h * 0.78)
    font = _font(int(h * 0.06), bold=True)
    # Centered using textbbox
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    draw.text(((w - tw) // 2, anchor_y), text,
              fill=PALETTE["ink"], font=font)


# ─────────────────────────── concept drawings ──────────────────────────

def _draw_scale_tipping(w, h, label="LOST LEVERAGE"):
    """An unbalanced scale — left pan way up, right pan way down."""
    img = _new_canvas(w, h)
    d = ImageDraw.Draw(img)
    cx, cy = w // 2, int(h * 0.42)
    arm_len = int(w * 0.20)
    arm_w = max(8, h // 80)
    # Tilt the arm
    angle = math.radians(-22)
    # Pillar
    d.rectangle([cx - 8, cy, cx + 8, cy + int(h * 0.30)],
                fill=PALETTE["primary"])
    # Base
    d.rectangle([cx - int(w * 0.10), cy + int(h * 0.30),
                 cx + int(w * 0.10), cy + int(h * 0.32)],
                fill=PALETTE["primary"])
    # Arm endpoints
    lx = cx - int(arm_len * math.cos(angle))
    ly = cy - int(arm_len * math.sin(angle))
    rx = cx + int(arm_len * math.cos(angle))
    ry = cy + int(arm_len * math.sin(angle))
    d.line([lx, ly, rx, ry], fill=PALETTE["primary"], width=arm_w)
    # Pans (circles) with chains
    pan_r = int(w * 0.05)
    for px, py, color in [(lx, ly + int(h * 0.10), PALETTE["muted"]),
                           (rx, ry + int(h * 0.10), PALETTE["secondary"])]:
        # chain
        d.line([px, ly if px == lx else ry, px, py - pan_r],
               fill=PALETTE["muted"], width=4)
        # pan
        d.ellipse([px - pan_r, py - pan_r // 2,
                   px + pan_r, py + pan_r], outline=color, width=6)
    _label(img, label)
    return img


def _draw_lock_opening(w, h, label="EXCLUSIVITY ENDED"):
    """A padlock with the shackle disengaged."""
    img = _new_canvas(w, h)
    d = ImageDraw.Draw(img)
    cx, cy = w // 2, int(h * 0.46)
    body_w, body_h = int(w * 0.18), int(h * 0.20)
    # Body
    d.rounded_rectangle(
        [cx - body_w // 2, cy, cx + body_w // 2, cy + body_h],
        radius=20, outline=PALETTE["secondary"], width=10
    )
    # Shackle (open — arc shifted right)
    arc_r = int(body_w * 0.45)
    arc_x = cx - arc_r // 2
    arc_y = cy - int(body_h * 0.85)
    d.arc([arc_x, arc_y, arc_x + arc_r * 2, arc_y + arc_r * 2],
          start=180, end=350, fill=PALETTE["secondary"], width=10)
    # Keyhole
    d.ellipse([cx - 12, cy + body_h // 2 - 14,
               cx + 12, cy + body_h // 2 + 10],
              fill=PALETTE["primary"])
    d.rectangle([cx - 4, cy + body_h // 2 + 6, cx + 4, cy + body_h - 18],
                fill=PALETTE["primary"])
    _label(img, label)
    return img


def _draw_chain_breaking(w, h, label="MONOPOLY BROKEN"):
    """Two chain links separating with a gap and a fracture spark."""
    img = _new_canvas(w, h)
    d = ImageDraw.Draw(img)
    cx, cy = w // 2, int(h * 0.42)
    link_w, link_h = int(w * 0.10), int(h * 0.13)
    gap = int(w * 0.03)
    # Left link
    d.rounded_rectangle(
        [cx - link_w - gap, cy - link_h // 2,
         cx - gap, cy + link_h // 2],
        radius=link_h // 2, outline=PALETTE["primary"], width=10,
    )
    # Right link
    d.rounded_rectangle(
        [cx + gap, cy - link_h // 2,
         cx + link_w + gap, cy + link_h // 2],
        radius=link_h // 2, outline=PALETTE["primary"], width=10,
    )
    # Spark in the middle
    spark_pts = []
    for i in range(8):
        ang = i * (2 * math.pi / 8)
        r = 26 if i % 2 == 0 else 12
        spark_pts.append((cx + int(r * math.cos(ang)),
                          cy + int(r * math.sin(ang))))
    d.polygon(spark_pts, fill=PALETTE["secondary"])
    _label(img, label)
    return img


def _draw_arrow_up(w, h, label="GROWTH"):
    """Bold upward arrow."""
    img = _new_canvas(w, h)
    d = ImageDraw.Draw(img)
    cx, cy = w // 2, int(h * 0.42)
    al = int(h * 0.34)
    aw = int(w * 0.10)
    # Shaft
    d.rectangle([cx - aw // 4, cy, cx + aw // 4, cy + al],
                fill=PALETTE["primary"])
    # Head
    d.polygon([(cx, cy - aw // 2),
               (cx + aw, cy + aw // 2),
               (cx - aw, cy + aw // 2)],
              fill=PALETTE["primary"])
    _label(img, label)
    return img


def _draw_arrow_down(w, h, label="DECLINE"):
    """Bold downward arrow in alert orange."""
    img = _new_canvas(w, h)
    d = ImageDraw.Draw(img)
    cx, cy = w // 2, int(h * 0.32)
    al = int(h * 0.34)
    aw = int(w * 0.10)
    d.rectangle([cx - aw // 4, cy, cx + aw // 4, cy + al],
                fill=PALETTE["secondary"])
    d.polygon([(cx, cy + al + aw // 2),
               (cx + aw, cy + al - aw // 2),
               (cx - aw, cy + al - aw // 2)],
              fill=PALETTE["secondary"])
    _label(img, label)
    return img


def _draw_overlap_circles(w, h, label="PARTNERSHIP"):
    """Two overlapping rings (Venn diagram)."""
    img = _new_canvas(w, h)
    d = ImageDraw.Draw(img)
    cx, cy = w // 2, int(h * 0.42)
    r = int(h * 0.16)
    offset = int(r * 0.6)
    d.ellipse([cx - offset - r, cy - r, cx - offset + r, cy + r],
              outline=PALETTE["primary"], width=10)
    d.ellipse([cx + offset - r, cy - r, cx + offset + r, cy + r],
              outline=PALETTE["secondary"], width=10)
    _label(img, label)
    return img


def _draw_castle_moat(w, h, label="MOAT DRAINED"):
    """Castle silhouette with a near-empty moat."""
    img = _new_canvas(w, h)
    d = ImageDraw.Draw(img)
    cx, cy = w // 2, int(h * 0.50)
    cw, ch = int(w * 0.22), int(h * 0.20)
    # Castle body
    d.rectangle([cx - cw // 2, cy - ch // 2, cx + cw // 2, cy + ch // 2],
                fill=PALETTE["panel"], outline=PALETTE["primary"], width=6)
    # Crenellations
    crenel_w = cw // 7
    for i in range(7):
        if i % 2 == 0:
            x0 = cx - cw // 2 + i * crenel_w
            d.rectangle([x0, cy - ch // 2 - crenel_w,
                         x0 + crenel_w, cy - ch // 2],
                        fill=PALETTE["primary"])
    # Door
    d.rectangle([cx - 18, cy + ch // 2 - 50, cx + 18, cy + ch // 2],
                fill=PALETTE["bg"])
    # Drained moat — thin orange line at the bottom (would have been blue)
    moat_y = cy + ch // 2 + 60
    d.line([cx - cw, moat_y, cx + cw, moat_y],
           fill=PALETTE["secondary"], width=4)
    # Cracks in the dry moat bed
    for ox in (-cw // 2, 0, cw // 2):
        d.line([cx + ox, moat_y + 4, cx + ox + 30, moat_y + 30],
               fill=PALETTE["muted"], width=2)
    _label(img, label)
    return img


def _draw_network_nodes(w, h, label="MULTI-CLOUD"):
    """A central node connected to many surrounding nodes."""
    img = _new_canvas(w, h)
    d = ImageDraw.Draw(img)
    cx, cy = w // 2, int(h * 0.42)
    r = int(h * 0.025)
    # Outer ring of nodes
    n = 8
    radius = int(h * 0.20)
    points = []
    for i in range(n):
        ang = i * (2 * math.pi / n) - math.pi / 2
        x = cx + int(radius * math.cos(ang))
        y = cy + int(radius * math.sin(ang))
        points.append((x, y))
    # Lines from center
    for x, y in points:
        d.line([cx, cy, x, y], fill=PALETTE["muted"], width=3)
    # Nodes
    for x, y in points:
        d.ellipse([x - r, y - r, x + r, y + r],
                  fill=PALETTE["primary"])
    # Center node — bigger, secondary
    d.ellipse([cx - r * 2, cy - r * 2, cx + r * 2, cy + r * 2],
              fill=PALETTE["secondary"])
    _label(img, label)
    return img


def _draw_arrows_leaving(w, h, label="CUSTOMER EXODUS"):
    """A hub with arrows pointing OUT in all directions."""
    img = _new_canvas(w, h)
    d = ImageDraw.Draw(img)
    cx, cy = w // 2, int(h * 0.42)
    hub_r = int(h * 0.04)
    d.ellipse([cx - hub_r, cy - hub_r, cx + hub_r, cy + hub_r],
              fill=PALETTE["secondary"])
    arrow_r = int(h * 0.20)
    head = int(h * 0.025)
    for i in range(6):
        ang = i * (2 * math.pi / 6) - math.pi / 2
        ex = cx + int(arrow_r * math.cos(ang))
        ey = cy + int(arrow_r * math.sin(ang))
        d.line([cx, cy, ex, ey], fill=PALETTE["secondary"], width=6)
        # Arrowhead
        ax = int(head * math.cos(ang))
        ay = int(head * math.sin(ang))
        perp_x = int(head * math.cos(ang + math.pi / 2))
        perp_y = int(head * math.sin(ang + math.pi / 2))
        d.polygon([(ex + ax, ey + ay),
                   (ex - perp_x // 2, ey - perp_y // 2),
                   (ex + perp_x // 2, ey + perp_y // 2)],
                  fill=PALETTE["secondary"])
    _label(img, label)
    return img


def _draw_path_branching(w, h, label="STRATEGIC SHIFT"):
    """A path that splits into two divergent directions."""
    img = _new_canvas(w, h)
    d = ImageDraw.Draw(img)
    sx, sy = int(w * 0.20), int(h * 0.62)
    fork_x = int(w * 0.50)
    fork_y = int(h * 0.42)
    # Approach
    d.line([sx, sy, fork_x, fork_y], fill=PALETTE["muted"], width=10)
    # Up branch
    d.line([fork_x, fork_y, int(w * 0.80), int(h * 0.28)],
           fill=PALETTE["primary"], width=10)
    # Down branch
    d.line([fork_x, fork_y, int(w * 0.80), int(h * 0.58)],
           fill=PALETTE["secondary"], width=10)
    _label(img, label)
    return img


def _draw_shield(w, h, label="DEFENSIVE PLAY"):
    """A shield silhouette."""
    img = _new_canvas(w, h)
    d = ImageDraw.Draw(img)
    cx, cy = w // 2, int(h * 0.42)
    sw, sh = int(w * 0.16), int(h * 0.30)
    pts = [
        (cx - sw, cy - sh // 2),
        (cx + sw, cy - sh // 2),
        (cx + sw, cy + sh // 4),
        (cx, cy + sh // 2 + 20),
        (cx - sw, cy + sh // 4),
    ]
    d.polygon(pts, outline=PALETTE["primary"], width=10)
    # Center cross or chevron
    d.line([cx, cy - sh // 4, cx, cy + sh // 4],
           fill=PALETTE["primary"], width=6)
    d.line([cx - sw // 2, cy, cx + sw // 2, cy],
           fill=PALETTE["primary"], width=6)
    _label(img, label)
    return img


def _draw_commodity_grid(w, h, label="COMMODITIZED"):
    """A grid of identical squares — visual metaphor for sameness."""
    img = _new_canvas(w, h)
    d = ImageDraw.Draw(img)
    cx, cy = w // 2, int(h * 0.42)
    cell = int(h * 0.07)
    gap = int(cell * 0.25)
    cols, rows = 5, 4
    grid_w = cols * cell + (cols - 1) * gap
    grid_h = rows * cell + (rows - 1) * gap
    x0 = cx - grid_w // 2
    y0 = cy - grid_h // 2
    for r in range(rows):
        for c in range(cols):
            x = x0 + c * (cell + gap)
            y = y0 + r * (cell + gap)
            d.rounded_rectangle([x, y, x + cell, y + cell],
                                radius=8, fill=PALETTE["muted"])
    _label(img, label)
    return img


# ──────────────────────────── concept registry ─────────────────────────

CONCEPT_REGISTRY = {
    # slug → (drawer_fn, default_label)
    "lost_leverage":         (_draw_scale_tipping,    "LOST LEVERAGE"),
    "leverage":              (_draw_scale_tipping,    "LEVERAGE"),
    "scale_tipping":         (_draw_scale_tipping,    "SCALE TIPPING"),
    "exclusivity_lost":      (_draw_lock_opening,     "EXCLUSIVITY ENDED"),
    "exclusive_access":      (_draw_lock_opening,     "EXCLUSIVE ACCESS"),
    "monopoly_ends":         (_draw_chain_breaking,   "MONOPOLY BROKEN"),
    "monopoly_broken":       (_draw_chain_breaking,   "MONOPOLY BROKEN"),
    "growth":                (_draw_arrow_up,         "GROWTH"),
    "rise":                  (_draw_arrow_up,         "RISE"),
    "decline":               (_draw_arrow_down,       "DECLINE"),
    "pricing_power_collapse":(_draw_arrow_down,       "PRICING COLLAPSE"),
    "aggressive_discounting":(_draw_arrow_down,       "DISCOUNTING"),
    "pricing_pressure":      (_draw_arrow_down,       "PRICING PRESSURE"),
    "partnership":           (_draw_overlap_circles,  "PARTNERSHIP"),
    "negotiation":           (_draw_overlap_circles,  "NEGOTIATION"),
    "moat_drained":          (_draw_castle_moat,      "MOAT DRAINED"),
    "moat":                  (_draw_castle_moat,      "MOAT"),
    "multi_cloud":           (_draw_network_nodes,    "MULTI-CLOUD"),
    "omnichannel_distribution":(_draw_network_nodes,  "DISTRIBUTION"),
    "multi_model_choice":    (_draw_network_nodes,    "MODEL CHOICE"),
    "ecosystem":             (_draw_network_nodes,    "ECOSYSTEM"),
    "customer_attrition":    (_draw_arrows_leaving,   "CUSTOMER EXODUS"),
    "exodus":                (_draw_arrows_leaving,   "EXODUS"),
    "strategic_shift":       (_draw_path_branching,   "STRATEGIC SHIFT"),
    "ground_shifting":       (_draw_path_branching,   "GROUND SHIFTING"),
    "tectonic_shift":        (_draw_path_branching,   "TECTONIC SHIFT"),
    "fork":                  (_draw_path_branching,   "FORK"),
    "pivot":                 (_draw_path_branching,   "PIVOT"),
    "defense":               (_draw_shield,           "DEFENSIVE PLAY"),
    "defensive":             (_draw_shield,           "DEFENSIVE PLAY"),
    "commoditization":       (_draw_commodity_grid,   "COMMODITIZED"),
    "commoditized":          (_draw_commodity_grid,   "COMMODITIZED"),
}


def list_concepts():
    return sorted(CONCEPT_REGISTRY)


def match_concept(query):
    """Fuzzy-match a free-form concept word to a known slug.

    Strategy:
      1. Exact (case/punctuation-normalized) match
      2. Substring match (query in slug or slug in query)
      3. Token overlap — return the slug with most shared tokens
    """
    if not query:
        return None
    norm = query.lower().replace("-", "_").replace(" ", "_")
    if norm in CONCEPT_REGISTRY:
        return norm
    # Substring
    for slug in CONCEPT_REGISTRY:
        if slug in norm or norm in slug:
            return slug
    # Token overlap
    qtokens = set(norm.split("_"))
    best, best_score = None, 0
    for slug in CONCEPT_REGISTRY:
        score = len(qtokens & set(slug.split("_")))
        if score > best_score:
            best, best_score = slug, score
    return best


# ──────────────────────────── render ───────────────────────────────────

def _ffmpeg():
    return shutil.which("ffmpeg") or "ffmpeg"


def _png_for_concept(concept_slug, w, h):
    fn, label = CONCEPT_REGISTRY[concept_slug]
    img = fn(w, h, label)
    key = hashlib.sha1(f"{concept_slug}_{w}x{h}".encode()).hexdigest()[:12]
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    png_path = CACHE_DIR / f"{concept_slug}_{key}.png"
    img.save(png_path, "PNG")
    return png_path


def render_concept(concept, duration, output_path,
                   w=1920, h=1080, fps=30):
    """Render a concept as a static MP4 of `duration` seconds.

    Returns the output Path on success, None if no concept match."""
    slug = match_concept(concept)
    if not slug:
        return None
    png_path = _png_for_concept(slug, w, h)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    # Per FIX 2A from v19b: NO motion. Just loop the static PNG.
    cmd = [
        _ffmpeg(), "-y",
        "-loop", "1", "-i", str(png_path),
        "-t", str(duration),
        "-vf", f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
               f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,format=yuv420p",
        "-c:v", "libx264",
        "-profile:v", "main",
        "-pix_fmt", "yuv420p",
        "-colorspace", "bt709",
        "-color_primaries", "bt709",
        "-color_trc", "bt709",
        "-preset", "medium",
        "-crf", "20",
        "-an", "-r", str(fps),
        "-movflags", "+faststart",
        str(out),
    ]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        sys.stderr.write(r.stderr.decode("utf-8", "replace")[-1500:])
        return None
    return out


def main():
    p = argparse.ArgumentParser(description="Phase 20 concept illustrations")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="List known concept slugs")

    pv = sub.add_parser("preview", help="Save the PNG for a concept")
    pv.add_argument("concept")
    pv.add_argument("--out", default=None)

    rd = sub.add_parser("render", help="Render concept as MP4")
    rd.add_argument("concept")
    rd.add_argument("output")
    rd.add_argument("--duration", type=float, default=4.0)

    mt = sub.add_parser("match", help="Show what slug matches a query")
    mt.add_argument("query")

    args = p.parse_args()

    if args.cmd == "list":
        for slug in list_concepts():
            print(f"  {slug}")
        print(f"\n{len(list_concepts())} concepts; "
              f"{len(set(fn for fn, _ in CONCEPT_REGISTRY.values()))} "
              f"unique drawings")
    elif args.cmd == "preview":
        slug = match_concept(args.concept)
        if not slug:
            print(f"❌ no match for {args.concept!r}")
            sys.exit(2)
        png = _png_for_concept(slug, 1920, 1080)
        if args.out:
            shutil.copy(png, args.out)
            print(f"✅ {slug} → {args.out}")
        else:
            print(f"✅ {slug} → {png}")
    elif args.cmd == "render":
        out = render_concept(args.concept, args.duration, args.output)
        if not out:
            print(f"❌ no concept match or render failed")
            sys.exit(2)
        sz = out.stat().st_size / 1024
        print(f"✅ {args.concept} → {out}  ({sz:.0f} KB)")
    elif args.cmd == "match":
        slug = match_concept(args.query)
        print(f"  {args.query!r}  →  {slug}")


if __name__ == "__main__":
    main()
