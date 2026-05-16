#!/usr/bin/env python3
"""
McNeillium_AI — Phase 19 Step 2 — Agent 33: Real Footage Collector

Pulls short fair-use clips from YouTube (and other sources yt-dlp
supports) so the Visual Director can prefer real-event footage over
generic stock when available.

────────────────────────────────────────────────────────────────────
Fair-use & ToS notes — read before enabling auto-download
────────────────────────────────────────────────────────────────────

  - Fair use is a defense, not a permission slip. The clips you pull
    here MUST be (a) ≤ 15 seconds, (b) paired with substantial
    original commentary, and (c) attributed in the description.

  - YouTube's ToS prohibits automated downloading. Channels operating
    at scale typically license footage or work from press kits. Treat
    this tool as: "I, the user, manually curated these URLs because
    I need them for fair-use commentary," not "robot, go scrape."

  - The default mode is `--from-list` (a YAML/JSON file you maintain)
    rather than `--auto-search`, to keep the tool inside the manual-
    curation lane.

  - Clips are clipped server-side via yt-dlp's `download_ranges` so we
    don't keep full-length copies on disk. Every download appends a
    row to knowledge_base/fair_use_log.csv.

────────────────────────────────────────────────────────────────────
Public API
────────────────────────────────────────────────────────────────────

  collect(spec_or_path, out_dir=...) -> list[dict]
      spec is a dict like:
        {
          "topic": "anthropic-950b",
          "clips": [
            {"url": "...", "start": 30, "end": 42,
             "purpose": "Amodei talking about safety", "channel": "Anthropic"}
          ]
        }
      or a path to a JSON file with that structure.

  build_shot_entries(clips) -> list[dict]
      Convert downloaded clip metadata into shot-list entries the
      Visual Director can splice into its existing shot dict.

CLI:
  python utils/real_footage_collector.py --from-list specs/altman.json
"""

import argparse
import csv
import datetime as _dt
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
FOOTAGE_DIR = PROJECT_ROOT / "output" / "_real_footage"
FAIR_USE_LOG = PROJECT_ROOT / "knowledge_base" / "fair_use_log.csv"
MAX_CLIP_SECONDS = 15

# Channels whose content we treat as primary-source for fair-use
# commentary. Anything outside this list is rejected by default;
# pass --allow-unverified to override on a one-off basis.
VERIFIED_CHANNELS = {
    "OpenAI", "Anthropic", "Google", "Google DeepMind",
    "Microsoft", "Meta", "Meta AI", "NVIDIA",
    "Bloomberg", "Bloomberg Television", "CNBC",
    "Wall Street Journal", "Reuters", "BBC News", "Sky News",
    "60 Minutes", "Lex Fridman", "TED", "Y Combinator",
}


def _ydl_opts(out_template, start, end):
    """yt-dlp options with server-side clipping + safe defaults."""
    return {
        "format": "best[ext=mp4][height<=1080]/best",
        "outtmpl": out_template,
        "download_ranges": _range_lambda(start, end),
        "force_keyframes_at_cuts": True,
        "quiet": True,
        "noprogress": True,
        "concurrent_fragment_downloads": 1,
        # Don't write the metadata sidecar — we keep our own CSV.
        "writeinfojson": False,
    }


def _range_lambda(start, end):
    def _r(info, ydl):
        return [{"start_time": float(start), "end_time": float(end)}]
    return _r


def _log_fair_use(row):
    FAIR_USE_LOG.parent.mkdir(parents=True, exist_ok=True)
    new = not FAIR_USE_LOG.exists()
    with open(FAIR_USE_LOG, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["timestamp", "topic", "url", "channel",
                        "title", "start_s", "end_s", "purpose",
                        "saved_to"])
        w.writerow([row["timestamp"], row["topic"], row["url"],
                    row["channel"], row["title"],
                    row["start"], row["end"], row["purpose"],
                    row["saved_to"]])


def collect(spec, out_dir=None, allow_unverified=False):
    """Download every clip in `spec`, returning a list of result dicts."""
    try:
        import yt_dlp
    except ImportError:
        print("❌ yt-dlp not installed. `pip install yt-dlp`")
        return []

    if isinstance(spec, (str, Path)):
        spec = json.loads(Path(spec).read_text(encoding="utf-8"))

    topic = spec.get("topic", "untitled")
    clips = spec.get("clips", [])
    out_dir = Path(out_dir or FOOTAGE_DIR / topic)
    out_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for i, c in enumerate(clips, 1):
        url = c["url"]
        start = float(c.get("start", 0))
        end = float(c.get("end", start + 10))
        clip_dur = end - start
        if clip_dur > MAX_CLIP_SECONDS:
            print(f"  ⏭  {url} — requested {clip_dur:.1f}s exceeds "
                  f"{MAX_CLIP_SECONDS}s cap; clipping to {MAX_CLIP_SECONDS}s")
            end = start + MAX_CLIP_SECONDS
            clip_dur = MAX_CLIP_SECONDS

        out_template = str(out_dir / f"{i:02d}_%(id)s.%(ext)s")
        opts = _ydl_opts(out_template, start, end)
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                channel = info.get("uploader") or info.get("channel") or ""
                title = info.get("title") or ""
                if not allow_unverified and channel not in VERIFIED_CHANNELS:
                    print(f"  ⛔ {url} — channel {channel!r} not verified; "
                          f"skipping. (--allow-unverified to override)")
                    continue
                ydl.download([url])
            saved_files = sorted(out_dir.glob(f"{i:02d}_*.*"))
            saved = str(saved_files[0]) if saved_files else ""
            row = {
                "timestamp": _dt.datetime.now().isoformat(timespec="seconds"),
                "topic": topic, "url": url, "channel": channel,
                "title": title, "start": start, "end": end,
                "purpose": c.get("purpose", ""), "saved_to": saved,
            }
            _log_fair_use(row)
            results.append(row)
            print(f"  ✅ [{i}/{len(clips)}] {channel}: {title[:60]}  "
                  f"({clip_dur:.1f}s)")
        except Exception as e:
            print(f"  ❌ [{i}/{len(clips)}] {url} — {type(e).__name__}: {e}")
    return results


def build_shot_entries(clip_results):
    """Convert collect() results into shot-list dict entries.

    The Visual Director can splice these into its existing shot
    list using shot_type='real_footage'. Each entry is keyed by
    purpose, so the director can match against its narration text.
    """
    return [
        {
            "shot_type": "real_footage",
            "source_url": r["url"],
            "channel": r["channel"],
            "title": r["title"],
            "purpose": r["purpose"],
            "duration_s": r["end"] - r["start"],
            "path": r["saved_to"],
            "attribution": f"Source: {r['channel']} via YouTube",
        }
        for r in clip_results if r.get("saved_to")
    ]


def main():
    p = argparse.ArgumentParser(description="Phase 19 real footage collector")
    p.add_argument("--from-list", required=True,
                   help="Path to JSON spec (topic + clips list)")
    p.add_argument("--out-dir", default=None)
    p.add_argument("--allow-unverified", action="store_true",
                   help="Bypass the verified-channel whitelist")
    args = p.parse_args()

    print("📺 Real footage collector — yt-dlp + verified-channel allowlist")
    results = collect(args.from_list, out_dir=args.out_dir,
                      allow_unverified=args.allow_unverified)
    print(f"\n✅ {len(results)} clip(s) downloaded → fair_use_log appended")
    sys.exit(0 if results else 2)


if __name__ == "__main__":
    main()
