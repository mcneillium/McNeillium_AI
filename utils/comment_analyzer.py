#!/usr/bin/env python3
"""
McNeillium_AI — Agent 45: Comment Sentiment Analyzer

Fetches comments on recent videos via the YouTube Data API and
categorises each into:
  - question     (→ future video idea)
  - confusion    (→ script clarity issue)
  - praise       (→ what to reinforce)
  - criticism    (→ what to fix)
  - other

Uses simple regex heuristics — no LLM call, no external sentiment model.
Per-video tallies + extracted sample comments are appended to
knowledge_base/audience_insights.md.
"""

import argparse
import collections
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
INSIGHTS = PROJECT_ROOT / "knowledge_base" / "audience_insights.md"


QUESTION_RE = re.compile(r"\?$|^(what|how|why|when|where|who|which|can|does|is|are)\b", re.I)
CONFUSION_RE = re.compile(r"\b(confused|i don'?t (get|understand)|wait what|what does that mean|too fast|lost me)\b", re.I)
PRAISE_RE = re.compile(r"\b(amazing|excellent|love|fantastic|brilliant|underrated|nailed it|great video|so good|best)\b", re.I)
CRITICISM_RE = re.compile(r"\b(boring|wrong|terrible|misleading|clickbait|dislike|hate|disagree|inaccurate)\b", re.I)


def categorize(text):
    text = (text or "").strip()
    if not text:
        return "other"
    if CONFUSION_RE.search(text):
        return "confusion"
    if PRAISE_RE.search(text):
        return "praise"
    if CRITICISM_RE.search(text):
        return "criticism"
    if QUESTION_RE.search(text):
        return "question"
    return "other"


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
            scopes=["https://www.googleapis.com/auth/youtube.readonly",
                    "https://www.googleapis.com/auth/youtube.upload",
                    "https://www.googleapis.com/auth/youtube.force-ssl"],
        )
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        return build("youtube", "v3", credentials=creds)
    except Exception:
        return None


def fetch_comments(yt, video_id, max_comments=100):
    out = []
    page_token = None
    fetched = 0
    while fetched < max_comments:
        resp = yt.commentThreads().list(
            part="snippet",
            videoId=video_id,
            maxResults=min(100, max_comments - fetched),
            pageToken=page_token,
            textFormat="plainText",
            order="time",
        ).execute()
        for item in resp.get("items", []):
            snip = item["snippet"]["topLevelComment"]["snippet"]
            out.append({
                "author": snip.get("authorDisplayName"),
                "text": snip.get("textDisplay", ""),
                "likes": snip.get("likeCount", 0),
                "published": snip.get("publishedAt"),
            })
            fetched += 1
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return out


def analyze_video(yt, video_id, video_title, max_comments=100):
    try:
        comments = fetch_comments(yt, video_id, max_comments=max_comments)
    except Exception as e:
        print(f"  ⚠️  comments fetch failed for {video_id}: {e}")
        return None
    if not comments:
        return None
    tallies = collections.Counter()
    samples = collections.defaultdict(list)
    for c in comments:
        cat = categorize(c["text"])
        tallies[cat] += 1
        if len(samples[cat]) < 3:
            samples[cat].append(c["text"][:160])
    return {
        "video_id": video_id,
        "title": video_title,
        "comment_count": len(comments),
        "tallies": dict(tallies),
        "samples": dict(samples),
    }


def write_insights(reports):
    INSIGHTS.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    if INSIGHTS.exists():
        lines = INSIGHTS.read_text(encoding="utf-8").splitlines()
    lines.append("")
    lines.append(f"## Comment scan — {datetime.date.today()}")
    for r in reports:
        if not r:
            continue
        lines.append("")
        lines.append(f"### {r['title']}")
        lines.append(f"- {r['comment_count']} comments scanned")
        for k, v in sorted(r["tallies"].items(), key=lambda x: -x[1]):
            lines.append(f"  - `{k}`: {v}")
        for cat in ("question", "confusion", "praise", "criticism"):
            for s in r["samples"].get(cat, []):
                lines.append(f"  > **{cat}** — _{s}_")
    INSIGHTS.write_text("\n".join(lines), encoding="utf-8")


def run(video_ids):
    yt = _services()
    if not yt:
        print("⏭  YouTube Data API unavailable.")
        return False

    reports = []
    for vid in video_ids:
        meta = yt.videos().list(part="snippet", id=vid).execute()
        items = meta.get("items", [])
        title = items[0]["snippet"]["title"] if items else vid
        print(f"💬 Analyzing comments for: {title}")
        r = analyze_video(yt, vid, title)
        if r:
            for k, v in sorted(r["tallies"].items(), key=lambda x: -x[1]):
                print(f"    {k:12s} {v}")
            reports.append(r)

    if reports:
        write_insights(reports)
        print(f"💾 Insights → {INSIGHTS}")
    return True


def main():
    p = argparse.ArgumentParser()
    p.add_argument("video_ids", nargs="+",
                   help="YouTube video IDs to analyse")
    args = p.parse_args()
    ok = run(args.video_ids)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
