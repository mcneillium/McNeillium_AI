#!/usr/bin/env python3
"""
McNeillium_AI — Phrase / Viral Caption Designer (Phase 11)

The Phase 10 phrase caption renderer was straight ASS text lines — fine
but not viral. Phase 11 rewrites this to the TikTok / Reels style:

  - Font: Impact 96pt (104pt for reaction mode)
  - White text past words at 75% opacity, current word yellow #FFEB3B
    at 110% scale
  - 6px black outline, 4px drop shadow
  - Semi-transparent dark backdrop blob behind the active word
    (BorderStyle=3 with BackColour ≈ 0.65 opacity)
  - Position: bottom 22% of frame, centered
  - Phrase mode: groups up to 3 words at a time (explainer, tutorial)
  - Word mode: word-by-word with active highlight (reaction, fireship)

The renderer emits one ASS Dialogue line per ACTIVE word. The line
shows the surrounding context (past words muted, active word styled)
so the viewer reads the active word against its phrase, not in
isolation. This is the same karaoke mechanic captions.py uses for word
captions — Phase 11 just upgrades the font, sizing, and positioning.
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


# ASS colours are &HAABBGGRR
WHITE         = "&H00FFFFFF"
WHITE_75      = "&H40FFFFFF"   # alpha 0x40 (~75% opacity)
YELLOW_ACTIVE = "&H0035EBFF"   # #FFEB3B → BGR 0x35EBFF (slight muted yellow because ASS expects BGR)
BLACK_OUTLINE = "&H00000000"
DROP_SHADOW   = "&H80000000"
BACKDROP_DARK = "&HA0000000"   # alpha 0xA0 (~37% transparent dark blob)


# Font fallback list — libass picks the first match
PRIMARY_FONT = "Impact"
FALLBACK_FONT = "Arial Black"


# ─── Pair-based grouping (Phase 12.1) ──────────────────────────
# Hard cap of 2 words on screen at a time. No fade, no scale, no
# backdrop blob. Each PAIR is shown as a unit from word1.start to
# word2.end (or just word1.end for the trailing single).

def group_pairs(words):
    """Group words into max-2-word pairs."""
    return [words[i:i + 2] for i in range(0, len(words), 2)]


# ─── ASS rendering ──────────────────────────────────────────────

def _ass_ts(ms):
    total_cs = int(ms / 10)
    cs = total_cs % 100
    total_s = total_cs // 100
    s = total_s % 60
    m = (total_s // 60) % 60
    h = total_s // 3600
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def _render_pair_dialogues(pair):
    """Emit dialogue lines for a 1-2 word pair.

    Phase 12.1 lockdown rules:
      - Single ASS Style ("Lock") for every line → libass renders every
        line at the same baseline. No flashing.
      - No fade in/out. No scale animation. Inline colour overrides
        only (yellow active, white past), nothing that changes glyph
        metrics.
      - Both words of a pair stay on screen for the whole pair window.
    """
    if len(pair) == 1:
        w = pair[0]
        start = w["offset_ms"]
        end = w["offset_ms"] + w["duration_ms"]
        text = f"{{\\c{YELLOW_ACTIVE}}}{w['text']}"
        return [
            f"Dialogue: 0,{_ass_ts(start)},{_ass_ts(end)},Lock,,0,0,0,,{text}"
        ]

    w1, w2 = pair
    t1_start = w1["offset_ms"]
    t1_end = w1["offset_ms"] + w1["duration_ms"]
    t2_start = w2["offset_ms"]
    t2_end = w2["offset_ms"] + w2["duration_ms"]

    lines = []
    # Window A: word1 is being spoken (yellow), word2 is queued ahead (white)
    text_a = (
        f"{{\\c{YELLOW_ACTIVE}}}{w1['text']}{{\\c{WHITE}}} "
        f"{{\\c{WHITE_75}}}{w2['text']}"
    )
    lines.append(
        f"Dialogue: 0,{_ass_ts(t1_start)},{_ass_ts(t2_start)},"
        f"Lock,,0,0,0,,{text_a}"
    )
    # Window B: word2 is being spoken (yellow), word1 is past (faded white)
    text_b = (
        f"{{\\c{WHITE_75}}}{w1['text']}{{\\c{WHITE}}} "
        f"{{\\c{YELLOW_ACTIVE}}}{w2['text']}"
    )
    lines.append(
        f"Dialogue: 0,{_ass_ts(t2_start)},{_ass_ts(t2_end)},"
        f"Lock,,0,0,0,,{text_b}"
    )
    return lines


def build_viral_ass(words, output_path, width=1920, height=1080,
                    mode="reaction", palette=None):
    """Phase 12.1 locked-position renderer.

    - Single Style "Lock", same on every line — baseline never moves.
    - Anchor 2 (bottom-centre) + MarginV pinned at 25% of frame height
      from the bottom, putting the caption strip baseline at y≈75% of
      a 1080p frame. The Y coordinate is locked across the whole video.
    - 8px black outline, 4px shadow, no backdrop box, no scale, no fade.
    - Max 2 words on screen at any time (pair-based).

    `mode` only changes font size:
      reaction → 104pt, everything else → 96pt.
    The palette argument is accepted but ignored — Phase 12.1 simplifies
    captions to a single yellow/white scheme to stop the flashing.
    """
    if not words:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text("", encoding="utf-8-sig")
        return str(output_path), 0

    font_size = 104 if mode == "reaction" else 96
    # 25% of frame from the bottom — text bottom sits at y = 75% × H,
    # so the visible text strip spans ~65-75% (96-104pt is ~120-130px
    # tall at 1080p). Locked. Never moves.
    margin_v = int(height * 0.25)

    # ONE style for every line. Outline 8, shadow 4, BorderStyle 1
    # (outline only — no backdrop box to flash). The yellow/white
    # split is done with inline {\c...} overrides on the same Style.
    header = f"""[Script Info]
Title: McNeillium_AI Locked Captions (Phase 12.1)
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Lock,{PRIMARY_FONT},{font_size},{WHITE},&H000000FF,{BLACK_OUTLINE},&H80000000,-1,0,0,0,100,100,0,0,1,8,4,2,40,40,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    body = []
    for pair in group_pairs(words):
        body.extend(_render_pair_dialogues(pair))

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(header + "\n".join(body) + "\n",
                                  encoding="utf-8-sig")
    return str(output_path), len(body)


def build_phrase_ass(words, output_path, width=1920, height=1080,
                     fade_ms=200, palette=None, technical_terms=None,
                     position_hint_by_time=None, mode="fireship"):
    """Compat shim — generate_video.py calls this name. Phase 11 routes
    every call through the new viral renderer."""
    path, count = build_viral_ass(
        words, output_path, width=width, height=height,
        mode=mode, palette=palette or {},
    )
    return path, count


# ═══════════════════════════════════════════════════════════════
# Phase 12.2 — Shorts subtitle generator (plain, mid-frame, no flash)
# ═══════════════════════════════════════════════════════════════
#
# Used ONLY by utils/shorts_producer.py. Long-form videos no longer
# burn captions. This generator:
#   - Groups Whisper/AssemblyAI words into SENTENCES then splits to
#     6-word max chunks (CHUNK_MAX_WORDS)
#   - Holds each chunk 2.0-2.8s (CHUNK_HOLD_MIN_MS / MAX_MS)
#   - Plain white text + thick black outline, no animations
#   - Position middle of frame (alignment 5)
#   - Designed for 1080x1920 vertical (Shorts)

CHUNK_MAX_WORDS = 6
CHUNK_HOLD_MIN_MS = 2000
CHUNK_HOLD_MAX_MS = 2800
SHORT_FONT = "Arial Black"   # Reliably available on Windows + Linux
SHORT_FONT_SIZE = 60          # Reads cleanly at 1080 wide


def group_sentences_for_short(words, max_words=CHUNK_MAX_WORDS,
                               hold_min_ms=CHUNK_HOLD_MIN_MS,
                               hold_max_ms=CHUNK_HOLD_MAX_MS):
    """Split words into sentence-like chunks for Shorts subtitling.

    Breaks at:
      - end-of-sentence punctuation
      - max_words reached
      - cumulative duration >= hold_max_ms
    Hold each chunk for at least hold_min_ms (extends the end time of
    the last chunk's last word if necessary).
    """
    chunks = []
    buf = []
    for i, w in enumerate(words):
        buf.append(w)
        ends_sentence = w["text"].rstrip().endswith((".", "?", "!", ":"))
        end_ms = w["offset_ms"] + w["duration_ms"]
        chunk_dur = end_ms - buf[0]["offset_ms"]
        if (len(buf) >= max_words
                or chunk_dur >= hold_max_ms
                or ends_sentence
                or i == len(words) - 1):
            chunks.append(buf)
            buf = []
    return chunks


def build_short_subtitles_ass(words, output_path, width=1080, height=1920):
    """Emit a plain-style subtitle ASS file for a Short.

    `words` should be in SHORT-LOCAL time — i.e. the first word at the
    Short's start is offset_ms=0. shorts_producer.py shifts the master
    word list before calling.
    """
    if not words:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text("", encoding="utf-8-sig")
        return str(output_path), 0

    chunks = group_sentences_for_short(words)

    header = f"""[Script Info]
Title: McNeillium Shorts Subtitles
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: ShortSub,{SHORT_FONT},{SHORT_FONT_SIZE},{WHITE},&H000000FF,{BLACK_OUTLINE},&H00000000,-1,0,0,0,100,100,0,0,1,5,2,5,80,80,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    body = []
    for chunk in chunks:
        start = chunk[0]["offset_ms"]
        last = chunk[-1]
        end = last["offset_ms"] + last["duration_ms"]
        # Pad to hold for at least min_hold so the eye has time to read
        if end - start < CHUNK_HOLD_MIN_MS:
            end = start + CHUNK_HOLD_MIN_MS
        text = " ".join(w["text"].strip() for w in chunk).strip()
        # Escape ASS-special characters: { } \
        text = (text.replace("\\", "\\\\")
                    .replace("{", "\\{").replace("}", "\\}"))
        body.append(
            f"Dialogue: 0,{_ass_ts(start)},{_ass_ts(end)},"
            f"ShortSub,,0,0,0,,{text}"
        )

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(header + "\n".join(body) + "\n",
                                  encoding="utf-8-sig")
    return str(output_path), len(chunks)


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
    p.add_argument("--out", default="output/audio/viral_captions.ass")
    p.add_argument("--audio-offset-ms", type=float, default=0)
    p.add_argument("--mode", choices=["explainer", "reaction",
                                       "fireship", "tutorial"],
                   default="explainer")
    p.add_argument("--palette", default="output/color_palette.json")
    args = p.parse_args()

    words = load_verified_words(args.verified, args.audio_offset_ms)
    if not words:
        print(f"❌ No words at {args.verified}")
        sys.exit(1)

    palette_map = {}
    if Path(args.palette).exists():
        try:
            data = json.loads(Path(args.palette).read_text(encoding="utf-8"))
            for term, hex_c in data.get("term_colours", {}).items():
                h = hex_c.lstrip("#")
                if len(h) == 6:
                    r, g, b = h[0:2], h[2:4], h[4:6]
                    palette_map[term.lower()] = f"&H00{b}{g}{r}".upper()
        except Exception:
            pass

    path, count = build_viral_ass(
        words, args.out, mode=args.mode, palette=palette_map,
    )
    print(f"📝 Viral captions ({args.mode}): {count} active-word lines → {path}")


if __name__ == "__main__":
    main()
