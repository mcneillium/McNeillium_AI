#!/usr/bin/env python3
"""
McNeillium_AI — ASS Subtitle Caption Generator
Converts word-level timestamps into karaoke-style ASS subtitles.
Current word: yellow + bold + slight scale-up.
Past words: white at 70% opacity.
"""

import json
from pathlib import Path

# ASS uses &HAABBGGRR (hex, alpha-blue-green-red) for colours
YELLOW = "&H0000FFFF"       # bright yellow FFFF00
WHITE_70 = "&H4DFFFFFF"     # white at ~70% opacity
OUTLINE_BLACK = "&H00000000"
SHADOW_BLACK = "&H80000000"

FONT_NAME = "Arial Black"
FONT_SIZE = 48
OUTLINE_WIDTH = 3
SHADOW_DEPTH = 2
MAX_VISIBLE_WORDS = 4
MARGIN_BOTTOM_PCT = 18       # percent from bottom


def _ass_timestamp(ms: float) -> str:
    """Convert milliseconds to ASS timestamp H:MM:SS.cc (centiseconds)."""
    total_cs = int(ms / 10)
    cs = total_cs % 100
    total_s = total_cs // 100
    s = total_s % 60
    m = (total_s // 60) % 60
    h = total_s // 3600
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _build_header(width: int, height: int) -> str:
    """Generate the ASS file header with style definitions."""
    margin_v = int(height * MARGIN_BOTTOM_PCT / 100)

    return f"""[Script Info]
Title: McNeillium_AI Captions
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Active,{FONT_NAME},{FONT_SIZE},{YELLOW},&H000000FF,{OUTLINE_BLACK},{SHADOW_BLACK},-1,0,0,0,110,110,0,0,1,{OUTLINE_WIDTH},{SHADOW_DEPTH},2,20,20,{margin_v},1
Style: Past,{FONT_NAME},{FONT_SIZE},{WHITE_70},&H000000FF,{OUTLINE_BLACK},{SHADOW_BLACK},-1,0,0,0,100,100,0,0,1,{OUTLINE_WIDTH},{SHADOW_DEPTH},2,20,20,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def generate_ass(words: list[dict], output_path: str,
                 width: int = 1920, height: int = 1080) -> str:
    """
    Generate an ASS subtitle file with karaoke-style word highlights.

    Args:
        words: list of {"text": str, "offset_ms": float, "duration_ms": float}
        output_path: where to save the .ass file
        width/height: video resolution

    Returns:
        path to the generated .ass file
    """
    if not words:
        return None

    lines = [_build_header(width, height)]

    # Group words into display chunks of MAX_VISIBLE_WORDS
    chunks = []
    for i in range(0, len(words), MAX_VISIBLE_WORDS):
        chunk = words[i:i + MAX_VISIBLE_WORDS]
        chunks.append(chunk)

    for chunk in chunks:
        chunk_start_ms = chunk[0]["offset_ms"]
        chunk_end_ms = chunk[-1]["offset_ms"] + chunk[-1]["duration_ms"]

        # Render each word in the chunk as it becomes active
        for word_idx, word in enumerate(chunk):
            word_start = word["offset_ms"]
            word_end = word_start + word["duration_ms"]

            # Build the text line: past words (white) + active word (yellow) + future (hidden)
            # Active word event: show from word_start to word_end
            text_parts = []
            for j, w in enumerate(chunk):
                if j < word_idx:
                    # Past word — white at 70% opacity
                    text_parts.append(f"{{\\rPast}}{w['text']} ")
                elif j == word_idx:
                    # Active word — yellow, scaled up
                    text_parts.append(f"{{\\rActive}}{w['text']} ")
                # Future words not shown

            text = "".join(text_parts).rstrip()

            start_ts = _ass_timestamp(word_start)
            end_ts = _ass_timestamp(word_end)

            lines.append(
                f"Dialogue: 0,{start_ts},{end_ts},Active,,0,0,0,,{text}"
            )

        # After all words in chunk have been active, show them all as "past"
        # for a brief moment until next chunk starts
        last_word = chunk[-1]
        past_start = last_word["offset_ms"] + last_word["duration_ms"]

        if chunks.index(chunk) < len(chunks) - 1:
            next_chunk_start = chunks[chunks.index(chunk) + 1][0]["offset_ms"]
        else:
            next_chunk_start = past_start + 500

        if next_chunk_start > past_start + 50:
            all_past = " ".join(f"{w['text']}" for w in chunk)
            lines.append(
                f"Dialogue: 0,{_ass_timestamp(past_start)},"
                f"{_ass_timestamp(next_chunk_start)},Past,,0,0,0,,{all_past}"
            )

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w", encoding="utf-8-sig") as f:
        f.write("\n".join(lines))

    return str(output)


def load_verified_words(verified_path: str,
                         audio_start_offset_ms: float) -> list[dict] | None:
    """
    Load Whisper-verified word timestamps written by Agent 26 (sync_validator).
    Word offset_ms is stored relative to the audio start, so we add the
    intro/logo offset to align with the final video timeline.

    Returns None if no verified file exists or it has no words.
    """
    path = Path(verified_path)
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None
    words = data.get("words", []) if isinstance(data, dict) else []
    if not words:
        return None
    return [
        {
            "text": w["text"],
            "offset_ms": float(w["offset_ms"]) + audio_start_offset_ms,
            "duration_ms": float(w["duration_ms"]),
        }
        for w in words
    ]


def load_caption_words(captions_dir: str, section_indices: list[tuple[int, str]],
                       section_offsets_ms: list[float]) -> list[dict]:
    """
    Load per-section caption JSONs and merge into a single word list
    with absolute timestamps.

    Args:
        captions_dir: path to output/audio/captions/
        section_indices: list of (index, section_id) tuples
        section_offsets_ms: cumulative start time of each section in ms

    Returns:
        merged list of {"text", "offset_ms", "duration_ms"} with absolute times
    """
    all_words = []
    cap_dir = Path(captions_dir)

    for (idx, sid), offset_ms in zip(section_indices, section_offsets_ms):
        cap_file = cap_dir / f"segment_{idx:02d}_{sid}.json"
        if not cap_file.exists():
            continue

        try:
            with open(cap_file, encoding="utf-8") as f:
                words = json.load(f)
        except Exception:
            continue

        if not words:
            continue

        for w in words:
            all_words.append({
                "text": w["text"],
                "offset_ms": w["offset_ms"] + offset_ms,
                "duration_ms": w["duration_ms"],
            })

    return all_words


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python captions.py <captions_dir_or_json> [output.ass]")
        sys.exit(1)

    src = Path(sys.argv[1])
    out = sys.argv[2] if len(sys.argv) > 2 else "captions.ass"

    if src.is_file() and src.suffix == ".json":
        with open(src, encoding="utf-8") as f:
            words = json.load(f)
        result = generate_ass(words, out)
        if result:
            print(f"Generated {result} with {len(words)} words")
    else:
        print("Provide a JSON file with word timestamps")
