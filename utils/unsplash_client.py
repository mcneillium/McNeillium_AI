#!/usr/bin/env python3
"""
McNeillium_AI — Phase 22.4b: Unsplash Photo Source

Atmospheric / "feeling" photos for environmental and contextual shots
where Pexels stock video would feel too literal. Real photos > stock
video for moody establishing shots.

Free tier: 5,000 requests/hour with UNSPLASH_ACCESS_KEY in .env.

Public API
──────────
  fetch_photo(query, *, orientation='landscape') -> Path | None
      Cached download of a representative Unsplash photo.

CLI:
  python utils/unsplash_client.py "courthouse exterior dusk"
"""

import argparse
import io
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower().replace("-", "") != "utf8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8",
                                  errors="replace")

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = PROJECT_ROOT / "output" / "_unsplash_cache"
USER_AGENT = "Mozilla/5.0 (McNeillium_AI Phase22 unsplash client)"


def fetch_photo(query, *, orientation="landscape"):
    """Return Path to a cached Unsplash photo or None."""
    key = os.getenv("UNSPLASH_ACCESS_KEY", "")
    if not key:
        return None
    if not query:
        return None
    safe = re.sub(r"[^a-z0-9]+", "_", query.lower()).strip("_")[:60]
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = CACHE_DIR / f"{safe}_{orientation}.jpg"
    if cache_path.exists() and cache_path.stat().st_size > 1000:
        return cache_path

    enc = urllib.parse.quote(query)
    api = (f"https://api.unsplash.com/search/photos?query={enc}"
           f"&per_page=3&orientation={orientation}")
    try:
        req = urllib.request.Request(api, headers={
            "Authorization": f"Client-ID {key}",
            "User-Agent": USER_AGENT,
        })
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode())
    except Exception:
        return None

    results = data.get("results", [])
    if not results:
        return None
    # Pick first result (Unsplash's relevance order is good)
    img_url = results[0].get("urls", {}).get("regular")
    if not img_url:
        return None
    try:
        req = urllib.request.Request(img_url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=20) as resp:
            cache_path.write_bytes(resp.read())
    except Exception:
        return None
    time.sleep(0.1)
    return cache_path


def main():
    p = argparse.ArgumentParser(description="Phase 22.4b Unsplash client")
    p.add_argument("query")
    p.add_argument("--orientation", default="landscape",
                   choices=["landscape", "portrait", "squarish"])
    args = p.parse_args()
    path = fetch_photo(args.query, orientation=args.orientation)
    print(path or "(miss)")


if __name__ == "__main__":
    main()
