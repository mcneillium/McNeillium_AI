#!/usr/bin/env python3
"""
McNeillium_AI — Phase 19 Step 1: Pro Transition Library

Wraps FFmpeg's xfade filter (44 transition types) into a small API the
video producer can call instead of always crossfading.

Public API:
  pick_transition(mode, seen=None) -> str
      Random pick from the per-mode profile, biased to avoid repeats.

  xfade(clip_a, clip_b, output, transition="fade", duration=0.4)
      Render clip_a → clip_b with the named xfade transition. Returns
      the output path. Raises subprocess.CalledProcessError on FFmpeg
      failure so the caller can fall back to a hard cut.

  generate_samples(clip_a, clip_b, out_dir, transitions=None)
      Render one short MP4 per transition for visual review.

Per-mode profiles match the Phase 19 brief:
  news      — energetic but professional
  explainer — calm, contemplative
  reaction  — varied, engaging (this is the channel default)
"""

import argparse
import io
import random
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

# Subset of xfade transitions confirmed in FFmpeg 5+. The full list is
# 56 entries in ffmpeg-7 but we keep the conservative 44 from the brief.
ALL_XFADE = [
    "fade", "fadeblack", "fadewhite", "fadegrays",
    "wipeleft", "wiperight", "wipeup", "wipedown",
    "slideleft", "slideright", "slideup", "slidedown",
    "circleopen", "circleclose", "vertopen", "vertclose",
    "horzopen", "horzclose", "dissolve", "pixelize", "radial",
    "hlslice", "hrslice", "vuslice", "vdslice",
    "smoothleft", "smoothright", "smoothup", "smoothdown",
    "diagtl", "diagtr", "diagbl", "diagbr",
    "squeezeh", "squeezev",
    "wipetl", "wipetr", "wipebl", "wipebr",
    "rectcrop", "circlecrop", "distance", "hblur",
]

TRANSITION_PROFILES = {
    # Phase 19b: aesthetic preference is news-anchor static — slides,
    # circles, and pixelize all introduce motion that the channel
    # voice doesn't want. Profiles below are limited to cut / fade /
    # dissolve. The xfade engine has no literal "cut" — for a hard
    # cut, callers should skip xfade entirely; pick_transition will
    # never return "cut" because xfade can't render it. See
    # transition_picker_with_cuts() if you need a cut-aware picker.
    "news":      ["fade", "dissolve"],
    "explainer": ["fade", "dissolve", "fadegrays"],
    "reaction":  ["fade", "dissolve"],
}

# Brief calls for 70% cut, 20% fade, 10% dissolve. xfade can't do a
# "cut" (it's not a transition, just no transition). The helper below
# returns either a fake "cut" sentinel — in which case the caller
# should hard-concat — or one of the transition names above.
CUT_BIASED_DISTRIBUTION = [
    ("cut",      0.70),
    ("fade",     0.20),
    ("dissolve", 0.10),
]


def pick_transition_with_cuts(rng=None):
    """Return one of: 'cut', 'fade', 'dissolve'. 70 / 20 / 10 split.
    Callers handle 'cut' as a hard concat (no xfade)."""
    rng = rng or random
    r = rng.random()
    cum = 0.0
    for name, weight in CUT_BIASED_DISTRIBUTION:
        cum += weight
        if r < cum:
            return name
    return "cut"


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


def _probe_duration(path):
    r = subprocess.run(
        [FFPROBE, "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    try:
        return float(r.stdout.strip() or 0)
    except Exception:
        return 0.0


def pick_transition(mode="reaction", seen=None):
    """Pick a transition from the mode's profile, avoiding recent repeats.

    `seen` is the set of transitions already used in this video. We
    prefer unseen transitions; fall back to the full profile if all
    have been used.
    """
    profile = TRANSITION_PROFILES.get(mode, TRANSITION_PROFILES["reaction"])
    seen = seen or set()
    fresh = [t for t in profile if t not in seen]
    return random.choice(fresh or profile)


def xfade(clip_a, clip_b, output, transition="fade", duration=0.4,
          width=1920, height=1080, fps=30):
    """Render clip_a → clip_b with the named xfade transition.

    The transition starts `duration` seconds before the end of clip_a.
    Output is normalized to (width, height, fps) so the xfade filter
    can stitch clips of different sources cleanly.
    """
    dur_a = _probe_duration(clip_a)
    if dur_a <= duration:
        # clip_a too short for a meaningful xfade — fall back to copy
        offset = max(0.0, dur_a * 0.5)
    else:
        offset = dur_a - duration

    out_path = Path(output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Normalize both inputs to common pixel format / fps to keep xfade
    # happy. Without this, mixed 24fps + 30fps inputs produce stutter.
    filter_complex = (
        f"[0:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps},"
        f"format=yuv420p[a];"
        f"[1:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps},"
        f"format=yuv420p[b];"
        f"[a][b]xfade=transition={transition}:duration={duration}:"
        f"offset={offset:.3f}"
    )

    cmd = [
        FFMPEG, "-y",
        "-i", str(clip_a),
        "-i", str(clip_b),
        "-filter_complex", filter_complex,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-an",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return out_path


def generate_samples(clip_a, clip_b, out_dir, transitions=None):
    """Render one sample MP4 per transition for visual review."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    transitions = transitions or sorted({
        *TRANSITION_PROFILES["news"],
        *TRANSITION_PROFILES["explainer"],
        *TRANSITION_PROFILES["reaction"],
    })
    rendered = []
    failed = []
    for t in transitions:
        out = out_dir / f"sample_{t}.mp4"
        try:
            xfade(clip_a, clip_b, out, transition=t, duration=0.4)
            rendered.append(t)
            print(f"  ✅ {t:14s} → {out.name}")
        except subprocess.CalledProcessError as e:
            failed.append((t, e.stderr.decode("utf-8", "replace")[-200:]))
            print(f"  ❌ {t:14s} — FFmpeg failed")
    return rendered, failed


def main():
    p = argparse.ArgumentParser(description="Phase 19 transition library")
    p.add_argument("--clip-a", default=None,
                   help="Path to first clip (default: first cached Kling)")
    p.add_argument("--clip-b", default=None,
                   help="Path to second clip")
    p.add_argument("--out-dir",
                   default=str(PROJECT_ROOT / "output" / "_transition_test"))
    p.add_argument("--mode", default="all",
                   choices=["all", "news", "explainer", "reaction"])
    args = p.parse_args()

    # Auto-pick clips from the Kling cache if not provided
    if not args.clip_a or not args.clip_b:
        kling_dir = PROJECT_ROOT / "output" / "_kling_cache"
        clips = sorted(kling_dir.glob("*.mp4"))
        if len(clips) < 2:
            print("❌ Need at least 2 cached clips and none provided.")
            sys.exit(2)
        args.clip_a = args.clip_a or str(clips[0])
        args.clip_b = args.clip_b or str(clips[1])

    if args.mode == "all":
        transitions = sorted({
            *TRANSITION_PROFILES["news"],
            *TRANSITION_PROFILES["explainer"],
            *TRANSITION_PROFILES["reaction"],
        })
    else:
        transitions = TRANSITION_PROFILES[args.mode]

    print(f"🎬 Phase 19 transition samples")
    print(f"   clip A: {Path(args.clip_a).name}")
    print(f"   clip B: {Path(args.clip_b).name}")
    print(f"   {len(transitions)} transitions →  {args.out_dir}")
    rendered, failed = generate_samples(args.clip_a, args.clip_b,
                                        args.out_dir, transitions)
    print(f"\n   ✅ {len(rendered)} rendered  ⚠️ {len(failed)} failed")
    if failed:
        for t, err in failed[:3]:
            print(f"     {t}: {err.splitlines()[-1] if err else ''}")
    sys.exit(0 if rendered else 2)


if __name__ == "__main__":
    main()
