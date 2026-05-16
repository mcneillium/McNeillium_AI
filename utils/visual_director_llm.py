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


SYSTEM_PROMPT = """You are the Visual Director / asset librarian for an AI
news commentary YouTube channel. The aesthetic is "news-anchor static":
clean cuts, real photos held still, conceptual illustrations for abstract
ideas. You're picking from a real asset library, not searching the web.

ASSET LIBRARY (all local, all free):
  - person_photo:         Wikipedia photos for ~50 named tech execs.
                          Just give the canonical name.
  - company_logo:         ~4,200 brand logos (Simple Icons + Lobe AI).
                          Covers Microsoft, OpenAI, Anthropic, Google,
                          Apple, Meta, Nvidia, AWS, Azure, Copilot, IBM,
                          Mistral, Cohere, Claude, Gemini, X, Grok and
                          most other named AI brands. Just give the
                          company name as `company`.
  - concept_illustration: Polished Lucide line-art icons. Use one of the
                          REGISTERED CONCEPT SLUGS below — these map
                          directly to drawings. If the perfect concept
                          isn't listed, pick the closest registered slug
                          rather than inventing a new one.
  - stock_footage:        Pexels + Pixabay + Wikimedia + Internet Archive
                          parallel search. Use for physical scenes only
                          (data center, city skyline, hands typing) —
                          not for abstract concepts.
  - chart:                Numeric statistics (must include the value).
  - article_screenshot:   Pre-fetched news articles.

REGISTERED CONCEPT SLUGS (pick exactly one as `concept`):
  lost_leverage, scale_tipping, control_shift, narrative_control,
  exclusivity_lost, exclusive_access, monopoly_ends, monopoly_broken,
  gatekeeper, growth, rise, first_mover_advantage, race, decline,
  collapse, pricing_power_collapse, aggressive_discounting,
  pricing_pressure, partnership, negotiation, seamless_integration,
  engagement, moat_drained, moat, defense, defensive, multi_cloud,
  omnichannel_distribution, multi_model_choice, ecosystem,
  autonomous_agent, context_awareness, agent_routing, customer_attrition,
  exodus, strategic_shift, ground_shifting, tectonic_shift, fork, pivot,
  transformation, following_not_leading, commoditization, commoditized,
  apps_as_functions, old_model_apps

DECISION RULES:
  - Specific PERSON named (CEO, founder, executive)  → person_photo
  - Specific COMPANY named (any brand)               → company_logo
  - Abstract concept ("lost leverage", "moat drained", "exodus",
    "pivot", "scale tipping")                        → concept_illustration
                                                        with a registered slug
  - Direct quote / named article                     → article_screenshot
  - Statistic stated as the focus ("$950 billion")   → chart
  - Concrete physical scene described                → stock_footage

Prefer SPECIFIC over GENERIC. A logo lands harder than stock footage of
servers. A concept illustration lands harder than vague tech b-roll.

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
