#!/usr/bin/env python3
"""
McNeillium_AI — Phase 19 post-processing pass

Apply Phase 19 visual upgrades to a rendered video without touching
the assembly pipeline (which is risky to refactor):

  1. Cinematic color grade (cinema_standard look)
  2. Optional: lower-third overlay at a given timestamp
  3. Optional: title card at section starts (deferred)

Used by Step 10 to produce _v19_*_full_upgrade.mp4 from a stock render.
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
sys.path.insert(0, str(PROJECT_ROOT))

from utils.color_grade import grade_filter, DEFAULT_LOOK
from utils.motion_graphics import lower_third, composite


def _ffmpeg():
    return shutil.which("ffmpeg") or "ffmpeg"


def apply_grade_only(input_video, output, look=DEFAULT_LOOK):
    """Color grade an input video, preserving audio."""
    chain = grade_filter(look)
    cmd = [
        _ffmpeg(), "-y",
        "-i", str(input_video),
        "-vf", chain,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "copy",
        str(output),
    ]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        sys.stderr.write(r.stderr.decode("utf-8", "replace")[-2000:])
        raise subprocess.CalledProcessError(r.returncode, cmd)
    return Path(output)


def apply_grade_and_lower_third(input_video, output, *,
                                 name, sublabel, t_start,
                                 look=DEFAULT_LOOK,
                                 lt_duration=4.0,
                                 lt_position=(80, 940)):
    """Apply grade + render and overlay one lower-third at t_start."""
    tmp_dir = Path(output).parent / "_phase19_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    # 1. Grade pass
    graded = tmp_dir / "01_graded.mp4"
    apply_grade_only(input_video, graded, look=look)

    # 2. Render the lower-third overlay
    lt_path = tmp_dir / "02_lt.mov"
    lower_third(name, sublabel, lt_path, duration=lt_duration)

    # 3. Composite
    composite(graded, lt_path, output,
              x=lt_position[0], y=lt_position[1] - 940,
              t_start=t_start)
    return Path(output)


def main():
    p = argparse.ArgumentParser(description="Phase 19 post-processing")
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("--look", default=DEFAULT_LOOK,
                   choices=["cinema_standard", "news_network", "documentary"])
    p.add_argument("--lower-third-name", default=None)
    p.add_argument("--lower-third-sub", default=None)
    p.add_argument("--lower-third-t", type=float, default=None)
    args = p.parse_args()

    inp = Path(args.input)
    if not inp.exists():
        print(f"❌ input not found: {inp}")
        sys.exit(2)
    print(f"🎨 Phase 19 post-process — {inp.name}")
    print(f"   look: {args.look}")

    if args.lower_third_name and args.lower_third_t is not None:
        print(f"   lower-third: {args.lower_third_name!r} at "
              f"{args.lower_third_t}s")
        out = apply_grade_and_lower_third(
            inp, args.output,
            name=args.lower_third_name,
            sublabel=args.lower_third_sub or "",
            t_start=args.lower_third_t,
            look=args.look,
        )
    else:
        out = apply_grade_only(inp, args.output, look=args.look)

    sz = out.stat().st_size / (1024 * 1024)
    print(f"   ✅ {out}  ({sz:.1f} MB)")


if __name__ == "__main__":
    main()
