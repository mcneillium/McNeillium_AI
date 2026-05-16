#!/usr/bin/env python3
"""
McNeillium_AI — Phase 19 Step 7: Cinematic Color Grading (LUT)

Three channel looks, all FFmpeg-native (no external .cube files needed
— though the API accepts one if the user drops it into assets/luts/):

  cinema_standard  — subtle teal-orange, mild contrast bump
  news_network     — slight blue tint, higher contrast
  documentary      — warmer, more saturated

Public API
──────────
  grade_filter(name) -> str
      Returns an FFmpeg filter chain (string) that applies the named
      look. Insert into your existing -filter_complex.

  grade_video(input_video, output, name="cinema_standard")
      One-shot: re-encode `input_video` with the grade applied.

  apply_lut3d(input_video, output, lut_cube_path)
      Use a real .cube file from assets/luts/. lut3d filter.

CLI:
  python utils/color_grade.py grade input.mp4 output.mp4 --look cinema_standard
  python utils/color_grade.py preview --look cinema_standard
      Renders a 3-second sample of the look on a test gradient.
"""

import argparse
import io
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
LUT_DIR = PROJECT_ROOT / "assets" / "luts"


# Cinematic looks expressed as FFmpeg filter chains. These approximate
# the named looks without requiring an external .cube file. They can
# be composed with the rest of the render's filter graph.
LOOKS = {
    # Subtle teal-orange: lift shadows toward teal, push midtones warm.
    "cinema_standard": (
        "eq=contrast=1.08:saturation=0.92:gamma=1.02,"
        "curves=r='0/0 0.4/0.42 0.7/0.74 1/1':"
        "g='0/0 0.5/0.5 1/0.96':"
        "b='0/0.04 0.4/0.42 0.7/0.66 1/0.92'"
    ),
    # News network: cool blue tint, sharper contrast — feels "broadcast"
    "news_network": (
        "eq=contrast=1.18:saturation=0.85:gamma=0.98,"
        "curves=r='0/0 0.5/0.46 1/0.96':"
        "b='0/0.06 0.5/0.55 1/1'"
    ),
    # Documentary: warm earth tones, slightly saturated greens & yellows
    "documentary": (
        "eq=contrast=1.06:saturation=1.10:gamma=1.04,"
        "curves=r='0/0 0.5/0.55 1/1':"
        "g='0/0 0.5/0.52 1/1':"
        "b='0/0 0.5/0.46 1/0.92'"
    ),
}

DEFAULT_LOOK = "cinema_standard"


def _ffmpeg():
    return shutil.which("ffmpeg") or "ffmpeg"


def grade_filter(name=DEFAULT_LOOK):
    """Return the FFmpeg filter chain for the named look."""
    if name not in LOOKS:
        raise ValueError(f"unknown look {name!r}; "
                         f"choose from {list(LOOKS)}")
    return LOOKS[name]


def _safe_encode_args():
    """Phase 19b: shared Windows-compatible encode args. Pair with
    a filter chain that ends in `,format=yuv420p`."""
    return [
        "-c:v", "libx264",
        "-profile:v", "main",
        "-pix_fmt", "yuv420p",
        "-colorspace", "bt709",
        "-color_primaries", "bt709",
        "-color_trc", "bt709",
        "-preset", "medium",
        "-crf", "20",
        "-c:a", "copy",
        "-movflags", "+faststart",
    ]


def grade_video(input_video, output, name=DEFAULT_LOOK):
    """One-shot: re-encode input with the named grade applied."""
    chain = grade_filter(name) + ",format=yuv420p"
    cmd = [
        _ffmpeg(), "-y",
        "-i", str(input_video),
        "-vf", chain,
        *_safe_encode_args(),
        str(output),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return Path(output)


def apply_lut3d(input_video, output, lut_cube_path):
    """Apply a .cube LUT via FFmpeg's lut3d filter."""
    lut = Path(lut_cube_path)
    if not lut.exists():
        raise FileNotFoundError(lut)
    # Escape colon for Windows-style path inside the filter argument
    lut_str = str(lut).replace("\\", "/").replace(":", r"\:")
    cmd = [
        _ffmpeg(), "-y",
        "-i", str(input_video),
        "-vf", f"lut3d=file='{lut_str}',format=yuv420p",
        *_safe_encode_args(),
        str(output),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return Path(output)


def preview(name=DEFAULT_LOOK, out_path=None, sample_clip=None,
            w=1280, h=720, fps=30):
    """Render a 3-second sample of the look. Uses a cached Kling clip
    when available so the preview shows real footage; falls back to a
    test pattern otherwise."""
    out_path = out_path or (PROJECT_ROOT / "output" / "_grade_test"
                            / f"preview_{name}.mp4")
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    chain = grade_filter(name)

    # Pick a sample clip from the Kling cache
    if sample_clip is None:
        cache = PROJECT_ROOT / "output" / "_kling_cache"
        clips = sorted(cache.glob("*.mp4"))
        sample_clip = clips[0] if clips else None

    if sample_clip and Path(sample_clip).exists():
        cmd = [
            _ffmpeg(), "-y",
            "-i", str(sample_clip),
            "-t", "3",
            "-vf", f"scale={w}:{h},format=yuv420p,{chain}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
            "-an",
            str(out_path),
        ]
    else:
        # Fallback: solid mid-gray test pattern (works without external assets)
        cmd = [
            _ffmpeg(), "-y",
            "-f", "lavfi",
            "-i", f"testsrc2=size={w}x{h}:rate={fps}:duration=3",
            "-vf", f"format=yuv420p,{chain}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
            str(out_path),
        ]
    subprocess.run(cmd, check=True, capture_output=True)
    return Path(out_path)


def main():
    p = argparse.ArgumentParser(description="Phase 19 cinematic color grade")
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("grade", help="Apply look to a video file")
    g.add_argument("input")
    g.add_argument("output")
    g.add_argument("--look", default=DEFAULT_LOOK, choices=list(LOOKS))

    pv = sub.add_parser("preview", help="Render a sample of a look")
    pv.add_argument("--look", default=DEFAULT_LOOK, choices=list(LOOKS))
    pv.add_argument("--out", default=None)

    al = sub.add_parser("lut3d", help="Apply a .cube LUT file")
    al.add_argument("input")
    al.add_argument("output")
    al.add_argument("--cube", required=True)

    args = p.parse_args()

    if args.cmd == "grade":
        out = grade_video(args.input, args.output, name=args.look)
        print(f"✅ {args.look} → {out}  ({out.stat().st_size / (1024*1024):.1f} MB)")
    elif args.cmd == "preview":
        out = preview(name=args.look, out_path=args.out)
        print(f"✅ preview → {out}")
    elif args.cmd == "lut3d":
        out = apply_lut3d(args.input, args.output, args.cube)
        print(f"✅ lut3d → {out}")


if __name__ == "__main__":
    main()
