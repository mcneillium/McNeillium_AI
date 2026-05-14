#!/usr/bin/env python3
"""
McNeillium_AI — Autonomous Video Pipeline
==========================================

Generates a complete YouTube video from a topic:
  1. Script  → Claude API writes the video script
  2. Voice   → Edge TTS narrates the script  
  3. Video   → Pillow + FFmpeg assembles screen-recording style video
  4. Git     → Auto-commits and pushes to GitHub

Usage:
  python pipeline.py --topic "What are AI Agents and why they matter"
  python pipeline.py --topic "How transformers work" --skip-git
"""

import argparse
import asyncio
import io
import sys
import time
from pathlib import Path

import yaml
from dotenv import load_dotenv

if sys.stdout.encoding and sys.stdout.encoding.lower().replace("-", "") != "utf8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

load_dotenv()

# Resolve paths relative to project root
PROJECT_ROOT = Path(__file__).resolve().parent
CONFIG_PATH = PROJECT_ROOT / "config.yaml"

# Add project root to path so modules can import each other
sys.path.insert(0, str(PROJECT_ROOT))


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def run_pipeline(topic: str, skip_git: bool = False, skip_video: bool = False):
    """Run the full content generation pipeline."""

    config = load_config()
    start_time = time.time()

    print("\n" + "=" * 60)
    print("  🎬  McNeillium_AI — Autonomous Video Pipeline")
    print("=" * 60)
    print(f"\n  Topic: {topic}")
    print(f"  Channel: {config['channel']['name']}")
    print()

    # ── STAGE 1: Script Generation ──
    print("━" * 60)
    print("  STAGE 1/4 — 📝 Script Generation")
    print("━" * 60)
    from scripts.generate_script import generate_script, save_script

    script_data = generate_script(topic, config)
    script_path = save_script(script_data, topic)
    print(f"  ✅ Script: {script_data.get('title', topic)}")
    print(f"     Sections: {len(script_data.get('sections', []))}")
    print()

    # ── STAGE 2: Voice Generation ──
    print("━" * 60)
    print("  STAGE 2/4 — 🎤 Voice Generation")
    print("━" * 60)
    from voice.generate_voice import generate_full_audio

    audio_path = asyncio.run(generate_full_audio(script_data, config))
    print(f"  ✅ Audio: {audio_path}")
    print()

    # ── STAGE 3: Video Assembly ──
    if not skip_video:
        print("━" * 60)
        print("  STAGE 3/4 — 🎬 Video Assembly")
        print("━" * 60)
        from video.generate_video import generate_video

        video_path = generate_video(str(script_path), str(audio_path), config)
        size_mb = video_path.stat().st_size / (1024 * 1024)
        print(f"  ✅ Video: {video_path} ({size_mb:.1f} MB)")
        print()
    else:
        print("  ⏭  Skipping video assembly (--skip-video)")
        video_path = None
        print()

    # ── STAGE 4: Multi-platform distribution (Phase 7) ──
    if video_path:
        print("━" * 60)
        print("  STAGE 4/5 — 🌐 Multi-platform Distribution")
        print("━" * 60)
        try:
            from utils.shorts_producer import run as run_shorts
            run_shorts(str(script_path), str(video_path),
                       str(PROJECT_ROOT / "output" / "shorts"), n=5)
        except Exception as e:
            print(f"  ⚠️  Shorts producer failed: {e}")
        try:
            from utils.blog_writer import run as run_blog
            run_blog(str(script_path),
                     str(PROJECT_ROOT / "output" / "blog"))
        except Exception as e:
            print(f"  ⚠️  Blog writer failed: {e}")
        try:
            from utils.twitter_thread import run as run_thread
            run_thread(str(script_path),
                       str(PROJECT_ROOT / "output" / "social"))
        except Exception as e:
            print(f"  ⚠️  Twitter thread failed: {e}")
        print()

    # ── STAGE 5: Git Push ──
    if not skip_git:
        print("━" * 60)
        print("  STAGE 5/5 — 📤 Git Push")
        print("━" * 60)
        from utils.git_push import git_push

        commit_msg = f"{script_data.get('title', topic)}"
        git_push(message=commit_msg, config=config)
        print()
    else:
        print("  ⏭  Skipping git push (--skip-git)")
        print()

    # ── Summary ──
    elapsed = time.time() - start_time
    minutes = int(elapsed // 60)
    seconds = int(elapsed % 60)

    print("=" * 60)
    print("  ✅  PIPELINE COMPLETE")
    print("=" * 60)
    print(f"  📝 Title:    {script_data.get('title', topic)}")
    print(f"  📄 Script:   {script_path}")
    print(f"  🎵 Audio:    {audio_path}")
    if video_path:
        print(f"  🎬 Video:    {video_path}")
    print(f"  ⏱  Time:     {minutes}m {seconds}s")
    print(f"  📑 Sections: {len(script_data.get('sections', []))}")
    print()

    return {
        "title": script_data.get("title"),
        "script_path": str(script_path),
        "audio_path": str(audio_path),
        "video_path": str(video_path) if video_path else None,
    }


def main():
    parser = argparse.ArgumentParser(
        description="McNeillium_AI — Generate a full YouTube video from a topic",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python pipeline.py --topic "What are AI Agents"
  python pipeline.py --topic "How RAG works" --skip-git
  python pipeline.py --topic "Claude 4 explained" --skip-video
        """,
    )
    parser.add_argument(
        "--topic", "-t",
        required=True,
        help="The video topic (be specific for better results)",
    )
    parser.add_argument(
        "--skip-git",
        action="store_true",
        help="Skip the git commit/push stage",
    )
    parser.add_argument(
        "--skip-video",
        action="store_true",
        help="Skip video assembly (generate script + audio only)",
    )
    args = parser.parse_args()

    result = run_pipeline(
        topic=args.topic,
        skip_git=args.skip_git,
        skip_video=args.skip_video,
    )

    return result


if __name__ == "__main__":
    main()
