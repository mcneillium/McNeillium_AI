#!/usr/bin/env python3
"""
McNeillium_AI — Phase 19 Step 9: Picture-in-Picture for Comparisons

When the script compares two things ("Anthropic vs OpenAI", "before/after"),
render a side-by-side or 60/40 split using FFmpeg's overlay filter.

Public API
──────────
  detect_comparisons(script_or_path) -> [{"section_id", "left", "right"}]
  side_by_side(clip_left, clip_right, output, layout="60/40") -> Path
      layout: "50/50" | "60/40" | "40/60"

CLI:
  python utils/picture_in_picture.py detect
  python utils/picture_in_picture.py compose A.mp4 B.mp4 out.mp4 --layout 60/40
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

# Patterns the Visual Director should treat as comparison cues
COMPARISON_PATTERNS = [
    re.compile(r"\b([A-Z][A-Za-z0-9]+)\s+vs\.?\s+([A-Z][A-Za-z0-9]+)\b"),
    re.compile(r"\b([A-Z][A-Za-z0-9]+)\s+versus\s+([A-Z][A-Za-z0-9]+)\b"),
    re.compile(r"\bbefore\b.{1,30}\bafter\b", re.I),
    re.compile(r"\bon one (side|hand)\b.{1,80}\bon the other\b", re.I),
]


def detect_comparisons(script_or_path):
    if isinstance(script_or_path, (str, Path)):
        script = json.loads(Path(script_or_path).read_text(encoding="utf-8"))
    else:
        script = script_or_path
    out = []
    for sec in script.get("sections", []):
        narr = sec.get("narration", "")
        for pat in COMPARISON_PATTERNS:
            for m in pat.finditer(narr):
                groups = m.groups() if m.groups() else (None, None)
                left = groups[0] if len(groups) >= 1 else None
                right = groups[1] if len(groups) >= 2 else None
                out.append({
                    "section_id": sec.get("id", ""),
                    "char_offset": m.start(),
                    "match": m.group()[:80],
                    "left": left,
                    "right": right,
                })
    return out


def _ffmpeg():
    return shutil.which("ffmpeg") or "ffmpeg"


def _split_widths(layout, total_w=1920):
    if layout == "50/50":
        return total_w // 2, total_w // 2
    if layout == "60/40":
        return int(total_w * 0.6), total_w - int(total_w * 0.6)
    if layout == "40/60":
        return int(total_w * 0.4), total_w - int(total_w * 0.4)
    raise ValueError(f"unknown layout {layout!r}")


def side_by_side(clip_left, clip_right, output, *, layout="60/40",
                 w=1920, h=1080, fps=30):
    """Render two clips side-by-side. Audio is taken from the left clip."""
    lw, rw = _split_widths(layout, total_w=w)
    fc = (
        f"[0:v]scale={lw}:{h}:force_original_aspect_ratio=increase,"
        f"crop={lw}:{h},setsar=1,fps={fps}[L];"
        f"[1:v]scale={rw}:{h}:force_original_aspect_ratio=increase,"
        f"crop={rw}:{h},setsar=1,fps={fps}[R];"
        f"[L][R]hstack=inputs=2[v]"
    )
    cmd = [
        _ffmpeg(), "-y",
        "-i", str(clip_left), "-i", str(clip_right),
        "-filter_complex", fc,
        "-map", "[v]", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        str(output),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return Path(output)


def main():
    p = argparse.ArgumentParser(description="Phase 19 picture-in-picture")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("detect", help="Print comparison cues in a script")
    d.add_argument("--script", default="output/scripts/latest.json")
    d.add_argument("--report",
                   default="knowledge_base/reviews/comparisons.json")

    c = sub.add_parser("compose", help="Render a side-by-side")
    c.add_argument("left")
    c.add_argument("right")
    c.add_argument("output")
    c.add_argument("--layout", default="60/40",
                   choices=["50/50", "60/40", "40/60"])

    args = p.parse_args()

    if args.cmd == "detect":
        cmps = detect_comparisons(args.script)
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(json.dumps(cmps, indent=2),
                                     encoding="utf-8")
        print(f"⚖️  {len(cmps)} comparison cue(s) in "
              f"{Path(args.script).name}:")
        for c in cmps:
            l = c.get("left") or "?"
            r = c.get("right") or "?"
            print(f"   {c['section_id']:14s}  {l} vs {r}  ('{c['match'][:60]}')")
        print(f"   📝 → {args.report}")
    else:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        out = side_by_side(args.left, args.right, args.output,
                           layout=args.layout)
        sz = out.stat().st_size / (1024 * 1024)
        print(f"✅ {args.layout} → {out}  ({sz:.1f} MB)")


if __name__ == "__main__":
    main()
