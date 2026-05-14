#!/usr/bin/env python3
"""
McNeillium_AI — Agent 48: Resource Monitor

Pre-flight + housekeeping for the pipeline. Run at the start of each
batch (or as cron, or as a CLI sanity check). Five checks:

  1. Disk free space (need 5GB by default)
  2. Pixabay API daily quota approximation (tracked locally)
  3. YouTube upload quota approximation (1 upload ≈ 1600 units of 10000)
  4. Temp file age — anything older than `--max-age-days` removed
  5. Clip cache size — capped at `--max-cache-mb`

Outputs:
  - logs/resource_report.md
  - non-zero exit if any blocking check fails
"""

import argparse
import datetime
import io
import json
import shutil
import sys
import time
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower().replace("-", "") != "utf8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8",
                                  errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = PROJECT_ROOT / "logs"
QUOTA_FILE = LOG_DIR / "quota_usage.json"

CLIP_CACHE = PROJECT_ROOT / "output" / "_clip_cache"
AI_CACHE = PROJECT_ROOT / "output" / "_ai_images"
TEMP_DIR = PROJECT_ROOT / "output" / "_temp_v4"

MIN_DISK_GB = 5
MAX_CACHE_MB = 4096
MAX_TEMP_AGE_DAYS = 7

# Approximate quotas
PIXABAY_DAILY_LIMIT = 5000     # generous; real limit varies by plan
YOUTUBE_UPLOAD_DAILY = 6        # 1 upload ≈ 1600 of 10000 unit daily quota


def disk_free_gb(path):
    usage = shutil.disk_usage(path)
    return usage.free / (1024 ** 3)


def cache_size_mb(directory):
    if not directory.exists():
        return 0
    return sum(f.stat().st_size for f in directory.rglob("*") if f.is_file()) / (1024 * 1024)


def _load_quota():
    if not QUOTA_FILE.exists():
        return {}
    try:
        return json.loads(QUOTA_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_quota(data):
    QUOTA_FILE.parent.mkdir(parents=True, exist_ok=True)
    QUOTA_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def record_usage(service, units=1):
    today = datetime.date.today().isoformat()
    data = _load_quota()
    bucket = data.setdefault(today, {})
    bucket[service] = bucket.get(service, 0) + units
    _save_quota(data)


def current_usage(service):
    today = datetime.date.today().isoformat()
    return _load_quota().get(today, {}).get(service, 0)


def clean_temp(max_age_days=MAX_TEMP_AGE_DAYS):
    """Delete files in temp dirs older than max_age_days. Return bytes freed."""
    cutoff = time.time() - max_age_days * 86400
    freed = 0
    for d in (TEMP_DIR,):
        if not d.exists():
            continue
        for f in d.rglob("*"):
            if f.is_file() and f.stat().st_mtime < cutoff:
                try:
                    freed += f.stat().st_size
                    f.unlink()
                except Exception:
                    pass
    return freed


def trim_cache(cache_dir, max_mb=MAX_CACHE_MB):
    """LRU-prune the cache to stay under max_mb. Return bytes freed."""
    if not cache_dir.exists():
        return 0
    files = [(f.stat().st_mtime, f.stat().st_size, f)
             for f in cache_dir.rglob("*") if f.is_file()]
    total = sum(s for _, s, _ in files) / (1024 * 1024)
    if total <= max_mb:
        return 0
    files.sort()
    freed = 0
    for _, sz, f in files:
        try:
            f.unlink()
            freed += sz
            total -= sz / (1024 * 1024)
            if total <= max_mb:
                break
        except Exception:
            pass
    return freed


def run(min_disk_gb=MIN_DISK_GB, max_cache_mb=MAX_CACHE_MB,
        max_age_days=MAX_TEMP_AGE_DAYS):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    report_path = LOG_DIR / "resource_report.md"

    free_gb = disk_free_gb(PROJECT_ROOT)
    clip_mb = cache_size_mb(CLIP_CACHE)
    ai_mb = cache_size_mb(AI_CACHE)
    pix_used = current_usage("pixabay")
    yt_used = current_usage("youtube_upload")

    blocking = []
    if free_gb < min_disk_gb:
        blocking.append(
            f"Disk free {free_gb:.1f}GB below threshold {min_disk_gb}GB",
        )

    print(f"💾 Resource Monitor")
    print(f"   disk free       : {free_gb:.1f}GB "
          f"({'OK' if free_gb >= min_disk_gb else 'LOW'})")
    print(f"   clip cache      : {clip_mb:.1f}MB")
    print(f"   ai image cache  : {ai_mb:.1f}MB")
    print(f"   pixabay today   : {pix_used} / ~{PIXABAY_DAILY_LIMIT}")
    print(f"   yt uploads today: {yt_used} / {YOUTUBE_UPLOAD_DAILY}")

    freed_temp = clean_temp(max_age_days)
    freed_cache = trim_cache(CLIP_CACHE, max_cache_mb)
    if freed_temp or freed_cache:
        print(f"   🧹 freed {freed_temp / 1e6:.1f}MB temp + "
              f"{freed_cache / 1e6:.1f}MB cache")

    if pix_used > PIXABAY_DAILY_LIMIT * 0.8:
        print("   ⚠️  Pixabay quota approaching limit — throttling recommended")
    if yt_used >= YOUTUBE_UPLOAD_DAILY:
        blocking.append("YouTube daily upload quota exhausted")

    lines = [
        f"# Resource Report — {datetime.datetime.now().isoformat(timespec='seconds')}",
        "",
        f"- Disk free: **{free_gb:.1f}GB**",
        f"- Clip cache: {clip_mb:.1f}MB",
        f"- AI image cache: {ai_mb:.1f}MB",
        f"- Pixabay today: {pix_used}",
        f"- YouTube uploads today: {yt_used}",
        f"- Cleanup freed: {freed_temp / 1e6:.1f}MB temp, "
        f"{freed_cache / 1e6:.1f}MB cache",
    ]
    if blocking:
        lines.append("")
        lines.append("## Blocking issues")
        for b in blocking:
            lines.append(f"- ⛔ {b}")
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"📝 {report_path}")

    return 0 if not blocking else 2


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--min-disk-gb", type=int, default=MIN_DISK_GB)
    p.add_argument("--max-cache-mb", type=int, default=MAX_CACHE_MB)
    p.add_argument("--max-age-days", type=int, default=MAX_TEMP_AGE_DAYS)
    args = p.parse_args()
    sys.exit(run(min_disk_gb=args.min_disk_gb,
                 max_cache_mb=args.max_cache_mb,
                 max_age_days=args.max_age_days))


if __name__ == "__main__":
    main()
