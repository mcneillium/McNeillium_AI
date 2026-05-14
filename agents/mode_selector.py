#!/usr/bin/env python3
"""
McNeillium_AI — Agent 52: Production Mode Selector (Phase 10)

Reads the script and picks one of four production modes. The mode
config is written to output/mode_config.json and consumed by:

  - Video Producer   (beat hold durations, footage:illustration ratio)
  - Caption Designer (phrase vs word, semantic vs plain)
  - Music Composer   (ambient vs energetic vs dramatic vs calm)
  - Visual Director  (shot density target)

Modes:
  fireship   — news/reactions, fast cuts (5-8s), heavy stock
  explainer  — 3B1B-style deep dives, held shots (15-30s), illustration-heavy
  reaction   — breaking news, very fast cuts (3-5s), meme inserts
  tutorial   — how-to / walkthroughs, slow steps (10-15s), code-heavy
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
CONFIG_PATH = PROJECT_ROOT / "output" / "mode_config.json"


# Mode → config dict.
# beat_hold_seconds: min target duration per beat in this mode
# footage_to_illustration: target percentage of beats that are stock vs custom
# caption_style: word_simple | word_emphasis | phrase_semantic | phrase_code
# music_style: energetic | minimal_ambient | dramatic | focused_calm
# illustration_density_per_minute: target illustrations per minute of narration
MODE_CONFIGS = {
    "fireship": {
        "beat_hold_seconds": [5, 8],
        "footage_to_illustration": 70,
        "caption_style": "word_simple",
        "music_style": "energetic",
        "illustration_density_per_minute": 0.5,
        "stat_card_emphasis": "high",
        "color_palette_intensity": "default",
    },
    "explainer": {
        "beat_hold_seconds": [15, 30],
        "footage_to_illustration": 20,
        "caption_style": "phrase_semantic",
        "music_style": "minimal_ambient",
        "illustration_density_per_minute": 2.4,
        "stat_card_emphasis": "subtle",
        "color_palette_intensity": "strong",
    },
    "reaction": {
        "beat_hold_seconds": [3, 5],
        "footage_to_illustration": 80,
        "caption_style": "word_emphasis",
        "music_style": "dramatic",
        "illustration_density_per_minute": 0.25,
        "stat_card_emphasis": "high",
        "color_palette_intensity": "default",
    },
    "tutorial": {
        "beat_hold_seconds": [10, 15],
        "footage_to_illustration": 30,
        "caption_style": "phrase_code",
        "music_style": "focused_calm",
        "illustration_density_per_minute": 1.2,
        "stat_card_emphasis": "subtle",
        "color_palette_intensity": "default",
    },
}


# Title-pattern triggers — ordered most-specific first.
# Phase 12 pivot: explainer mode is now opt-in only. The title must
# START with "Explainer:" (case-insensitive). Without that prefix we
# pick reaction by default — the channel is an AI news channel now.
EXPLAINER_PREFIX_RE = re.compile(r"^\s*explainer\s*:", re.I)
REACTION_RE = re.compile(
    r"\b(just\s+(?:launched|released|got|added|dropped|shipped|"
    r"announced|tweeted|said|gave|raised|revealed)|"
    r"breaking|"
    r"now has|now offers|"
    r"new\s+(?:from|in)\s+|"
    r"announces?|launches?|releases?|"
    r"\b(?:yesterday|today|this morning|this week)\b|"
    r"quietly|cooked|finally|reacts?\b)",
    re.I,
)
TUTORIAL_RE = re.compile(
    r"\b(build\s+(?:your|a|an)|"
    r"how to\s+(?:build|create|make|use|setup|set up|install|deploy)|"
    r"tutorial|walkthrough|step by step|step-by-step|"
    r"\bfrom scratch\b)",
    re.I,
)


def select_mode(script):
    """Pick a mode for this script. Returns (mode_name, reason).

    Phase 12 pivot policy:
      1. explainer  — opt-in only, requires "Explainer:" title prefix
      2. tutorial   — opt-in via build/tutorial/walkthrough patterns
      3. reaction   — DEFAULT for everything else (the channel is a
                      daily AI news/commentary show)
    """
    title = (script.get("title") or "").strip()
    meta = script.get("metadata") or {}
    pillar = (meta.get("content_pillar") or "").lower()

    # Explainer is opt-in only — explicit "Explainer:" prefix
    if EXPLAINER_PREFIX_RE.match(title) or pillar in {
        "deep_dive", "fundamentals", "explainer",
    }:
        return "explainer", f"explicit explainer opt-in (prefix or pillar)"

    if pillar in {"tutorial", "build", "walkthrough"} or TUTORIAL_RE.search(title):
        return "tutorial", "tutorial pillar or title pattern"

    # Everything else is reaction (news/commentary default).
    if pillar in {"breaking_news", "news", "reaction", "daily_roundup",
                  "tool_review", "weekly_recap", "industry_analysis"}:
        return "reaction", f"news pillar={pillar!r}"
    if REACTION_RE.search(title):
        return "reaction", "title matches news/reaction pattern"

    return "reaction", "default (news channel — pivoted Phase 12)"


def run(script_path, config_path):
    if not Path(script_path).exists():
        print(f"❌ Script not found: {script_path}")
        return False
    with open(script_path, encoding="utf-8") as f:
        script = json.load(f)

    mode, reason = select_mode(script)
    config = {
        "mode": mode,
        "reason": reason,
        "title": script.get("title"),
        **MODE_CONFIGS[mode],
    }
    Path(config_path).parent.mkdir(parents=True, exist_ok=True)
    Path(config_path).write_text(json.dumps(config, indent=2), encoding="utf-8")
    print(f"🎯 Mode Selector — chose `{mode}`")
    print(f"   reason: {reason}")
    for k, v in MODE_CONFIGS[mode].items():
        print(f"   {k}: {v}")
    print(f"💾 Mode config → {config_path}")
    return True


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--script", default=str(SCRIPT_PATH))
    p.add_argument("--out", default=str(CONFIG_PATH))
    args = p.parse_args()
    ok = run(args.script, args.out)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
