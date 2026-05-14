#!/usr/bin/env python3
"""
McNeillium_AI — Audio Quality Director (Agent 16)
FFmpeg audio processing chain: highpass → EQ → compression → loudnorm.
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
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
AUDIO_DIR = PROJECT_ROOT / "output" / "audio"


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

AUDIO_CHAIN = (
    "highpass=f=80,"
    "equalizer=f=3000:width_type=h:width=2000:g=2,"
    "compand=attacks=0.05:decays=0.3:"
    "points=-90/-60|-60/-40|-40/-25|-20/-15:soft-knee=6:gain=0,"
    "loudnorm=I=-14:TP=-1.5:LRA=11"
)

# Phase 6 "pro" chain — adds de-esser, presence, gentle warmth saturation,
# and a subtle short reverb send. Used when --pro is passed.
AUDIO_CHAIN_PRO = (
    "highpass=f=80,"
    # de-esser: notch around 6.5 kHz where sibilants live
    "equalizer=f=6500:width_type=h:width=1500:g=-3,"
    # presence boost (same as default chain)
    "equalizer=f=3000:width_type=h:width=2000:g=2,"
    # subtle low-mid warmth
    "equalizer=f=180:width_type=h:width=200:g=1.5,"
    # compression
    "compand=attacks=0.05:decays=0.3:"
    "points=-90/-60|-60/-40|-40/-25|-20/-15:soft-knee=6:gain=0,"
    # very subtle aecho for "studio room" feel (low wet)
    "aecho=0.7:0.85:30:0.12,"
    "loudnorm=I=-14:TP=-1.5:LRA=11"
)


def process_audio(input_path: str, output_path: str = None,
                  pro: bool = False) -> str:
    """Apply the broadcast audio chain to a narration file.

    Pass `pro=True` to use the Phase 6 chain with de-esser, warmth EQ,
    and subtle reverb send.
    """
    inp = Path(input_path)
    if not inp.exists():
        raise FileNotFoundError(f"Audio file not found: {inp}")

    if output_path is None:
        out = inp.with_stem(inp.stem + ("_pro" if pro else "_processed"))
    else:
        out = Path(output_path)

    out.parent.mkdir(parents=True, exist_ok=True)

    chain = AUDIO_CHAIN_PRO if pro else AUDIO_CHAIN
    cmd = [
        FFMPEG, "-y",
        "-i", str(inp),
        "-af", chain,
        "-c:a", "libmp3lame", "-q:a", "2",
        str(out),
    ]

    print(f"    🔧 Processing audio: {inp.name}")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"    ❌ Audio processing failed: {result.stderr[-300:]}")
        return None

    print(f"    ✅ Processed audio: {out.name}")
    return str(out)


def measure_loudness(audio_path: str) -> dict:
    """Measure loudness stats using FFmpeg loudnorm in print mode."""
    cmd = [
        FFMPEG,
        "-i", str(audio_path),
        "-af", "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json",
        "-f", "null", "-",
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    combined = result.stderr + result.stdout

    match = re.search(r'\{[^}]*"input_i"[^}]*\}', combined, re.DOTALL)
    if not match:
        return {}

    try:
        stats = json.loads(match.group())
    except json.JSONDecodeError:
        return {}

    return stats


def score_audio(audio_path: str) -> dict:
    """Score processed audio quality (0-10) based on loudness metrics."""
    stats = measure_loudness(audio_path)
    if not stats:
        return {"score": 0, "details": "Could not measure loudness", "stats": {}}

    score = 10.0
    details = []

    integrated = float(stats.get("output_i", stats.get("input_i", -99)))
    tp = float(stats.get("output_tp", stats.get("input_tp", 0)))
    lra = float(stats.get("output_lra", stats.get("input_lra", 99)))

    lufs_diff = abs(integrated - (-14.0))
    if lufs_diff > 2.0:
        score -= 3.0
        details.append(f"Loudness {integrated:.1f} LUFS (target -14)")
    elif lufs_diff > 1.0:
        score -= 1.5
        details.append(f"Loudness {integrated:.1f} LUFS (slightly off target)")
    else:
        details.append(f"Loudness {integrated:.1f} LUFS ✓")

    if tp > -0.5:
        score -= 2.0
        details.append(f"True peak {tp:.1f} dBTP (too hot)")
    elif tp > -1.0:
        score -= 1.0
        details.append(f"True peak {tp:.1f} dBTP (marginal)")
    else:
        details.append(f"True peak {tp:.1f} dBTP ✓")

    if lra > 15:
        score -= 2.0
        details.append(f"LRA {lra:.1f} (too dynamic)")
    elif lra > 12:
        score -= 1.0
        details.append(f"LRA {lra:.1f} (slightly wide)")
    else:
        details.append(f"LRA {lra:.1f} ✓")

    score = max(0, min(10, score))

    return {
        "score": round(score, 1),
        "details": details,
        "stats": {
            "integrated_lufs": integrated,
            "true_peak_dbtp": tp,
            "lra": lra,
        },
    }


def process_and_score(input_path: str, replace: bool = False) -> dict:
    """Process audio and return quality score. Optionally replace original."""
    processed = process_audio(input_path)
    if not processed:
        return {"score": 0, "error": "Processing failed"}

    result = score_audio(processed)

    if replace and result["score"] >= 5.0:
        inp = Path(input_path)
        backup = inp.with_suffix(".original.mp3")
        if not backup.exists():
            shutil.copy2(inp, backup)
        shutil.move(processed, inp)
        result["replaced"] = True
        result["backup"] = str(backup)
        print(f"    📦 Original backed up to {backup.name}")
    else:
        result["output"] = processed
        result["replaced"] = False

    return result


def main():
    parser = argparse.ArgumentParser(description="Process narration audio to broadcast quality")
    parser.add_argument("input", help="Path to input audio file")
    parser.add_argument("-o", "--output", help="Output path (default: input_processed.mp3)")
    parser.add_argument("--replace", action="store_true", help="Replace original (backup saved)")
    parser.add_argument("--score-only", action="store_true", help="Just measure and score")
    parser.add_argument("--pro", action="store_true",
                        help="Phase 6 chain: de-esser + warmth + subtle reverb")
    args = parser.parse_args()

    print("\n🎛  McNeillium_AI — Audio Quality Director")
    print("=" * 45)

    if args.score_only:
        result = score_audio(args.input)
        print(f"\n  Score: {result['score']}/10")
        for d in result.get("details", []):
            print(f"    {d}")
        return

    if args.pro:
        processed = process_audio(args.input, args.output, pro=True)
        result = score_audio(processed) if processed else {"score": 0}
        if args.replace and processed and result.get("score", 0) >= 5:
            inp = Path(args.input)
            backup = inp.with_suffix(".original.mp3")
            if not backup.exists():
                shutil.copy2(inp, backup)
            shutil.move(processed, inp)
            result["replaced"] = True
            result["backup"] = str(backup)
    else:
        result = process_and_score(args.input, replace=args.replace)
    print(f"\n  Quality Score: {result.get('score', 0)}/10")
    for d in result.get("details", []):
        print(f"    {d}")

    if result.get("replaced"):
        print(f"  Original replaced (backup: {result['backup']})")
    elif result.get("output"):
        print(f"  Output: {result['output']}")


if __name__ == "__main__":
    main()
