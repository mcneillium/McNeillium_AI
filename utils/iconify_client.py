#!/usr/bin/env python3
"""
McNeillium_AI — Phase 22.4: Iconify API Client

Iconify aggregates 200,000+ icons across 150+ icon sets behind one
free public API. No key required.

URL pattern:
  https://api.iconify.design/{prefix}/{name}.svg

Useful sets for AI news commentary:
  mdi          — Material Design Icons (7K)
  tabler       — Tabler Icons (5K)
  heroicons    — Heroicons (450)
  phosphor     — Phosphor Icons (7K)
  fluent       — Microsoft Fluent (5K)
  carbon       — IBM Carbon (2.5K)
  material-symbols — Google Material Symbols (3K)
  logos        — SVG brand logos (1.8K)

Public API
──────────
  fetch(prefix, name) -> Path | None     # cached SVG path on disk
  fetch_concept(query) -> Path | None    # heuristic search across sets

CLI:
  python utils/iconify_client.py fetch mdi scale-balance
  python utils/iconify_client.py concept "scales of justice"
"""

import argparse
import io
import re
import sys
import time
import urllib.request
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower().replace("-", "") != "utf8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8",
                                  errors="replace")


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = PROJECT_ROOT / "assets" / "illustrations" / "iconify"
USER_AGENT = "Mozilla/5.0 (McNeillium_AI Phase22 iconify client)"

# Sets to search when user gives a free-form concept query. Order
# matters — we try each in turn and keep the first hit.
CONCEPT_SETS = [
    "mdi", "tabler", "phosphor", "heroicons", "fluent",
    "carbon", "material-symbols",
]


def fetch(prefix, name):
    """Return Path to cached SVG, downloading if needed. None on miss."""
    if not prefix or not name:
        return None
    safe = re.sub(r"[^a-z0-9-]", "", name.lower())
    if not safe:
        return None
    set_dir = CACHE_DIR / prefix
    set_dir.mkdir(parents=True, exist_ok=True)
    cache_path = set_dir / f"{safe}.svg"
    if cache_path.exists() and cache_path.stat().st_size > 50:
        return cache_path

    url = f"https://api.iconify.design/{prefix}/{safe}.svg"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read()
    except Exception:
        return None

    # Iconify returns a 404 page that's still 200 OK in some cases —
    # check the body really starts with <svg
    if not body.lstrip().startswith(b"<svg"):
        return None
    cache_path.write_bytes(body)
    time.sleep(0.05)  # be polite
    return cache_path


def fetch_concept(query):
    """Try the query as an icon name across CONCEPT_SETS. Returns first
    hit, or None. Slugifies spaces to dashes."""
    if not query:
        return None
    norm = re.sub(r"[^a-z0-9 -]", "", query.lower()).strip()
    candidates = [norm.replace(" ", "-")]
    # Common alt: drop articles + plurals
    parts = [w for w in norm.split() if w not in ("the", "a", "an", "of")]
    if parts:
        candidates.append("-".join(parts))
        candidates.append(parts[0])
    for prefix in CONCEPT_SETS:
        for cand in candidates:
            p = fetch(prefix, cand)
            if p:
                return p
    return None


def main():
    p = argparse.ArgumentParser(description="Phase 22.4 Iconify client")
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("prefix")
    f.add_argument("name")
    c = sub.add_parser("concept")
    c.add_argument("query")
    args = p.parse_args()
    if args.cmd == "fetch":
        path = fetch(args.prefix, args.name)
    else:
        path = fetch_concept(args.query)
    print(path or "(miss)")


if __name__ == "__main__":
    main()
