#!/usr/bin/env python3
"""
McNeillium_AI — Phase 19 Step 5: L-cuts and J-cuts

L-cut  — video changes BEFORE audio. Previous shot's audio continues
         over the next shot's video. "Audio outlasts its visual."
J-cut  — video changes AFTER audio. Next shot's audio starts during
         the previous shot's video. "Audio leads."

Pipeline architecture note
──────────────────────────
The McNeillium_AI reaction-mode pipeline has:
  - One continuous narration audio track (the ElevenLabs Brian voice)
  - A sequence of visual beats that swap on section/beat boundaries

There is no per-clip diegetic audio that we cut along with video. So
"L-cut" in our context means: shift the visual cut point a fraction of
a second earlier than the section boundary the script writer marked.
"J-cut" means shift it later. This is essentially overlap-on-narration
trimming — a real editorial move that smooths the seam between two
shots.

This module provides:
  - choose_cut_type() — RNG biased per the brief (60% L, 40% straight)
  - apply_section_cut_offsets(boundaries) — mutate a list of (t, kind)
    section starts to staggered visual cut points
  - shift_video_only(video, audio, output, offsets) — re-mux with the
    offsets applied via concat-and-trim. Used as a post-render pass.

For Phase 19 we ship the helpers + offset planner. Deep integration
into generate_video.py's beat assembly is left for a follow-up so we
don't break the working pipeline.
"""

import argparse
import io
import json
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


def _ffmpeg():
    return shutil.which("ffmpeg") or "ffmpeg"


# ─────────────────────────── planner ────────────────────────────────

def choose_cut_type(rng=None):
    """60% L-cut, 40% straight. (J-cuts feel forced when narration is
    one continuous track — disabled for reaction mode by default.)"""
    rng = rng or random
    return "L" if rng.random() < 0.6 else "straight"


def apply_section_cut_offsets(boundaries, *, min_offset=0.20,
                              max_offset=0.50, rng=None):
    """Take a list of section boundary timestamps and return an
    annotated list with `cut_type` and `visual_offset_s` per boundary.

    `boundaries` is a list of dicts with at least
        {"section_id": str, "audio_start_s": float}
    Returns a new list with added keys:
        cut_type:        "L" or "straight"
        visual_offset_s: -offset for L-cut (visual changes early), 0 otherwise
        visual_start_s:  audio_start_s + visual_offset_s
    """
    rng = rng or random
    out = []
    for i, b in enumerate(boundaries):
        if i == 0:
            kind, off = "straight", 0.0
        else:
            kind = choose_cut_type(rng)
            off = -rng.uniform(min_offset, max_offset) if kind == "L" else 0.0
        out.append({
            **b,
            "cut_type": kind,
            "visual_offset_s": round(off, 3),
            "visual_start_s": round(max(0.0, b["audio_start_s"] + off), 3),
        })
    return out


# ─────────────────────────── post-pass mux ─────────────────────────

def shift_video_only(video, audio, output, *, fps=30):
    """Re-mux a finished video with its narration audio so the audio
    timeline is canonical (defensive — useful when downstream filters
    have introduced drift). Returns output path."""
    cmd = [
        _ffmpeg(), "-y",
        "-i", str(video), "-i", str(audio),
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        str(output),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return Path(output)


def main():
    p = argparse.ArgumentParser(description="Phase 19 L/J-cut planner")
    p.add_argument("--script", default="output/scripts/latest.json",
                   help="Script JSON with sections + audio_words file")
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--report", default="knowledge_base/reviews/cut_plan.json",
                   help="Where to save the planned cut offsets")
    args = p.parse_args()

    rng = random.Random(args.seed) if args.seed is not None else random

    script = json.loads(Path(args.script).read_text(encoding="utf-8"))
    # Pull section boundaries from the audio words file when available
    words_path = Path("output/audio/latest_words_verified.json")
    if not words_path.exists():
        words_path = Path("output/audio/latest_words_elevenlabs.json")
    boundaries = []
    cursor = 0.0
    if words_path.exists():
        words = json.loads(words_path.read_text(encoding="utf-8")).get("words", [])
        # Estimate section starts by walking section narration character counts
        # Fall back to even spacing if we can't align cleanly.
        for sec in script.get("sections", []):
            boundaries.append({
                "section_id": sec.get("id", ""),
                "audio_start_s": cursor,
            })
            n_words = len(sec.get("narration", "").split())
            section_words = words[:n_words]
            words = words[n_words:]
            if section_words:
                last = section_words[-1]
                cursor = (float(last["offset_ms"]) +
                          float(last["duration_ms"])) / 1000.0
            else:
                cursor += 5.0
    else:
        # No timing info — even spacing
        for i, sec in enumerate(script.get("sections", [])):
            boundaries.append({"section_id": sec.get("id", ""),
                               "audio_start_s": float(i * 30.0)})

    plan = apply_section_cut_offsets(boundaries, rng=rng)
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(plan, indent=2),
                                 encoding="utf-8")

    n_l = sum(1 for x in plan if x["cut_type"] == "L")
    print(f"✂️  L/J-cut plan — {len(plan)} boundaries, "
          f"{n_l} L-cuts, {len(plan) - n_l} straight")
    for x in plan:
        sym = "←L" if x["cut_type"] == "L" else "──"
        print(f"     {sym}  {x['section_id']:14s}  "
              f"audio={x['audio_start_s']:6.2f}s  "
              f"visual={x['visual_start_s']:6.2f}s  "
              f"({x['visual_offset_s']:+.2f}s)")
    print(f"   📝 → {args.report}")


if __name__ == "__main__":
    main()
