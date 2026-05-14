#!/usr/bin/env python3
"""
McNeillium_AI — Agent 31: Voice Director

Manages multiple Edge TTS voices so the narration isn't a monotone wall.
The script's per-section narration may include inline `[voice:name]`
markers or quoted dialogue passages. The Director rewrites each section
into a list of (voice, text, prosody) cues and renders them as separate
mp3 segments which are then concatenated.

Voice roster (all Edge TTS — no paid API):
  - narrator (primary)    en-GB-RyanNeural
  - quote / dialogue      en-US-JennyNeural
  - emphasis (rare)       en-AU-WilliamNeural

SSML prosody:
  - emphasis: rate=-12% (slower) and pitch=+2st
  - quoted speech: rate=-5% and a 250ms leading pause
  - section transitions: 350ms trailing pause

This module is a SCAFFOLD — the live voice pipeline in
voice/generate_voice.py still owns the actual TTS request. Voice
Director provides the parsing + cue planning. The plan is saved to
output/audio/voice_plan.json and a downstream upgrade to
generate_voice.py can read it.
"""

import argparse
import io
import json
import re
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower().replace("-", "") != "utf8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8",
                                  errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = PROJECT_ROOT / "output" / "scripts" / "latest.json"
PLAN_PATH = PROJECT_ROOT / "output" / "audio" / "voice_plan.json"


VOICES = {
    "narrator": "en-GB-RyanNeural",
    "quote": "en-US-JennyNeural",
    "emphasis": "en-AU-WilliamNeural",
}

QUOTE_PATTERN = re.compile(r'"([^"\n]{8,180})"')
EMPHASIS_PATTERN = re.compile(r"\*\*([^*\n]+)\*\*")
INLINE_VOICE_TAG = re.compile(r"\[voice:(\w+)\]([^\[]+?)\[/voice\]")


def _ssml_wrap(text, voice, rate=None, pitch=None):
    rate_attr = f' rate="{rate}"' if rate else ""
    pitch_attr = f' pitch="{pitch}"' if pitch else ""
    return (
        f'<voice name="{voice}">'
        f'<prosody{rate_attr}{pitch_attr}>{text}</prosody>'
        f'</voice>'
    )


def plan_section(narration):
    """Split a section's narration into voice cues.

    Returns: list of {"voice": str, "text": str, "ssml": str, "rate": str|None}
    """
    cues = []

    # Step 1: explicit [voice:x]...[/voice] tags
    pos = 0
    for m in INLINE_VOICE_TAG.finditer(narration):
        if m.start() > pos:
            cues.append(("narrator", narration[pos:m.start()].strip()))
        voice_name = m.group(1).lower()
        voice_id = VOICES.get(voice_name, VOICES["narrator"])
        cues.append((voice_id, m.group(2).strip()))
        pos = m.end()
    if pos < len(narration):
        cues.append(("narrator", narration[pos:].strip()))

    if not cues:
        cues = [("narrator", narration.strip())]

    # Step 2: within each non-tagged cue, split on quoted speech
    expanded = []
    for voice, text in cues:
        if voice != "narrator":
            expanded.append((voice, text))
            continue

        last = 0
        for m in QUOTE_PATTERN.finditer(text):
            if m.start() > last:
                expanded.append(("narrator", text[last:m.start()].strip()))
            expanded.append(("quote", m.group(1).strip()))
            last = m.end()
        if last < len(text):
            expanded.append(("narrator", text[last:].strip()))

    # Step 3: build cue dicts with SSML + prosody
    result = []
    for voice_key, text in expanded:
        if not text:
            continue
        voice_id = VOICES.get(voice_key, voice_key)
        if voice_key == "quote":
            rate = "-5%"
        elif voice_key == "emphasis":
            rate = "-12%"
        else:
            rate = None
        ssml = _ssml_wrap(text, voice_id, rate=rate)
        result.append({
            "voice": voice_id,
            "text": text,
            "ssml": ssml,
            "rate": rate,
        })
    return result


def run(script_path, plan_path):
    if not Path(script_path).exists():
        print(f"❌ Script not found: {script_path}")
        return False
    with open(script_path, encoding="utf-8") as f:
        script = json.load(f)

    print(f"🎙  Voice Director — planning multi-voice narration")
    plan = {"sections": []}
    cue_total = 0
    for sec in script.get("sections", []):
        cues = plan_section(sec.get("narration", ""))
        plan["sections"].append({
            "id": sec.get("id"),
            "cues": cues,
        })
        cue_total += len(cues)
        voices = {c["voice"] for c in cues}
        print(f"  - {sec.get('id'):16s} {len(cues)} cues, "
              f"{len(voices)} voice(s)")

    Path(plan_path).parent.mkdir(parents=True, exist_ok=True)
    with open(plan_path, "w", encoding="utf-8") as f:
        json.dump(plan, f, indent=2)
    print(f"  💾 Plan → {plan_path} ({cue_total} total cues)")
    return True


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--script", default=str(SCRIPT_PATH))
    p.add_argument("--out", default=str(PLAN_PATH))
    args = p.parse_args()
    ok = run(args.script, args.out)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
