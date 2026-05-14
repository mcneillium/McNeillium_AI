#!/usr/bin/env python3
"""
McNeillium_AI — YouTube Uploader
Uploads videos to YouTube using the YouTube Data API v3.

First-time setup requires browser-based OAuth consent.
After that, a refresh token is saved and reused automatically.
"""

import argparse
import io
import json
import os
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower().replace("-", "") != "utf8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_DIR = PROJECT_ROOT / "output" / "scripts"
VIDEO_DIR = PROJECT_ROOT / "output" / "videos"
TOKEN_PATH = PROJECT_ROOT / ".youtube_token.json"

# Default upload settings
DEFAULT_CATEGORY = "28"  # Science & Technology
DEFAULT_PRIVACY = "private"  # Start as private so you can review before publishing


def get_authenticated_service():
    """Build and return an authenticated YouTube API service."""
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError:
        print("  ERROR: Missing Google API packages. Install them:")
        print("  pip install google-api-python-client google-auth-oauthlib google-auth-httplib2")
        sys.exit(1)

    SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

    creds = None

    # Load saved token
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    # Refresh or re-auth
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("  🔄 Refreshing access token...")
            creds.refresh(Request())
        else:
            client_secrets = PROJECT_ROOT / "client_secrets.json"
            if not client_secrets.exists():
                print("  ERROR: client_secrets.json not found in project root.")
                print("")
                print("  To set up YouTube uploads:")
                print("  1. Go to https://console.cloud.google.com/")
                print("  2. Create a project (or select existing)")
                print("  3. Enable 'YouTube Data API v3'")
                print("  4. Go to Credentials → Create Credentials → OAuth Client ID")
                print("  5. Application type: Desktop App")
                print("  6. Download the JSON and save as client_secrets.json")
                print("     in ~/Documents/McNeillium_AI/")
                sys.exit(1)

            print("  🌐 Opening browser for YouTube authorisation...")
            print("     (This only happens once)")
            flow = InstalledAppFlow.from_client_secrets_file(
                str(client_secrets), SCOPES
            )
            creds = flow.run_local_server(port=8090)

        # Save token for next time
        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())
        print("  💾 Token saved — no browser needed next time")

    return build("youtube", "v3", credentials=creds)


EXPECTED_CHANNEL_FRAGMENT = "mcneillium"


def verify_channel(youtube, expected_fragment=EXPECTED_CHANNEL_FRAGMENT):
    """Refuse to upload unless the authenticated channel matches the brand.

    Calls channels.list(mine=true), reads snippet.title, requires that
    the expected_fragment (case-insensitive) appears in the title.
    Returns (ok: bool, channel_title: str, channel_id: str).
    """
    try:
        resp = youtube.channels().list(part="snippet", mine=True).execute()
    except Exception as e:
        print(f"  ❌ Could not query the authenticated channel: {e}")
        return False, None, None
    items = resp.get("items", []) or []
    if not items:
        print("  ❌ No channel returned by channels.list(mine=true).")
        return False, None, None
    ch = items[0]
    title = ch.get("snippet", {}).get("title", "")
    ch_id = ch.get("id", "")
    print(f"  🎬 Authenticated channel: {title!r}  (id={ch_id})")
    if expected_fragment.lower() not in title.lower():
        print(f"  ❌ ABORT — expected the title to contain "
              f"{expected_fragment!r}.")
        print(f"  ❌ This looks like the WRONG channel "
              f"(possibly a personal account).")
        print(f"  ❌ Delete .youtube_token.json and re-run; the OAuth "
              f"flow will let you pick the McNeillium AI brand account.")
        return False, title, ch_id
    print(f"  ✅ Channel verified — uploads will go to "
          f"the McNeillium AI brand account.")
    return True, title, ch_id


def upload_video(
    video_path: str,
    title: str,
    description: str,
    tags: list[str] = None,
    category: str = DEFAULT_CATEGORY,
    privacy: str = DEFAULT_PRIVACY,
    skip_channel_check: bool = False,
) -> str:
    """Upload a video to YouTube and return the video ID."""
    from googleapiclient.http import MediaFileUpload

    youtube = get_authenticated_service()
    if not skip_channel_check:
        ok, _ct, _cid = verify_channel(youtube)
        if not ok:
            print("  ⛔ Upload aborted by channel verification.")
            sys.exit(2)

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags or [],
            "categoryId": category,
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
        },
    }

    print(f"  📤 Uploading: {title}")
    print(f"  🔒 Privacy: {privacy} (change to 'public' when ready)")

    media = MediaFileUpload(
        video_path,
        mimetype="video/mp4",
        resumable=True,
        chunksize=1024 * 1024 * 5,  # 5MB chunks
    )

    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            pct = int(status.progress() * 100)
            print(f"  📊 Upload progress: {pct}%")

    video_id = response["id"]
    video_url = f"https://youtu.be/{video_id}"

    print(f"  ✅ Uploaded! {video_url}")
    # Phase 12.2: long-form videos ship with no burned-in captions.
    # YouTube auto-generates English CC from the audio within ~24 hours
    # of upload — viewers toggle them via the CC button. No API flag
    # is needed; this is the default behaviour for any video with a
    # detectable language.
    print(f"  📝 YouTube will auto-generate captions from audio within "
          f"~24h — viewers can toggle CC on this video.")
    return video_id


def upload_from_script(script_path: str, video_path: str, privacy: str = DEFAULT_PRIVACY) -> str:
    """Upload using metadata from a script JSON file."""
    with open(script_path, encoding="utf-8") as f:
        script_data = json.load(f)

    title = script_data.get("title", "McNeillium_AI Video")
    description = script_data.get("description", "")

    # Add channel branding to description
    description += "\n\n---"
    description += "\n🤖 McNeillium_AI — AI & Emerging Tech"
    description += "\nLike & Subscribe for more AI content!"
    description += "\n\n#AI #MachineLearning #Tech #McNeilliumAI"

    tags = script_data.get("tags", [])
    tags.extend(["AI", "artificial intelligence", "machine learning", "McNeillium_AI", "tech"])
    tags = list(set(tags))  # Deduplicate

    return upload_video(
        video_path=video_path,
        title=title,
        description=description,
        tags=tags,
        privacy=privacy,
    )


def main():
    parser = argparse.ArgumentParser(description="Upload video to YouTube")
    parser.add_argument(
        "--script", "-s",
        default=str(SCRIPT_DIR / "latest.json"),
        help="Path to script JSON (for title, description, tags)",
    )
    parser.add_argument(
        "--video", "-v",
        default=str(VIDEO_DIR / "latest.mp4"),
        help="Path to video file",
    )
    parser.add_argument(
        "--privacy", "-p",
        default=DEFAULT_PRIVACY,
        choices=["private", "unlisted", "public"],
        help="Video privacy status (default: private)",
    )
    args = parser.parse_args()

    print("\n📺 McNeillium_AI — YouTube Uploader")
    print("=" * 50)

    video_id = upload_from_script(
        script_path=args.script,
        video_path=args.video,
        privacy=args.privacy,
    )

    print(f"\n  🎬 Video ID: {video_id}")
    print(f"  🔗 URL: https://youtu.be/{video_id}")
    print(f"  📋 Studio: https://studio.youtube.com/video/{video_id}/edit")


if __name__ == "__main__":
    main()
