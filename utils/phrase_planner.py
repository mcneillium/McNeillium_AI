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

# Anticipation buffer: visual appears N ms before the entity word is
# spoken so it's already on screen when Brian says it.
ENTITY_ANTICIPATION_MS = 100

# Entity vocabulary for word-level sync. The phrase-splitter snaps
# beat boundaries to the offset_ms of any of these words.
KNOWN_ENTITIES = {
    # Companies — keys are lowercase tokens, values are the canonical
    # display name the Director will use as `company`.
    "openai":      ("company", "OpenAI"),
    "microsoft":   ("company", "Microsoft"),
    "anthropic":   ("company", "Anthropic"),
    "google":      ("company", "Google"),
    "apple":       ("company", "Apple"),
    "meta":        ("company", "Meta"),
    "nvidia":      ("company", "Nvidia"),
    "amazon":      ("company", "Amazon"),
    "aws":         ("company", "AWS"),
    "azure":       ("company", "Azure"),
    "oracle":      ("company", "Oracle"),
    "ibm":         ("company", "IBM"),
    "tesla":       ("company", "Tesla"),
    "spacex":      ("company", "SpaceX"),
    "claude":      ("product", "Claude"),
    "chatgpt":     ("product", "ChatGPT"),
    "gpt":         ("product", "GPT"),
    "gemini":      ("product", "Gemini"),
    "copilot":     ("product", "Copilot"),
    "bedrock":     ("product", "Bedrock"),
    "vertex":      ("product", "Vertex"),
    # People — surname triggers the snap (typical pattern in narration)
    "altman":      ("person", "Sam Altman"),
    "musk":        ("person", "Elon Musk"),
    "amodei":      ("person", "Dario Amodei"),
    "pichai":      ("person", "Sundar Pichai"),
    "nadella":     ("person", "Satya Nadella"),
    "ellison":     ("person", "Larry Ellison"),
    "huang":       ("person", "Jensen Huang"),
    "zuckerberg":  ("person", "Mark Zuckerberg"),
    "hassabis":    ("person", "Demis Hassabis"),
    "sutskever":   ("person", "Ilya Sutskever"),
    "samat":       ("person", "Sameer Samat"),
}


def _word_clean(word_text):
    """Strip punctuation, lowercase. AssemblyAI words come without
    most punct already, but defensive."""
    return re.sub(r"[^a-z0-9]", "", word_text.lower())


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


def _entity_split(phrases):
    """FINAL FIX 1: walk each phrase, split it at entity word boundaries
    so the beat for that entity STARTS exactly when Brian says it
    (minus a 100ms anticipation buffer).

    Each split fragment carries a `pinned_entity` field the Visual
    Director uses to lock the visual to that exact word."""
    out = []
    for phrase in phrases:
        if len(phrase) <= 1:
            out.append(phrase)
            continue

        # Find entity hits inside this phrase, indexed by position
        hits = []
        for i, w in enumerate(phrase):
            clean = _word_clean(w["text"])
            if clean in KNOWN_ENTITIES:
                hits.append((i, KNOWN_ENTITIES[clean]))

        if not hits:
            out.append(phrase)
            continue

        # Split: each entity word starts a new fragment. The fragment
        # before the first entity is its own piece (if non-empty).
        cursor = 0
        for hit_idx, entity_info in hits:
            if hit_idx > cursor:
                pre = phrase[cursor:hit_idx]
                if pre:
                    out.append(pre)
            # Build the entity-anchored fragment up to (but not
            # including) the next entity, or to the end.
            next_hit = next((h[0] for h in hits if h[0] > hit_idx),
                            len(phrase))
            entity_frag = phrase[hit_idx:next_hit]
            # Tag with the pinned entity for the Director to consume.
            for w in entity_frag:
                w["_pinned"] = entity_info
            out.append(entity_frag)
            cursor = next_hit
        if cursor < len(phrase):
            tail = phrase[cursor:]
            if tail:
                out.append(tail)
    return out


def plan_phrases(words_path=None, script_path=None,
                 *, entity_sync=True):
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
    if entity_sync:
        phrases_raw = _entity_split(phrases_raw)

    # Build the basic out list first (entity-pinned + plain).
    out = []
    prev_end_s = 0.0
    for i, phrase_words in enumerate(phrases_raw):
        pass  # placeholder so original loop below works
    out = []
    prev_end_s = 0.0
    for i, phrase_words in enumerate(phrases_raw):
        if not phrase_words:
            continue
        # Anticipation buffer: shift start back by 100ms IF the first
        # word is a pinned entity, but never overlap the previous beat.
        first_offset_s = float(phrase_words[0]["offset_ms"]) / 1000.0
        pinned = phrase_words[0].get("_pinned")
        if pinned:
            anticipated = first_offset_s - (ENTITY_ANTICIPATION_MS / 1000.0)
            start_s = max(prev_end_s, anticipated)
        else:
            start_s = first_offset_s
        end_s = _word_end_ms(phrase_words[-1]) / 1000.0
        text = " ".join(w["text"] for w in phrase_words)
        entry = {
            "phrase_idx": i,
            "section_id": phrase_words[0].get("section_id", ""),
            "start_s": round(start_s, 3),
            "end_s": round(end_s, 3),
            "duration_s": round(end_s - start_s, 3),
            "text": text,
        }
        if pinned:
            entry["pinned_entity_kind"] = pinned[0]   # company|person|product
            entry["pinned_entity_name"] = pinned[1]
        out.append(entry)
        prev_end_s = end_s

    # FINAL FIX 1: extend short entity beats to >= 1.5s by stealing
    # from the next phrase. Keeps the entity visual on screen long
    # enough to register, while preserving the snap-to-word start.
    MIN_ENTITY_DUR = 1.5
    MAX_STEAL = 1.2
    for i in range(len(out) - 1):
        cur, nxt = out[i], out[i + 1]
        if cur.get("pinned_entity_name") and cur["duration_s"] < MIN_ENTITY_DUR:
            shortfall = MIN_ENTITY_DUR - cur["duration_s"]
            steal = min(shortfall, MAX_STEAL,
                        max(0.0, nxt["duration_s"] - 0.6))
            if steal <= 0:
                continue
            cur["end_s"] = round(cur["end_s"] + steal, 3)
            cur["duration_s"] = round(cur["end_s"] - cur["start_s"], 3)
            nxt["start_s"] = cur["end_s"]
            nxt["duration_s"] = round(nxt["end_s"] - nxt["start_s"], 3)
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
