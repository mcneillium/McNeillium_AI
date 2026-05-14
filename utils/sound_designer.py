#!/usr/bin/env python3
"""
McNeillium_AI — Agent 33: Sound Designer

Places SFX at narrative beats — whoosh on transitions, ding on stat reveals,
alert on warnings, etc. Each placement carries a precise time-in-audio
target so the SFX hits the syllable.

Inputs:
  - output/scripts/latest.json        (narration + section ids)
  - output/audio/captions/*.json      (Edge TTS word timestamps)

Outputs:
  - output/audio/sfx_track.mp3        (silent base with SFX placed)
  - output/audio/sfx_plan.json        (which SFX hit which word + offset)

SFX library is read from assets/sfx/. Trigger phrases map to file names.
Missing files are logged and skipped — design is robust to a sparse
library. (See `download_starter_pack()` below for fetching from Pixabay
when PIXABAY_API_KEY is set.)
"""

import argparse
import io
import json
import os
import random
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower().replace("-", "") != "utf8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8",
                                  errors="replace")

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = PROJECT_ROOT / "output" / "scripts" / "latest.json"
CAPTIONS_DIR = PROJECT_ROOT / "output" / "audio" / "captions"
SFX_DIR = PROJECT_ROOT / "assets" / "sfx"
SFX_PLAN = PROJECT_ROOT / "output" / "audio" / "sfx_plan.json"
SFX_TRACK = PROJECT_ROOT / "output" / "audio" / "sfx_track.mp3"


# ═══════════════════════════════════════════════════════════════
# Trigger registry — phrase regex → SFX file name + gain (dB)
# ═══════════════════════════════════════════════════════════════

TRIGGERS = [
    # Transitions
    (re.compile(r"\b(but|however|here'?s the (twist|catch|thing))\b", re.I),
     "whoosh.mp3", -8),
    # Stat reveals
    (re.compile(r"\b\d+(\.\d+)?\s*(%|percent|x|times|million|billion|trillion)\b", re.I),
     "ding.mp3", -10),
    # Alerts / warnings
    (re.compile(r"\b(warning|danger|critical|alarming|shocking)\b", re.I),
     "alert.mp3", -12),
    # Reveals
    (re.compile(r"\b(reveal|imagine|picture this|here'?s the wildest)\b", re.I),
     "reveal_sweep.mp3", -10),
    # Quotes
    (re.compile(r"\b(said|told|tweeted|stated)\b", re.I),
     "type_keystroke.mp3", -18),
    # Section transitions (hook→intro, etc.)
    # handled separately by section_id below
]

SECTION_INTRO_SFX = {
    "hook": ("dramatic_riser.mp3", -10),
    "demo": ("type_keystroke.mp3", -16),
    "outro": ("warm_swell.mp3", -10),
}


# ═══════════════════════════════════════════════════════════════
# Optional: download a starter pack from Pixabay
# ═══════════════════════════════════════════════════════════════

PIXABAY_KEY = os.getenv("PIXABAY_API_KEY", "")
STARTER_QUERIES = {
    "whoosh.mp3": "whoosh transition",
    "ding.mp3": "notification ding",
    "alert.mp3": "alert beep",
    "reveal_sweep.mp3": "white noise sweep",
    "type_keystroke.mp3": "keyboard typing",
    "dramatic_riser.mp3": "dramatic riser",
    "warm_swell.mp3": "warm pad swell",
}


def download_starter_pack():
    """Fetch missing starter SFX from Pixabay's free audio CDN."""
    if not PIXABAY_KEY:
        print("  ⚠️  PIXABAY_API_KEY missing — cannot download SFX")
        return 0

    SFX_DIR.mkdir(parents=True, exist_ok=True)
    fetched = 0
    for fname, query in STARTER_QUERIES.items():
        target = SFX_DIR / fname
        if target.exists() and target.stat().st_size > 1000:
            continue
        try:
            enc = urllib.parse.quote(query)
            url = (f"https://pixabay.com/api/?key={PIXABAY_KEY}"
                   f"&q={enc}&audio_type=sound_effects&per_page=5")
            with urllib.request.urlopen(url, timeout=15) as r:
                data = json.loads(r.read().decode())
            hits = data.get("hits", []) or data.get("audio", []) or []
            if not hits:
                print(f"    ⚠️  no Pixabay hit for {query}")
                continue
            audio = hits[0]
            dl_url = (audio.get("audio") or audio.get("preview")
                      or audio.get("audio_url"))
            if not dl_url:
                continue
            req = urllib.request.Request(
                dl_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as r2:
                target.write_bytes(r2.read())
            print(f"    📥 {fname} ← {query}")
            fetched += 1
            time.sleep(0.5)
        except Exception as e:
            print(f"    ⚠️  failed {fname}: {e}")
    return fetched


# ═══════════════════════════════════════════════════════════════
# Planning
# ═══════════════════════════════════════════════════════════════

def _load_word_timeline(captions_dir, sections):
    """Build absolute-time word list across all sections."""
    merged = []
    running = 0.0
    for idx, sec in enumerate(sections):
        sid = sec.get("id", f"section_{idx}")
        cap_file = Path(captions_dir) / f"segment_{idx:02d}_{sid}.json"
        if not cap_file.exists():
            continue
        try:
            with open(cap_file, encoding="utf-8") as f:
                words = json.load(f)
        except Exception:
            continue
        first_offset = running
        for w in words:
            merged.append({
                "text": w["text"],
                "offset_ms": float(w["offset_ms"]) + first_offset,
                "section_id": sid,
            })
        if words:
            last = words[-1]
            running = first_offset + float(last["offset_ms"]) + \
                      float(last["duration_ms"])
    return merged


def plan_sfx(script_path, captions_dir):
    with open(script_path, encoding="utf-8") as f:
        script = json.load(f)
    sections = script.get("sections", [])
    timeline = _load_word_timeline(captions_dir, sections)
    if not timeline:
        return []

    placements = []
    # Section intro SFX
    section_first_word = {}
    for w in timeline:
        sid = w["section_id"]
        if sid not in section_first_word:
            section_first_word[sid] = w["offset_ms"]
    for sid, file_gain in SECTION_INTRO_SFX.items():
        if sid in section_first_word:
            fname, gain = file_gain
            placements.append({
                "file": fname,
                "offset_ms": max(0, section_first_word[sid] - 300),
                "gain_db": gain,
                "trigger": f"section_intro:{sid}",
            })

    # Trigger phrases — match against sliding windows of words
    for i in range(len(timeline)):
        text_window = " ".join(
            w["text"] for w in timeline[i:i + 6]
        )
        for pattern, fname, gain in TRIGGERS:
            if pattern.search(text_window):
                placements.append({
                    "file": fname,
                    "offset_ms": timeline[i]["offset_ms"],
                    "gain_db": gain,
                    "trigger": pattern.pattern[:60],
                })
                # Don't trigger again within the next 4 words for same SFX
                break

    # Dedupe: at most one SFX every 1.5s
    placements.sort(key=lambda p: p["offset_ms"])
    deduped = []
    last_time = -2000
    for p in placements:
        if p["offset_ms"] - last_time >= 1500:
            deduped.append(p)
            last_time = p["offset_ms"]
    return deduped


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


def assemble_sfx_track(placements, duration_ms, out_path):
    """Build a single SFX-only mp3 track using FFmpeg adelay+amix."""
    available = []
    for p in placements:
        path = SFX_DIR / p["file"]
        if path.exists() and path.stat().st_size > 200:
            available.append((path, p))
        else:
            print(f"    ⚠️  missing SFX: {p['file']} (skipped)")

    if not available:
        print("  ⚠️  No SFX files present — skipping track assembly.")
        return False

    cmd = [FFMPEG, "-y"]
    for path, _ in available:
        cmd.extend(["-i", str(path)])

    filter_parts = []
    for i, (_, p) in enumerate(available):
        delay = int(p["offset_ms"])
        gain_db = p["gain_db"]
        filter_parts.append(
            f"[{i}:a]adelay={delay}|{delay},"
            f"volume={10 ** (gain_db / 20):.3f}[s{i}]"
        )
    mix_inputs = "".join(f"[s{i}]" for i in range(len(available)))
    filter_parts.append(
        f"{mix_inputs}amix=inputs={len(available)}:duration=longest:"
        f"dropout_transition=0[mix]"
    )
    filter_parts.append(f"[mix]apad[bed]")

    cmd.extend([
        "-filter_complex", ";".join(filter_parts),
        "-map", "[bed]",
        "-t", str(duration_ms / 1000),
        "-c:a", "libmp3lame", "-q:a", "5",
        str(out_path),
    ])

    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"  ⚠️  SFX assemble failed: {r.stderr[-300:]}")
        return False
    return True


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

def run(script_path, captions_dir, plan_path, track_path,
        download=False):
    if download:
        print("📥 Sound Designer — downloading SFX starter pack...")
        download_starter_pack()

    placements = plan_sfx(script_path, captions_dir)
    print(f"🔊 Sound Designer — {len(placements)} SFX placements planned")
    for p in placements[:10]:
        print(f"  - {p['file']:24s} @ {p['offset_ms']/1000:.1f}s  "
              f"({p['trigger'][:30]})")
    if len(placements) > 10:
        print(f"  ... +{len(placements) - 10} more")

    Path(plan_path).parent.mkdir(parents=True, exist_ok=True)
    with open(plan_path, "w", encoding="utf-8") as f:
        json.dump(placements, f, indent=2)
    print(f"  💾 Plan → {plan_path}")

    if placements:
        last_ms = max(p["offset_ms"] for p in placements) + 3000
        assemble_sfx_track(placements, last_ms, track_path)
    return True


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--script", default=str(SCRIPT_PATH))
    p.add_argument("--captions-dir", default=str(CAPTIONS_DIR))
    p.add_argument("--plan", default=str(SFX_PLAN))
    p.add_argument("--track", default=str(SFX_TRACK))
    p.add_argument("--download", action="store_true",
                   help="Fetch missing starter SFX from Pixabay")
    args = p.parse_args()
    ok = run(args.script, args.captions_dir, args.plan, args.track,
             download=args.download)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
