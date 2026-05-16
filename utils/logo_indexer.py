#!/usr/bin/env python3
"""
McNeillium_AI — Phase 21.1: Simple Icons Logo Indexer

Builds a fast lookup from "company name said in narration" → SVG file
on disk under assets/logos/simple_icons/.

The Simple Icons project keeps two pieces of state:
  - assets/logos/simple_icons/<slug>.svg  (3,400+ brand SVGs)
  - assets/logos/simple-icons-meta.json   (title + aliases per brand)

The slug rule is "lowercase title, drop spaces and most punctuation".
Rather than re-implement that algorithm, we walk the actual files we
have and match each one to its meta entry by sluggified title. Then
we expose three lookup keys per brand:

  - the canonical title  ("Anthropic", "GitHub")
  - all known aliases    (from meta "aliases.aka")
  - a normalized lower-case-no-space key

Output:
  knowledge_base/logo_index.json
    { "anthropic":      "assets/logos/simple_icons/anthropic.svg",
      "claude":         "assets/logos/simple_icons/claude.svg",
      "google gemini":  "assets/logos/simple_icons/googlegemini.svg",
      ... }

Public API
──────────
  load_index() -> dict[str, str]   # cached read
  lookup(name) -> str | None       # SVG path, or None if not in library
  rebuild() -> dict                # re-walk + re-write the index
"""

import argparse
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


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ICONS_DIR = PROJECT_ROOT / "assets" / "logos" / "simple_icons"
META_PATH = PROJECT_ROOT / "assets" / "logos" / "simple-icons-meta.json"
INDEX_PATH = PROJECT_ROOT / "knowledge_base" / "logo_index.json"
RENDER_CACHE = PROJECT_ROOT / "output" / "_logo_render_cache"

_index_cache = None


def _slugify(title):
    """Approximate Simple Icons' slug rule (lowercase, drop most punct)."""
    s = title.lower()
    # Drop everything that isn't ascii alnum
    s = re.sub(r"[^a-z0-9]", "", s)
    return s


def _norm(s):
    """Lookup key: lowercase, collapse whitespace, no punct."""
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def rebuild():
    """Walk SVGs + meta, write knowledge_base/logo_index.json."""
    if not META_PATH.exists():
        print(f"❌ meta file missing: {META_PATH}")
        return {}
    if not ICONS_DIR.exists():
        print(f"❌ icons dir missing: {ICONS_DIR}")
        return {}

    meta = json.loads(META_PATH.read_text(encoding="utf-8"))
    # Group meta entries by sluggified title for cheap join
    meta_by_slug = {}
    for m in meta:
        title = m.get("title", "")
        if not title:
            continue
        slug = _slugify(title)
        meta_by_slug.setdefault(slug, []).append(m)

    index = {}
    matched = unmatched = 0
    for svg in ICONS_DIR.glob("*.svg"):
        slug = svg.stem  # filename slug
        relpath = str(svg.resolve()).replace("\\", "/")
        # Match meta entries (handle the rare case where multiple titles
        # collapse to the same slug — Simple Icons appends a suffix)
        ms = meta_by_slug.get(slug, [])
        if not ms:
            # Fallback — index the slug itself so it's still queryable
            index[slug] = relpath
            unmatched += 1
            continue
        matched += 1
        for m in ms:
            title = m.get("title", "")
            if title:
                index[_norm(title)] = relpath
            for alias in (m.get("aliases", {}).get("aka") or []):
                index[_norm(alias)] = relpath
            for alias in (m.get("aliases", {}).get("dup") or []):
                if isinstance(alias, dict):
                    t = alias.get("title", "")
                    if t:
                        index[_norm(t)] = relpath
                elif isinstance(alias, str):
                    index[_norm(alias)] = relpath
        # Always include the bare slug
        index[slug] = relpath

    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_text(json.dumps(index, indent=2, sort_keys=True),
                          encoding="utf-8")
    print(f"📚 logo index built: {len(index):,} keys "
          f"({matched} SVGs matched to meta, {unmatched} slug-only)")
    print(f"💾 → {INDEX_PATH}")
    return index


def load_index():
    """Lazy-load the cached index. Build it if missing."""
    global _index_cache
    if _index_cache is not None:
        return _index_cache
    if not INDEX_PATH.exists():
        rebuild()
    try:
        _index_cache = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    except Exception:
        _index_cache = {}
    return _index_cache


def render_logo_png(name, *, size=512, accent_bg=False):
    """Render a Simple Icons SVG to a PNG file (cached). Returns Path | None.

    Uses resvg_py (Rust-backed, no native deps on Windows). The
    rendered PNG is RGBA at the requested size; the SVG is centered
    inside a transparent square. accent_bg=True adds a dark panel
    behind the icon so monochrome SVGs don't disappear on dark
    video backgrounds — matches the channel news-card style.
    """
    svg_path = lookup(name)
    if not svg_path:
        return None

    RENDER_CACHE.mkdir(parents=True, exist_ok=True)
    cache_key = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:60]
    bg_tag = "card" if accent_bg else "plain"
    out_path = RENDER_CACHE / f"{cache_key}_{size}_{bg_tag}.png"
    if out_path.exists() and out_path.stat().st_size > 200:
        return out_path

    try:
        import resvg_py
    except ImportError:
        print("⚠️  resvg-py not installed; pip install resvg-py")
        return None

    try:
        svg_text = Path(svg_path).read_text(encoding="utf-8")
    except Exception as e:
        print(f"⚠️  read failed for {svg_path}: {e}")
        return None

    # Simple Icons defaults to a single-color path matching
    # `currentColor` or black. We tint to the accent so it pops on
    # dark backgrounds.
    svg_text = svg_text.replace("<svg ",
                                '<svg fill="#58a6ff" ', 1)

    try:
        png_bytes = resvg_py.svg_to_bytes(
            svg_string=svg_text, width=size, height=size,
        )
    except Exception as e:
        print(f"⚠️  resvg render failed for {name}: {e}")
        return None

    if accent_bg:
        # Composite onto a dark rounded card (using Pillow)
        from PIL import Image, ImageDraw
        from io import BytesIO
        icon = Image.open(BytesIO(bytes(png_bytes))).convert("RGBA")
        # Card background
        card = Image.new("RGBA", (size, size), (13, 17, 23, 255))
        # Subtle rounded-corner mask
        mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            [0, 0, size, size], radius=size // 24, fill=255)
        card.putalpha(mask)
        # Center icon at 70% of card size
        icon_size = int(size * 0.70)
        icon = icon.resize((icon_size, icon_size), Image.LANCZOS)
        ox = (size - icon_size) // 2
        oy = (size - icon_size) // 2
        card.paste(icon, (ox, oy), icon)
        card.save(out_path, "PNG")
    else:
        out_path.write_bytes(bytes(png_bytes))
    return out_path


def lookup(name):
    """Return SVG path (str) or None."""
    if not name:
        return None
    idx = load_index()
    key = _norm(name)
    if key in idx:
        return idx[key]
    # Try without common suffixes/prefixes
    for stripped in (key.replace(" ai", ""), key.replace(" inc", ""),
                     key.replace(" corp", ""), key.replace(" labs", ""),
                     key.replace("the ", "")):
        if stripped != key and stripped in idx:
            return idx[stripped]
    # Substring fallback: company name might be a multi-word, the index
    # might have the brand-only entry (e.g. "Google Cloud" → "google")
    parts = key.split()
    if len(parts) > 1:
        for p in parts:
            if p in idx and len(p) >= 3:
                return idx[p]
    return None


def main():
    p = argparse.ArgumentParser(description="Phase 21 logo indexer")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("rebuild", help="Re-scan SVGs + meta")
    sub.add_parser("stats", help="Print index size")
    lk = sub.add_parser("lookup", help="Test lookup for one or more names")
    lk.add_argument("names", nargs="+")
    args = p.parse_args()

    if args.cmd == "rebuild":
        rebuild()
    elif args.cmd == "stats":
        idx = load_index()
        print(f"  {len(idx):,} keys in {INDEX_PATH}")
    elif args.cmd == "lookup":
        for n in args.names:
            path = lookup(n)
            print(f"  {n!r:40s} → {path}")


if __name__ == "__main__":
    main()
