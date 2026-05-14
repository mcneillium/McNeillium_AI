#!/usr/bin/env python3
"""
McNeillium AI — SFX Synthesizer (Phase 14)

Generates a 10-effect baseline SFX library using FFmpeg signal sources.
No network calls — runs offline, deterministic, and avoids the
flakiness of live-fetching from Pixabay every time.

Outputs to assets/sfx/. If a file already exists, it's left alone
(idempotent — call this once, then drop in higher-quality replacements
manually if you find better ones online).

Effects produced:
  whoosh_transition.mp3   — section transitions
  ding_reveal.mp3         — stat / number reveals
  alert_negative.mp3      — warnings / problems
  click_emphasis.mp3      — key-point click
  typewriter.mp3          — quote reveals (short ticks)
  swoosh_in.mp3           — short-form intro swoosh
  swoosh_out.mp3          — outro fade
  glitch_short.mp3        — "but wait" moments
  bell_positive.mp3       — good news / wins
  dramatic_riser.mp3      — pre-reveal builds
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
SFX_DIR = PROJECT_ROOT / "assets" / "sfx"
LIBRARY_YAML = SFX_DIR / "library.yaml"


def _ffmpeg():
    r = shutil.which("ffmpeg")
    if r:
        return r
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return "ffmpeg"


FFMPEG = _ffmpeg()


def _run_ffmpeg(filter_complex, duration, output_path):
    """Run a one-shot synth-to-MP3 ffmpeg pipeline."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-t", str(duration),
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-c:a", "libmp3lame", "-q:a", "4",
        str(output_path),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode == 0


def synth_whoosh(target, duration=0.8):
    # Filtered noise with rising frequency sweep, mono → stereo
    fc = (
        "anoisesrc=color=brown:duration=" + str(duration) + ":sample_rate=44100,"
        f"bandpass=f=1000:width_type=h:width=2000,"
        f"volume=2.5,"
        f"afade=t=in:st=0:d=0.05,"
        f"afade=t=out:st={duration-0.15:.2f}:d=0.15,"
        "asetnsamples=2048,"
        "pan=stereo|c0=c0|c1=c0[out]"
    )
    return _run_ffmpeg(fc, duration, target)


def synth_ding(target, duration=0.8):
    # Pure sine + harmonic + bell-curve envelope
    fc = (
        f"sine=frequency=1760:duration={duration}:sample_rate=44100,"
        f"volume=0.4,"
        f"afade=t=in:st=0:d=0.005,"
        f"afade=t=out:st=0.05:d={duration-0.05:.2f},"
        "pan=stereo|c0=c0|c1=c0[out]"
    )
    return _run_ffmpeg(fc, duration, target)


def synth_alert(target, duration=0.5):
    fc = (
        f"sine=frequency=880:duration={duration}:sample_rate=44100,"
        f"volume=0.5,"
        f"tremolo=f=10:d=0.7,"
        f"afade=t=in:st=0:d=0.02,"
        f"afade=t=out:st={duration-0.1:.2f}:d=0.1,"
        "pan=stereo|c0=c0|c1=c0[out]"
    )
    return _run_ffmpeg(fc, duration, target)


def synth_click(target, duration=0.12):
    fc = (
        f"sine=frequency=3000:duration={duration}:sample_rate=44100,"
        f"volume=0.45,"
        f"afade=t=in:st=0:d=0.003,"
        f"afade=t=out:st=0.01:d={duration-0.01:.3f},"
        "pan=stereo|c0=c0|c1=c0[out]"
    )
    return _run_ffmpeg(fc, duration, target)


def synth_typewriter(target, duration=0.3):
    # Several short clicks at typewriter rate
    fc = (
        f"sine=frequency=2200:duration={duration}:sample_rate=44100,"
        f"volume=0.35,"
        f"tremolo=f=25:d=0.95,"
        f"afade=t=in:st=0:d=0.01,"
        f"afade=t=out:st=0.05:d={duration-0.05:.2f},"
        "pan=stereo|c0=c0|c1=c0[out]"
    )
    return _run_ffmpeg(fc, duration, target)


def synth_swoosh_in(target, duration=0.6):
    fc = (
        "anoisesrc=color=pink:duration=" + str(duration) + ":sample_rate=44100,"
        f"highpass=f=400,"
        f"volume=2.0,"
        f"afade=t=in:st=0:d=0.05,"
        f"afade=t=out:st={duration-0.1:.2f}:d=0.1,"
        "pan=stereo|c0=c0|c1=c0[out]"
    )
    return _run_ffmpeg(fc, duration, target)


def synth_swoosh_out(target, duration=0.6):
    fc = (
        "anoisesrc=color=pink:duration=" + str(duration) + ":sample_rate=44100,"
        f"lowpass=f=2000,"
        f"volume=1.8,"
        f"afade=t=in:st=0:d=0.1,"
        f"afade=t=out:st={duration-0.05:.2f}:d=0.05,"
        "pan=stereo|c0=c0|c1=c0[out]"
    )
    return _run_ffmpeg(fc, duration, target)


def synth_glitch(target, duration=0.25):
    fc = (
        "anoisesrc=color=white:duration=" + str(duration) + ":sample_rate=44100,"
        f"bandpass=f=3000:width_type=h:width=1500,"
        f"volume=2.5,"
        f"tremolo=f=40:d=1.0,"
        f"afade=t=in:st=0:d=0.005,"
        f"afade=t=out:st={duration-0.02:.3f}:d=0.02,"
        "pan=stereo|c0=c0|c1=c0[out]"
    )
    return _run_ffmpeg(fc, duration, target)


def synth_bell(target, duration=1.2):
    fc = (
        f"sine=frequency=1320:duration={duration}:sample_rate=44100,"
        f"volume=0.4,"
        f"afade=t=in:st=0:d=0.005,"
        f"afade=t=out:st=0.05:d={duration-0.05:.2f},"
        "pan=stereo|c0=c0|c1=c0[out]"
    )
    return _run_ffmpeg(fc, duration, target)


def synth_dramatic_riser(target, duration=2.0):
    fc = (
        "anoisesrc=color=brown:duration=" + str(duration) + ":sample_rate=44100,"
        f"highpass=f=200,"
        f"volume=1.5,"
        f"afade=t=in:st=0:d={duration*0.85:.2f},"
        f"afade=t=out:st={duration-0.1:.2f}:d=0.1,"
        "pan=stereo|c0=c0|c1=c0[out]"
    )
    return _run_ffmpeg(fc, duration, target)


LIBRARY = [
    ("whoosh_transition.mp3", synth_whoosh, "Section transitions"),
    ("ding_reveal.mp3",       synth_ding,    "Stat/number reveal"),
    ("alert_negative.mp3",    synth_alert,   "Warning / negative"),
    ("click_emphasis.mp3",    synth_click,   "Key-point click"),
    ("typewriter.mp3",        synth_typewriter, "Quote reveal"),
    ("swoosh_in.mp3",         synth_swoosh_in,  "Intro swoosh"),
    ("swoosh_out.mp3",        synth_swoosh_out, "Outro swoosh"),
    ("glitch_short.mp3",      synth_glitch,    "'But wait' moments"),
    ("bell_positive.mp3",     synth_bell,      "Good news / win"),
    ("dramatic_riser.mp3",    synth_dramatic_riser, "Pre-reveal build"),
]


def run(force=False):
    SFX_DIR.mkdir(parents=True, exist_ok=True)
    catalogue = []
    ok = 0
    for filename, fn, desc in LIBRARY:
        target = SFX_DIR / filename
        catalogue.append({"file": filename, "use": desc})
        if target.exists() and not force:
            print(f"  ⏭  {filename} (exists)")
            ok += 1
            continue
        if fn(target):
            print(f"  ✅ {filename} — {desc}")
            ok += 1
        else:
            print(f"  ⚠️  {filename} failed")

    # Write library.yaml catalogue
    try:
        import yaml
        LIBRARY_YAML.write_text(
            yaml.safe_dump(
                {"sfx_library": catalogue,
                 "generated_by": "utils/sfx_synthesizer.py"},
                sort_keys=False,
            ),
            encoding="utf-8",
        )
    except ImportError:
        LIBRARY_YAML.write_text(
            json.dumps({"sfx_library": catalogue}, indent=2),
            encoding="utf-8",
        )
    print(f"\n  📋 Library catalogue → {LIBRARY_YAML}")
    print(f"  🎚  {ok}/{len(LIBRARY)} effects ready in {SFX_DIR}")
    return ok == len(LIBRARY)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--force", action="store_true",
                   help="Re-synthesize even if files already exist")
    args = p.parse_args()
    ok = run(force=args.force)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
