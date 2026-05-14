#!/usr/bin/env python3
"""
McNeillium_AI — Agent 49: Content Scheduler

Maintains an upload calendar and schedules YouTube uploads at optimal
slots. Default cadence:

    Tuesday 16:00 GMT, Thursday 16:00 GMT, Saturday 14:00 GMT

Two modes:
  - Local calendar: writes knowledge_base/calendar.md with the next 4
    weeks of planned upload slots + topics from a queue file.
  - Scheduled publish: takes an already-uploaded `videoId` and changes
    its `status.publishAt` via the YouTube Data API.

Cross-platform stagger (recommended manual cadence, not enforced):
    YouTube → +1hr Shorts → +2hr Blog → +3hr Twitter
"""

import argparse
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
QUEUE_PATH = PROJECT_ROOT / "knowledge_base" / "upload_queue.json"
CALENDAR_PATH = PROJECT_ROOT / "knowledge_base" / "calendar.md"
TOKEN_PATH = PROJECT_ROOT / ".youtube_token.json"

# Tuesday=1, Thursday=3, Saturday=5 in Python (Monday=0)
SLOTS = [(1, 16, 0), (3, 16, 0), (5, 14, 0)]


def next_slots(weeks=4, start=None):
    out = []
    today = start or datetime.datetime.now().replace(
        minute=0, second=0, microsecond=0)
    for w in range(weeks):
        base = today + datetime.timedelta(weeks=w)
        # Anchor to Monday of that week
        monday = base - datetime.timedelta(days=base.weekday())
        for day, hh, mm in SLOTS:
            slot = monday.replace(hour=hh, minute=mm) + \
                   datetime.timedelta(days=day)
            if slot > today:
                out.append(slot)
    return out


def load_queue():
    if not QUEUE_PATH.exists():
        return []
    try:
        return json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []


def save_queue(items):
    QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    QUEUE_PATH.write_text(json.dumps(items, indent=2), encoding="utf-8")


def render_calendar(weeks=4):
    queue = load_queue()
    slots = next_slots(weeks=weeks)
    lines = [f"# Upload Calendar — next {weeks} weeks", ""]
    for i, slot in enumerate(slots):
        topic = queue[i]["topic"] if i < len(queue) else "(needs a topic)"
        lines.append(f"- **{slot.strftime('%a %d %b %H:%M')} GMT** — {topic}")
    if queue and len(queue) > len(slots):
        lines.append("")
        lines.append(f"## Queue overflow ({len(queue) - len(slots)} extra)")
        for q in queue[len(slots):]:
            lines.append(f"- {q['topic']}")
    CALENDAR_PATH.parent.mkdir(parents=True, exist_ok=True)
    CALENDAR_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"📅 Calendar → {CALENDAR_PATH}")


# ═══════════════════════════════════════════════════════════════
# Optional: actually set publishAt on a YouTube video
# ═══════════════════════════════════════════════════════════════

def _yt_service():
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError:
        return None
    if not TOKEN_PATH.exists():
        return None
    try:
        creds = Credentials.from_authorized_user_file(
            str(TOKEN_PATH),
            scopes=["https://www.googleapis.com/auth/youtube.force-ssl"],
        )
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        return build("youtube", "v3", credentials=creds)
    except Exception:
        return None


def schedule_publish(video_id, when_iso):
    """Update a video's status.publishAt + privacyStatus=private."""
    yt = _yt_service()
    if not yt:
        print("⏭  YouTube service unavailable — skipping API call")
        return False
    body = {
        "id": video_id,
        "status": {
            "privacyStatus": "private",
            "publishAt": when_iso,
            "selfDeclaredMadeForKids": False,
        },
    }
    try:
        yt.videos().update(part="status", body=body).execute()
        print(f"✅ Scheduled {video_id} → {when_iso}")
        return True
    except Exception as e:
        print(f"❌ Schedule failed: {e}")
        return False


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    p_cal = sub.add_parser("calendar")
    p_cal.add_argument("--weeks", type=int, default=4)

    p_add = sub.add_parser("add")
    p_add.add_argument("--topic", required=True)

    p_sched = sub.add_parser("schedule")
    p_sched.add_argument("video_id")
    p_sched.add_argument("--when", required=True,
                         help="ISO datetime, e.g. 2026-05-21T16:00:00Z")

    args = p.parse_args()

    if args.cmd == "calendar":
        render_calendar(weeks=args.weeks)
    elif args.cmd == "add":
        q = load_queue()
        q.append({"topic": args.topic,
                  "added": datetime.datetime.now().isoformat()})
        save_queue(q)
        print(f"➕ Added: {args.topic} (queue depth {len(q)})")
        render_calendar()
    elif args.cmd == "schedule":
        ok = schedule_publish(args.video_id, args.when)
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
