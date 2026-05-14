#!/usr/bin/env python3
"""
McNeillium AI — Daily Scheduler (Phase 18)

Designed to be invoked once a day by Windows Task Scheduler at 06:00 GMT.
Workflow:
  1. Run the Trend Researcher (utils/trend_researcher.py).
  2. Inspect the top story's score.
       score >= 85 → mark as urgent; write urgent_picks.json
       score < 85  → fall back to today's pick from content_queue.md
  3. Drop a desktop notification file at output/queue/notify_<date>.md
     so the user knows when they open the laptop.
  4. (Optional) trigger batch_producer for the picked topic.

This module does NOT auto-upload. Approvals happen via the dashboard.

Windows Task Scheduler setup (one-time, manual):
    schtasks /create /tn "McNeillium Daily" /tr ^
      "C:/Python314/python.exe C:/Users/.../utils/daily_scheduler.py" ^
      /sc DAILY /st 06:00
"""

import argparse
import datetime
import io
import json
import os
import subprocess
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower().replace("-", "") != "utf8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8",
                                  errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
QUEUE_DIR = PROJECT_ROOT / "output" / "queue"
URGENT_PICKS = QUEUE_DIR / "urgent_picks.json"
KB = PROJECT_ROOT / "knowledge_base"
NEWS_QUEUE = KB / "news_queue.json"
CONTENT_QUEUE = KB / "content_queue.md"

URGENT_THRESHOLD = 85.0


def _today():
    return datetime.date.today().isoformat()


def run_trend_researcher():
    cmd = [PY, str(PROJECT_ROOT / "utils" / "trend_researcher.py")]
    print(f"⏰ Daily Scheduler — running Trend Researcher...")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"   ⚠️  trend researcher failed: {r.stderr[-300:]}")
        return None
    if not NEWS_QUEUE.exists():
        return None
    try:
        return json.loads(NEWS_QUEUE.read_text(encoding="utf-8"))
    except Exception:
        return None


def pick_today(queue):
    """Return the picked story dict + urgency flag."""
    if not queue:
        return None, False
    top = (queue.get("top") or [None])[0]
    if not top:
        return None, False
    score = float(top.get("score", 0))
    return top, score >= URGENT_THRESHOLD


def write_notification(pick, urgent):
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    today = _today()
    path = QUEUE_DIR / f"notify_{today}.md"
    if not pick:
        lines = [f"# Daily pick — {today}",
                 "",
                 "No story scored above the urgent threshold. Fall back to",
                 "knowledge_base/content_queue.md for the day's hand-picked",
                 "topic.", ""]
    else:
        verdict = "🚨 URGENT" if urgent else "📰 normal pick"
        lines = [f"# Daily pick — {today}  {verdict}",
                 "",
                 f"**Title**: {pick.get('title')}",
                 f"**Source**: {pick.get('source')}",
                 f"**Score**: {pick.get('score')}",
                 f"**URL**: {pick.get('url')}",
                 "",
                 "Breakdown:",
                 f"```",
                 json.dumps(pick.get("breakdown", {}), indent=2),
                 "```",
                 "",
                 "Next steps:",
                 "  python utils/cost_governor.py status",
                 "  python utils/news_asset_collector.py",
                 "  python video/generate_video.py",
                 ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"  💾 notification → {path}")


def run(urgent_only=False, dry_run=False):
    queue = run_trend_researcher()
    pick, urgent = pick_today(queue)
    if not pick:
        print("  ⚠️  no pick today — try content_queue.md")
        write_notification(None, False)
        return False
    if urgent_only and not urgent:
        print(f"  ⏭  pick scored {pick.get('score')}, below urgent threshold "
              f"({URGENT_THRESHOLD}). No video today.")
        write_notification(pick, False)
        return True

    print(f"  🎯 Pick: {pick.get('title')[:80]}  (score={pick.get('score')})")
    write_notification(pick, urgent)

    if urgent:
        QUEUE_DIR.mkdir(parents=True, exist_ok=True)
        URGENT_PICKS.write_text(json.dumps(pick, indent=2),
                                  encoding="utf-8")
    if dry_run:
        print("  🧪 dry-run — not invoking batch producer")
    else:
        # The user runs batch_producer manually after reviewing the pick.
        # The scheduler stops here so we never spend money unattended.
        print("  ℹ️  scheduler stops short of production. Run:")
        print("      python utils/batch_producer.py --topics ...")
    return True


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--urgent-only", action="store_true",
                   help="Only act when a story scores above the urgent threshold")
    p.add_argument("--dry-run", action="store_true",
                   help="Don't trigger any downstream action")
    args = p.parse_args()
    ok = run(urgent_only=args.urgent_only, dry_run=args.dry_run)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
