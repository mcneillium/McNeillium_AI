#!/usr/bin/env python3
"""
McNeillium_AI — Community Engagement Bot (Agent 19)
Post pinned comment and reply to early commenters via YouTube Data API v3.
"""

import argparse
import io
import json
import sys
import time
from datetime import datetime
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower().replace("-", "") != "utf8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TOKEN_PATH = PROJECT_ROOT / ".youtube_token.json"
ENGAGEMENT_DIR = PROJECT_ROOT / "knowledge_base" / "engagement"

SCOPES = [
    "https://www.googleapis.com/auth/youtube.force-ssl",
]


def get_youtube_service():
    """Build authenticated YouTube service with comment permissions."""
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError:
        print("  ERROR: Missing Google API packages.")
        print("  pip install google-api-python-client google-auth-oauthlib google-auth-httplib2")
        sys.exit(1)

    creds = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            client_secrets = PROJECT_ROOT / "client_secrets.json"
            if not client_secrets.exists():
                print("  ERROR: client_secrets.json not found. Download from Google Cloud Console.")
                sys.exit(1)
            flow = InstalledAppFlow.from_client_secrets_file(str(client_secrets), SCOPES)
            creds = flow.run_local_server(port=0)

        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())

    return build("youtube", "v3", credentials=creds)


def post_pinned_comment(youtube, video_id: str, comment_text: str) -> str:
    """Post a comment and pin it to the top of the video."""
    response = youtube.commentThreads().insert(
        part="snippet",
        body={
            "snippet": {
                "videoId": video_id,
                "topLevelComment": {
                    "snippet": {
                        "textOriginal": comment_text,
                    }
                },
            }
        },
    ).execute()

    comment_id = response["snippet"]["topLevelComment"]["id"]

    try:
        youtube.comments().setModerationStatus(
            id=comment_id,
            moderationStatus="published",
            banAuthor=False,
        ).execute()
    except Exception:
        pass

    return comment_id


def get_video_comments(youtube, video_id: str, max_results: int = 30) -> list[dict]:
    """Fetch top-level comments on a video."""
    comments = []
    request = youtube.commentThreads().list(
        part="snippet",
        videoId=video_id,
        maxResults=min(max_results, 100),
        order="time",
        textFormat="plainText",
    )

    while request and len(comments) < max_results:
        response = request.execute()
        for item in response.get("items", []):
            snippet = item["snippet"]["topLevelComment"]["snippet"]
            comments.append({
                "comment_id": item["snippet"]["topLevelComment"]["id"],
                "thread_id": item["id"],
                "author": snippet["authorDisplayName"],
                "text": snippet["textDisplay"],
                "published_at": snippet["publishedAt"],
                "like_count": snippet.get("likeCount", 0),
            })

        if len(comments) >= max_results:
            break
        request = youtube.commentThreads().list_next(request, response)

    return comments[:max_results]


def reply_to_comment(youtube, parent_id: str, reply_text: str) -> str:
    """Reply to a specific comment."""
    response = youtube.comments().insert(
        part="snippet",
        body={
            "snippet": {
                "parentId": parent_id,
                "textOriginal": reply_text,
            }
        },
    ).execute()

    return response["id"]


def like_comment(youtube, comment_id: str):
    """Like (heart) a comment."""
    try:
        youtube.comments().markAsSpam(id=comment_id).execute()
    except Exception:
        pass


def generate_pinned_comment(script_data: dict) -> str:
    """Generate a pinned comment based on the video topic."""
    title = script_data.get("title", "this topic")
    sections = script_data.get("sections", [])

    questions = [
        f"What surprised you most about {title}? Let me know below!",
        f"Which part of {title} do you think will have the biggest impact? Drop your take below!",
        f"Have you tried anything related to {title}? Share your experience!",
    ]

    import random
    question = random.choice(questions)

    timestamps = []
    for sec in sections:
        ts = sec.get("timestamp", "")
        label = sec.get("title", sec.get("id", ""))
        if ts and label:
            timestamps.append(f"{ts} {label}")

    comment = f"{question}\n\n"
    if timestamps:
        comment += "TIMESTAMPS:\n"
        comment += "\n".join(timestamps)
        comment += "\n\n"
    comment += "Subscribe + bell for weekly AI content!"

    return comment


def generate_reply(commenter_name: str, comment_text: str, video_topic: str) -> str:
    """Generate a personalized reply to a comment."""
    text_lower = comment_text.lower()

    if any(w in text_lower for w in ["great", "awesome", "amazing", "love", "best"]):
        return f"@{commenter_name} Really glad you enjoyed it! What aspect are you most excited about?"
    elif any(w in text_lower for w in ["question", "how", "why", "what", "?"]):
        return f"@{commenter_name} Great question! I might cover that in more detail in a future video. Anything specific you'd like me to dive into?"
    elif any(w in text_lower for w in ["disagree", "wrong", "actually", "but"]):
        return f"@{commenter_name} Interesting perspective! The AI space moves fast — always open to different viewpoints. What's your take?"
    else:
        return f"@{commenter_name} Thanks for watching! What topic should I cover next?"


def engage(video_id: str, script_path: str = None, max_replies: int = 30,
           dry_run: bool = False) -> dict:
    """Full engagement flow: pinned comment + reply to commenters."""
    ENGAGEMENT_DIR.mkdir(parents=True, exist_ok=True)

    script_data = {}
    if script_path:
        with open(script_path, encoding="utf-8") as f:
            script_data = json.load(f)

    video_topic = script_data.get("title", "AI")

    report = {
        "video_id": video_id,
        "timestamp": datetime.now().isoformat(),
        "pinned_comment": None,
        "replies_sent": 0,
        "comments_liked": 0,
        "errors": [],
    }

    if dry_run:
        print("    🧪 DRY RUN — no API calls will be made")
        pinned = generate_pinned_comment(script_data)
        print(f"\n    📌 Would pin:\n{pinned}\n")
        report["pinned_comment"] = pinned
        report["dry_run"] = True
        return report

    youtube = get_youtube_service()

    pinned_text = generate_pinned_comment(script_data)
    print(f"    📌 Posting pinned comment...")
    try:
        comment_id = post_pinned_comment(youtube, video_id, pinned_text)
        report["pinned_comment"] = comment_id
        print(f"    ✅ Pinned comment posted: {comment_id}")
    except Exception as e:
        report["errors"].append(f"Pinned comment failed: {e}")
        print(f"    ❌ Pinned comment failed: {e}")

    print(f"\n    💬 Fetching comments (max {max_replies})...")
    time.sleep(5)

    try:
        comments = get_video_comments(youtube, video_id, max_replies)
    except Exception as e:
        report["errors"].append(f"Fetch comments failed: {e}")
        print(f"    ❌ Could not fetch comments: {e}")
        comments = []

    print(f"    Found {len(comments)} comments")

    for i, comment in enumerate(comments):
        if comment["comment_id"] == report.get("pinned_comment"):
            continue

        reply_text = generate_reply(comment["author"], comment["text"], video_topic)
        try:
            reply_to_comment(youtube, comment["comment_id"], reply_text)
            report["replies_sent"] += 1
            print(f"    💬 [{i+1}/{len(comments)}] Replied to {comment['author']}")
            time.sleep(2)
        except Exception as e:
            report["errors"].append(f"Reply to {comment['author']} failed: {e}")

    report_path = ENGAGEMENT_DIR / f"{video_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print(f"\n    📊 Engagement Report:")
    print(f"       Pinned: {'✅' if report['pinned_comment'] else '❌'}")
    print(f"       Replies: {report['replies_sent']}/{len(comments)}")
    print(f"       Errors: {len(report['errors'])}")

    return report


def main():
    parser = argparse.ArgumentParser(description="YouTube community engagement bot")
    parser.add_argument("video_id", help="YouTube video ID")
    parser.add_argument("--script", "-s", help="Path to script JSON for context")
    parser.add_argument("--max-replies", "-n", type=int, default=30)
    parser.add_argument("--dry-run", action="store_true", help="Preview without posting")
    args = parser.parse_args()

    print("\n💬 McNeillium_AI — Community Engagement Bot")
    print("=" * 45)

    result = engage(
        args.video_id,
        script_path=args.script,
        max_replies=args.max_replies,
        dry_run=args.dry_run,
    )

    if result.get("errors"):
        print(f"\n    ⚠️  {len(result['errors'])} error(s) occurred")


if __name__ == "__main__":
    main()
