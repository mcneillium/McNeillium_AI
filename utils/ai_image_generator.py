#!/usr/bin/env python3
"""
McNeillium_AI — Agent 28: AI Image Generator

Generates custom images for moments stock footage can't show — portraits
of AI figures, product mockups, abstract concept art, scene illustrations.
Backed by Hugging Face's Inference API for SDXL on the free tier
(30 req/min). Falls back to local diffusers if HF is unreachable and the
library is installed; otherwise records a placeholder and continues.

Style consistency: every prompt receives the same suffix so all generated
images share an aesthetic — "cinematic, dark moody, blue accents, high
detail, 4k". The Style-Transfer Director (Agent 30) further unifies the
final composite.

Cache: output/_ai_images/<sha256-of-prompt>.png — repeated topics don't
re-burn HF quota.
"""

import argparse
import hashlib
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower().replace("-", "") != "utf8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8",
                                  errors="replace")

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = PROJECT_ROOT / "output" / "scripts" / "latest.json"
SHOT_LIST_PATH = PROJECT_ROOT / "output" / "shot_list.json"
CACHE_DIR = PROJECT_ROOT / "output" / "_ai_images"

HF_API_TOKEN = os.getenv("HF_API_TOKEN", "")
HF_MODEL = "stabilityai/stable-diffusion-xl-base-1.0"
HF_ENDPOINT = f"https://api-inference.huggingface.co/models/{HF_MODEL}"

STYLE_SUFFIX = ("cinematic, dark moody, blue accents, high detail, 4k, "
                "professional lighting, shallow depth of field")
NEGATIVE_PROMPT = ("blurry, low quality, distorted, text, watermark, "
                   "ugly, deformed, cartoon")


# ═══════════════════════════════════════════════════════════════
# Prompt detection — which beats need an AI image?
# ═══════════════════════════════════════════════════════════════

PORTRAIT_TRIGGERS = re.compile(
    r"\b(Sam Altman|Dario Amodei|Demis Hassabis|Yann LeCun|Geoffrey Hinton|"
    r"Andrej Karpathy|Mira Murati|Greg Brockman|Ilya Sutskever)\b",
    re.I,
)
PRODUCT_TRIGGERS = re.compile(
    r"\b(GPT-?\d|Claude\s*\d|Gemini\s*\d|Llama\s*\d|GPT-?5|"
    r"Vision Pro|Tesla Bot|Optimus)\b",
    re.I,
)
ABSTRACT_TRIGGERS = re.compile(
    r"\b(AGI|superintelligence|consciousness|reasoning|emergence|"
    r"alignment problem|p\(doom\))\b",
    re.I,
)


def detect_ai_image_need(narration):
    """Return a list of (prompt_seed, category) tuples for beats that need AI imagery."""
    out = []
    for m in PORTRAIT_TRIGGERS.finditer(narration):
        out.append((f"photorealistic portrait of {m.group(0)}, "
                    f"AI industry leader", "portrait"))
    for m in PRODUCT_TRIGGERS.finditer(narration):
        out.append((f"product key-art of {m.group(0)}, sleek device "
                    f"on dark backdrop, studio lighting", "product"))
    for m in ABSTRACT_TRIGGERS.finditer(narration):
        out.append((f"abstract conceptual art representing {m.group(0)}, "
                    f"glowing neural patterns", "abstract"))
    # Dedupe while preserving order
    seen = set()
    unique = []
    for prompt, cat in out:
        key = (prompt[:80], cat)
        if key not in seen:
            seen.add(key)
            unique.append((prompt, cat))
    return unique


# ═══════════════════════════════════════════════════════════════
# Generation
# ═══════════════════════════════════════════════════════════════

def _cache_path(prompt):
    h = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]
    return CACHE_DIR / f"{h}.png"


def _hf_generate(prompt, output_path, timeout=120):
    """Call the HF Inference API with retries on cold-start 503s."""
    if not HF_API_TOKEN:
        return False, "no HF_API_TOKEN set in .env"

    full_prompt = f"{prompt}, {STYLE_SUFFIX}"
    data = json.dumps({
        "inputs": full_prompt,
        "parameters": {
            "negative_prompt": NEGATIVE_PROMPT,
            "guidance_scale": 7.5,
            "num_inference_steps": 28,
            "width": 1024,
            "height": 1024,
        },
        "options": {"wait_for_model": True},
    }).encode("utf-8")

    req = urllib.request.Request(
        HF_ENDPOINT, data=data,
        headers={
            "Authorization": f"Bearer {HF_API_TOKEN}",
            "Content-Type": "application/json",
        },
    )

    last_err = ""
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read()
                ctype = resp.headers.get("Content-Type", "")
                if "image/" in ctype:
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    output_path.write_bytes(body)
                    return True, "hf-inference"
                try:
                    err = json.loads(body.decode("utf-8"))
                    last_err = err.get("error", str(err))
                except Exception:
                    last_err = body[:200].decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code == 503:
                last_err = "model loading (503) — retrying"
                time.sleep(8 * (attempt + 1))
                continue
            try:
                last_err = e.read().decode("utf-8", errors="replace")[:200]
            except Exception:
                last_err = str(e)
            break
        except Exception as e:
            last_err = str(e)
            time.sleep(2)

    return False, last_err


def _local_diffusers_generate(prompt, output_path):
    """Optional local SDXL via diffusers. Slow but free."""
    try:
        from diffusers import StableDiffusionXLPipeline
        import torch
    except Exception:
        return False, "diffusers/torch not available locally"

    try:
        pipe = StableDiffusionXLPipeline.from_pretrained(
            "stabilityai/stable-diffusion-xl-base-1.0",
            torch_dtype=torch.float32, use_safetensors=True,
        )
        full_prompt = f"{prompt}, {STYLE_SUFFIX}"
        image = pipe(full_prompt, negative_prompt=NEGATIVE_PROMPT,
                     num_inference_steps=24, guidance_scale=7.5).images[0]
        output_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(str(output_path), "PNG")
        return True, "local-diffusers"
    except Exception as e:
        return False, f"local diffusion failed: {e}"


def generate_image(prompt, category="general"):
    """Generate or fetch a cached AI image. Returns (path_or_None, source_str)."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = _cache_path(prompt)
    if cache.exists() and cache.stat().st_size > 1000:
        return str(cache), "cache"

    ok, source = _hf_generate(prompt, cache)
    if ok:
        return str(cache), source

    # Local fallback if available
    ok, source = _local_diffusers_generate(prompt, cache)
    if ok:
        return str(cache), source

    return None, source


# ═══════════════════════════════════════════════════════════════
# Shot list injection
# ═══════════════════════════════════════════════════════════════

def inject_ai_image_beats(shot_list, plan):
    by_section = {}
    for entry in plan:
        by_section.setdefault(entry["section_id"], []).append(entry)

    for section in shot_list.get("sections", []):
        sid = section.get("section_id")
        if sid not in by_section:
            continue
        for entry in by_section[sid]:
            section.setdefault("shots", []).append({
                "type": "ai_image",
                "path": entry["image_path"],
                "duration": 5.0,
                "motion": "ken_burns_in",
                "category": entry["category"],
                "prompt": entry["prompt"],
            })
    return shot_list


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

def run(script_path, shot_list_path, max_per_section=2):
    if not Path(script_path).exists():
        print(f"❌ Script not found: {script_path}")
        return False

    with open(script_path, encoding="utf-8") as f:
        script = json.load(f)
    shot_list = None
    if Path(shot_list_path).exists():
        with open(shot_list_path, encoding="utf-8") as f:
            shot_list = json.load(f)

    print(f"🎨 AI Image Generator — HF token configured: {bool(HF_API_TOKEN)}")
    if not HF_API_TOKEN:
        print("   ⚠️  HF_API_TOKEN missing from .env — scaffolding only; "
              "no images will render until you add a token from "
              "https://huggingface.co/settings/tokens")

    plan = []
    counter = 0
    for sec in script.get("sections", []):
        sid = sec.get("id", "")
        narration = sec.get("narration", "")
        needs = detect_ai_image_need(narration)[:max_per_section]
        for prompt, category in needs:
            counter += 1
            path, source = generate_image(prompt, category)
            status = "✅" if path else "⚠️"
            print(f"  [{counter}] {sid}: {category} — {status} ({source})")
            plan.append({
                "section_id": sid,
                "category": category,
                "prompt": prompt,
                "image_path": path or "",
                "source": source,
            })

    if shot_list:
        rendered = [p for p in plan if p["image_path"]]
        if rendered:
            shot_list = inject_ai_image_beats(shot_list, rendered)
            with open(shot_list_path, "w", encoding="utf-8") as f:
                json.dump(shot_list, f, indent=2)
            print(f"  ✅ Injected {len(rendered)} AI image beat(s)")
        else:
            print(f"  ⚠️  No AI images rendered (planned: {len(plan)})")

    return True


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--script", default=str(SCRIPT_PATH))
    p.add_argument("--shot-list", default=str(SHOT_LIST_PATH))
    p.add_argument("--max-per-section", type=int, default=2)
    args = p.parse_args()
    ok = run(args.script, args.shot_list,
             max_per_section=args.max_per_section)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
