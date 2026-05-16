#!/usr/bin/env python3
"""
McNeillium_AI — Phase 20.1: LLM-Powered Visual Director

Replaces the keyword-based `section_search_query()` in
video/generate_video.py with Claude Haiku-driven shot planning.

For each section, sends the narration to Claude and asks for an
ordered list of shots, each tagged with:
  - shot_type:    person_photo | company_logo | concept_illustration |
                  stock_footage | chart | article_screenshot
  - search_terms: specific visual concept (3-7 words, not abstract)
  - person_name / company / concept: the entity for the chosen type
  - reasoning:    one-sentence rationale (kept for the cache log)

Output is a `shot_list.json` compatible structure that the existing
generate_video.py loader already understands. The downstream
visual_director_enricher.py still runs after this and overrides
specific beats with real Wikipedia photos when available.

Cache
─────
Each section response is cached by SHA-256 of (narration + n_beats)
under output/_visual_director_cache/<hash>.json. Re-running on the
same script is free; you only pay for newly-narrated sections.

Cost
────
~32 beats per video × 1 call/section (8 sections, batched) = 8 calls
× ~250 tokens in / 600 tokens out = ~$0.005/video on Haiku 4.5. The
brief estimated $0.05; we run an order of magnitude cheaper.
"""

import argparse
import hashlib
import io
import json
import os
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower().replace("-", "") != "utf8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8",
                                  errors="replace")

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SCRIPT = PROJECT_ROOT / "output" / "scripts" / "latest.json"
DEFAULT_OUT = PROJECT_ROOT / "output" / "shot_list.json"
CACHE_DIR = PROJECT_ROOT / "output" / "_visual_director_cache"

MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 1500
DEFAULT_BEATS_PER_SECTION = 4


SYSTEM_PROMPT = """You are the Visual Director for an AI news commentary
YouTube channel. Your job: pick the best visuals for each moment of the
narration. The host's aesthetic is "news-anchor static" — clean cuts,
real photos held still, conceptual illustrations for abstract ideas.

For each beat, choose ONE shot_type from this exact set:
  - person_photo:        a specific named person (Altman, Pichai, etc.)
  - company_logo:        a specific named company (OpenAI, Google, etc.)
  - concept_illustration: an abstract concept (leverage, partnership,
                           negotiation, growth, conflict, scale tipping)
  - stock_footage:       a physical thing or action (data center, hands
                           typing, city skyline, server room)
  - chart:               a numeric statistic worth visualizing
  - article_screenshot:  a referenced news article or publication

Heuristics:
  - If a person is named → person_photo
  - If a company is named → company_logo
  - If the narration is conceptual ("lost leverage", "partnership ended")
    → concept_illustration with a concrete metaphor concept word
  - If a concrete physical scene is described → stock_footage
  - If a number is given as the focus → chart
  - Avoid generic stock when a specific real asset would land harder

Output JSON only — no prose, no markdown fences."""


def _sha(narration, n_beats):
    h = hashlib.sha256()
    h.update(narration.encode("utf-8"))
    h.update(b"|")
    h.update(str(n_beats).encode("utf-8"))
    return h.hexdigest()[:16]


def _cached(key):
    p = CACHE_DIR / f"{key}.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def _save_cache(key, payload):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (CACHE_DIR / f"{key}.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8")


def _get_client():
    try:
        import anthropic
    except ImportError:
        print("❌ anthropic SDK missing. `pip install anthropic`")
        sys.exit(2)
    return anthropic.Anthropic()


def plan_section(section, n_beats=DEFAULT_BEATS_PER_SECTION,
                 *, client=None, _verbose=True):
    """Return a list of n_beats shot dicts for this section.

    Each dict matches the shot_list.json schema the renderer expects:
      {"type": <shot_type>, "query": <search_terms>, "duration": ...,
       "motion": "static", plus any per-type extras}
    """
    sid = section.get("id", "")
    narration = section.get("narration", "")
    if not narration:
        return []

    key = _sha(narration, n_beats)
    cached = _cached(key)
    if cached:
        if _verbose:
            print(f"   [cache] {sid:14s} ({len(cached.get('beats', []))} beats)")
        return cached.get("beats", [])

    client = client or _get_client()

    user_prompt = (
        f"Section id: {sid}\n"
        f"Narration:\n{narration[:1200]}\n\n"
        f"Plan {n_beats} shots that visually carry this narration in "
        f"order. Output JSON exactly like:\n"
        '{"beats":[{"shot_type":"...","search_terms":"...",'
        '"person_name":null,"company":null,"concept":null,'
        '"reasoning":"..."}]}'
    )

    msg = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )
    raw = msg.content[0].text.strip()
    # Strip code fences if Claude added them despite the instruction
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip("` \n")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"   ⚠️  {sid}: JSON parse failed ({e}); raw={raw[:200]!r}")
        return []

    beats_in = data.get("beats", [])
    beats_out = []
    # Default per-type duration (matches existing visual_director_enricher)
    DURATIONS = {
        "person_photo":         4.5,
        "company_logo":         3.5,
        "concept_illustration": 4.0,
        "stock_footage":        3.5,
        "chart":                5.0,
        "article_screenshot":   4.5,
    }
    for b in beats_in[:n_beats]:
        st = b.get("shot_type") or "stock_footage"
        if st not in DURATIONS:
            st = "stock_footage"
        # Map our shot_type to the renderer's `type` key:
        #   stock_footage → "footage" (existing renderer key)
        renderer_type = "footage" if st == "stock_footage" else st
        # Claude often returns null for redundant fields (e.g. no
        # search_terms when the concept/company carries the meaning).
        # Coerce to fallback strings so the renderer's stock_fetcher
        # always gets something to query.
        search_terms = b.get("search_terms") or ""
        if not search_terms:
            search_terms = (b.get("concept") or b.get("person_name")
                            or b.get("company") or "").strip()
        beat = {
            "type":     renderer_type,
            "query":    search_terms,
            "duration": DURATIONS[st],
            "motion":   "static",
        }
        if st == "person_photo" and b.get("person_name"):
            beat["name"] = b["person_name"]
        if st == "company_logo" and b.get("company"):
            beat["company"] = b["company"]
        if st == "concept_illustration" and b.get("concept"):
            beat["concept"] = b["concept"]
        beat["_reasoning"] = b.get("reasoning") or ""
        beats_out.append(beat)

    payload = {
        "section_id": sid,
        "narration_preview": narration[:120],
        "beats": beats_out,
        "model": MODEL,
        "tokens_in": getattr(msg.usage, "input_tokens", None),
        "tokens_out": getattr(msg.usage, "output_tokens", None),
    }
    _save_cache(key, payload)

    if _verbose:
        ti = payload.get("tokens_in") or 0
        to = payload.get("tokens_out") or 0
        print(f"   [llm  ] {sid:14s} ({len(beats_out)} beats, "
              f"in={ti} out={to})")
    return beats_out


def plan_script(script_path, *, n_beats=DEFAULT_BEATS_PER_SECTION,
                client=None):
    """Plan an entire script. Returns shot_list.json structure."""
    script = json.loads(Path(script_path).read_text(encoding="utf-8"))
    client = client or _get_client()

    sections_out = []
    total_in = total_out = 0
    for sec in script.get("sections", []):
        beats = plan_section(sec, n_beats=n_beats, client=client)
        # Attach the cached usage if we just paid for it
        cached = _cached(_sha(sec.get("narration", ""), n_beats)) or {}
        total_in += cached.get("tokens_in") or 0
        total_out += cached.get("tokens_out") or 0
        sections_out.append({
            "section_id": sec.get("id", ""),
            "shots": beats,
        })

    return {
        "video_title": script.get("title", ""),
        "model": MODEL,
        "sections": sections_out,
        "_cost_estimate_usd": round(
            (total_in / 1_000_000) * 1.0 +     # Haiku 4.5 input ≈ $1/MTok
            (total_out / 1_000_000) * 5.0, 4   # Haiku 4.5 output ≈ $5/MTok
        ),
        "_total_tokens_in": total_in,
        "_total_tokens_out": total_out,
    }


def main():
    p = argparse.ArgumentParser(description="Phase 20 LLM Visual Director")
    p.add_argument("--script", default=str(DEFAULT_SCRIPT))
    p.add_argument("--out", default=str(DEFAULT_OUT))
    p.add_argument("--beats-per-section", type=int,
                   default=DEFAULT_BEATS_PER_SECTION)
    p.add_argument("--print-only", action="store_true",
                   help="Don't write to --out, just print")
    args = p.parse_args()

    if not os.getenv("ANTHROPIC_API_KEY"):
        print("❌ ANTHROPIC_API_KEY not set in environment / .env")
        sys.exit(2)

    print(f"🎬 Visual Director (LLM) — script={Path(args.script).name}")
    plan = plan_script(args.script, n_beats=args.beats_per_section)

    n_total = sum(len(s["shots"]) for s in plan["sections"])
    print(f"   {n_total} beats across {len(plan['sections'])} sections")
    print(f"   tokens: in={plan['_total_tokens_in']} "
          f"out={plan['_total_tokens_out']}  → "
          f"~${plan['_cost_estimate_usd']:.4f}")

    if args.print_only:
        print(json.dumps(plan, indent=2)[:1500])
    else:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(plan, indent=2),
                                  encoding="utf-8")
        print(f"💾 → {args.out}")


if __name__ == "__main__":
    main()
