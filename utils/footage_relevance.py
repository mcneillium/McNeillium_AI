#!/usr/bin/env python3
"""
McNeillium_AI — Agent 25: Footage Relevance Checker

Reviews the shot list and scores each beat's `query` against the narration
of its parent section. Generic, low-information queries (data flowing, AI,
technology, innovation, future, abstract, digital) are rejected. The agent
rewrites weak queries to use concrete nouns and visual descriptors before
the Video Producer ever runs.

Heuristic scoring (no LLM needed) — fast and deterministic:
  - Banned-term coverage     → caps score at 4 if the query is mostly banned terms
  - Concrete-noun overlap    → +1 per content-bearing word also in the narration
  - Visual-descriptor bonus  → +2 if the query names a colour, lighting, angle,
                              or composition cue (e.g. "close up", "aerial")
  - Length sanity            → 4-8 words is the sweet spot; outside that → -1
  - Section-id alignment     → +1 if the query nods to the section's purpose

Beats scoring <7 are rewritten using a per-section concrete-noun bank.
"""

import argparse
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SHOT_LIST_PATH = PROJECT_ROOT / "output" / "shot_list.json"
SCRIPT_PATH = PROJECT_ROOT / "output" / "scripts" / "latest.json"
REPORT_DIR = PROJECT_ROOT / "knowledge_base" / "reviews"


BANNED_TERMS = {
    "technology", "innovation", "data flowing", "data flow",
    "ai", "artificial intelligence", "digital", "future",
    "abstract", "concept", "modern", "cyber", "tech", "futuristic",
    "data", "information", "computing", "computer",
}

VISUAL_DESCRIPTORS = {
    "close up", "closeup", "wide shot", "aerial", "drone", "macro",
    "overhead", "tilt", "tracking", "slow motion",
    "blue", "red", "green", "orange", "purple", "neon",
    "dark", "bright", "glowing", "lit", "dim", "warm", "cool",
    "rack", "office", "desk", "room", "warehouse", "factory",
    "screen", "monitor", "keyboard", "headphones", "cable",
    "binary", "code on screen",
}

STOPWORDS = {
    "the", "a", "an", "of", "in", "on", "to", "and", "or", "for",
    "with", "from", "by", "is", "are", "be", "was", "were", "have",
    "has", "had", "this", "that", "these", "those", "it", "its",
    "as", "at", "but", "if", "then", "than", "so", "do", "does",
    "did", "not", "no", "yes", "all", "some", "any", "you", "your",
    "we", "they", "their", "our", "us", "them", "i", "me", "my",
    "he", "she", "his", "her", "him", "what", "which", "who", "how",
    "why", "when", "where", "while", "about", "into", "out", "up",
    "down", "over", "under", "again", "more", "most", "less",
    "very", "just", "only", "even", "also", "much", "many",
    "one", "two", "three", "first", "second", "third",
}


def _words(s):
    return [w for w in re.findall(r"[A-Za-z]+", s.lower())
            if w not in STOPWORDS and len(w) > 2]


def _contains_banned(query):
    q = query.lower()
    hits = 0
    for term in BANNED_TERMS:
        if re.search(rf"\b{re.escape(term)}\b", q):
            hits += 1
    return hits


def _contains_visual(query):
    q = query.lower()
    for term in VISUAL_DESCRIPTORS:
        if term in q:
            return True
    return False


def score_query(query, narration, section_id=""):
    """Return (score 1-10, list of reasons)."""
    if not query:
        return 1, ["empty query"]

    reasons = []
    score = 5

    word_count = len(query.split())
    if 4 <= word_count <= 8:
        score += 1
        reasons.append(f"good length ({word_count})")
    elif word_count < 3:
        score -= 2
        reasons.append(f"too short ({word_count})")
    elif word_count > 10:
        score -= 1
        reasons.append(f"too long ({word_count})")

    banned_hits = _contains_banned(query)
    if banned_hits >= 2:
        score = min(score, 3)
        reasons.append(f"contains {banned_hits} banned generic terms")
    elif banned_hits == 1:
        score -= 1
        reasons.append("one banned generic term")

    if _contains_visual(query):
        score += 2
        reasons.append("has visual descriptor")
    else:
        score -= 1
        reasons.append("no visual descriptor")

    q_words = set(_words(query))
    n_words = set(_words(narration))
    overlap = q_words & n_words
    overlap_bonus = min(2, len(overlap))
    if overlap_bonus > 0:
        score += overlap_bonus
        reasons.append(f"{len(overlap)} concrete words overlap narration")
    elif q_words:
        score -= 1
        reasons.append("no narration overlap")

    # Section-id-specific bonus
    if section_id in {"hook", "outro"} and any(
        w in query.lower() for w in ("aerial", "city", "sunset", "drone")
    ):
        score += 1
        reasons.append("matches hook/outro vibe")

    score = max(1, min(10, score))
    return score, reasons


# ═══════════════════════════════════════════════════════════════
# Rewriting weak queries
# ═══════════════════════════════════════════════════════════════

SECTION_FALLBACKS = {
    "hook": "city skyline night drone aerial",
    "intro": "server room blue LEDs close up",
    "demo": "developer hands keyboard dark monitor",
    "summary": "data centre racks blue lights wide shot",
    "outro": "sunset cityscape timelapse warm tones",
}

DEFAULT_VISUAL_ADDENDA = [
    "close up", "dark room", "blue lights", "wide shot",
    "macro detail", "office desk", "screen glow",
]


def _extract_concrete_nouns(narration, k=4):
    """Pick the k most concrete nouns from narration."""
    raw = _words(narration)
    counts = {}
    for w in raw:
        if w in BANNED_TERMS:
            continue
        counts[w] = counts.get(w, 0) + 1
    sorted_nouns = sorted(counts.items(), key=lambda x: (-x[1], x[0]))
    return [w for w, _ in sorted_nouns[:k]]


def rewrite_query(narration, section_id, visual_idx=0):
    """Build a stronger query from narration nouns + a visual descriptor."""
    nouns = _extract_concrete_nouns(narration, 3)
    descriptor = DEFAULT_VISUAL_ADDENDA[
        visual_idx % len(DEFAULT_VISUAL_ADDENDA)
    ]
    if not nouns:
        return SECTION_FALLBACKS.get(section_id, "server room blue LEDs close up")
    return f"{' '.join(nouns)} {descriptor}"


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

def run(shot_list_path, script_path, threshold=7, dry_run=False):
    if not Path(shot_list_path).exists():
        print(f"❌ Shot list not found: {shot_list_path}")
        return False
    if not Path(script_path).exists():
        print(f"❌ Script not found: {script_path}")
        return False

    with open(shot_list_path, encoding="utf-8") as f:
        shot_list = json.load(f)
    with open(script_path, encoding="utf-8") as f:
        script = json.load(f)

    narration_by_id = {
        s.get("id", ""): s.get("narration", "")
        for s in script.get("sections", [])
    }

    report_lines = ["# Footage Relevance Report", ""]
    total_beats = 0
    rewritten = 0
    avg_before = []
    avg_after = []

    for section in shot_list.get("sections", []):
        sid = section.get("section_id", "")
        narration = narration_by_id.get(sid, "")
        shots = section.get("shots", [])
        report_lines.append(f"## Section: {sid}")

        for idx, shot in enumerate(shots):
            if (shot.get("type") or shot.get("shot_type")) not in (
                "footage", None,
            ) and not shot.get("query"):
                continue
            total_beats += 1
            query = shot.get("query") or shot.get("footage_query") or ""
            score, reasons = score_query(query, narration, sid)
            avg_before.append(score)

            status = "✅" if score >= threshold else "⚠️"
            report_lines.append(
                f"- [{idx + 1}] {status} score={score}  `{query}`"
            )
            for r in reasons:
                report_lines.append(f"    - {r}")

            if score < threshold and not dry_run:
                new_q = rewrite_query(narration, sid, idx)
                new_score, _ = score_query(new_q, narration, sid)
                shot["query"] = new_q
                shot["relevance_score"] = new_score
                shot["relevance_score_original"] = score
                shot["original_query"] = query
                avg_after.append(new_score)
                rewritten += 1
                report_lines.append(
                    f"    ↻ rewritten → `{new_q}` (score {new_score})"
                )
            else:
                shot["relevance_score"] = score
                avg_after.append(score)

        report_lines.append("")

    if avg_before:
        avg_b = sum(avg_before) / len(avg_before)
        avg_a = sum(avg_after) / len(avg_after) if avg_after else avg_b
        report_lines.insert(
            1,
            f"\nBeats scored: {total_beats}  |  rewritten: {rewritten}\n"
            f"Average score before: {avg_b:.2f}  |  after: {avg_a:.2f}\n",
        )

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_DIR / "footage_relevance.md"
    report_path.write_text("\n".join(report_lines), encoding="utf-8")
    print(f"📝 Report: {report_path}")

    if not dry_run:
        with open(shot_list_path, "w", encoding="utf-8") as f:
            json.dump(shot_list, f, indent=2)
        print(f"💾 Shot list updated: {shot_list_path}")

    return True


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--shot-list", default=str(SHOT_LIST_PATH))
    p.add_argument("--script", default=str(SCRIPT_PATH))
    p.add_argument("--threshold", type=int, default=7)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    ok = run(args.shot_list, args.script,
             threshold=args.threshold, dry_run=args.dry_run)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
