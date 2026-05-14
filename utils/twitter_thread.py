#!/usr/bin/env python3
"""
McNeillium_AI — Agent 38: Twitter Thread Generator

Builds a 6-8 tweet thread from the script: a hook tweet, one key insight
per main point, and a closing tweet that links to the YouTube video.
Each tweet is capped at 270 characters (room for "1/8" prefix and any
mentions/hashtags).

The thread is written to output/social/twitter_thread.txt and
twitter_thread.json for manual posting; auto-posting requires Twitter
API credentials that are intentionally not wired up here.
"""

import argparse
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
SCRIPT_PATH = PROJECT_ROOT / "output" / "scripts" / "latest.json"
SOCIAL_DIR = PROJECT_ROOT / "output" / "social"

MAX_TWEET_LEN = 270


def _first_sentence(text):
    m = re.search(r"^[^.!?\n]+[.!?]", text.strip())
    return m.group(0) if m else text[:240]


def _condense(text, target_len=240):
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= target_len:
        return text
    # truncate at last complete word
    cut = text[:target_len].rsplit(" ", 1)[0]
    return cut.rstrip(",.;:") + "…"


def build_thread(script, video_url=None):
    title = script.get("title", "Untitled")
    sections = script.get("sections", [])
    meta = script.get("metadata", {}) or {}
    tags = [t.lstrip("#") for t in (meta.get("tags") or [])][:3]

    hook = next((s for s in sections if s.get("id") == "hook"), None)
    summary = next((s for s in sections if s.get("id") == "summary"), None)
    main_points = [s for s in sections
                   if (s.get("id") or "").startswith("main_point")]

    tweets = []

    # Tweet 1: hook
    hook_text = ""
    if hook:
        hook_text = _condense(hook.get("narration", title), 220)
    else:
        hook_text = _condense(title, 220)
    tweets.append(hook_text + " 🧵👇")

    # Tweets 2..N: one per main point — leading sentence
    for sec in main_points[:4]:
        text = _first_sentence(sec.get("narration", ""))
        tweets.append(_condense(text, 250))

    # Closing tweet
    closing = _condense(
        (summary.get("narration", title) if summary else title),
        220,
    )
    if video_url:
        closing = (
            f"{closing}\n\n"
            f"📺 Full video: {video_url}\n\n"
            f"Subscribe to @McNeillium_AI for more"
        )
    else:
        closing = (
            f"{closing}\n\n"
            f"Subscribe to @McNeillium_AI for more deep dives."
        )
    if tags:
        closing += "\n\n" + " ".join(f"#{t}" for t in tags[:3])
    tweets.append(closing)

    # Tighten count to 6-8
    if len(tweets) < 6 and main_points:
        # Add a second insight from the longest section
        longest = max(main_points, key=lambda s: len(s.get("narration", "")))
        sentences = re.split(r"(?<=[.!?])\s+",
                             longest.get("narration", ""))
        if len(sentences) > 1:
            tweets.insert(-1, _condense(sentences[1], 250))

    if len(tweets) > 8:
        tweets = tweets[:7] + [tweets[-1]]

    # Number them
    total = len(tweets)
    return [
        f"{i + 1}/{total} {t}" if i < total - 1 else f"{i + 1}/{total} {t}"
        for i, t in enumerate(tweets)
    ]


def run(script_path, out_dir, video_url=None):
    if not Path(script_path).exists():
        print(f"❌ Script not found: {script_path}")
        return False
    with open(script_path, encoding="utf-8") as f:
        script = json.load(f)

    tweets = build_thread(script, video_url=video_url)

    Path(out_dir).mkdir(parents=True, exist_ok=True)
    txt_path = Path(out_dir) / "twitter_thread.txt"
    json_path = Path(out_dir) / "twitter_thread.json"

    txt_path.write_text("\n\n---\n\n".join(tweets), encoding="utf-8")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"title": script.get("title"), "tweets": tweets},
                  f, indent=2)

    print(f"🐦 Thread: {len(tweets)} tweets")
    for i, t in enumerate(tweets, 1):
        marker = "✅" if len(t) <= 280 else "⚠️ "
        print(f"  {marker} [{i}/{len(tweets)}] {len(t)} chars")
    print(f"  💾 {txt_path}")
    return True


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--script", default=str(SCRIPT_PATH))
    p.add_argument("--out-dir", default=str(SOCIAL_DIR))
    p.add_argument("--video-url", default="")
    args = p.parse_args()
    ok = run(args.script, args.out_dir,
             video_url=args.video_url or None)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
