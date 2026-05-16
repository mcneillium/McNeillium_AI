#!/usr/bin/env python3
"""
McNeillium_AI — Phase 19 Step 3: Unified Stock Fetcher

Wraps Pixabay (default), Pixabay AI category, and Pexels Video API
behind a single `fetch_video(query)` call. Sources are queried in
parallel; the highest-scoring result wins.

Score (per candidate):
  + 30 if duration in [min_duration, 30s]
  + 25 if resolution >= 1920x1080
  + 15 if resolution >= 1280x720
  + 10 if not from Pixabay (diversity bonus over default source)
  + 5  if duration > min_duration + 4 (room for trim)

The CLIP_CACHE path matches the one used by the legacy
video.generate_video.fetch_stock_video, so existing cached files are
reused. New cache filenames namespace the source so the same query
across sources doesn't collide:
  <CLIP_CACHE>/<source>__<safe_query>.mp4
"""

import io
import json
import os
import random
import re
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

if sys.stdout.encoding and sys.stdout.encoding.lower().replace("-", "") != "utf8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8",
                                  errors="replace")


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CLIP_CACHE = PROJECT_ROOT / "output" / "_clip_cache"
USER_AGENT = "Mozilla/5.0 (McNeillium_AI Phase19 stock fetcher)"

DEFAULT_SOURCES = ("pexels", "pixabay", "pixabay_ai", "wikimedia",
                   "internet_archive")


def _safe(s, n=50):
    return re.sub(r"[^a-zA-Z0-9]", "_", s)[:n]


def _cache_path(source, query):
    CLIP_CACHE.mkdir(parents=True, exist_ok=True)
    return CLIP_CACHE / f"{source}__{_safe(query)}.mp4"


def _download(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        with open(dest, "wb") as f:
            f.write(resp.read())
    time.sleep(0.2)


def _fetch_pixabay(query, ai=False):
    """Pixabay video search. ai=True restricts to AI category."""
    api_key = os.getenv("PIXABAY_API_KEY", "")
    if not api_key:
        return []
    cat = "&category=ai" if ai else ""
    enc = urllib.parse.quote(query)
    url = (f"https://pixabay.com/api/videos/?key={api_key}&q={enc}"
           f"&video_type=film&min_width=1280&min_height=720&per_page=10"
           f"{cat}")
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            data = json.loads(resp.read().decode())
    except Exception:
        return []
    out = []
    src_name = "pixabay_ai" if ai else "pixabay"
    for hit in data.get("hits", [])[:10]:
        videos = hit.get("videos", {})
        # Prefer large; the "large" variant has the highest resolution
        for q in ("large", "medium", "small"):
            v = videos.get(q, {})
            if v.get("url"):
                out.append({
                    "source": src_name,
                    "url": v["url"],
                    "width": v.get("width", 0),
                    "height": v.get("height", 0),
                    "duration_s": float(hit.get("duration", 0) or 0),
                })
                break
    return out


def _fetch_pexels(query):
    api_key = os.getenv("PEXELS_API_KEY", "")
    if not api_key:
        return []
    enc = urllib.parse.quote(query)
    url = (f"https://api.pexels.com/videos/search?query={enc}"
           f"&per_page=10&orientation=landscape")
    try:
        req = urllib.request.Request(url, headers={"Authorization": api_key,
                                                   "User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
    except Exception:
        return []
    out = []
    for v in data.get("videos", [])[:10]:
        # Pick the best video_file: highest resolution at <= 1920w
        files = sorted(v.get("video_files", []),
                       key=lambda f: (f.get("width", 0), f.get("height", 0)),
                       reverse=True)
        # Filter to mp4, <= 1920w (downscale isn't needed)
        candidates = [f for f in files
                      if f.get("file_type") == "video/mp4"
                      and f.get("width", 0) <= 1920]
        if not candidates and files:
            candidates = [files[0]]
        if not candidates:
            continue
        best = candidates[0]
        out.append({
            "source": "pexels",
            "url": best.get("link"),
            "width": best.get("width", 0),
            "height": best.get("height", 0),
            "duration_s": float(v.get("duration", 0) or 0),
        })
    return out


def _fetch_wikimedia(query):
    """Wikimedia Commons video search. No API key required.

    Returns up to 5 candidates as {source, url, width, height,
    duration_s} dicts. Wikimedia tends to have lower-quality but
    legitimately public-domain footage — we score it lower than
    Pexels but higher than nothing."""
    enc = urllib.parse.quote(query)
    # mediasearch returns mixed results; we filter to files with
    # a video mime type.
    api_url = (f"https://commons.wikimedia.org/w/api.php?"
               f"action=query&format=json&list=search&srnamespace=6&"
               f"srsearch={enc}+filetype:video&srlimit=10")
    try:
        req = urllib.request.Request(api_url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
    except Exception:
        return []
    out = []
    titles = [r["title"] for r in data.get("query", {}).get("search", [])][:5]
    if not titles:
        return []
    # Bulk imageinfo query for the URLs and metadata
    titles_param = urllib.parse.quote("|".join(titles))
    info_url = (f"https://commons.wikimedia.org/w/api.php?"
                f"action=query&format=json&prop=imageinfo&"
                f"iiprop=url|size|mime|mediatype&"
                f"titles={titles_param}")
    try:
        req = urllib.request.Request(info_url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=15) as resp:
            info = json.loads(resp.read().decode())
    except Exception:
        return []
    pages = info.get("query", {}).get("pages", {})
    for page in pages.values():
        ii = (page.get("imageinfo") or [{}])[0]
        mime = ii.get("mime", "")
        if not mime.startswith("video/"):
            continue
        url = ii.get("url")
        if not url:
            continue
        out.append({
            "source": "wikimedia",
            "url": url,
            "width": ii.get("width", 0),
            "height": ii.get("height", 0),
            # duration not in imageinfo; treat as unknown (fits scorer)
            "duration_s": 10.0,
        })
    return out


def _fetch_internet_archive(query):
    """Internet Archive video search via their advancedsearch JSON API.

    Filters to mediatype=movies. Pulls thumbnail-quality is often
    grainy but the catalog is huge."""
    enc = urllib.parse.quote(f"{query} AND mediatype:movies")
    api = (f"https://archive.org/advancedsearch.php?"
           f"q={enc}&fl[]=identifier&fl[]=title&"
           f"sort[]=downloads+desc&rows=5&page=1&output=json")
    try:
        req = urllib.request.Request(api, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
    except Exception:
        return []
    docs = data.get("response", {}).get("docs", [])
    out = []
    for d in docs[:5]:
        ident = d.get("identifier")
        if not ident:
            continue
        # Look up the metadata to find an actual mp4 file
        try:
            meta_url = f"https://archive.org/metadata/{ident}"
            req = urllib.request.Request(meta_url,
                                         headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=15) as resp:
                meta = json.loads(resp.read().decode())
        except Exception:
            continue
        # Pick the first mp4 file
        mp4 = next((f for f in meta.get("files", [])
                    if f.get("format", "").lower() in
                    ("h.264", "mpeg4", "ipod", "mp4", "h.264 hd")
                    and f.get("name", "").lower().endswith(".mp4")), None)
        if not mp4:
            continue
        # Filenames in IA can contain spaces and special chars — encode.
        download_url = (f"https://archive.org/download/{ident}/"
                        f"{urllib.parse.quote(mp4['name'])}")
        out.append({
            "source": "internet_archive",
            "url": download_url,
            "width": int(mp4.get("width", 0) or 0),
            "height": int(mp4.get("height", 0) or 0),
            "duration_s": float(mp4.get("length", 0) or 0)
                          if str(mp4.get("length", "0")).replace(".", "").isdigit()
                          else 10.0,
        })
    return out


def _score(c, min_duration):
    s = 0
    d = c.get("duration_s", 0)
    if min_duration <= d <= 30:
        s += 30
    if c.get("width", 0) >= 1920:
        s += 25
    elif c.get("width", 0) >= 1280:
        s += 15
    if c.get("source") != "pixabay":
        s += 10
    if d >= min_duration + 4:
        s += 5
    return s


def fetch_video(query, min_duration=8, sources=DEFAULT_SOURCES,
                _verbose=True):
    """Search all sources in parallel, return path to best cached MP4."""
    # Cache check: if any source already has a cached file for this
    # query, reuse it without re-downloading.
    for src in sources:
        cp = _cache_path(src, query)
        if cp.exists() and cp.stat().st_size > 10000:
            return str(cp)

    # Parallel API calls
    fetchers = {
        "pixabay":         lambda: _fetch_pixabay(query, ai=False),
        "pixabay_ai":      lambda: _fetch_pixabay(query, ai=True),
        "pexels":          lambda: _fetch_pexels(query),
        "wikimedia":       lambda: _fetch_wikimedia(query),
        "internet_archive":lambda: _fetch_internet_archive(query),
    }
    candidates = []
    with ThreadPoolExecutor(max_workers=len(sources)) as ex:
        future_to_src = {ex.submit(fetchers[s]): s
                         for s in sources if s in fetchers}
        for fut in as_completed(future_to_src):
            try:
                candidates.extend(fut.result())
            except Exception:
                pass

    if not candidates:
        if _verbose:
            print(f"        ⚠️  no stock results for '{query}' "
                  f"across {sources}")
        return None

    # Pick the highest-scoring candidate, with light random tiebreak
    candidates.sort(key=lambda c: (_score(c, min_duration),
                                   random.random()),
                    reverse=True)
    best = candidates[0]

    cp = _cache_path(best["source"], query)
    try:
        _download(best["url"], cp)
        if _verbose:
            print(f"        📥 [{best['source']}] {best['width']}x"
                  f"{best['height']} {best['duration_s']:.0f}s "
                  f"score={_score(best, min_duration)} → {cp.name}")
        return str(cp)
    except Exception as e:
        if _verbose:
            print(f"        ⚠️  download failed {best['source']}: {e}")
        return None


def main():
    import argparse
    p = argparse.ArgumentParser(description="Phase 19 stock fetcher (multi-source)")
    p.add_argument("query")
    p.add_argument("--min-duration", type=int, default=8)
    p.add_argument("--sources", nargs="+", default=list(DEFAULT_SOURCES),
                   choices=["pixabay", "pixabay_ai", "pexels",
                            "wikimedia", "internet_archive"])
    args = p.parse_args()
    path = fetch_video(args.query, min_duration=args.min_duration,
                       sources=tuple(args.sources))
    if not path:
        sys.exit(2)
    print(path)


if __name__ == "__main__":
    main()
