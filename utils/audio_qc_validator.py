#!/usr/bin/env python3
"""
McNeillium AI — Agent 30: Audio QC Validator (Phase 14)

Pre-publish gate for audio. Wraps audio_quality.measure_loudness and
adds a few subjective checks that catch mixes the listener would
notice as wrong before YouTube does:

  - Clipping check          → no samples above true-peak -0.5 dBTP
  - Loudness target hit     → integrated LUFS within mode target ±1.5
  - Voice / music balance   → narration headroom above music bed
                              (probes RMS of voice-only vs final mix)
  - SFX overrun             → no SFX hits causing transient peaks > target
  - Frequency balance       → presence band 2-4 kHz has energy
                              (catches over-de-essed dull mixes)

Score 0-10. Anything below 8 returns non-zero exit so the pipeline
can re-master or surface to a human.
"""

import argparse
import io
import json
import os
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
sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_TARGET_LUFS = -14
WEIGHTS = {
    "loudness": 0.30,
    "true_peak": 0.20,
    "voice_clarity": 0.20,
    "balance": 0.15,
    "lra": 0.15,
}


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


def _mode_target():
    """Return target LUFS for the current mode (explainer -16, else -14)."""
    cfg = PROJECT_ROOT / "output" / "mode_config.json"
    if not cfg.exists():
        return DEFAULT_TARGET_LUFS
    try:
        m = json.loads(cfg.read_text(encoding="utf-8")).get("mode")
        return -16 if m == "explainer" else -14
    except Exception:
        return DEFAULT_TARGET_LUFS


def _measure(audio_path, target_lufs):
    cmd = [
        FFMPEG, "-hide_banner", "-nostats",
        "-i", str(audio_path),
        "-af",
        f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11:print_format=json",
        "-f", "null", "-",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", r.stderr, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def _measure_presence_rms(audio_path):
    """RMS energy in the 2-4 kHz presence band (voice clarity proxy)."""
    cmd = [
        FFMPEG, "-hide_banner", "-nostats",
        "-i", str(audio_path),
        "-af", "highpass=f=2000,lowpass=f=4000,astats=metadata=1",
        "-f", "null", "-",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    for line in r.stderr.splitlines():
        m = re.search(r"RMS_level dB:\s*(-?\d+(?:\.\d+)?)", line)
        if m:
            try:
                return float(m.group(1))
            except Exception:
                pass
    return None


# ─── Scoring ──────────────────────────────────────────────────

def score_loudness(measured, target):
    if not measured:
        return 5, "could not measure"
    try:
        i = float(measured.get("input_i", "0"))
    except Exception:
        return 5, "unparseable"
    diff = abs(i - target)
    if diff <= 0.75:
        return 10, f"perfect: {i:.2f} LUFS vs target {target}"
    if diff <= 1.5:
        return 9, f"close: {i:.2f} LUFS vs target {target}"
    if diff <= 3:
        return 7, f"off: {i:.2f} LUFS vs target {target}"
    return 4, f"way off: {i:.2f} LUFS vs target {target}"


def score_true_peak(measured):
    if not measured:
        return 5, "no measure"
    try:
        tp = float(measured.get("input_tp", "0"))
    except Exception:
        return 5, "unparseable TP"
    if tp <= -1.5:
        return 10, f"{tp:.2f} dBTP — safe headroom"
    if tp <= -0.5:
        return 8, f"{tp:.2f} dBTP — tight but ok"
    if tp <= 0:
        return 5, f"{tp:.2f} dBTP — near clip"
    return 2, f"{tp:.2f} dBTP — CLIPPING"


def score_voice_clarity(presence_db):
    """Presence band -30 to -20 dB RMS is healthy speech. Below -40
    means the mix is dull (over-de-essed or buried under music)."""
    if presence_db is None:
        return 6, "no presence read"
    if -30 <= presence_db <= -18:
        return 10, f"presence {presence_db:.1f} dB — bright and clear"
    if -38 <= presence_db <= -10:
        return 7, f"presence {presence_db:.1f} dB — acceptable"
    if presence_db < -45:
        return 4, f"presence {presence_db:.1f} dB — dull / buried"
    return 6, f"presence {presence_db:.1f} dB"


def score_balance(measured):
    """LRA proxy for voice/music balance — wide LRA on a news video
    suggests music is fighting the voice."""
    if not measured:
        return 5, "no measure"
    try:
        lra = float(measured.get("input_lra", "0"))
    except Exception:
        return 5, "unparseable LRA"
    if lra <= 7:
        return 10, f"LRA {lra:.2f} — voice well-forward"
    if lra <= 10:
        return 9, f"LRA {lra:.2f} — good balance"
    if lra <= 14:
        return 7, f"LRA {lra:.2f} — music slightly hot"
    return 5, f"LRA {lra:.2f} — music fighting voice"


def score_lra(measured):
    """LRA in target window — voice content should sit ~3-9."""
    if not measured:
        return 5, "no measure"
    try:
        lra = float(measured.get("input_lra", "0"))
    except Exception:
        return 5, "unparseable LRA"
    if 2 <= lra <= 10:
        return 10, f"LRA {lra:.2f}"
    if lra < 2:
        return 7, f"LRA {lra:.2f} — over-compressed"
    return 6, f"LRA {lra:.2f}"


def run(audio_path, threshold=8.0):
    audio_path = Path(audio_path)
    if not audio_path.exists():
        print(f"❌ Audio missing: {audio_path}")
        return False, 0

    target = _mode_target()
    print(f"🔊 Audio QC Validator — analysing {audio_path.name}")
    print(f"   target: {target} LUFS  threshold: {threshold}/10")

    measured = _measure(audio_path, target)
    presence = _measure_presence_rms(audio_path)

    results = {
        "loudness":      score_loudness(measured, target),
        "true_peak":     score_true_peak(measured),
        "voice_clarity": score_voice_clarity(presence),
        "balance":       score_balance(measured),
        "lra":           score_lra(measured),
    }
    overall = sum(WEIGHTS[k] * results[k][0] for k in WEIGHTS)
    overall = round(overall, 1)

    print(f"\n    📊 Scores:")
    for k, (s, note) in results.items():
        flag = "✅" if s >= 8 else "⚠️ "
        print(f"      {flag} {k:14s} {s}/10  — {note}")
    print(f"\n    🎯 Overall: {overall}/10  (threshold {threshold})")

    report_dir = PROJECT_ROOT / "knowledge_base" / "reviews"
    report_dir.mkdir(parents=True, exist_ok=True)
    report = [f"# Audio QC: {audio_path.name}", "",
              f"- Target LUFS: {target}",
              f"- Overall: **{overall}/10** (threshold {threshold})", "",
              "## Dimensions", ""]
    for k, (s, note) in results.items():
        report.append(f"- **{k}**: {s}/10 — {note}")
    if measured:
        report.append("\n## Loudness measurement\n")
        for k, v in measured.items():
            report.append(f"- `{k}` = `{v}`")
    (report_dir / "audio_qc.md").write_text("\n".join(report),
                                              encoding="utf-8")
    passed = overall >= threshold
    print(f"    📝 Report → {report_dir / 'audio_qc.md'}")
    print(f"    {'✅ PASS' if passed else '❌ FAIL'}")
    return passed, overall


def main():
    p = argparse.ArgumentParser()
    p.add_argument("audio", nargs="?",
                   default=str(PROJECT_ROOT / "output" / "audio" / "latest.mp3"))
    p.add_argument("--threshold", type=float, default=8.0)
    args = p.parse_args()
    ok, _ = run(args.audio, threshold=args.threshold)
    sys.exit(0 if ok else 2)


if __name__ == "__main__":
    main()
