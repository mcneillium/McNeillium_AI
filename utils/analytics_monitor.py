#!/usr/bin/env python3
"""
McNeillium_AI — Agent 41: YouTube Analytics Monitor

Polls the YouTube Analytics API for per-video performance and saves a
daily snapshot to knowledge_base/performance_data.json so the Trend
Researcher and Script Writer can read it.

Requires the YouTube Analytics API enabled in the same Google Cloud
project as the upload OAuth. Add this scope and re-consent if needed:

    https://www.googleapis.com/auth/yt-analytics.readonly

Per video, we record: views, ctr, average_view_duration, watch_time_min,
estimated_minutes_watched, top traffic sources. Missing API access
falls back to graceful no-op so the pipeline still runs.
"""

import argparse
import datetime
import io
import json
import os
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower().replace("-", "") != "utf8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8",
                                  errors="replace")

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TOKEN_PATH = PROJECT_ROOT / ".youtube_token.json"
PERF_PATH = PROJECT_ROOT / "knowledge_base" / "performance_data.json"

ANALYTICS_SCOPE = "https://www.googleapis.com/auth/yt-analytics.readonly"
DATA_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"


def _get_services():
    """Return (youtube_v3, ytanalytics_v2) or (None, None) on failure."""
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError:
        print("⚠️  google-api-python-client not installed")
        return None, None

    if not TOKEN_PATH.exists():
        print(f"⚠️  No OAuth token at {TOKEN_PATH} — run the uploader once "
              f"to consent (then re-consent with analytics scope).")
        return None, None

    try:
        creds = Credentials.from_authorized_user_file(
            str(TOKEN_PATH),
            scopes=[ANALYTICS_SCOPE, DATA_SCOPE,
                    "https://www.googleapis.com/auth/youtube.upload"],
        )
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        yt = build("youtube", "v3", credentials=creds)
        ya = build("youtubeAnalytics", "v2", credentials=creds)
        return yt, ya
    except Exception as e:
        print(f"⚠️  Failed to build services: {e}")
        return None, None


def list_my_videos(youtube, max_results=20):
    """List videos uploaded by the authenticated channel."""
    req = youtube.channels().list(part="contentDetails", mine=True)
    resp = req.execute()
    items = resp.get("items", [])
    if not items:
        return []
    uploads = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
    pl = youtube.playlistItems().list(
        part="contentDetails,snippet",
        playlistId=uploads,
        maxResults=max_results,
    ).execute()
    return [
        {
            "video_id": it["contentDetails"]["videoId"],
            "title": it["snippet"]["title"],
            "published_at": it["contentDetails"]["videoPublishedAt"],
        }
        for it in pl.get("items", [])
    ]


def query_video_stats(ytanalytics, video_id, days=30):
    """Return dict of headline metrics for the last N days."""
    end = datetime.date.today().isoformat()
    start = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    metrics = ",".join([
        "views", "estimatedMinutesWatched", "averageViewDuration",
        "averageViewPercentage", "subscribersGained",
    ])
    resp = ytanalytics.reports().query(
        ids="channel==MINE",
        startDate=start, endDate=end,
        metrics=metrics,
        filters=f"video=={video_id}",
    ).execute()
    rows = resp.get("rows") or [[]]
    headers = [h["name"] for h in resp.get("columnHeaders", [])]
    return dict(zip(headers, rows[0])) if rows[0] else {}


def query_traffic_sources(ytanalytics, video_id, days=30):
    end = datetime.date.today().isoformat()
    start = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    resp = ytanalytics.reports().query(
        ids="channel==MINE",
        startDate=start, endDate=end,
        metrics="views",
        dimensions="insightTrafficSourceType",
        filters=f"video=={video_id}",
        sort="-views",
        maxResults=5,
    ).execute()
    return [
        {"source": row[0], "views": row[1]}
        for row in resp.get("rows", [])
    ]


def run(days=30, max_videos=20):
    yt, ya = _get_services()
    if not yt or not ya:
        print("⏭  Analytics services unavailable — recording empty snapshot.")
        snapshot = {
            "captured_at": datetime.datetime.now().isoformat(),
            "videos": [],
            "note": "OAuth or API access missing — re-run after enabling YouTube Analytics scope.",
        }
    else:
        videos = list_my_videos(yt, max_results=max_videos)
        print(f"📊 Analytics Monitor — {len(videos)} videos to query")
        rows = []
        for v in videos:
            try:
                stats = query_video_stats(ya, v["video_id"], days=days)
                traffic = query_traffic_sources(ya, v["video_id"], days=days)
            except Exception as e:
                print(f"  ⚠️  {v['video_id']}: {e}")
                stats, traffic = {}, []
            entry = {**v, "stats": stats, "top_traffic": traffic}
            rows.append(entry)
            print(f"  - {v['title'][:50]:50s} "
                  f"views={stats.get('views', 0)} "
                  f"avd={stats.get('averageViewDuration', 0)}s")
        snapshot = {
            "captured_at": datetime.datetime.now().isoformat(),
            "days_window": days,
            "videos": rows,
        }

    PERF_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Append to a list so we can see daily history
    history = []
    if PERF_PATH.exists():
        try:
            history = json.loads(PERF_PATH.read_text(encoding="utf-8"))
            if isinstance(history, dict):
                history = [history]
        except Exception:
            history = []
    history.append(snapshot)
    PERF_PATH.write_text(
        json.dumps(history[-30:], indent=2), encoding="utf-8")
    print(f"💾 Performance snapshot → {PERF_PATH} "
          f"(history depth: {len(history[-30:])})")
    return True


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--max-videos", type=int, default=20)
    args = p.parse_args()
    ok = run(days=args.days, max_videos=args.max_videos)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
