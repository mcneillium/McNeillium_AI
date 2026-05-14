#!/usr/bin/env python3
"""
McNeillium_AI — Agent 32: Music Composer

Replaces the single background track with mood-matched scoring per section.
A small library of ambient tracks is kept in assets/music/, named by mood:

  dramatic_build.mp3   — hook / cold-open
  ambient_calm.mp3     — main points / explanation
  energetic_tech.mp3   — demo / process
  warm_outro.mp3       — outro / summary

The Composer picks one track per section based on section id, builds an
FFmpeg filter chain that concatenates them with 1-second crossfades, and
writes the assembled bed to output/audio/music_bed.mp3 (matching the
audio's total duration).

Missing tracks fall back gracefully: any mood without a file in
assets/music/ uses the global fallback (ambient_tech.mp3), and if THAT
is missing the section gets silence.
"""

import argparse
import io
import json
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
MUSIC_DIR = PROJECT_ROOT / "assets" / "music"
SCRIPT_PATH = PROJECT_ROOT / "output" / "scripts" / "latest.json"
AUDIO_PATH = PROJECT_ROOT / "output" / "audio" / "latest.mp3"
BED_OUT = PROJECT_ROOT / "output" / "audio" / "music_bed.mp3"
FALLBACK = "ambient_tech.mp3"

SECTION_MOOD = {
    "hook": "dramatic_build.mp3",
    "intro": "ambient_calm.mp3",
    "main_point_1": "ambient_calm.mp3",
    "main_point_2": "ambient_calm.mp3",
    "main_point_3": "ambient_calm.mp3",
    "demo": "energetic_tech.mp3",
    "summary": "warm_outro.mp3",
    "outro": "warm_outro.mp3",
}


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
FFPROBE = shutil.which("ffprobe") or "ffprobe"


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


def pick_track(section_id):
    """Return the Path of the track to use for this section."""
    name = SECTION_MOOD.get(section_id, FALLBACK)
    p = MUSIC_DIR / name
    if p.exists():
        return p
    p_fallback = MUSIC_DIR / FALLBACK
    if p_fallback.exists():
        return p_fallback
    return None


def plan_bed(script_path, audio_path):
    """Build the per-section list of (track_path, target_duration_s)."""
    with open(script_path, encoding="utf-8") as f:
        script = json.load(f)

    audio_dur = probe_duration(audio_path)
    if audio_dur <= 0:
        return [], 0

    sections = script.get("sections", [])
    char_counts = [len(s.get("narration", "")) for s in sections]
    total = sum(char_counts) or 1

    # Match the duration accounting used by generate_video (intro/outro 3.5s each)
    INTRO_DUR = 3.5
    OUTRO_DUR = 3.5
    content_dur = max(1.0, audio_dur - INTRO_DUR - OUTRO_DUR)
    durs = [(c / total) * content_dur for c in char_counts]

    plan = []
    for sec, d in zip(sections, durs):
        sid = sec.get("id", "intro")
        track = pick_track(sid)
        plan.append({
            "section_id": sid,
            "track": str(track) if track else None,
            "duration": d,
        })
    return plan, audio_dur


def assemble_bed(plan, audio_dur, out_path):
    """Concatenate mood tracks with 1-second crossfades into a single bed."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    available = [p for p in plan if p["track"] and Path(p["track"]).exists()]
    if not available:
        print("  ⚠️  No music tracks available — skipping bed.")
        return False

    # Inputs
    cmd = [FFMPEG, "-y"]
    for p in available:
        cmd.extend(["-i", p["track"]])

    # Build filter: for each input, atrim to target duration then crossfade-chain
    filter_parts = []
    for i, p in enumerate(available):
        dur = max(2.0, p["duration"])
        filter_parts.append(
            f"[{i}:a]atrim=0:{dur},asetpts=PTS-STARTPTS,"
            f"afade=t=in:st=0:d=0.6,"
            f"afade=t=out:st={max(0.0, dur - 0.8):.2f}:d=0.8[a{i}]"
        )

    # Concatenate with acrossfade
    if len(available) == 1:
        filter_parts.append("[a0]volume=0.18[bed]")
    else:
        chain = "[a0]"
        for i in range(1, len(available)):
            label = f"[m{i}]" if i < len(available) - 1 else "[bed_raw]"
            filter_parts.append(
                f"{chain}[a{i}]acrossfade=d=1:c1=tri:c2=tri{label}"
            )
            chain = label
        filter_parts.append(f"{chain}volume=0.18[bed]")
        # NB: the last chain entry already feeds [bed_raw]; we replace.
        # Simpler: re-emit the volume on bed_raw.
        # Rebuild cleanly:
        filter_parts = filter_parts[:len(available)]
        chain = "[a0]"
        for i in range(1, len(available)):
            out = f"[m{i}]"
            if i == len(available) - 1:
                out = "[bed_raw]"
            filter_parts.append(
                f"{chain}[a{i}]acrossfade=d=1:c1=tri:c2=tri{out}"
            )
            chain = out
        filter_parts.append(f"{chain}volume=0.18[bed]")

    cmd.extend([
        "-filter_complex", ";".join(filter_parts),
        "-map", "[bed]",
        "-t", str(audio_dur),
        "-c:a", "libmp3lame", "-q:a", "5",
        str(out_path),
    ])

    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"  ⚠️  Music bed assembly failed: {r.stderr[-300:]}")
        return False
    print(f"  💾 Bed → {out_path}")
    return True


def run(script_path, audio_path, out_path):
    plan, audio_dur = plan_bed(script_path, audio_path)
    if not plan:
        print("❌ No plan built")
        return False
    print(f"🎵 Music Composer — {len(plan)} sections, "
          f"audio {audio_dur:.1f}s")
    for p in plan:
        track_name = Path(p["track"]).name if p["track"] else "—"
        print(f"  - {p['section_id']:16s} {p['duration']:5.1f}s  {track_name}")
    return assemble_bed(plan, audio_dur, out_path)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--script", default=str(SCRIPT_PATH))
    p.add_argument("--audio", default=str(AUDIO_PATH))
    p.add_argument("--out", default=str(BED_OUT))
    args = p.parse_args()
    ok = run(args.script, args.audio, args.out)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
