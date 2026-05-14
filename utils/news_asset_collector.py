#!/usr/bin/env python3
"""
McNeillium AI — Agent 28: News Asset Collector (Phase 12.3)

Runs AFTER the script writer, BEFORE the Visual Director enricher.
Reads the latest script and pulls real assets the news/commentary
format needs:

  A) People photos      — Wikipedia REST API thumbnails (CC-licensed)
  B) Company logos      — Wikipedia first, then Google s2 favicons,
                          fall back to a generated text card
  C) Article screenshots — Playwright headless Chromium, top 1920x800
                          slice of the page, cached by URL hash
  D) Animated data charts — PIL + FFmpeg quick reveal of headline stats

All assets are cached. Wikipedia & favicons keep forever (90-day TTL
soft refresh). Article screenshots cache by sha256(URL). Reruns are
near-free.

Manifest output: output/_news_assets/manifest.json
"""

import argparse
import hashlib
import io
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower().replace("-", "") != "utf8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8",
                                  errors="replace")

from PIL import Image, ImageDraw, ImageFont

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = PROJECT_ROOT / "output" / "scripts" / "latest.json"
ASSETS_DIR = PROJECT_ROOT / "output" / "_news_assets"
PEOPLE_DIR = ASSETS_DIR / "people"
LOGO_DIR = ASSETS_DIR / "logos"
ARTICLE_DIR = ASSETS_DIR / "articles"
CHART_DIR = ASSETS_DIR / "charts"
MANIFEST_PATH = ASSETS_DIR / "manifest.json"

CACHE_TTL_DAYS = 90


# ─── Known entities (keeps us out of spaCy territory) ─────────────────
# These are people/companies the channel covers regularly. Add as needed.
KNOWN_PEOPLE = {
    "sam altman":      "Sam Altman",
    "altman":          "Sam Altman",
    "elon musk":       "Elon Musk",
    "musk":            "Elon Musk",
    "dario amodei":    "Dario Amodei",
    "amodei":          "Dario Amodei",
    "demis hassabis":  "Demis Hassabis",
    "hassabis":        "Demis Hassabis",
    "sundar pichai":   "Sundar Pichai",
    "pichai":          "Sundar Pichai",
    "mark zuckerberg": "Mark Zuckerberg",
    "zuckerberg":      "Mark Zuckerberg",
    "greg brockman":   "Greg Brockman",
    "ilya sutskever":  "Ilya Sutskever",
    "yann lecun":      "Yann LeCun",
    "andrej karpathy": "Andrej Karpathy",
    "jensen huang":    "Jensen Huang",
    "satya nadella":   "Satya Nadella",
}

KNOWN_COMPANIES = {
    # Surface form → (wikipedia title, domain for favicon fallback)
    "openai":     ("OpenAI", "openai.com"),
    "anthropic":  ("Anthropic", "anthropic.com"),
    "google":     ("Google",  "google.com"),
    "google deepmind": ("Google DeepMind", "deepmind.google"),
    "deepmind":   ("Google DeepMind", "deepmind.google"),
    "meta":       ("Meta Platforms", "meta.com"),
    "meta ai":    ("Meta AI", "ai.meta.com"),
    "microsoft":  ("Microsoft", "microsoft.com"),
    "nvidia":     ("Nvidia", "nvidia.com"),
    "apple":      ("Apple Inc.", "apple.com"),
    "amazon":     ("Amazon (company)", "amazon.com"),
    "tesla":      ("Tesla, Inc.", "tesla.com"),
    "xai":        ("XAI (company)", "x.ai"),
    "x.ai":       ("XAI (company)", "x.ai"),
    "perplexity": ("Perplexity AI", "perplexity.ai"),
    "mistral":    ("Mistral AI", "mistral.ai"),
    "hugging face": ("Hugging Face", "huggingface.co"),
    "cursor":     ("Cursor (code editor)", "cursor.com"),
    "github":     ("GitHub", "github.com"),
    "cnbc":       ("CNBC", "cnbc.com"),
    "fortune":    ("Fortune (magazine)", "fortune.com"),
    "techcrunch": ("TechCrunch", "techcrunch.com"),
    "reuters":    ("Reuters", "reuters.com"),
    "bloomberg":  ("Bloomberg L.P.", "bloomberg.com"),
}


STAT_PATTERN = re.compile(
    r"\b\$?\s*(\d+(?:\.\d+)?)\s*"
    r"(billion|million|trillion|percent|%|b\b|m\b|x\b)",
    re.I,
)


# ─── Cache helpers ───────────────────────────────────────────────

def _slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60]


def _is_fresh(path, days=CACHE_TTL_DAYS):
    if not path.exists():
        return False
    age = time.time() - path.stat().st_mtime
    return age < days * 86400


def _http_bytes(url, timeout=20):
    req = urllib.request.Request(url, headers={
        "User-Agent": "McNeilliumAI-AssetBot/1.0 (research; contact: github)"
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _http_json(url, timeout=20):
    return json.loads(_http_bytes(url, timeout).decode("utf-8"))


# ─── A) People photos ────────────────────────────────────────────

def fetch_person_photo(canonical_name):
    """Download a person's Wikipedia thumbnail. Returns local path or None."""
    slug = _slug(canonical_name)
    target = PEOPLE_DIR / f"{slug}.jpg"
    if _is_fresh(target):
        return str(target)

    title = urllib.parse.quote(canonical_name.replace(" ", "_"))
    api = f"https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
    try:
        data = _http_json(api)
    except Exception as e:
        print(f"      ⚠️  wikipedia lookup failed for {canonical_name}: {e}")
        return None
    thumb = (data.get("originalimage") or data.get("thumbnail") or {})
    img_url = thumb.get("source")
    if not img_url:
        print(f"      ⚠️  no image on Wikipedia page for {canonical_name}")
        return None
    try:
        img_bytes = _http_bytes(img_url)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(img_bytes)
        return str(target)
    except Exception as e:
        print(f"      ⚠️  image download failed: {e}")
        return None


# ─── B) Company logos ────────────────────────────────────────────

def _generate_text_logo(company_name, output_path):
    """Last-resort logo: dark card with company name text."""
    W, H = 512, 512
    img = Image.new("RGBA", (W, H), (10, 14, 24, 255))
    d = ImageDraw.Draw(img)
    font = _find_bold_font(56)
    text = company_name.upper()
    bbox = d.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    d.text(((W - tw) // 2, (H - th) // 2 - 10), text, font=font,
           fill=(91, 163, 245, 255))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(output_path), "PNG")
    return str(output_path)


def fetch_company_logo(key, canonical_name, domain):
    """Try Wikipedia thumbnail, then Google s2 favicon, then text card."""
    slug = _slug(key)
    target = LOGO_DIR / f"{slug}.png"
    if _is_fresh(target):
        return str(target)

    # Try 1: Wikipedia page-summary thumbnail (often the logo for companies)
    title = urllib.parse.quote(canonical_name.replace(" ", "_"))
    api = f"https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
    try:
        data = _http_json(api)
        thumb = (data.get("originalimage") or data.get("thumbnail") or {})
        img_url = thumb.get("source")
        if img_url and any(ext in img_url.lower()
                            for ext in (".png", ".svg", ".jpg", ".jpeg")):
            img_bytes = _http_bytes(img_url)
            target.parent.mkdir(parents=True, exist_ok=True)
            # Convert SVG / WebP / etc to PNG by routing through Pillow
            try:
                Image.open(io.BytesIO(img_bytes)).convert("RGBA")\
                     .save(str(target), "PNG")
                return str(target)
            except Exception:
                pass  # fall through to favicon
    except Exception as e:
        print(f"      ⚠️  wiki logo lookup failed for {key}: {e}")

    # Try 2: Google s2 favicon (works for almost every domain, returns PNG)
    if domain:
        favicon = (f"https://www.google.com/s2/favicons"
                   f"?domain={domain}&sz=256")
        try:
            img_bytes = _http_bytes(favicon)
            Image.open(io.BytesIO(img_bytes)).convert("RGBA")\
                 .save(str(target), "PNG")
            return str(target)
        except Exception as e:
            print(f"      ⚠️  favicon fetch failed for {domain}: {e}")

    # Try 3: generated text card
    return _generate_text_logo(canonical_name, target)


# ─── C) Article screenshots (Playwright) ─────────────────────────

def _playwright_available():
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
        return True
    except Exception:
        return False


def fetch_article_screenshot(url, slug_hint=""):
    """Use Playwright to screenshot the top of a news article."""
    if not url:
        return None
    url_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
    slug = (_slug(slug_hint) + "-" if slug_hint else "") + url_hash
    target = ARTICLE_DIR / f"{slug}.png"
    if _is_fresh(target):
        return str(target)

    if not _playwright_available():
        print(f"      ⏭  Playwright unavailable — skipping {url}")
        return None

    try:
        from playwright.sync_api import sync_playwright
        target.parent.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/124.0.0.0 Safari/537.36"),
            )
            page = ctx.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=25000)
            # Give cookie banners / lazy images a moment to settle
            page.wait_for_timeout(2500)
            # Try to dismiss obvious cookie banners (best-effort)
            for sel in [
                "button:has-text('Accept')", "button:has-text('I agree')",
                "button:has-text('Got it')", "button:has-text('Allow all')",
            ]:
                try:
                    page.locator(sel).first.click(timeout=800)
                    break
                except Exception:
                    pass
            page.wait_for_timeout(1200)
            page.screenshot(path=str(target),
                            clip={"x": 0, "y": 0, "width": 1920, "height": 800})
            browser.close()
        return str(target)
    except Exception as e:
        print(f"      ⚠️  screenshot failed for {url}: {e}")
        return None


# ─── D) Animated data charts ─────────────────────────────────────

def _find_bold_font(size):
    for fp in [
        "C:/Windows/Fonts/impact.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]:
        if Path(fp).exists():
            return ImageFont.truetype(fp, size)
    return ImageFont.load_default()


def _find_body_font(size):
    for fp in [
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]:
        if Path(fp).exists():
            return ImageFont.truetype(fp, size)
    return ImageFont.load_default()


def _ffmpeg():
    r = shutil.which("ffmpeg")
    if r:
        return r
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return "ffmpeg"


FFMPEG = _ffmpeg()


def generate_stat_chart(value_str, label, output_path,
                        duration_s=5, w=1920, h=1080, fps=30):
    """Animated number reveal — counts up from 0 to value over ~1s,
    then holds. Channel blue accents."""
    target = Path(output_path)
    if _is_fresh(target):
        return str(target)

    # Parse a leading number out of value_str
    m = re.search(r"(\d+(?:\.\d+)?)", value_str.replace(",", ""))
    target_num = float(m.group(1)) if m else 0
    suffix = value_str[m.end():].strip() if m else ""
    prefix = value_str[:m.start()].strip() if m else ""

    total_frames = duration_s * fps
    count_up_frames = int(1.2 * fps)
    frames_dir = target.parent / f"_chart_frames_{_slug(label)}"
    if frames_dir.exists():
        shutil.rmtree(frames_dir)
    frames_dir.mkdir(parents=True, exist_ok=True)

    big_font = _find_bold_font(280)
    label_font = _find_body_font(54)

    for f_idx in range(total_frames):
        img = Image.new("RGB", (w, h), (10, 14, 24))
        d = ImageDraw.Draw(img)
        # Gradient background
        for y in range(0, h, 4):
            shade = int(2 + 14 * (y / h))
            d.rectangle([0, y, w, y + 4],
                        fill=(10 + shade // 2, 14 + shade // 2, 24 + shade))

        # Count up: ease-out cubic
        if f_idx < count_up_frames:
            t = f_idx / max(1, count_up_frames)
            eased = 1 - (1 - t) ** 3
            shown = target_num * eased
        else:
            shown = target_num

        # Render the number with the same suffix
        if target_num >= 1 and target_num == int(target_num):
            shown_str = f"{prefix}{int(shown)}{suffix}"
        else:
            shown_str = f"{prefix}{shown:.1f}{suffix}"

        cx, cy = w // 2, h // 2 - 30
        # Drop shadow
        d.text((cx + 6, cy + 6), shown_str, font=big_font,
               fill=(0, 0, 0), anchor="mm")
        # Main number in channel blue
        d.text((cx, cy), shown_str, font=big_font,
               fill=(91, 163, 245), anchor="mm")
        # Label below
        d.text((cx, cy + 200), label, font=label_font,
               fill=(220, 228, 236), anchor="mm")
        # Channel accent underline
        d.rectangle([cx - 240, cy + 160, cx + 240, cy + 164],
                    fill=(255, 107, 53))

        img.save(str(frames_dir / f"frame_{f_idx:06d}.png"), "PNG")

    target.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        FFMPEG, "-y", "-framerate", str(fps),
        "-i", str(frames_dir / "frame_%06d.png"),
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "20",
        "-pix_fmt", "yuv420p",
        str(target),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    shutil.rmtree(frames_dir, ignore_errors=True)
    return str(target) if r.returncode == 0 else None


# ─── Detection ──────────────────────────────────────────────────

def detect_people(text):
    found = []
    lower = text.lower()
    seen = set()
    for surface, canon in KNOWN_PEOPLE.items():
        if surface in lower and canon not in seen:
            seen.add(canon)
            found.append(canon)
    return found


def detect_companies(text):
    found = {}
    lower = text.lower()
    for surface, info in KNOWN_COMPANIES.items():
        if surface in lower:
            # key uses the short surface form (openai, anthropic, etc.)
            short = surface.split()[0]
            if short not in found:
                found[short] = info
    return found


def detect_stats(text, limit=4):
    out = []
    seen = set()
    for m in STAT_PATTERN.finditer(text):
        value = m.group(0).strip()
        if value in seen:
            continue
        seen.add(value)
        # Build a label from surrounding context (~6 words after)
        tail = text[m.end():m.end() + 80]
        label_words = re.findall(r"[A-Za-z][A-Za-z'-]*", tail)[:6]
        label = " ".join(label_words).strip() or "stat"
        out.append({"value": value, "label": label})
        if len(out) >= limit:
            break
    return out


# ─── Main ──────────────────────────────────────────────────────

def run(script_path, do_screenshots=True):
    if not Path(script_path).exists():
        print(f"❌ Script not found: {script_path}")
        return False
    with open(script_path, encoding="utf-8") as f:
        script = json.load(f)

    for d in (PEOPLE_DIR, LOGO_DIR, ARTICLE_DIR, CHART_DIR):
        d.mkdir(parents=True, exist_ok=True)

    full_text = " ".join(
        s.get("narration", "") for s in script.get("sections", [])
    )
    title = script.get("title", "")

    print(f"📰 News Asset Collector — analysing '{title[:60]}…'")

    # People
    people_names = detect_people(full_text)
    print(f"   👤 People mentioned: {people_names}")
    people = {}
    for name in people_names:
        path = fetch_person_photo(name)
        if path:
            people[_slug(name)] = {
                "name": name,
                "path": path,
            }
            print(f"      ✓ {name}: {Path(path).name}")

    # Companies
    companies_detected = detect_companies(full_text)
    print(f"   🏢 Companies mentioned: {list(companies_detected.keys())}")
    logos = {}
    for key, (canon, domain) in companies_detected.items():
        path = fetch_company_logo(key, canon, domain)
        if path:
            logos[key] = {
                "name": canon,
                "domain": domain,
                "path": path,
            }
            print(f"      ✓ {canon}: {Path(path).name}")

    # Article screenshots (URLs come from script metadata.sources)
    articles = {}
    sources = (script.get("metadata", {}) or {}).get("sources") or []
    sources = [s for s in sources if s]
    if sources and do_screenshots:
        print(f"   📄 Sources to screenshot: {len(sources)}")
        for src in sources[:5]:
            url = src.get("url") if isinstance(src, dict) else src
            hint = src.get("label", "") if isinstance(src, dict) else ""
            path = fetch_article_screenshot(url, slug_hint=hint)
            if path:
                articles[_slug(hint or url)] = {
                    "url": url,
                    "label": hint,
                    "path": path,
                }
                print(f"      ✓ {url[:70]}")

    # Stats / charts
    stats = detect_stats(full_text, limit=4)
    print(f"   📊 Stats detected: {[s['value'] for s in stats]}")
    charts = []
    for s in stats:
        slug = _slug(f"{s['value']}-{s['label']}")
        target = CHART_DIR / f"{slug}.mp4"
        path = generate_stat_chart(s["value"], s["label"], target)
        if path:
            charts.append({
                "value": s["value"],
                "label": s["label"],
                "path": path,
            })
            print(f"      ✓ chart: {s['value']} — {s['label']}")

    manifest = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "title": title,
        "people": people,
        "logos": logos,
        "articles": articles,
        "charts": charts,
    }
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2),
                              encoding="utf-8")
    print(f"💾 Manifest → {MANIFEST_PATH}")
    return True


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--script", default=str(SCRIPT_PATH))
    p.add_argument("--skip-screenshots", action="store_true",
                   help="Skip Playwright (faster, no Chromium needed)")
    args = p.parse_args()
    ok = run(args.script, do_screenshots=not args.skip_screenshots)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
