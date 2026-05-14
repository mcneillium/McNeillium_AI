#!/usr/bin/env python3
"""
McNeillium AI — Title & Thumbnail Performance Tracker (Phase 17)

Reads each video's CTR + view counts from the analytics snapshot and
classifies the title by pattern. Aggregates per-pattern CTR to learn
which title shapes win on this channel.

Title pattern taxonomy:
  X_JUST_DID_Y     "OpenAI Just Launched X"
  X_IS_COMING_FOR  "Anthropic Is Coming for OpenAI"
  QUESTION_TITLE   ends with ? or starts with Why/How/What
  NUMBER_TITLE     starts with a digit ("5 AI Tools…")
  WHY_X_WRONG      "Why [common belief] is wrong"
  DRAMA_VERB       contains lost / cooked / quietly / under oath
  PERSON_QUOTE     "Sam Altman Just Said …"

Outputs:
  knowledge_base/title_performance.csv
  knowledge_base/title_patterns.md

The SEO Optimizer can read title_patterns.md to favour high-CTR
patterns for new titles.
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
TITLE_CSV = PROJECT_ROOT / "knowledge_base" / "title_performance.csv"
TITLE_MD = PROJECT_ROOT / "knowledge_base" / "title_patterns.md"


TITLE_PATTERNS = {
    "X_JUST_DID_Y":   re.compile(r"\b(just|now|finally|recently)\s+\w+", re.I),
    "X_IS_COMING_FOR": re.compile(r"\b(coming for|comes for|takes on)\b", re.I),
    "QUESTION_TITLE": re.compile(r"\?$|^(why|how|what|when|who)\b", re.I),
    "NUMBER_TITLE":   re.compile(r"^\d+\b"),
    "WHY_X_WRONG":    re.compile(r"\bwhy .* (wrong|fails|broken|hype)\b", re.I),
    "DRAMA_VERB":     re.compile(r"\b(lost|cooked|quietly|under oath|leaked|fired|sued)\b", re.I),
    "PERSON_QUOTE":   re.compile(r"^([A-Z][a-z]+\s+){1,2}(just\s+)?(said|told|tweeted)", re.I),
    "VS_TITLE":       re.compile(r"\bvs\.?\b", re.I),
    "LIST_OF":        re.compile(r"\b(every|all|each)\s+\w+", re.I),
}


def classify_title(title):
    out = []
    for label, pat in TITLE_PATTERNS.items():
        if pat.search(title):
            out.append(label)
    return out or ["UNCLASSIFIED"]


def run():
    if not PERF_JSON.exists():
        TITLE_MD.parent.mkdir(parents=True, exist_ok=True)
        TITLE_MD.write_text(
            "# Title patterns\n\n_Needs analytics data — re-consent OAuth"
            " with yt-analytics.readonly scope, then run "
            "utils/analytics_monitor.py daily._\n", encoding="utf-8")
        print("⏭  No performance_data.json yet — scaffold written.")
        return True

    try:
        history = json.loads(PERF_JSON.read_text(encoding="utf-8"))
        if isinstance(history, dict):
            history = [history]
    except Exception:
        history = []

    if not history:
        return True

    latest = history[-1]
    rows = []
    stats = defaultdict(lambda: {"samples": 0, "views_total": 0,
                                   "avg_views": 0})

    TITLE_CSV.parent.mkdir(parents=True, exist_ok=True)
    new_csv = not TITLE_CSV.exists()
    with open(TITLE_CSV, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new_csv:
            w.writerow(["captured_at", "video_id", "title",
                         "patterns", "views", "avg_view_duration_s"])
        for v in latest.get("videos", []):
            title = v.get("title", "")
            video_id = v.get("video_id")
            patterns = classify_title(title)
            stats_dict = v.get("stats") or {}
            views = int(stats_dict.get("views", 0)) if stats_dict else 0
            avd = float(stats_dict.get("averageViewDuration", 0)) \
                if stats_dict else 0
            w.writerow([latest.get("captured_at"), video_id, title,
                         "|".join(patterns), views, avd])
            for p in patterns:
                stats[p]["samples"] += 1
                stats[p]["views_total"] += views
            rows.append({"title": title, "patterns": patterns,
                         "views": views})

    for p, s in stats.items():
        s["avg_views"] = (s["views_total"] / s["samples"]) \
            if s["samples"] else 0

    lines = ["# Title performance patterns", "",
             "Average views per pattern based on the latest analytics",
             "snapshot. SEO Optimizer biases toward higher-performing",
             "patterns for new titles.", ""]
    if stats:
        lines.append("| pattern | samples | total views | avg views |")
        lines.append("|---|---:|---:|---:|")
        for p, s in sorted(stats.items(), key=lambda kv: -kv[1]["avg_views"]):
            lines.append(
                f"| {p} | {s['samples']} | {s['views_total']} | "
                f"{s['avg_views']:.0f} |"
            )
    else:
        lines.append("_No videos in snapshot._")
    TITLE_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"✅ Title tracker — {len(rows)} videos, {len(stats)} patterns "
          f"→ {TITLE_MD}")
    return True


def main():
    argparse.ArgumentParser().parse_args()
    sys.exit(0 if run() else 1)


if __name__ == "__main__":
    main()
