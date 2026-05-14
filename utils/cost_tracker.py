#!/usr/bin/env python3
"""
McNeillium_AI — Cost Tracker (Phase 11)

Logs every billable API call to knowledge_base/costs/YYYY-MM.csv so we
have an honest running total of what each video costs to produce. Other
agents call `record_eleven_chars()` / `record_fal_clip()` /
`record_assemblyai_seconds()` right after they hit the wire.

Pricing assumptions (approximate, update when plans change):
  ElevenLabs Creator       $22 / 100,000 chars ≈ $0.000220 / char
  fal-ai Kling v1.6 std    $0.30 / 5-second clip
  AssemblyAI Universal     $0.37 / hour audio ≈ $0.000103 / second

The CSV columns are:
  timestamp, video_title, service, units, cost_usd, cumulative_video_cost

A per-video totals roll-up is appended to the same file once the
caller invokes `finalise(title)`.
"""

import argparse
import csv
import datetime
import io
import os
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower().replace("-", "") != "utf8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8",
                                  errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
COST_DIR = PROJECT_ROOT / "knowledge_base" / "costs"

PRICE_PER_ELEVEN_CHAR = 22.0 / 100_000.0   # $0.000220
PRICE_PER_FAL_CLIP = 0.30                   # $0.30 / 5s clip
PRICE_PER_ASSEMBLY_SECOND = 0.37 / 3600.0   # $0.0001028


def _csv_path():
    today = datetime.date.today()
    COST_DIR.mkdir(parents=True, exist_ok=True)
    return COST_DIR / f"{today.year}-{today.month:02d}.csv"


def _append_row(row):
    path = _csv_path()
    new_file = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow([
                "timestamp", "video_title", "service",
                "units", "unit_label", "cost_usd",
            ])
        w.writerow(row)


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def record_eleven_chars(title, n_chars):
    cost = n_chars * PRICE_PER_ELEVEN_CHAR
    _append_row([_now(), title, "elevenlabs", n_chars, "chars", f"{cost:.4f}"])
    print(f"💰 ElevenLabs: {n_chars} chars  →  ${cost:.4f}")
    return cost


def record_fal_clip(title, clip_count=1, prompt=""):
    cost = clip_count * PRICE_PER_FAL_CLIP
    _append_row([_now(), title, "fal_kling", clip_count,
                 f"clips ({prompt[:60]})", f"{cost:.4f}"])
    print(f"💰 fal.ai Kling: {clip_count} clip(s)  →  ${cost:.4f}")
    return cost


def record_assemblyai_seconds(title, seconds):
    cost = seconds * PRICE_PER_ASSEMBLY_SECOND
    _append_row([_now(), title, "assemblyai", round(seconds, 1),
                 "seconds", f"{cost:.4f}"])
    print(f"💰 AssemblyAI: {seconds:.1f}s  →  ${cost:.4f}")
    return cost


def summary(title=None):
    """Return totals for the current month, optionally filtered to a title."""
    path = _csv_path()
    totals = {"elevenlabs": 0.0, "fal_kling": 0.0, "assemblyai": 0.0}
    units = {"elevenlabs": 0, "fal_kling": 0, "assemblyai": 0.0}
    if not path.exists():
        return totals, units
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if title and row["video_title"] != title:
                continue
            svc = row["service"]
            if svc in totals:
                try:
                    totals[svc] += float(row["cost_usd"])
                    units[svc] += float(row["units"])
                except Exception:
                    pass
    return totals, units


def report(title=None):
    totals, units = summary(title)
    grand = sum(totals.values())
    label = f"video '{title}'" if title else "month-to-date"
    print(f"📊 Cost report — {label}")
    print(f"   ElevenLabs   {int(units['elevenlabs']):>7} chars   "
          f"${totals['elevenlabs']:.4f}")
    print(f"   fal.ai Kling {int(units['fal_kling']):>7} clips   "
          f"${totals['fal_kling']:.4f}")
    print(f"   AssemblyAI   {units['assemblyai']:>7.1f} sec     "
          f"${totals['assemblyai']:.4f}")
    print(f"   --------------------------------------")
    print(f"   TOTAL                          ${grand:.4f}")
    return grand


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--title", default=None)
    args = p.parse_args()
    report(args.title)


if __name__ == "__main__":
    main()
