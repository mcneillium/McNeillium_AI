#!/usr/bin/env python3
"""
McNeillium AI — Cost Governor (Phase 18)

Hard limits enforced on top of utils/cost_tracker.py. If the day's
or month's spend exceeds the configured ceiling, the governor refuses
further API calls until reset.

Limits (defaults — override via knowledge_base/cost_limits.yaml):
  daily      $20
  monthly    $200
  per_video  $5   (warning, not hard-block — alerts if exceeded)

Usage from other agents:
  from utils.cost_governor import check_can_spend, mark_spent

  if not check_can_spend("elevenlabs", estimated_dollars=1.20,
                          title="Tonight's video"):
      sys.exit(2)   # governor blocked the call
  ...do the API call...
  mark_spent("elevenlabs", actual_dollars=1.18, title="Tonight's video")

When a hard limit trips, the governor writes
knowledge_base/costs/alert_<date>.md and returns False.

The Tracker (Phase 11) is the source of truth — the governor reads it
each call and decides.
"""

import argparse
import csv
import datetime
import io
import json
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower().replace("-", "") != "utf8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8",
                                  errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LIMITS_YAML = PROJECT_ROOT / "knowledge_base" / "cost_limits.yaml"
COSTS_DIR = PROJECT_ROOT / "knowledge_base" / "costs"
sys.path.insert(0, str(PROJECT_ROOT))
from utils import cost_tracker  # noqa: E402


DEFAULTS = {
    "daily_usd":     20.0,
    "monthly_usd":   200.0,
    "per_video_usd": 5.0,
}


def _load_limits():
    if not LIMITS_YAML.exists():
        return dict(DEFAULTS)
    try:
        import yaml
        data = yaml.safe_load(LIMITS_YAML.read_text(encoding="utf-8"))
        out = dict(DEFAULTS)
        for k in DEFAULTS:
            if k in (data or {}):
                out[k] = float(data[k])
        return out
    except Exception:
        return dict(DEFAULTS)


def _spent_today():
    """Read all cost rows from this month's CSV and sum today's."""
    today = datetime.date.today()
    p = COSTS_DIR / f"{today.year}-{today.month:02d}.csv"
    if not p.exists():
        return 0.0
    total = 0.0
    today_iso = today.isoformat()
    with open(p, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            ts = row.get("timestamp", "")[:10]
            if ts == today_iso:
                try:
                    total += float(row.get("cost_usd", "0"))
                except Exception:
                    pass
    return total


def _spent_this_month():
    today = datetime.date.today()
    p = COSTS_DIR / f"{today.year}-{today.month:02d}.csv"
    if not p.exists():
        return 0.0
    total = 0.0
    with open(p, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                total += float(row.get("cost_usd", "0"))
            except Exception:
                pass
    return total


def _spent_for_video(title):
    totals, _units = cost_tracker.summary(title=title)
    return sum(totals.values())


def _write_alert(message):
    COSTS_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.date.today().isoformat()
    p = COSTS_DIR / f"alert_{today}.md"
    line = f"- [{datetime.datetime.now().isoformat(timespec='seconds')}] {message}"
    with open(p, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def check_can_spend(service, estimated_dollars, title=None):
    """Return True if the spend is allowed, False if any hard limit
    would be tripped. Hard limits are daily + monthly."""
    limits = _load_limits()
    today_spent = _spent_today()
    month_spent = _spent_this_month()
    if today_spent + estimated_dollars > limits["daily_usd"]:
        msg = (f"DAILY LIMIT — {service} ${estimated_dollars:.2f} would "
               f"push today's spend from ${today_spent:.2f} over the "
               f"${limits['daily_usd']:.2f} cap.")
        print(f"⛔ {msg}")
        _write_alert(msg)
        return False
    if month_spent + estimated_dollars > limits["monthly_usd"]:
        msg = (f"MONTHLY LIMIT — {service} ${estimated_dollars:.2f} would "
               f"push this month's spend from ${month_spent:.2f} over the "
               f"${limits['monthly_usd']:.2f} cap.")
        print(f"⛔ {msg}")
        _write_alert(msg)
        return False
    if title:
        video_spent = _spent_for_video(title)
        if video_spent + estimated_dollars > limits["per_video_usd"]:
            msg = (f"PER-VIDEO WARN — '{title}' already at "
                   f"${video_spent:.2f}; adding ${estimated_dollars:.2f} "
                   f"crosses the ${limits['per_video_usd']:.2f} guideline.")
            print(f"⚠️  {msg}")
            _write_alert(msg)
            # Warning only — does not block
    return True


def report():
    limits = _load_limits()
    today = _spent_today()
    month = _spent_this_month()
    print(f"💰 Cost Governor — limits: "
          f"daily ${limits['daily_usd']:.2f} / "
          f"monthly ${limits['monthly_usd']:.2f} / "
          f"per-video ${limits['per_video_usd']:.2f}")
    print(f"   today:   ${today:.2f}")
    print(f"   month:   ${month:.2f}")
    print(f"   daily headroom:   ${limits['daily_usd'] - today:.2f}")
    print(f"   monthly headroom: ${limits['monthly_usd'] - month:.2f}")


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd")
    p_status = sub.add_parser("status")
    p_check = sub.add_parser("check")
    p_check.add_argument("--service", required=True)
    p_check.add_argument("--dollars", type=float, required=True)
    p_check.add_argument("--title", default=None)
    args = p.parse_args()
    if args.cmd == "check":
        ok = check_can_spend(args.service, args.dollars, args.title)
        sys.exit(0 if ok else 2)
    report()


if __name__ == "__main__":
    main()
