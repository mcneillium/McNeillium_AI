#!/usr/bin/env python3
"""
McNeillium_AI — Agent 57: Colour System Director (Phase 10)

Builds a per-video colour palette so every illustration, stat card,
caption, and grade pulls from the same set. The aim is element-colour
consistency: if "retriever" is green in one illustration, it must be
green everywhere it appears, including the captions.

Output: output/color_palette.json
{
  "palette": {
    "primary":   "#5BA3F5",   // BLUE — main entity
    "secondary": "#7EE787",   // GREEN — second entity
    "tertiary":  "#FFA657",   // ORANGE — quantity / stats
    "quaternary":"#BC8CFF",   // PURPLE — supporting concept
    "warning":   "#FF7B72",
    "neutral":   "#E6EDF3"
  },
  "term_colours": {
    "retriever": "#7EE787",
    "llm":       "#BC8CFF",
    ...
  }
}

The Caption Designer reads `term_colours`. The Illustration Engineer
reads `palette` slots. The Style Director reads palette for grade.

Heuristic: pick the 4-6 most-mentioned content nouns from the script,
assign them to palette slots in order. Sentinel terms (numbers, warning,
error) get fixed colours.
"""

import argparse
import collections
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
PALETTE_PATH = PROJECT_ROOT / "output" / "color_palette.json"


PALETTE = {
    "primary":    "#5BA3F5",
    "secondary":  "#7EE787",
    "tertiary":   "#FFA657",
    "quaternary": "#BC8CFF",
    "quinary":    "#FFDC6E",
    "warning":    "#FF7B72",
    "neutral":    "#E6EDF3",
}


STOPWORDS = {
    "the", "a", "an", "of", "in", "on", "to", "and", "or", "for", "with",
    "from", "by", "is", "are", "be", "was", "were", "have", "has", "had",
    "this", "that", "these", "those", "it", "its", "as", "at", "but",
    "if", "then", "than", "so", "do", "does", "did", "not", "no", "yes",
    "all", "some", "any", "you", "your", "we", "they", "their", "our",
    "us", "them", "i", "me", "my", "he", "she", "his", "her", "him",
    "what", "which", "who", "how", "why", "when", "where", "while",
    "about", "into", "out", "up", "down", "over", "under", "more",
    "most", "less", "very", "just", "only", "even", "also", "much",
    "many", "one", "two", "three", "first", "second", "third",
    "today", "yesterday", "last", "next", "every", "each", "still",
    "again", "before", "after", "now", "here", "there", "really",
    "actually", "thing", "way", "people", "lot", "kind",
}


CONCEPT_BOOST = {
    "model", "agent", "agents", "vector", "embedding", "retrieval",
    "retriever", "llm", "transformer", "attention", "softmax",
    "encoder", "decoder", "query", "key", "value", "context",
    "prompt", "token", "chunk", "database", "search", "rag",
    "rank", "ranker", "rerank", "reranker", "fine-tune", "tuning",
    "memory", "session", "anthropic", "openai", "google", "claude",
}


def _content_nouns(script, k=6):
    text_blob = " ".join(
        s.get("narration", "") for s in script.get("sections", [])
    )
    words = re.findall(r"[A-Za-z][A-Za-z'-]+", text_blob.lower())
    counts = collections.Counter()
    for w in words:
        if w in STOPWORDS or len(w) < 4:
            continue
        boost = 3 if w in CONCEPT_BOOST else 1
        counts[w] += boost
    # Penalise verbs / generic words that aren't usually entities
    for w in ("would", "could", "should", "happens", "happen",
              "means", "going", "right", "looks", "look"):
        counts.pop(w, None)
    return [w for w, _ in counts.most_common(k)]


def build_palette(script):
    nouns = _content_nouns(script, k=8)
    slots = ["primary", "secondary", "tertiary", "quaternary",
             "quinary"]
    term_colours = {}
    for slot, term in zip(slots, nouns):
        term_colours[term] = PALETTE[slot]
    # Always-fixed sentinel mappings
    term_colours.update({
        "warning": PALETTE["warning"],
        "danger": PALETTE["warning"],
        "error": PALETTE["warning"],
        "critical": PALETTE["warning"],
    })
    return {
        "palette": PALETTE,
        "term_colours": term_colours,
        "top_nouns": nouns,
    }


def run(script_path, palette_path):
    if not Path(script_path).exists():
        print(f"❌ Script not found: {script_path}")
        return False
    with open(script_path, encoding="utf-8") as f:
        script = json.load(f)
    data = build_palette(script)
    Path(palette_path).parent.mkdir(parents=True, exist_ok=True)
    Path(palette_path).write_text(json.dumps(data, indent=2),
                                  encoding="utf-8")
    print(f"🎨 Colour palette built for {script.get('title')!r}")
    for term, col in data["term_colours"].items():
        print(f"   {term:18s} {col}")
    print(f"💾 → {palette_path}")
    return True


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--script", default=str(SCRIPT_PATH))
    p.add_argument("--out", default=str(PALETTE_PATH))
    args = p.parse_args()
    ok = run(args.script, args.out)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
