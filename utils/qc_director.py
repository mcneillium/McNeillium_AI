#!/usr/bin/env python3
"""
McNeillium_AI — Agent 27: Quality Control Director

Final gate before upload. Samples frames from the rendered video and runs
deterministic heuristics across five quality dimensions:

    1. Visual variety       — frame-to-frame change (footage isn't static)
    2. Caption legibility   — bottom 18% has high contrast (captions visible)
    3. Brightness sanity    — no long stretches of black/white frames
    4. Audio loudness       — integrated LUFS in [-16, -13] range
    5. Duration sanity      — at least 60s, not absurdly long

Each dimension scores 0-10. The final score is the weighted average.
Anything below the pass threshold (default 8) is logged and the script
exits non-zero so the calling pipeline can decide to re-render.

NOTE: This is heuristic, not perceptual. It catches gross failures
(black video, silent audio, monotone footage) reliably; subjective
quality judgements remain a human's job.
"""

import argparse
import io
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from statistics import mean, pstdev

if sys.stdout.encoding and sys.stdout.encoding.lower().replace("-", "") != "utf8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8",
                                  errors="replace")

import numpy as np
from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parent.parent
VIDEO_DIR = PROJECT_ROOT / "output" / "videos"
DEFAULT_VIDEO = VIDEO_DIR / "latest.mp4"
REPORT_DIR = PROJECT_ROOT / "knowledge_base" / "reviews"


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
    r = shutil.which("ffprobe")
    if r:
        return r
    return "ffprobe"


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


def probe_loudness(path):
    """Run ffmpeg loudnorm in measurement mode. Returns dict or None."""
    cmd = [
        FFMPEG, "-nostats", "-i", str(path),
        "-af", "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json",
        "-f", "null", "-",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    text = r.stderr
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def sample_frames(video_path, sample_dir, samples=20):
    """Extract up to `samples` frames spread across the video."""
    sample_dir.mkdir(parents=True, exist_ok=True)
    duration = probe_duration(video_path)
    if duration < 2:
        return []

    rate = max(1, int(samples / max(1, duration / samples)))
    cmd = [
        FFMPEG, "-y", "-i", str(video_path),
        "-vf", f"fps=1/{max(1, duration / samples):.2f}",
        "-frames:v", str(samples),
        str(sample_dir / "frame_%03d.jpg"),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        # Fallback: take frames every 5 seconds
        cmd = [
            FFMPEG, "-y", "-i", str(video_path),
            "-vf", "fps=1/5", "-frames:v", str(samples),
            str(sample_dir / "frame_%03d.jpg"),
        ]
        subprocess.run(cmd, capture_output=True, text=True)
    return sorted(sample_dir.glob("frame_*.jpg"))


def score_visual_variety(frame_paths):
    """Compute average frame-to-frame change. Higher = more visual variety."""
    if len(frame_paths) < 3:
        return 5, "not enough frames sampled"

    diffs = []
    prev = None
    for p in frame_paths:
        try:
            img = Image.open(p).convert("L").resize((192, 108))
            arr = np.asarray(img, dtype=np.float32)
            if prev is not None:
                diffs.append(float(np.mean(np.abs(arr - prev))))
            prev = arr
        except Exception:
            continue

    if not diffs:
        return 5, "no diffs computed"

    avg = mean(diffs)
    if avg < 1.5:
        return 3, f"footage is too static (avg diff {avg:.2f})"
    if avg < 4:
        return 6, f"moderate variety (avg diff {avg:.2f})"
    if avg < 10:
        return 9, f"good variety (avg diff {avg:.2f})"
    return 10, f"high variety (avg diff {avg:.2f})"


def score_caption_legibility(frame_paths):
    """Check bottom 18% for high local contrast (proxy for visible captions)."""
    if len(frame_paths) < 3:
        return 5, "not enough frames"

    contrasts = []
    for p in frame_paths:
        try:
            img = Image.open(p).convert("L")
            w, h = img.size
            crop = img.crop((0, int(h * 0.82), w, h))
            arr = np.asarray(crop, dtype=np.float32)
            contrasts.append(float(arr.std()))
        except Exception:
            continue

    if not contrasts:
        return 5, "no caption region read"

    avg_contrast = mean(contrasts)
    if avg_contrast < 18:
        return 4, f"bottom region low contrast ({avg_contrast:.1f}) — captions may be missing"
    if avg_contrast < 35:
        return 7, f"bottom region adequate contrast ({avg_contrast:.1f})"
    return 9, f"bottom region high contrast ({avg_contrast:.1f}) — captions clearly visible"


def score_brightness(frame_paths):
    """Penalise frames that are truly broken (uniformly black or white).

    A frame is "broken" only if both:
      - mean luminance below 12 (or above 245)
      - AND standard deviation below 15 (i.e. nothing visible on it)
    A dark Manim illustration has low mean but high std-dev (bright text
    on dark bg), which is valid content — not a failure.
    """
    if not frame_paths:
        return 5, "no frames"
    stats = []
    for p in frame_paths:
        try:
            img = Image.open(p).convert("L").resize((128, 72))
            arr = np.asarray(img, dtype=np.float32)
            stats.append((float(arr.mean()), float(arr.std())))
        except Exception:
            continue
    if not stats:
        return 5, "no brightness reads"

    means = [m for m, _ in stats]
    broken = sum(1 for m, s in stats
                 if (m < 12 and s < 15) or (m > 245 and s < 15))
    bad_frac = broken / len(stats)
    avg_mean = mean(means)

    if bad_frac > 0.25:
        return 3, f"{bad_frac:.0%} of frames truly black/white (avg {avg_mean:.1f})"
    if bad_frac > 0.10:
        return 6, f"{bad_frac:.0%} of frames truly black/white"
    return 9, f"brightness healthy (avg {avg_mean:.1f}, broken {bad_frac:.0%})"


def score_loudness(loud_info):
    """Score based on integrated LUFS measurement."""
    if not loud_info:
        return 6, "could not measure loudness"
    try:
        i = float(loud_info.get("input_i", "0"))
    except Exception:
        return 6, "unparseable loudness"

    if -16 <= i <= -13:
        return 10, f"perfect: input_i = {i:.2f} LUFS"
    if -18 <= i <= -11:
        return 7, f"close to target: input_i = {i:.2f} LUFS (target -14)"
    if i < -25 or i > -5:
        return 3, f"input_i = {i:.2f} LUFS — way off target"
    return 5, f"input_i = {i:.2f} LUFS — needs renormalisation"


def score_duration(duration):
    """Sanity-check the duration."""
    if duration < 60:
        return 4, f"only {duration:.0f}s — too short for a real video"
    if duration > 1800:
        return 5, f"{duration:.0f}s — suspiciously long"
    if 480 <= duration <= 900:
        return 10, f"{duration:.0f}s — ideal range for a YouTube explainer"
    return 8, f"{duration:.0f}s — within acceptable range"


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

WEIGHTS = {
    "visual_variety": 0.25,
    "caption_legibility": 0.20,
    "brightness": 0.15,
    "loudness": 0.25,
    "duration": 0.15,
}


def run(video_path, samples=20, threshold=8):
    video_path = Path(video_path)
    if not video_path.exists():
        print(f"❌ Video not found: {video_path}")
        return False, 0

    print(f"🎬 QC Director — analysing {video_path.name}")

    duration = probe_duration(video_path)
    print(f"    ⏱  Duration: {duration:.1f}s")

    sample_dir = video_path.parent / f"_qc_frames_{video_path.stem}"
    if sample_dir.exists():
        shutil.rmtree(sample_dir)
    frame_paths = sample_frames(video_path, sample_dir, samples=samples)
    print(f"    🖼  Sampled {len(frame_paths)} frames")

    loud = probe_loudness(video_path)

    results = {
        "visual_variety": score_visual_variety(frame_paths),
        "caption_legibility": score_caption_legibility(frame_paths),
        "brightness": score_brightness(frame_paths),
        "loudness": score_loudness(loud),
        "duration": score_duration(duration),
    }

    shutil.rmtree(sample_dir, ignore_errors=True)

    weighted = sum(WEIGHTS[k] * results[k][0] for k in WEIGHTS)
    overall = round(weighted, 1)

    print(f"\n    📊 Scores:")
    for k, (score, note) in results.items():
        flag = "✅" if score >= threshold else "⚠️ "
        print(f"      {flag} {k:20s} {score}/10  — {note}")
    print(f"\n    🎯 Overall: {overall}/10  (threshold {threshold})")

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_DIR / "qc_report.md"
    lines = [
        f"# QC Report: {video_path.name}",
        "",
        f"- Duration: {duration:.1f}s",
        f"- Overall score: **{overall}/10**  (threshold {threshold})",
        "",
        "## Dimensions",
        "",
    ]
    for k, (score, note) in results.items():
        lines.append(f"- **{k}**: {score}/10 — {note}")
    if loud:
        lines.append("")
        lines.append("## Loudness Measurement")
        for k, v in loud.items():
            lines.append(f"- `{k}` = `{v}`")
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n    📝 Report: {report_path}")

    passed = overall >= threshold
    if passed:
        print("    ✅ APPROVED for upload")
    else:
        print("    ❌ REJECTED — review the report and re-run the failing stage")
    return passed, overall


def main():
    p = argparse.ArgumentParser()
    p.add_argument("video", nargs="?", default=str(DEFAULT_VIDEO))
    p.add_argument("--samples", type=int, default=20)
    p.add_argument("--threshold", type=float, default=8.0)
    args = p.parse_args()
    passed, score = run(args.video, samples=args.samples,
                        threshold=args.threshold)
    sys.exit(0 if passed else 2)


if __name__ == "__main__":
    main()
