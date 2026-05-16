#!/usr/bin/env python3
"""
McNeillium_AI — Phase 19 Step 8: Speed Ramping on Punch Moments

Detect "punch" moments in a script (revelations, big-number reveals,
quote callouts) and apply video-only speed ramps:

  pre-punch:  1.5x quick zoom-in (1s window before)
  punch:      0.7x slow-mo (1s window covering the line)
  resume:     1.0x normal

Audio (narration) is NOT touched — speeding up Brian's voice would
chip the words; slowing it down stretches them. We ramp video only,
which means the visual emphasis hits while the narration stays clean.

Punch detection heuristics (no LLM):
  - "$NN billion" / "$NN B" / "NN%" / "Nx more"
  - Sentence ending in "!"
  - Quoted text > 20 chars ("`...`" or "...")
  - Phrases like "the wildest part is", "here's the thing", "watch this"

Public API:
  detect_punches(script_or_path) -> [{"section_id", "char_offset", "trigger"}]
  ramp_segment(input_video, output, *, pre_speed=1.5, punch_speed=0.7,
               pre_window=1.0, punch_window=1.0)

CLI:
  python utils/speed_ramp.py detect              # dump punches in latest.json
  python utils/speed_ramp.py demo --input X.mp4  # render a sample ramp
"""

import argparse
import io
import json
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

# ───────────────────── punch detection ────────────────────────────

BIG_NUMBER_RE = re.compile(
    r"\$\s?\d+(?:\.\d+)?\s*(?:billion|million|trillion|B|M|T)\b|"
    r"\b\d+(?:\.\d+)?\s*(?:percent|%)\b|"
    r"\b\d+(?:\.\d+)?\s*x\b",
    re.I,
)
HOOK_PHRASES_RE = re.compile(
    r"\b(here'?s the wildest|here'?s the thing|"
    r"watch this|read that again|but wait|"
    r"the catch is|here'?s why|here'?s the kicker|"
    r"and that'?s when)\b",
    re.I,
)
QUOTE_RE = re.compile(r"[\"“]([^\"“”]{20,150})[\"”]")


def detect_punches(script_or_path):
    """Walk script sections; return punch moments with their trigger."""
    if isinstance(script_or_path, (str, Path)):
        script = json.loads(Path(script_or_path).read_text(encoding="utf-8"))
    else:
        script = script_or_path

    punches = []
    for sec in script.get("sections", []):
        sid = sec.get("id", "")
        narr = sec.get("narration", "")
        for m in BIG_NUMBER_RE.finditer(narr):
            punches.append({"section_id": sid, "char_offset": m.start(),
                            "trigger": "big_number", "match": m.group()})
        for m in HOOK_PHRASES_RE.finditer(narr):
            punches.append({"section_id": sid, "char_offset": m.start(),
                            "trigger": "hook_phrase", "match": m.group()})
        for m in QUOTE_RE.finditer(narr):
            punches.append({"section_id": sid, "char_offset": m.start(),
                            "trigger": "quote", "match": m.group(1)[:60]})
        for m in re.finditer(r"[A-Za-z][!]+", narr):
            punches.append({"section_id": sid, "char_offset": m.start(),
                            "trigger": "exclamation", "match": m.group()})
    # Deduplicate by (section, offset)
    seen = set()
    out = []
    for p in punches:
        k = (p["section_id"], p["char_offset"])
        if k not in seen:
            seen.add(k)
            out.append(p)
    return out


# ───────────────────── speed ramp render ──────────────────────────

def _ffmpeg():
    return shutil.which("ffmpeg") or "ffmpeg"


def ramp_segment(input_video, output, *,
                 pre_speed=1.5, punch_speed=0.7,
                 pre_window=1.0, punch_window=1.0):
    """Render a 3-window speed ramp on a short clip:
        [0..pre_window)     at pre_speed (1.5x default)
        [pre_window..pre_window+punch_window) at punch_speed (0.7x)
        [punch_window+pre_window..end)      at 1x

    Note: this is video-only (suitable for inserting as a hero beat).
    """
    # Clip total source duration in slow-down/up land:
    #   first section: source [0, pre_window/pre_speed) → output pre_window
    #   second:        source [pre_window/pre_speed, pre_window/pre_speed
    #                          + punch_window/punch_speed) → output punch_window
    #   third:         source [pre_window/pre_speed + punch_window/punch_speed, end)
    #                          → output at 1x

    src_pre = pre_window / pre_speed
    src_punch = punch_window / punch_speed
    src_resume_start = src_pre + src_punch

    # We assume the input clip is long enough; if not, the third section
    # just yields a shorter ramp.
    fc = (
        f"[0:v]trim=0:{src_pre},setpts=PTS/{pre_speed},setpts=PTS-STARTPTS[v1];"
        f"[0:v]trim={src_pre}:{src_resume_start},"
        f"setpts=PTS/{punch_speed},setpts=PTS-STARTPTS[v2];"
        f"[0:v]trim={src_resume_start},setpts=PTS-STARTPTS[v3];"
        f"[v1][v2][v3]concat=n=3:v=1:a=0[out]"
    )

    cmd = [
        _ffmpeg(), "-y",
        "-i", str(input_video),
        "-filter_complex", fc,
        "-map", "[out]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        str(output),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return Path(output)


def main():
    p = argparse.ArgumentParser(description="Phase 19 speed ramp")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("detect", help="Print punches in a script")
    d.add_argument("--script", default="output/scripts/latest.json")
    d.add_argument("--report",
                   default="knowledge_base/reviews/punches.json")

    dm = sub.add_parser("demo", help="Render a sample speed ramp")
    dm.add_argument("--input", required=False)
    dm.add_argument("--output", default="output/_ramp_test/sample.mp4")

    args = p.parse_args()

    if args.cmd == "detect":
        punches = detect_punches(args.script)
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(json.dumps(punches, indent=2),
                                     encoding="utf-8")
        print(f"💥 {len(punches)} punch moments in "
              f"{Path(args.script).name}:")
        for p in punches[:30]:
            print(f"   [{p['trigger']:12s}] "
                  f"{p['section_id']:14s}  '{p['match'][:60]}'")
        if len(punches) > 30:
            print(f"   ...+{len(punches)-30} more")
        print(f"   📝 → {args.report}")
    else:
        if not args.input:
            cache = PROJECT_ROOT / "output" / "_kling_cache"
            clips = sorted(cache.glob("*.mp4"))
            if not clips:
                print("❌ no input clip provided and no cached Kling clips found")
                sys.exit(2)
            args.input = str(clips[0])
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        out = ramp_segment(args.input, args.output)
        sz = out.stat().st_size / 1024
        print(f"✅ ramp → {out}  ({sz:.0f} KB)")


if __name__ == "__main__":
    main()
