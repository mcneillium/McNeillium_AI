#!/usr/bin/env python3
"""
McNeillium_AI — Agent 30: Style-Transfer Director

Applies a consistent visual grade across every clip so stock footage, AI
images, illustrations, and stat cards all feel like ONE video — invisible
cuts, unified palette.

The grade is a teal-orange cinema curve with light film grain and a
subtle vignette. It is implemented as a reusable FFmpeg filter chain
(`style_grade_filter`) plus a per-clip applicator (`apply_grade`) that
re-encodes a clip in place.

Public helpers (callable from generate_video.py):
  - style_grade_filter()  → returns the filter string to bake into vf
  - apply_grade(input_path, output_path) → one-shot re-encode

Defaults err on the subtle side. Stronger looks are gated by --intensity.
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


def _find_ffmpeg():
    r = shutil.which("ffmpeg")
    if r:
        return r
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return "ffmpeg"


FFMPEG = _find_ffmpeg()


def style_grade_filter(intensity="default", with_grain=True,
                        with_vignette=True):
    """
    Return an FFmpeg filter chain string implementing the McNeillium grade.

    `intensity` ∈ {"subtle", "default", "strong"}
    """
    if intensity == "subtle":
        eq = "eq=brightness=-0.03:contrast=1.06:saturation=0.92"
        curves = "curves=m='0/0 0.35/0.30 0.7/0.74 1/1':r='0/0 0.5/0.52 1/1':b='0/0 0.5/0.49 1/1'"
        grain_strength = "noise=alls=4:allf=t+u" if with_grain else ""
    elif intensity == "strong":
        eq = "eq=brightness=-0.08:contrast=1.18:saturation=0.78"
        curves = "curves=m='0/0 0.28/0.22 0.72/0.78 1/1':r='0/0 0.5/0.56 1/1':b='0/0 0.5/0.45 1/1'"
        grain_strength = "noise=alls=10:allf=t+u" if with_grain else ""
    else:  # default
        eq = "eq=brightness=-0.06:contrast=1.10:saturation=0.85"
        curves = "curves=m='0/0 0.30/0.25 0.70/0.75 1/1':r='0/0 0.5/0.54 1/1':b='0/0 0.5/0.47 1/1'"
        grain_strength = "noise=alls=6:allf=t+u" if with_grain else ""

    parts = [eq, curves]
    if grain_strength:
        parts.append(grain_strength)
    if with_vignette:
        parts.append("vignette=PI/5")

    return ",".join(parts)


def apply_grade(input_path, output_path, intensity="default",
                with_grain=True, with_vignette=True):
    """Re-encode an MP4 with the style grade applied."""
    vf = style_grade_filter(intensity, with_grain, with_vignette)
    cmd = [
        FFMPEG, "-y", "-i", str(input_path),
        "-vf", vf,
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        "-c:a", "copy", "-pix_fmt", "yuv420p",
        str(output_path),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"⚠️  Grade apply failed: {r.stderr[-300:]}")
        return False
    return True


def main():
    p = argparse.ArgumentParser()
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("--intensity", choices=["subtle", "default", "strong"],
                   default="default")
    p.add_argument("--no-grain", action="store_true")
    p.add_argument("--no-vignette", action="store_true")
    args = p.parse_args()
    ok = apply_grade(args.input, args.output, args.intensity,
                     with_grain=not args.no_grain,
                     with_vignette=not args.no_vignette)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
