#!/usr/bin/env python3
"""
McNeillium_AI — Weekly Performance Report

Aggregates the last 7 days of analytics snapshots, retention killers,
and audience insights into a single markdown report at
knowledge_base/reports/YYYY-WW.md.

Includes:
  - Top performing video by views
  - Worst-retention sections this week
  - Most-frequent audience questions
  - Suggested next topics (derived from question samples)

No API calls — reads only local JSON/MD that earlier agents wrote.
"""

import argparse
import datetime
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
PERF_PATH = PROJECT_ROOT / "knowledge_base" / "performance_data.json"
KILLERS = PROJECT_ROOT / "knowledge_base" / "retention_killers.md"
INSIGHTS = PROJECT_ROOT / "knowledge_base" / "audience_insights.md"
REPORT_DIR = PROJECT_ROOT / "knowledge_base" / "reports"


def _load_perf_history():
    if not PERF_PATH.exists():
        return []
    try:
        data = json.loads(PERF_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else [data]
    except Exception:
        return []


def _aggregate_top_videos(history, days=7):
    """Find the top-viewing video over the last `days` snapshots."""
    if not history:
        return None
    recent = history[-days:]
    # Pick the latest snapshot's videos
    latest = recent[-1]
    videos = latest.get("videos", [])
    if not videos:
        return None
    return max(
        videos,
        key=lambda v: (v.get("stats") or {}).get("views", 0),
        default=None,
    )


def _recent_killers(days=7):
    if not KILLERS.exists():
        return []
    text = KILLERS.read_text(encoding="utf-8")
    today = datetime.date.today()
    cutoff = today - datetime.timedelta(days=days)
    sections = re.split(r"^## ", text, flags=re.M)[1:]
    out = []
    for s in sections:
        # First line is header containing date
        m = re.search(r"(\d{4}-\d{2}-\d{2})", s.splitlines()[0])
        if not m:
            continue
        try:
            d = datetime.date.fromisoformat(m.group(1))
        except Exception:
            continue
        if d >= cutoff:
            out.append("## " + s.strip())
    return out


def _question_samples(days=14):
    """Pull recent ?-questions from audience insights."""
    if not INSIGHTS.exists():
        return []
    text = INSIGHTS.read_text(encoding="utf-8")
    return re.findall(r"> \*\*question\*\* — _([^_]+)_", text)[-12:]


def build_report(week_key):
    history = _load_perf_history()
    top = _aggregate_top_videos(history, days=7)
    killers = _recent_killers(days=7)
    questions = _question_samples(days=14)

    lines = [f"# Weekly Report — {week_key}", ""]
    lines.append("## Performance")
    if top:
        stats = top.get("stats") or {}
        lines.append(
            f"- 🏆 **{top.get('title', '?')}** — "
            f"{stats.get('views', 0)} views, "
            f"avg view duration {stats.get('averageViewDuration', '?')}s"
        )
        for t in (top.get("top_traffic") or [])[:3]:
            lines.append(f"  - traffic via `{t['source']}`: {t['views']}")
    else:
        lines.append("- No analytics snapshots available yet.")

    lines.append("")
    lines.append("## Retention killers (last 7 days)")
    if killers:
        for k in killers:
            lines.append(k)
            lines.append("")
    else:
        lines.append("- None recorded.")

    lines.append("")
    lines.append("## Audience questions → topic seeds")
    if questions:
        for q in questions:
            lines.append(f"- {q.strip()}")
    else:
        lines.append("- No questions captured this period.")

    lines.append("")
    lines.append("## Recommended next topics")
    # Simple seeding from question patterns
    if questions:
        for q in questions[:5]:
            slug = re.sub(r"\s+", " ", q).strip()
            lines.append(f"- *“{slug}”* — turn this into a video")
    else:
        lines.append("- (No data — keep collecting analytics.)")

    return "\n".join(lines)


def run():
    today = datetime.date.today()
    year, week, _ = today.isocalendar()
    key = f"{year}-W{week:02d}"
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORT_DIR / f"{key}.md"
    text = build_report(key)
    path.write_text(text, encoding="utf-8")
    print(f"📊 Weekly report → {path}")
    return True


def main():
    p = argparse.ArgumentParser()
    args = p.parse_args()
    ok = run()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
