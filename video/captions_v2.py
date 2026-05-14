#!/usr/bin/env python3
"""
McNeillium_AI — Agent 53: Phrase Caption Designer (Phase 10)

Phrase-based caption renderer used in explainer (and tutorial) modes.
Groups Whisper-verified word timestamps into 1.5-4s phrases at natural
break points (long pauses, punctuation). Each phrase is rendered as a
single ASS dialogue line with:

  - Soft fade in/out (200ms each side)
  - Semantic colouring of key terms:
      proper nouns → BLUE   (#5BA3F5)
      technical    → TEAL   (#63DCDC)
      numbers/%/x  → ORANGE (#FFA657)
      regular      → WHITE  (#E6EDF3)
  - Drop shadow for legibility
  - Position: bottom 18%, or top 15% when the active beat is an
    illustration (the engineer flags this via the caption_position hint)

Falls back to a single uniform style when no colour palette is provided.
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


# ASS colour format is &HAABBGGRR
WHITE = "&H00E6EDF3"
BLUE = "&H00F5A35B"
TEAL = "&H00DCDC63"
ORANGE = "&H0057A6FF"
GREEN = "&H0087E77E"
PURPLE = "&H00FF8CBC"
OUTLINE = "&H00000000"
SHADOW = "&H80000000"


# Default technical terms — extended by colour palette at runtime
DEFAULT_TECHNICAL = {
    "rag", "embedding", "embeddings", "vector", "vectors", "tokens",
    "token", "transformer", "transformers", "attention", "softmax",
    "encoder", "decoder", "retrieval", "retriever", "context", "llm",
    "model", "models", "neural", "agent", "agents", "prompt", "query",
    "chunks", "chunk", "reranker", "reranking", "fine-tune", "fine-tuning",
}

NUMBER_RE = re.compile(
    r"^\d+(?:[\.,]\d+)?\s*"
    r"(?:%|percent|x|times|m|b|k|million|billion|trillion|"
    r"hertz|hz|hours?|minutes?|seconds?|gb|mb|kb|tb)?$",
    re.I,
)
PROPER_RE = re.compile(r"^[A-Z][a-zA-Z'-]+$")


def _ass_ts(ms):
    total_cs = int(ms / 10)
    cs = total_cs % 100
    total_s = total_cs // 100
    s = total_s % 60
    m = (total_s // 60) % 60
    h = total_s // 3600
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def group_into_phrases(words, min_dur_ms=1500, max_dur_ms=4000,
                       pause_break_ms=200, max_words=5):
    """Group word dicts into phrases at natural break points."""
    phrases = []
    cur = []
    for i, w in enumerate(words):
        cur.append(w)
        end_ms = w["offset_ms"] + w["duration_ms"]
        start_ms = cur[0]["offset_ms"]
        phrase_dur = end_ms - start_ms

        next_w = words[i + 1] if i + 1 < len(words) else None
        pause = (next_w["offset_ms"] - end_ms) if next_w else 999
        text = w["text"].rstrip()
        ends_sentence = text.endswith((".", "?", "!", ":", ";", ","))

        break_here = (
            phrase_dur >= max_dur_ms
            or (phrase_dur >= min_dur_ms and (pause >= pause_break_ms or ends_sentence))
            or len(cur) >= max_words
            or next_w is None
        )
        if break_here:
            phrases.append({
                "words": cur,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "text": " ".join(x["text"].strip() for x in cur),
            })
            cur = []
    return phrases


def _classify(word, technical_terms, palette_terms):
    """Return ASS colour escape for a word."""
    text = re.sub(r"[^\w%-]", "", word).strip()
    if not text:
        return WHITE
    lower = text.lower()

    # Palette match first (highest priority — keeps element-colour consistency)
    if lower in palette_terms:
        return palette_terms[lower]

    if NUMBER_RE.match(text):
        return ORANGE
    if lower in technical_terms:
        return TEAL
    if PROPER_RE.match(text):
        return BLUE
    return WHITE


def _style_phrase_text(phrase_text, technical_terms, palette_terms):
    """Insert per-word ASS colour overrides; first word keeps capitalisation."""
    parts = []
    for word in phrase_text.split():
        col = _classify(word, technical_terms, palette_terms)
        if col == WHITE:
            parts.append(word)
        else:
            parts.append(f"{{\\c{col}}}{word}{{\\c{WHITE}}}")
    return " ".join(parts)


def build_phrase_ass(words, output_path, width=1920, height=1080,
                     fade_ms=200, palette=None, technical_terms=None,
                     position_hint_by_time=None, mode="fireship"):
    """
    palette: dict of {term_lower: ASS_colour}
    technical_terms: extra terms to colour TEAL
    position_hint_by_time: list of (start_ms, end_ms, "top"|"bottom") slots —
        phrases overlapping a "top" slot get rendered at the top instead.
    mode: "explainer" uses Phase 10.1 high-contrast styling (semi-transparent
        backdrop box at alpha 0.65, ExtraBold weight, white outer glow) so
        captions remain legible over Manim's dark stylistic backgrounds.
    """
    palette = palette or {}
    technical_terms = set(t.lower() for t in (technical_terms or []))
    technical_terms.update(DEFAULT_TECHNICAL)

    phrases = group_into_phrases(words)
    margin_v_bottom = int(height * 0.16)
    margin_v_top = int(height * 0.10)

    if mode == "explainer":
        # Backdrop alpha 0xA0 ≈ 0.63 opacity dark box; BorderStyle=3 draws
        # the box, Outline acts as padding around the text. The Outline
        # colour is white at alpha 0xC8 (≈0.22 transparent) — that's the
        # "white outer glow" sitting between text and backdrop.
        styles = (
            f"Style: Phrase,Arial Black,56,{WHITE},&H000000FF,"
            f"&HC8FFFFFF,&HA0000000,-1,0,0,0,100,100,0,0,3,5,3,2,40,40,{margin_v_bottom},1\n"
            f"Style: PhraseTop,Arial Black,56,{WHITE},&H000000FF,"
            f"&HC8FFFFFF,&HA0000000,-1,0,0,0,100,100,0,0,3,5,3,8,40,40,{margin_v_top},1"
        )
    else:
        styles = (
            f"Style: Phrase,Arial Black,52,{WHITE},&H000000FF,"
            f"{OUTLINE},{SHADOW},-1,0,0,0,100,100,0,0,1,3,3,2,40,40,{margin_v_bottom},1\n"
            f"Style: PhraseTop,Arial Black,52,{WHITE},&H000000FF,"
            f"{OUTLINE},{SHADOW},-1,0,0,0,100,100,0,0,1,3,3,8,40,40,{margin_v_top},1"
        )

    header = f"""[Script Info]
Title: McNeillium_AI Phrase Captions
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
{styles}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]

    def _position_at(t_ms):
        if not position_hint_by_time:
            return "Phrase"
        for s, e, where in position_hint_by_time:
            if s <= t_ms <= e:
                return "PhraseTop" if where == "top" else "Phrase"
        return "Phrase"

    for ph in phrases:
        start = ph["start_ms"]
        end = ph["end_ms"]
        styled = _style_phrase_text(ph["text"], technical_terms, palette)
        style = _position_at((start + end) // 2)
        # Fade prefix: {\fad(in_ms,out_ms)}
        prefix = f"{{\\fad({fade_ms},{fade_ms})}}"
        lines.append(
            f"Dialogue: 0,{_ass_ts(start)},{_ass_ts(end)},{style},,0,0,0,,"
            f"{prefix}{styled}"
        )

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text("\n".join(lines), encoding="utf-8-sig")
    return str(output_path), len(phrases)


def load_verified_words(verified_path, audio_offset_ms=0):
    p = Path(verified_path)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []
    words = data.get("words", []) if isinstance(data, dict) else []
    return [
        {
            "text": w["text"],
            "offset_ms": float(w["offset_ms"]) + audio_offset_ms,
            "duration_ms": float(w["duration_ms"]),
        }
        for w in words
    ]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--verified",
                   default="output/audio/latest_words_verified.json")
    p.add_argument("--palette", default="output/color_palette.json")
    p.add_argument("--out", default="output/audio/phrase_captions.ass")
    p.add_argument("--audio-offset-ms", type=float, default=0)
    args = p.parse_args()

    words = load_verified_words(args.verified, args.audio_offset_ms)
    if not words:
        print(f"❌ No words at {args.verified}")
        sys.exit(1)

    palette_map = {}
    if Path(args.palette).exists():
        try:
            data = json.loads(Path(args.palette).read_text(encoding="utf-8"))
            for term, hex_colour in data.get("term_colours", {}).items():
                # Convert #RRGGBB to ASS &HAABBGGRR
                h = hex_colour.lstrip("#")
                if len(h) == 6:
                    r, g, b = h[0:2], h[2:4], h[4:6]
                    palette_map[term.lower()] = f"&H00{b}{g}{r}".upper()
        except Exception:
            pass

    path, count = build_phrase_ass(words, args.out, palette=palette_map)
    print(f"📝 Phrase captions: {count} phrases → {path}")


if __name__ == "__main__":
    main()
