#!/usr/bin/env python3
"""
McNeillium AI — Visual Director Enricher (Phase 12.3)

Runs AFTER the News Asset Collector. Reads:
  - output/scripts/latest.json
  - output/shot_list.json
  - output/_news_assets/manifest.json

For each section, scans the narration for entities (people, companies,
news sources, headline stats). When a real asset exists in the manifest
for that mention, REPLACES one footage beat in the section with a styled
real-asset beat. Kling hero beats and stat_cards are preserved untouched.

Result: shot_list.json now mixes real assets with Pixabay b-roll and the
existing Kling heroes. Each real asset is referenced by a pre-rendered
styled PNG (see utils/asset_renderers.py) which the video generator
treats as a static clip with Ken Burns motion.

Priorities (highest first):
  1. People photo when the narration names someone
  2. Company logo when the narration names a company
  3. Article screenshot when a source is mentioned
  4. Animated chart when a numeric stat is mentioned
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
sys.path.insert(0, str(PROJECT_ROOT))
from utils.news_asset_collector import (  # noqa: E402
    KNOWN_PEOPLE, KNOWN_COMPANIES, STAT_PATTERN,
)
from utils.asset_renderers import (  # noqa: E402
    render_person_card_png, render_logo_card_png, render_article_card_png,
)

SCRIPT_PATH = PROJECT_ROOT / "output" / "scripts" / "latest.json"
SHOT_LIST_PATH = PROJECT_ROOT / "output" / "shot_list.json"
MANIFEST_PATH = PROJECT_ROOT / "output" / "_news_assets" / "manifest.json"
RENDERED_DIR = PROJECT_ROOT / "output" / "_news_assets" / "rendered"

PERSON_ROLES = {
    "Sam Altman":       "CEO, OpenAI",
    "Elon Musk":        "CEO, xAI / Tesla",
    "Dario Amodei":     "CEO, Anthropic",
    "Demis Hassabis":   "CEO, Google DeepMind",
    "Sundar Pichai":    "CEO, Google / Alphabet",
    "Mark Zuckerberg":  "CEO, Meta",
    "Greg Brockman":    "President, OpenAI",
    "Ilya Sutskever":   "Founder, SSI",
    "Yann LeCun":       "Chief AI Scientist, Meta",
    "Andrej Karpathy":  "Eureka Labs",
    "Jensen Huang":     "CEO, Nvidia",
    "Satya Nadella":    "CEO, Microsoft",
}


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60]


def detect_section_assets(narration, manifest):
    """Return ordered list of asset beats to inject into this section.

    Each beat is a dict ready to drop into shot_list "shots":
      {"type": "person_photo"|"company_logo"|..., "path": ..., "duration": ...,
       "motion": ..., plus per-type metadata}
    """
    lower = narration.lower()
    beats = []
    seen_people = set()
    seen_companies = set()
    seen_stats = set()

    # People
    for surface, canon in KNOWN_PEOPLE.items():
        if canon in seen_people:
            continue
        if surface in lower:
            asset = manifest.get("people", {}).get(_slug(canon))
            if not asset:
                continue
            role = PERSON_ROLES.get(canon, "")
            png_path = RENDERED_DIR / f"person_{_slug(canon)}.png"
            ok = render_person_card_png(
                asset["path"], canon, role, png_path,
            )
            if ok:
                beats.append({
                    "type": "person_photo",
                    "path": str(png_path),
                    "duration": 4.5,
                    "motion": "ken_burns_in",
                    "name": canon,
                    "role": role,
                })
                seen_people.add(canon)

    # Companies
    for surface, (canon, domain) in KNOWN_COMPANIES.items():
        short = surface.split()[0]
        if short in seen_companies:
            continue
        if surface in lower:
            asset = manifest.get("logos", {}).get(short)
            if not asset:
                continue
            png_path = RENDERED_DIR / f"logo_{_slug(canon)}.png"
            ok = render_logo_card_png(asset["path"], canon, png_path)
            if ok:
                beats.append({
                    "type": "company_logo",
                    "path": str(png_path),
                    "duration": 3.5,
                    "motion": "static",
                    "company": canon,
                })
                seen_companies.add(short)

    # Article screenshots — match by topic keyword. News articles cover
    # the same story as the script, so we look for a few topic hooks
    # rather than expecting the script to name the publication.
    article_topic_hooks = {
        "altman-musk-trial-testimony-takeaways": (
            "testimony", "testify", "testified", "stand", "trial",
        ),
        "openai-trial-updates": ("trial", "court", "oakland", "lawsuit"),
        "behold-the-googlebook": (
            "anthropic", "valuation", "billion", "googlebook",
        ),
    }
    for slug, art in manifest.get("articles", {}).items():
        hits = False
        url = (art.get("url") or "").lower()
        label = (art.get("label") or "").lower()
        # Exact label or URL fragment match
        for token in (label, url):
            if token and len(token) >= 3 and token in lower:
                hits = True
                break
        # Topic-hook fallback
        if not hits:
            for key, hooks in article_topic_hooks.items():
                if key in slug.lower() or key in url:
                    if any(h in lower for h in hooks):
                        hits = True
                        break
        if hits:
            png_path = RENDERED_DIR / f"article_{slug}.png"
            ok = render_article_card_png(
                art["path"], art.get("label") or slug,
                "May 2026", png_path,
            )
            if ok:
                beats.append({
                    "type": "article_screenshot",
                    "path": str(png_path),
                    "duration": 4.5,
                    "motion": "ken_burns_in",
                    "source": art.get("label") or slug,
                })

    # Stats — pre-rendered MP4s from the asset collector
    for chart in manifest.get("charts", []):
        if chart["value"].lower() in seen_stats:
            continue
        val_norm = chart["value"].replace(" ", "").lower()
        if val_norm in re.sub(r"\s+", "", lower):
            beats.append({
                "type": "chart",
                "path": chart["path"],
                "duration": 5.0,
                "motion": "static",
                "stat": chart["value"],
                "label": chart["label"],
            })
            seen_stats.add(chart["value"].lower())

    return beats


def enrich_section(section, asset_beats, position_after=2):
    """Insert real-asset beats into the section's shot list.

    We REPLACE consecutive footage beats starting at `position_after`
    with the asset beats, so the hero beat at position 0 stays first
    and the run of stock footage gets swapped out for real assets.
    Stat_cards already in the shot list are preserved.
    """
    if not asset_beats:
        return section

    shots = section.get("shots", [])
    # Find indices we are allowed to replace (footage type, not stat/hero/etc.)
    replaceable_indices = [
        i for i, s in enumerate(shots)
        if (s.get("type") or s.get("shot_type")) in ("footage", None)
        and i >= position_after
    ]
    replaceable_indices.sort()

    # Replace up to len(asset_beats) of them
    n_to_replace = min(len(asset_beats), len(replaceable_indices))
    for asset_beat, idx in zip(asset_beats[:n_to_replace],
                                replaceable_indices[:n_to_replace]):
        shots[idx] = asset_beat
    # Drop any remaining unused asset beats into the section if there's room
    leftover = asset_beats[n_to_replace:]
    if leftover:
        insert_at = min(position_after + n_to_replace + 1, len(shots))
        for b in leftover:
            shots.insert(insert_at, b)
            insert_at += 1

    section["shots"] = shots
    return section


def run(script_path, shot_list_path, manifest_path):
    if not Path(manifest_path).exists():
        print(f"❌ Manifest missing: {manifest_path}")
        return False
    if not Path(shot_list_path).exists():
        print(f"❌ Shot list missing: {shot_list_path}")
        return False
    if not Path(script_path).exists():
        print(f"❌ Script missing: {script_path}")
        return False

    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    script = json.loads(Path(script_path).read_text(encoding="utf-8"))
    shot_list = json.loads(Path(shot_list_path).read_text(encoding="utf-8"))

    RENDERED_DIR.mkdir(parents=True, exist_ok=True)

    narration_by_id = {
        s.get("id", ""): s.get("narration", "")
        for s in script.get("sections", [])
    }

    total_injected = 0
    for section in shot_list.get("sections", []):
        sid = section.get("section_id")
        narration = narration_by_id.get(sid, "")
        if not narration:
            continue
        asset_beats = detect_section_assets(narration, manifest)
        if not asset_beats:
            continue
        types = [b["type"].replace("_", " ") for b in asset_beats]
        print(f"  📎 {sid}: +{len(asset_beats)} ({', '.join(types)})")
        enrich_section(section, asset_beats)
        total_injected += len(asset_beats)

    Path(shot_list_path).write_text(
        json.dumps(shot_list, indent=2), encoding="utf-8",
    )
    print(f"✅ Enriched shot list: {total_injected} real-asset beats injected")
    print(f"💾 → {shot_list_path}")
    return True


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--script", default=str(SCRIPT_PATH))
    p.add_argument("--shot-list", default=str(SHOT_LIST_PATH))
    p.add_argument("--manifest", default=str(MANIFEST_PATH))
    args = p.parse_args()
    ok = run(args.script, args.shot_list, args.manifest)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
