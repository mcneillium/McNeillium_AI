#!/usr/bin/env python3
"""
McNeillium_AI — Kling via fal.ai (Phase 11 hero shots)

Generates 5-second cinematic video clips from text prompts via fal.ai's
hosted Kling v1.6 standard endpoint. Used for "hero" beats only —
1-2 per section in explainer mode, 1 in reaction mode — where stock
footage genuinely can't deliver the shot.

Endpoint: fal-ai/kling-video/v1.6/standard
Output:   1280x720, 5 seconds, mp4
Cache:    output/_kling_cache/<sha256(prompt)>.mp4

Each generation costs ~$0.30 (logged via cost_tracker). The cache means
prompt re-use is free — important if the script is iterated.

The video generator picks this up automatically: any shot list beat
with type="hero" and a "prompt" field gets routed through fetch_hero().
"""

import argparse
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower().replace("-", "") != "utf8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8",
                                  errors="replace")

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from utils import cost_tracker  # noqa: E402

CACHE_DIR = PROJECT_ROOT / "output" / "_kling_cache"
DEFAULT_ENDPOINT = "fal-ai/kling-video/v1.6/standard/text-to-video"
DEFAULT_DURATION = 5

API_KEY = os.getenv("FAL_API_KEY", "")


# ─── Cache key ───────────────────────────────────────────────────

def _prompt_hash(prompt, extras=""):
    return hashlib.sha256(
        (prompt.strip().lower() + "|" + extras).encode("utf-8")
    ).hexdigest()[:16]


def _cache_path(prompt, extras=""):
    return CACHE_DIR / f"{_prompt_hash(prompt, extras)}.mp4"


# ─── fal.ai client wrapper ──────────────────────────────────────

def _ensure_client():
    if not API_KEY:
        return None
    # fal-client picks up FAL_KEY from env, but Phase 11 spec uses
    # FAL_API_KEY — translate it.
    os.environ.setdefault("FAL_KEY", API_KEY)
    try:
        import fal_client
        return fal_client
    except Exception as e:
        print(f"⚠️  fal_client import failed: {e}")
        return None


def _download(url, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        target.write_bytes(r.read())
    return target.exists() and target.stat().st_size > 1000


def fetch_hero(prompt, title="", duration=DEFAULT_DURATION,
               aspect_ratio="16:9"):
    """Generate or fetch a cached Kling clip for `prompt`.

    Returns the local mp4 path, or None on failure.
    """
    cache = _cache_path(prompt, f"{duration}s|{aspect_ratio}")
    if cache.exists() and cache.stat().st_size > 1000:
        print(f"    💾 Kling cache hit: {cache.name}")
        return str(cache)

    client = _ensure_client()
    if client is None:
        print(f"    ⚠️  fal.ai unavailable — skipping hero clip")
        return None

    print(f"    🎬 Kling generating ({duration}s, {aspect_ratio}): "
          f"\"{prompt[:80]}…\"")
    t0 = time.time()
    try:
        result = client.subscribe(
            DEFAULT_ENDPOINT,
            arguments={
                "prompt": prompt,
                "duration": str(duration),
                "aspect_ratio": aspect_ratio,
            },
            with_logs=False,
        )
    except Exception as e:
        print(f"    ❌ Kling call failed: {e}")
        return None
    elapsed = time.time() - t0

    video_url = None
    if isinstance(result, dict):
        video = result.get("video") or {}
        video_url = video.get("url") if isinstance(video, dict) else video
    if not video_url:
        print(f"    ⚠️  No video URL in fal result: {str(result)[:200]}")
        return None

    if not _download(video_url, cache):
        return None
    print(f"    ✅ Kling done in {elapsed:.0f}s → {cache.name}")
    cost_tracker.record_fal_clip(title, clip_count=1, prompt=prompt)
    return str(cache)


# ─── Batch helper for shot lists ─────────────────────────────────

def pre_generate_for_shotlist(shot_list_path, title="", aspect_ratio="16:9"):
    """Walk the shot list and pre-fetch every hero beat. Idempotent."""
    if not Path(shot_list_path).exists():
        print(f"❌ Shot list missing: {shot_list_path}")
        return False
    with open(shot_list_path, encoding="utf-8") as f:
        shot_list = json.load(f)

    title = title or shot_list.get("video_title", "(untitled)")
    total = 0
    fetched = 0
    for section in shot_list.get("sections", []):
        for shot in section.get("shots", []):
            if (shot.get("type") or shot.get("shot_type")) != "hero":
                continue
            prompt = shot.get("prompt") or shot.get("query")
            if not prompt:
                continue
            total += 1
            path = fetch_hero(prompt, title=title, aspect_ratio=aspect_ratio)
            if path:
                shot["path"] = path
                fetched += 1
    with open(shot_list_path, "w", encoding="utf-8") as f:
        json.dump(shot_list, f, indent=2)
    print(f"🎞  Hero beats: fetched {fetched} of {total}")
    return fetched > 0 or total == 0


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    p_one = sub.add_parser("one", help="Generate a single clip")
    p_one.add_argument("prompt")
    p_one.add_argument("--title", default="")
    p_one.add_argument("--duration", type=int, default=DEFAULT_DURATION)
    p_one.add_argument("--aspect", default="16:9")

    p_batch = sub.add_parser("batch", help="Pre-fetch all hero beats in shot list")
    p_batch.add_argument(
        "--shot-list",
        default=str(PROJECT_ROOT / "output" / "shot_list.json"),
    )
    p_batch.add_argument("--title", default="")
    p_batch.add_argument("--aspect", default="16:9")

    args = p.parse_args()
    if args.cmd == "one":
        path = fetch_hero(args.prompt, title=args.title,
                          duration=args.duration, aspect_ratio=args.aspect)
        sys.exit(0 if path else 1)
    elif args.cmd == "batch":
        ok = pre_generate_for_shotlist(args.shot_list, title=args.title,
                                       aspect_ratio=args.aspect)
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
