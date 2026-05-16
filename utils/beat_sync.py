#!/usr/bin/env python3
"""
McNeillium_AI — Phase 19 Step 6: Beat-synced cuts (librosa)

Detects beats in a music file and snaps a list of visual cut times to
the nearest beat. Use this only on intro / outro sections where music
is prominent — fighting the beat against narration on main sections
makes the video feel choppy. The brief explicitly calls this out.

Public API:
  detect_beats(music_path, sr=22050) -> {"tempo": float, "beats_s": [float]}

  snap_to_nearest_beat(times, beats, max_drift_s=0.4) -> [float]
      Move each input time to its nearest beat IF the beat is within
      max_drift_s. Otherwise leave the time alone (no point snapping
      a 4s gap to satisfy the beat — viewer feels the wrong-ness).

CLI:
  python utils/beat_sync.py [--music PATH] [--cuts t1,t2,t3]
"""

import argparse
import io
import json
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower().replace("-", "") != "utf8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8",
                                  errors="replace")


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MUSIC = PROJECT_ROOT / "assets" / "music" / "ambient_tech.mp3"


def detect_beats(music_path, sr=22050):
    """Return tempo (BPM) + beat onset times in seconds."""
    import librosa
    y, sr = librosa.load(str(music_path), sr=sr)
    tempo, beats = librosa.beat.beat_track(y=y, sr=sr)
    beats_s = librosa.frames_to_time(beats, sr=sr).tolist()
    # librosa 0.10+ returns tempo as a 1-element ndarray
    tempo_val = float(tempo.item() if hasattr(tempo, "item") else tempo)
    if hasattr(tempo, "shape") and len(getattr(tempo, "shape", ())) > 0:
        try:
            tempo_val = float(tempo[0])
        except Exception:
            tempo_val = float(tempo)
    return {
        "tempo": tempo_val,
        "beats_s": [round(b, 3) for b in beats_s],
        "duration_s": round(len(y) / sr, 3),
    }


def snap_to_nearest_beat(times, beats, max_drift_s=0.4):
    """For each t in `times`, find nearest beat. Move iff within drift."""
    if not beats:
        return list(times)
    snapped = []
    for t in times:
        # Binary-search nearest beat (linear is fine; beats list is small)
        nearest = min(beats, key=lambda b: abs(b - t))
        if abs(nearest - t) <= max_drift_s:
            snapped.append(round(nearest, 3))
        else:
            snapped.append(round(float(t), 3))
    return snapped


def main():
    p = argparse.ArgumentParser(description="Phase 19 beat detector")
    p.add_argument("--music", default=str(DEFAULT_MUSIC))
    p.add_argument("--cuts", default="",
                   help="Comma-separated cut times (s) to snap to beats")
    p.add_argument("--max-drift", type=float, default=0.4)
    p.add_argument("--report", default="knowledge_base/reviews/beat_report.json")
    args = p.parse_args()

    if not Path(args.music).exists():
        print(f"❌ Music file not found: {args.music}")
        sys.exit(2)

    print(f"🎵 Detecting beats in {Path(args.music).name}...")
    info = detect_beats(args.music)
    print(f"   tempo: {info['tempo']:.1f} BPM")
    print(f"   beats: {len(info['beats_s'])} over "
          f"{info['duration_s']:.1f}s")
    print(f"   first 6 beats: {info['beats_s'][:6]}")

    if args.cuts.strip():
        cuts = [float(x) for x in args.cuts.split(",")]
        snapped = snap_to_nearest_beat(cuts, info["beats_s"],
                                       max_drift_s=args.max_drift)
        print(f"\n   ✂️  Cut snap-to-beat:")
        for orig, snap in zip(cuts, snapped):
            mark = "→ snapped" if abs(snap - orig) > 1e-6 else "  unchanged"
            print(f"     {orig:6.2f}s  {mark}  →  {snap:6.2f}s")
        info["snapped_cuts"] = list(zip(cuts, snapped))

    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(info, indent=2),
                                 encoding="utf-8")
    print(f"   📝 → {args.report}")


if __name__ == "__main__":
    main()
