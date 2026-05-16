#!/usr/bin/env python3
"""
McNeillium_AI — Phase 22.1: Phrase Planner

Groups AssemblyAI-verified word timestamps into "phrases" — short
spans (target 3-5s) bounded by natural pauses or punctuation.

Each phrase becomes one beat in the video. Beats this granular let
the Visual Director align an asset to the EXACT moment it's spoken,
fixing the v21 problem where one image held for 8s while the
narration covered three different ideas.

Targets (from the Phase 22 brief)
─────────────────────────────────
  - 4 second target average beat duration
  - 6 second hard cap (anything longer gets split)
  - 2.5 second floor (sub-cap fragments get merged)
  - For a 5-min video → 80-100 phrases / beats

Splitting strategy
──────────────────
  1. Walk word timestamps in order.
  2. Cut at any inter-word silence > MIN_SILENCE_MS (250ms default).
  3. Cut at end-of-sentence punctuation (period, question mark,
     exclamation), inferred from the source script's narration.
  4. After splitting, merge any phrase < MIN_PHRASE_S into its
     neighbor.
  5. After merging, split any phrase > MAX_PHRASE_S at its
     longest internal silence.

Public API
──────────
  plan_phrases(words_path, script_path) -> [{
      phrase_idx, section_id, start_s, end_s, duration_s, text
  }]
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
DEFAULT_WORDS = PROJECT_ROOT / "output" / "audio" / "latest_words_verified.json"
DEFAULT_SCRIPT = PROJECT_ROOT / "output" / "scripts" / "latest.json"
DEFAULT_OUT = PROJECT_ROOT / "output" / "phrases.json"

TARGET_PHRASE_S = 4.0
MAX_PHRASE_S = 6.0
MIN_PHRASE_S = 2.5
MIN_SILENCE_MS = 250  # cut anything longer than this


def _is_sentence_end(text):
    return text.endswith(".") or text.endswith("!") or text.endswith("?")


def _word_end_ms(w):
    return float(w["offset_ms"]) + float(w["duration_ms"])


def _build_punctuation_lookup(script):
    """Build a (section_id, lower_word) → True/False map of "this word
    appears with terminal punctuation in the source script". The
    AssemblyAI words file strips punctuation; we recover it by
    matching against the original narration text."""
    out = {}
    for sec in script.get("sections", []):
        sid = sec.get("id", "")
        narration = sec.get("narration", "")
        # Find words ending in . ! ? — keep in section context
        for m in re.finditer(r"(\w+)([.!?])", narration):
            key = (sid, m.group(1).lower())
            out[key] = True
    return out


def _initial_split(words, ends_sentence_lookup):
    """First pass: cut at silences > MIN_SILENCE_MS and at sentence ends."""
    if not words:
        return []
    phrases = []
    current = [words[0]]
    for prev, w in zip(words, words[1:]):
        prev_end = _word_end_ms(prev)
        gap_ms = float(w["offset_ms"]) - prev_end
        is_silence = gap_ms > MIN_SILENCE_MS
        # Punctuation lookup uses prev word's clean text + section
        prev_clean = re.sub(r"[^a-zA-Z]", "", prev["text"]).lower()
        prev_sid = prev.get("section_id", "")
        is_sent_end = (prev_sid, prev_clean) in ends_sentence_lookup
        if is_silence or is_sent_end:
            phrases.append(current)
            current = [w]
        else:
            current.append(w)
    if current:
        phrases.append(current)
    return phrases


def _phrase_duration(phrase_words):
    if not phrase_words:
        return 0.0
    start = float(phrase_words[0]["offset_ms"]) / 1000.0
    end = _word_end_ms(phrase_words[-1]) / 1000.0
    return end - start


def _merge_short(phrases):
    """Merge phrases < MIN_PHRASE_S into the next phrase (or previous
    if at end of section)."""
    out = []
    i = 0
    while i < len(phrases):
        cur = phrases[i]
        if _phrase_duration(cur) < MIN_PHRASE_S and i + 1 < len(phrases):
            # Merge into next IF same section
            nxt = phrases[i + 1]
            if cur[-1].get("section_id") == nxt[0].get("section_id"):
                phrases[i + 1] = cur + nxt
                i += 1
                continue
        out.append(cur)
        i += 1
    # Second pass: any still-short fragment at the end merges with prev
    if len(out) >= 2 and _phrase_duration(out[-1]) < MIN_PHRASE_S:
        if out[-1][0].get("section_id") == out[-2][-1].get("section_id"):
            out[-2] = out[-2] + out[-1]
            out.pop()
    return out


def _split_long(phrases):
    """Split any phrase > MAX_PHRASE_S at its largest internal silence."""
    out = []
    for phrase in phrases:
        if _phrase_duration(phrase) <= MAX_PHRASE_S:
            out.append(phrase)
            continue
        # Find the largest internal gap
        best_idx = None
        best_gap = 0.0
        for j in range(len(phrase) - 1):
            gap = float(phrase[j + 1]["offset_ms"]) - _word_end_ms(phrase[j])
            if gap > best_gap:
                best_gap = gap
                best_idx = j
        if best_idx is None or best_idx < 1:
            # No good split — keep as-is
            out.append(phrase)
        else:
            left = phrase[: best_idx + 1]
            right = phrase[best_idx + 1:]
            # Recurse in case still too long
            out.extend(_split_long([left, right]))
    return out


def plan_phrases(words_path=None, script_path=None):
    words_path = Path(words_path or DEFAULT_WORDS)
    script_path = Path(script_path or DEFAULT_SCRIPT)
    if not words_path.exists():
        raise FileNotFoundError(f"words file: {words_path}")
    if not script_path.exists():
        raise FileNotFoundError(f"script: {script_path}")

    words = json.loads(words_path.read_text(encoding="utf-8")).get("words", [])
    script = json.loads(script_path.read_text(encoding="utf-8"))
    ends_lookup = _build_punctuation_lookup(script)

    phrases_raw = _initial_split(words, ends_lookup)
    phrases_raw = _merge_short(phrases_raw)
    phrases_raw = _split_long(phrases_raw)

    out = []
    for i, phrase_words in enumerate(phrases_raw):
        if not phrase_words:
            continue
        text = " ".join(w["text"] for w in phrase_words)
        out.append({
            "phrase_idx": i,
            "section_id": phrase_words[0].get("section_id", ""),
            "start_s": round(float(phrase_words[0]["offset_ms"]) / 1000.0, 3),
            "end_s": round(_word_end_ms(phrase_words[-1]) / 1000.0, 3),
            "duration_s": round(_phrase_duration(phrase_words), 3),
            "text": text,
        })
    return out


def main():
    p = argparse.ArgumentParser(description="Phase 22 phrase planner")
    p.add_argument("--words", default=str(DEFAULT_WORDS))
    p.add_argument("--script", default=str(DEFAULT_SCRIPT))
    p.add_argument("--out", default=str(DEFAULT_OUT))
    args = p.parse_args()

    phrases = plan_phrases(args.words, args.script)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(phrases, indent=2),
                              encoding="utf-8")

    durations = [p["duration_s"] for p in phrases]
    avg = sum(durations) / max(1, len(durations))
    print(f"📐 Phrase plan: {len(phrases)} phrases over "
          f"{phrases[-1]['end_s']:.1f}s")
    print(f"   avg duration: {avg:.2f}s   "
          f"(target {TARGET_PHRASE_S}s, range "
          f"{min(durations):.1f}-{max(durations):.1f}s)")
    print(f"   under {MIN_PHRASE_S}s: "
          f"{sum(1 for d in durations if d < MIN_PHRASE_S)}  "
          f"  over {MAX_PHRASE_S}s: "
          f"{sum(1 for d in durations if d > MAX_PHRASE_S)}")
    print(f"   💾 → {args.out}")


if __name__ == "__main__":
    main()
