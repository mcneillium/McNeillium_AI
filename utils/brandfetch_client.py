#!/usr/bin/env python3
"""
McNeillium_AI — Phase 21.2: Brandfetch CDN Client

Fills the gap left by Simple Icons. Simple Icons removed Microsoft,
OpenAI, ChatGPT, AWS, Amazon, Oracle, IBM, Azure, Cohere and a few
other major brands due to trademark/guideline pressure. Brandfetch
has them all.

Free tier: 500k requests/month. URL pattern:
  https://cdn.brandfetch.io/{domain}/icon?c={client_id}

We map "Company Name" → "domain.com" using a small built-in table for
the most-cited AI brands, plus a heuristic fallback (lowercased + .com).

Cache forever — logos don't change often. Cache key = domain.

Public API
──────────
  fetch_logo_png(name, *, domain=None, size=512) -> Path | None
      Returns a cached PNG path. Falls back through:
        - explicit domain arg
        - built-in NAME_TO_DOMAIN table
        - sluggified name + ".com"
"""

import argparse
import io
import os
import re
import sys
import time
import urllib.parse
import urllib.request
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
CACHE_DIR = PROJECT_ROOT / "output" / "_brandfetch_cache"
USER_AGENT = "Mozilla/5.0 (McNeillium_AI Phase21 brandfetch client)"

# Curated name→domain table for the brands Simple Icons removed,
# plus a few common variants. Lowercased for matching.
NAME_TO_DOMAIN = {
    "microsoft":             "microsoft.com",
    "msft":                  "microsoft.com",
    "azure":                 "azure.microsoft.com",
    "microsoft azure":       "azure.microsoft.com",
    "copilot":               "microsoft.com",
    "github copilot":        "github.com",
    "office":                "office.com",
    "office 365":            "microsoft.com",
    "openai":                "openai.com",
    "chatgpt":               "openai.com",
    "gpt":                   "openai.com",
    "gpt-5":                 "openai.com",
    "gpt-4":                 "openai.com",
    "gpt-3":                 "openai.com",
    "gpt-3.5":               "openai.com",
    "gpt 4":                 "openai.com",
    "gpt 5":                 "openai.com",
    "amazon":                "amazon.com",
    "amazon web services":   "aws.amazon.com",
    "aws":                   "aws.amazon.com",
    "aws bedrock":           "aws.amazon.com",
    "bedrock":               "aws.amazon.com",
    "oracle":                "oracle.com",
    "oracle cloud":          "oracle.com",
    "ibm":                   "ibm.com",
    "ibm watson":            "ibm.com",
    "cohere":                "cohere.com",
    "vertex":                "cloud.google.com",
    "google vertex":         "cloud.google.com",
    "vertex ai":             "cloud.google.com",
    "google deepmind":       "deepmind.google",
    "deepmind":              "deepmind.google",
    "play store":            "play.google.com",
    "google play":           "play.google.com",
    "google play store":     "play.google.com",
    "android":               "android.com",
    "pixel":                 "google.com",
    "google pixel":          "google.com",
    "wwdc":                  "developer.apple.com",
    "ios":                   "apple.com",
    "iphone":                "apple.com",
    "siri":                  "apple.com",
    # Useful supplements (these ARE in Simple Icons but the canonical
    # domain saves a search step for ambiguous names)
    "google cloud":          "cloud.google.com",
    "google ai":             "ai.google",
    "anthropic":             "anthropic.com",
    "claude":                "anthropic.com",
    "claude code":           "anthropic.com",
    "gemini":                "deepmind.google",
    "google gemini":         "deepmind.google",
    "x ai":                  "x.ai",
    "xai":                   "x.ai",
    "grok":                  "x.ai",
    "tesla":                 "tesla.com",
    "spacex":                "spacex.com",
    "twitter":               "x.com",
    "ssi":                   "ssi.inc",
    "safe superintelligence":"ssi.inc",
    "perplexity":            "perplexity.ai",
    "perplexity ai":         "perplexity.ai",
}


def _norm(s):
    return re.sub(r"\s+", " ", s.lower().strip())


def name_to_domain(name):
    """Return a best-guess domain for `name`. Never returns None — falls
    back to sluggified name + .com."""
    if not name:
        return None
    norm = _norm(name)
    if norm in NAME_TO_DOMAIN:
        return NAME_TO_DOMAIN[norm]
    # Strip common suffixes
    for suffix in (" inc", " corp", " corporation", " llc", " ltd",
                   " labs", " lab", ".com"):
        if norm.endswith(suffix):
            cand = norm[: -len(suffix)].strip()
            if cand in NAME_TO_DOMAIN:
                return NAME_TO_DOMAIN[cand]
    # Slugified fallback
    slug = re.sub(r"[^a-z0-9]+", "", norm)
    return f"{slug}.com" if slug else None


def fetch_logo_png(name, *, domain=None, size=512):
    """Download (or read from cache) a Brandfetch logo as PNG. Returns Path.

    Brandfetch returns image/webp by default; we re-encode to PNG via
    Pillow so the rest of the pipeline (which expects RGB PIL images)
    handles it cleanly. Tries /w/{size}/h/{size}, then /icon, then
    bare /{domain} as endpoint variants — domain coverage varies."""
    client_id = os.getenv("BRANDFETCH_CLIENT_ID", "")
    if not client_id:
        return None

    domain = domain or name_to_domain(name)
    if not domain:
        return None

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    safe_domain = re.sub(r"[^a-z0-9.]+", "_", domain.lower())
    cache_path = CACHE_DIR / f"{safe_domain}_{size}.png"
    if cache_path.exists() and cache_path.stat().st_size > 200:
        return cache_path

    # urllib trips TLS for some Brandfetch routes; requests works.
    try:
        import requests
    except ImportError:
        print("⚠️  requests not installed; pip install requests")
        return None

    sess = requests.Session()
    sess.headers.update({
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 Chrome/120.0"),
    })
    endpoints = [
        f"https://cdn.brandfetch.io/{domain}/w/{size}/h/{size}?c={client_id}",
        f"https://cdn.brandfetch.io/{domain}/icon?c={client_id}",
        f"https://cdn.brandfetch.io/{domain}?c={client_id}",
    ]
    img_bytes = None
    for url in endpoints:
        try:
            r = sess.get(url, timeout=12, allow_redirects=True)
            if r.status_code == 200 and len(r.content) > 800:
                img_bytes = r.content
                break
        except Exception:
            continue
    if not img_bytes:
        return None

    # Re-encode whatever Brandfetch sent (typically webp) to PNG.
    try:
        from PIL import Image
        from io import BytesIO
        img = Image.open(BytesIO(img_bytes)).convert("RGBA")
        img.save(cache_path, "PNG")
    except Exception as e:
        print(f"      ⚠️  brandfetch PNG conversion failed for {domain}: {e}")
        return None

    time.sleep(0.1)
    return cache_path


def main():
    p = argparse.ArgumentParser(description="Phase 21.2 Brandfetch client")
    sub = p.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("fetch", help="Fetch logo PNG by name")
    f.add_argument("names", nargs="+")
    f.add_argument("--size", type=int, default=512)

    d = sub.add_parser("domain", help="Show resolved domain only")
    d.add_argument("names", nargs="+")

    args = p.parse_args()

    if args.cmd == "fetch":
        if not os.getenv("BRANDFETCH_CLIENT_ID"):
            print("❌ BRANDFETCH_CLIENT_ID not set in .env")
            sys.exit(2)
        for n in args.names:
            p = fetch_logo_png(n, size=args.size)
            mark = "✅" if p else "❌"
            print(f"  {mark} {n!r:30s} → {p or '(miss)'}")
    elif args.cmd == "domain":
        for n in args.names:
            d = name_to_domain(n)
            print(f"  {n!r:30s} → {d}")


if __name__ == "__main__":
    main()
