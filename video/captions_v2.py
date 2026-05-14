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


# ─── Grouping ───────────────────────────────────────────────────

PAUSE_BREAK_MS = 220


def group_phrase(words, max_words=3, min_dur_ms=900, max_dur_ms=3500):
    """Group words into max-N-word display phrases at natural breaks."""
    groups = []
    buf = []
    for i, w in enumerate(words):
        buf.append(w)
        next_w = words[i + 1] if i + 1 < len(words) else None
        end_ms = w["offset_ms"] + w["duration_ms"]
        first_ms = buf[0]["offset_ms"]
        group_dur = end_ms - first_ms
        pause = (next_w["offset_ms"] - end_ms) if next_w else 999
        ends_sentence = w["text"].rstrip().endswith((".", "?", "!", ";"))
        full = len(buf) >= max_words or group_dur >= max_dur_ms
        natural = (group_dur >= min_dur_ms
                   and (pause >= PAUSE_BREAK_MS or ends_sentence))
        if full or natural or next_w is None:
            groups.append(buf)
            buf = []
    return groups


# ─── ASS rendering ──────────────────────────────────────────────

def _ass_ts(ms):
    total_cs = int(ms / 10)
    cs = total_cs % 100
    total_s = total_cs // 100
    s = total_s % 60
    m = (total_s // 60) % 60
    h = total_s // 3600
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _render_group_dialogues(group, font_size, palette_terms):
    """For each word in the group, emit one Dialogue line where that
    word is "active" (yellow + scaled + backdrop) and the others are
    past (white 75%) or future (hidden)."""
    lines = []
    for active_i, active in enumerate(group):
        start = active["offset_ms"]
        end = active["offset_ms"] + active["duration_ms"]
        parts = []
        for j, w in enumerate(group):
            txt = w["text"]
            if j < active_i:
                # Past — pick palette colour if applicable, fall back to white@75%
                term_col = palette_terms.get(_norm(txt))
                if term_col:
                    parts.append(
                        f"{{\\c{term_col}\\alpha&H40&}}{txt}{{\\alpha&H00&\\c{WHITE}}}"
                    )
                else:
                    parts.append(f"{{\\c{WHITE_75}}}{txt}{{\\c{WHITE}}}")
            elif j == active_i:
                # Active — yellow, 110% scale, full opacity
                parts.append(
                    f"{{\\c{YELLOW_ACTIVE}\\fscx110\\fscy110\\bord6}}"
                    f"{txt}"
                    f"{{\\fscx100\\fscy100\\c{WHITE}\\bord6}}"
                )
            # future words: omit
        text = " ".join(parts).rstrip()
        lines.append(
            f"Dialogue: 0,{_ass_ts(start)},{_ass_ts(end)},Active,,0,0,0,,"
            f"{{\\fad(80,80)}}{text}"
        )
    return lines


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def build_viral_ass(words, output_path, width=1920, height=1080,
                    mode="explainer", palette=None):
    """Phase 11 viral renderer. `mode` controls font size and grouping."""
    palette = palette or {}
    palette_terms = {k.lower(): v for k, v in palette.items()}

    if mode == "reaction":
        font_size = 104
        groups = [[w] for w in words]
    elif mode in {"fireship", "tutorial"}:
        font_size = 96
        groups = group_phrase(words, max_words=3,
                              min_dur_ms=700, max_dur_ms=2200)
    else:  # explainer (default)
        font_size = 96
        groups = group_phrase(words, max_words=3,
                              min_dur_ms=900, max_dur_ms=3500)

    margin_v = int(height * 0.22)

    # Active style uses BorderStyle=3 → BackColour fills a dark backdrop
    # blob behind the text. Outline acts as box padding (8 = bigger blob).
    # Past style uses BorderStyle=1 (outline only, no backdrop).
    header = f"""[Script Info]
Title: McNeillium_AI Viral Captions
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Active,{PRIMARY_FONT},{font_size},{WHITE},&H000000FF,{BLACK_OUTLINE},{BACKDROP_DARK},-1,0,0,0,100,100,0,0,3,6,4,2,40,40,{margin_v},1
Style: Past,{PRIMARY_FONT},{font_size},{WHITE_75},&H000000FF,{BLACK_OUTLINE},{DROP_SHADOW},-1,0,0,0,100,100,0,0,1,6,4,2,40,40,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    body = []
    for group in groups:
        body.extend(_render_group_dialogues(group, font_size, palette_terms))

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(header + "\n".join(body) + "\n",
                                  encoding="utf-8-sig")
    return str(output_path), sum(len(g) for g in groups)


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
