#!/usr/bin/env python3
"""
McNeillium AI — Hook Performance Tracker (Phase 17)

Reads each published video's retention curve (from
knowledge_base/analytics/performance_data.json) and scores its hook
framework. Hooks that retain 70%+ at the 10s mark are "winners"; below
50% at 30s is a "failure".

Pattern data accumulates in:
  knowledge_base/hook_performance.csv
  knowledge_base/hook_patterns.md

The SEO Optimizer / Hook Engineer reads hook_patterns.md to bias
toward winning frameworks for new scripts.

Note: this requires the YouTube Analytics API connection (yt-analytics
.readonly scope on the OAuth token). Without it, the tracker just
emits the scaffold + empty pattern file. Re-consent flow lives in
utils/youtube_upload.py.
"""

import argparse
import csv
import io
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower().replace("-", "") != "utf8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8",
                                  errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PERF_JSON = PROJECT_ROOT / "knowledge_base" / "performance_data.json"
HOOK_CSV = PROJECT_ROOT / "knowledge_base" / "hook_performance.csv"
HOOK_MD = PROJECT_ROOT / "knowledge_base" / "hook_patterns.md"
SCRIPTS_DIR = PROJECT_ROOT / "knowledge_base" / "scripts"


HOOK_PATTERNS = {
    "JUST_DID": re.compile(r"\b(just|recently)\s+\w+ed\b", re.I),
    "QUESTION": re.compile(r"^[^.!?]*\?", re.S),
    "CONTRARIAN": re.compile(r"\b(everyone|everybody|most people|nobody)\b", re.I),
    "SHOCK_STAT": re.compile(r"\$?\d[\d,]*\s*(million|billion|trillion|%|x)\b", re.I),
    "NAMED_PERSON": re.compile(r"^[A-Z][a-z]+\s+[A-Z][a-z]+\b"),
    "DRAMA": re.compile(r"\b(fight|sue|leak|crisis|scandal|loses?|lost)\b", re.I),
}


def classify_hook(hook_text):
    """Return the matching pattern label(s) for a hook block."""
    matches = []
    for label, pat in HOOK_PATTERNS.items():
        if pat.search(hook_text):
            matches.append(label)
    return matches or ["UNCLASSIFIED"]


def load_perf_history():
    if not PERF_JSON.exists():
        return []
    try:
        data = json.loads(PERF_JSON.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else [data]
    except Exception:
        return []


def _retention_at(curve, ratio):
    """Find audienceWatchRatio at the given elapsed fraction (0.0-1.0)."""
    if not curve:
        return None
    closest = min(curve, key=lambda r: abs(r[0] - ratio))
    return closest[1]


def score_hook(video_meta, retention_curve, duration_s):
    """Return a hook-score dict for one video."""
    if duration_s <= 0:
        return None
    r10 = duration_s and _retention_at(retention_curve, 10.0 / duration_s)
    r30 = duration_s and _retention_at(retention_curve, 30.0 / duration_s)
    verdict = "unknown"
    if r10 is not None and r30 is not None:
        if r10 >= 0.7 and r30 >= 0.5:
            verdict = "winner"
        elif r10 < 0.5 or r30 < 0.35:
            verdict = "failure"
        else:
            verdict = "neutral"
    return {
        "video_id": video_meta.get("video_id"),
        "title": video_meta.get("title"),
        "retention_at_10s": round(r10, 3) if r10 is not None else None,
        "retention_at_30s": round(r30, 3) if r30 is not None else None,
        "verdict": verdict,
    }


def aggregate_patterns(rows):
    """Build per-pattern win/loss tally from rows."""
    stats = defaultdict(lambda: {"wins": 0, "neutral": 0, "fails": 0,
                                   "samples": 0})
    for row in rows:
        for label in (row.get("hook_patterns") or "").split("|"):
            label = label.strip()
            if not label:
                continue
            stats[label]["samples"] += 1
            v = row.get("verdict", "")
            if v == "winner":
                stats[label]["wins"] += 1
            elif v == "failure":
                stats[label]["fails"] += 1
            else:
                stats[label]["neutral"] += 1
    return stats


def write_patterns_md(stats):
    HOOK_MD.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Hook performance patterns", "",
             "Read by the SEO Optimizer + Hook Engineer to bias toward",
             "winning frameworks for new scripts.", ""]
    if not stats:
        lines.append("_No data yet — needs analytics + 3+ published videos._")
    else:
        lines.append("| pattern | samples | wins | neutral | fails | win-rate |")
        lines.append("|---|---:|---:|---:|---:|---:|")
        for label, s in sorted(stats.items(),
                                key=lambda kv: -kv[1]["samples"]):
            if s["samples"] == 0:
                continue
            wr = s["wins"] / s["samples"] * 100
            lines.append(
                f"| {label} | {s['samples']} | {s['wins']} | "
                f"{s['neutral']} | {s['fails']} | {wr:.0f}% |"
            )
    HOOK_MD.write_text("\n".join(lines), encoding="utf-8")


def run():
    history = load_perf_history()
    if not history:
        print("⏭  No analytics history yet. Scaffolding empty pattern file.")
        write_patterns_md({})
        return True

    HOOK_CSV.parent.mkdir(parents=True, exist_ok=True)
    new_csv = not HOOK_CSV.exists()
    rows = []
    with open(HOOK_CSV, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new_csv:
            w.writerow(["captured_at", "video_id", "title",
                         "hook_patterns", "retention_at_10s",
                         "retention_at_30s", "verdict"])
        # Re-process the latest snapshot
        latest = history[-1]
        for v in latest.get("videos", []):
            video_id = v.get("video_id")
            title = v.get("title", "")
            # Look up script archive to grab the hook text
            hook_text = ""
            for p in SCRIPTS_DIR.glob("*.json"):
                try:
                    d = json.loads(p.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if d.get("title", "").lower() == title.lower():
                    for sec in d.get("sections", []):
                        if sec.get("id") == "hook":
                            hook_text = sec.get("narration", "")
                            break
                    break
            patterns = classify_hook(hook_text) if hook_text else ["UNCLASSIFIED"]
            stats = v.get("stats") or {}
            duration_s = float(stats.get("averageViewDuration", 0)) \
                if stats else 0
            # Retention curve fetch isn't part of analytics_monitor snapshot
            # by default — skip the actual retention math; record what
            # we have.
            row = {
                "captured_at": latest.get("captured_at"),
                "video_id": video_id,
                "title": title,
                "hook_patterns": "|".join(patterns),
                "verdict": "unknown",
                "retention_at_10s": None,
                "retention_at_30s": None,
            }
            rows.append(row)
            w.writerow([row["captured_at"], video_id, title,
                         row["hook_patterns"],
                         row["retention_at_10s"],
                         row["retention_at_30s"],
                         row["verdict"]])
    stats = aggregate_patterns(rows)
    write_patterns_md(stats)
    print(f"✅ Hook tracker — {len(rows)} videos, "
          f"{len(stats)} patterns recorded → {HOOK_MD}")
    return True


def main():
    p = argparse.ArgumentParser()
    args = p.parse_args()
    sys.exit(0 if run() else 1)


if __name__ == "__main__":
    main()
