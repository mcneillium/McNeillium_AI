#!/usr/bin/env python3
"""
McNeillium_AI — Agent 43: Retention Decoder

Pulls per-video second-by-second audience retention from the YouTube
Analytics API, identifies the three biggest drop-off moments, then
cross-references those moments against the script's section timeline
to label WHAT was being said when viewers left.

Writes a running list of "retention killers" to
knowledge_base/retention_killers.md that the Script Writer reads
before writing new scripts.

Requires:
  - yt-analytics.readonly scope on the OAuth token
  - The video must already be uploaded
  - The script JSON saved at knowledge_base/scripts/<title>.json
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
TOKEN_PATH = PROJECT_ROOT / ".youtube_token.json"
KILLERS = PROJECT_ROOT / "knowledge_base" / "retention_killers.md"
SCRIPT_DIR = PROJECT_ROOT / "knowledge_base" / "scripts"


def _services():
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
            scopes=["https://www.googleapis.com/auth/yt-analytics.readonly",
                    "https://www.googleapis.com/auth/youtube.readonly",
                    "https://www.googleapis.com/auth/youtube.upload"],
        )
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        return build("youtubeAnalytics", "v2", credentials=creds)
    except Exception:
        return None


def fetch_retention(ya, video_id):
    """Return list of (elapsed_video_ratio, audience_watch_ratio)."""
    end = datetime.date.today().isoformat()
    start = (datetime.date.today() - datetime.timedelta(days=90)).isoformat()
    resp = ya.reports().query(
        ids="channel==MINE",
        startDate=start, endDate=end,
        metrics="audienceWatchRatio",
        dimensions="elapsedVideoTimeRatio",
        filters=f"video=={video_id}",
    ).execute()
    return [(float(r[0]), float(r[1])) for r in resp.get("rows", [])]


def find_dropoffs(curve, top_n=3):
    """Return top-N largest drops in audienceWatchRatio between adjacent samples."""
    if len(curve) < 4:
        return []
    drops = []
    for i in range(1, len(curve)):
        prev_t, prev_w = curve[i - 1]
        t, w = curve[i]
        drop = prev_w - w
        if drop > 0:
            drops.append((drop, prev_t, t))
    drops.sort(key=lambda x: -x[0])
    return drops[:top_n]


def map_ratio_to_section(ratio, script, video_duration_s):
    """Return the section_id covering position `ratio` (0..1)."""
    sections = script.get("sections", [])
    if not sections:
        return None, None
    char_counts = [len(s.get("narration", "")) for s in sections]
    total_chars = sum(char_counts) or 1
    intro = 3.5
    outro = 3.5
    content = max(1.0, video_duration_s - intro - outro)
    t = intro
    target_t = ratio * video_duration_s
    for sec, c in zip(sections, char_counts):
        d = (c / total_chars) * content
        if target_t < t + d:
            # nearest sentence around target_t
            local_t = target_t - t
            sentences = re.split(r"(?<=[.!?])\s+",
                                 sec.get("narration", ""))
            if sentences:
                local_ratio = local_t / max(0.5, d)
                sentence_idx = min(
                    len(sentences) - 1,
                    int(local_ratio * len(sentences)),
                )
                return sec.get("id"), sentences[sentence_idx][:140]
            return sec.get("id"), None
        t += d
    return sections[-1].get("id"), None


def load_script_for_video(video_title):
    """Best-effort script lookup by slugified title."""
    slug = re.sub(r"[^a-z0-9]+", "_", (video_title or "").lower()).strip("_")
    for p in SCRIPT_DIR.glob("*.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not data:
            continue
        ds = re.sub(r"[^a-z0-9]+", "_",
                    data.get("title", "").lower()).strip("_")
        if slug and (slug in ds or ds in slug):
            return data
    return None


def run(video_id, video_title, video_duration_s):
    ya = _services()
    if not ya:
        print("⏭  Analytics service unavailable.")
        return False

    curve = fetch_retention(ya, video_id)
    if not curve:
        print(f"⚠️  No retention data for {video_id}")
        return False

    drops = find_dropoffs(curve, top_n=3)
    if not drops:
        print(f"⚠️  No notable drops in retention.")
        return True

    script = load_script_for_video(video_title)

    KILLERS.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    if KILLERS.exists():
        lines = KILLERS.read_text(encoding="utf-8").splitlines()
    lines.append("")
    lines.append(f"## {video_title} (`{video_id}`) — "
                 f"{datetime.date.today()}")
    for drop, start, end in drops:
        sid, sentence = (None, None)
        if script:
            sid, sentence = map_ratio_to_section(end, script,
                                                 video_duration_s)
        time_s = int(end * video_duration_s)
        lines.append(
            f"- **{drop*100:.1f}%** drop at {time_s}s "
            f"({end*100:.0f}% mark) — section `{sid}`"
        )
        if sentence:
            lines.append(f"    > {sentence}")
    KILLERS.write_text("\n".join(lines), encoding="utf-8")
    print(f"💾 Retention killers appended → {KILLERS}")
    return True


def main():
    p = argparse.ArgumentParser()
    p.add_argument("video_id")
    p.add_argument("--title", required=True)
    p.add_argument("--duration-s", type=float, required=True)
    args = p.parse_args()
    ok = run(args.video_id, args.title, args.duration_s)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
