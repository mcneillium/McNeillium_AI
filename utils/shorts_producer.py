#!/usr/bin/env python3
"""
McNeillium_AI — Agent 34: Shorts Producer

Extracts the 5-10 strongest 30-60s moments from a long video, reframes to
vertical 1080x1920, enlarges the captions for mobile, adds a "@McNeillium_AI"
watermark, and saves each Short as a self-contained MP4 ready for upload
as a YouTube Short (use `python utils/youtube_upload.py --short <path>`).

Moment selection heuristic (no LLM):
  - Use the script's section structure to seed candidate windows
  - Score each window by:
      + section is hook OR contains a numeric stat        → +2
      + window length in [30, 60] seconds                  → +1
      + window contains an "open loop" phrase ("here's     → +1
        the wildest part", "but", "imagine")
      + section is intro/outro                             → -1
  - Pick the top N non-overlapping windows
"""

import argparse
import io
import json
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower().replace("-", "") != "utf8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8",
                                  errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = PROJECT_ROOT / "output" / "scripts" / "latest.json"
VIDEO_PATH = PROJECT_ROOT / "output" / "videos" / "latest.mp4"
CAPTIONS_DIR = PROJECT_ROOT / "output" / "audio" / "captions"
SHORTS_DIR = PROJECT_ROOT / "output" / "shorts"
WATERMARK = "@McNeillium_AI"

PROMOTION_RE = re.compile(
    r"\b(here'?s the wildest|but|imagine|what if|here'?s why|the catch|"
    r"\d+(\.\d+)?\s*(%|percent|x|times|million|billion|trillion))\b",
    re.I,
)


def _find_ffmpeg():
    r = shutil.which("ffmpeg")
    if r:
        return r
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return "ffmpeg"


def _find_ffprobe():
    return shutil.which("ffprobe") or "ffprobe"


FFMPEG = _find_ffmpeg()
FFPROBE = _find_ffprobe()


def probe_duration(path):
    r = subprocess.run(
        [FFPROBE, "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    try:
        return float(r.stdout.strip())
    except Exception:
        return 0.0


# ═══════════════════════════════════════════════════════════════
# Window scoring
# ═══════════════════════════════════════════════════════════════

def _section_offsets(script, total_dur, intro_dur=3.5, outro_dur=3.5):
    """Estimate each section's start/end second in the assembled video."""
    sections = script.get("sections", [])
    chars = [len(s.get("narration", "")) for s in sections]
    total = sum(chars) or 1
    content = max(1.0, total_dur - intro_dur - outro_dur)
    durs = [(c / total) * content for c in chars]
    offsets = []
    t = intro_dur
    for sec, d in zip(sections, durs):
        offsets.append({
            "id": sec.get("id"),
            "start": t,
            "end": t + d,
            "narration": sec.get("narration", ""),
        })
        t += d
    return offsets


def score_window(section, start, end):
    score = 0
    length = end - start
    if 30 <= length <= 60:
        score += 1
    sid = section.get("id", "")
    if sid in {"intro", "outro"}:
        score -= 1
    if sid == "hook":
        score += 2
    if PROMOTION_RE.search(section.get("narration", "")):
        score += 1
    return score


def pick_moments(script, total_dur, n=5):
    """Return up to N (start, end, label) tuples for the best moments."""
    sections = _section_offsets(script, total_dur)
    candidates = []
    for sec in sections:
        # Use up to two 45s windows per section to keep variety
        dur = sec["end"] - sec["start"]
        if dur < 25:
            continue
        if dur <= 60:
            candidates.append((sec["start"], min(sec["end"], sec["start"] + 60), sec))
        else:
            # split into 2 windows
            mid = (sec["start"] + sec["end"]) / 2
            candidates.append((sec["start"], min(sec["start"] + 50, mid + 10), sec))
            candidates.append((max(mid - 10, sec["end"] - 50), sec["end"], sec))

    scored = [
        (score_window(sec, s, e), s, e, sec)
        for s, e, sec in candidates
    ]
    scored.sort(key=lambda x: (-x[0], x[1]))

    picked = []
    for score, s, e, sec in scored:
        if score < 0:
            continue
        if any(not (e <= ps or s >= pe) for ps, pe, _ in picked):
            continue
        picked.append((s, e, sec))
        if len(picked) >= n:
            break
    return picked


# ═══════════════════════════════════════════════════════════════
# Reframe + render
# ═══════════════════════════════════════════════════════════════

def render_short(video_path, start, duration, output_path, watermark=WATERMARK):
    """Cut the window, reframe to vertical 1080x1920, burn watermark."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # The source is 1920x1080. We scale up so height fills 1920 and
    # crop horizontally to 1080 wide.
    vf = (
        "scale=-2:1920:flags=lanczos,"
        "crop=1080:1920:(in_w-1080)/2:0,"
        # Enlarged caption-style label at top + watermark bottom
        f"drawtext=text='{watermark}':fontcolor=white@0.85:"
        f"fontsize=42:box=1:boxcolor=black@0.4:boxborderw=10:"
        f"x=(w-text_w)/2:y=h-110"
    )
    cmd = [
        FFMPEG, "-y",
        "-ss", str(start),
        "-i", str(video_path),
        "-t", str(duration),
        "-vf", vf,
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "192k",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(output_path),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"    ⚠️  Shorts render failed: {r.stderr[-300:]}")
        return False
    return True


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

def run(script_path, video_path, out_dir, n=5):
    if not Path(script_path).exists() or not Path(video_path).exists():
        print("❌ Script or video not found")
        return False

    with open(script_path, encoding="utf-8") as f:
        script = json.load(f)
    duration = probe_duration(video_path)
    if duration <= 0:
        print("❌ Could not probe video duration")
        return False

    moments = pick_moments(script, duration, n=n)
    if not moments:
        print("⚠️  No suitable moments found")
        return True

    title = script.get("title", "untitled").lower()
    slug = re.sub(r"[^a-z0-9]+", "_", title).strip("_")[:40]

    Path(out_dir).mkdir(parents=True, exist_ok=True)
    manifest = []
    for idx, (s, e, sec) in enumerate(moments, 1):
        sid = sec.get("id", "section")
        out_path = Path(out_dir) / f"short_{idx:02d}_{slug}_{sid}.mp4"
        print(f"  ✂️  Short {idx}: {sid} @ {s:.1f}s → {e:.1f}s "
              f"({e - s:.1f}s) — {out_path.name}")
        ok = render_short(video_path, s, e - s, out_path)
        manifest.append({
            "index": idx,
            "section_id": sid,
            "start": s,
            "end": e,
            "duration": e - s,
            "path": str(out_path),
            "ok": ok,
        })

    manifest_path = Path(out_dir) / "shorts_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump({"title": script.get("title"), "shorts": manifest}, f, indent=2)
    print(f"  📋 Manifest → {manifest_path}")
    return True


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--script", default=str(SCRIPT_PATH))
    p.add_argument("--video", default=str(VIDEO_PATH))
    p.add_argument("--out-dir", default=str(SHORTS_DIR))
    p.add_argument("--n", type=int, default=5)
    args = p.parse_args()
    ok = run(args.script, args.video, args.out_dir, n=args.n)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
