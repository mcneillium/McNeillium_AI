#!/usr/bin/env python3
"""
McNeillium_AI — Phase 20.4: Entity Asset Packs

Builds multi-image packs per major entity so the same person doesn't
appear with identical framing across videos.

Wikipedia page → list all images on the page → filter to plausible
portraits (skip icons, edit chrome, tiny stubs) → keep up to 4 →
save under knowledge_base/entity_packs/<slug>/.

Pack layout:
  knowledge_base/entity_packs/sam-altman/
    portrait_01.jpg
    portrait_02.jpg
    portrait_03.jpg
    pack.json   (manifest with source URLs + dimensions)

Public API
──────────
  build_pack(entity_name, max_images=4, force=False) -> Path
      Returns the pack directory; downloads if missing.

  pick_pack_image(slug, rng=None) -> Path | None
      Return a random image path from an existing pack. The Visual
      Director Enricher uses this in place of the single
      person_photo path so each video varies.

  build_all(entity_names, ...) -> dict[str, Path]

CLI:
  python utils/entity_pack_builder.py build "Sam Altman" "Dario Amodei"
  python utils/entity_pack_builder.py pick sam-altman
"""

import argparse
import io
import json
import random
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


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PACKS_DIR = PROJECT_ROOT / "knowledge_base" / "entity_packs"
USER_AGENT = "Mozilla/5.0 (McNeillium_AI Phase20 entity pack builder)"

# Filenames containing any of these tokens are almost certainly UI
# chrome rather than portraits — skip them.
IMAGE_BLOCKLIST = (
    "icon", "edit-clear", "wikimedia", "commons-logo", "wiki", "ambox",
    "wikidata", "stub", "padlock", "question_book",
)
MIN_IMAGE_BYTES = 12_000  # smaller than this = thumbnail or stub


def _slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60]


def _http_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def _http_bytes(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def _wikipedia_image_titles(entity_name):
    """List all File: titles on the entity's Wikipedia page."""
    title = urllib.parse.quote(entity_name.replace(" ", "_"))
    api = (f"https://en.wikipedia.org/w/api.php?"
           f"action=query&format=json&prop=images&"
           f"titles={title}&imlimit=50")
    try:
        data = _http_json(api)
    except Exception as e:
        print(f"      ⚠️  page lookup failed for {entity_name}: {e}")
        return []
    pages = data.get("query", {}).get("pages", {})
    titles = []
    for page in pages.values():
        for img in page.get("images", []) or []:
            t = img.get("title", "")
            if t:
                titles.append(t)
    return titles


def _resolve_image_urls(file_titles):
    """Bulk-resolve File: titles to download URLs + sizes.

    Uses iiurlwidth=1200 to get thumb URLs that Wikimedia allows for
    hotlinking — direct upload.wikimedia.org links to originals get
    HTTP 429 rate-limited very quickly.
    """
    if not file_titles:
        return []
    out = []
    for i in range(0, len(file_titles), 30):
        chunk = file_titles[i:i + 30]
        titles_param = urllib.parse.quote("|".join(chunk))
        api = (f"https://en.wikipedia.org/w/api.php?"
               f"action=query&format=json&prop=imageinfo&"
               f"iiprop=url|size|mime&iiurlwidth=1200&"
               f"titles={titles_param}")
        try:
            data = _http_json(api)
        except Exception:
            continue
        pages = data.get("query", {}).get("pages", {})
        for page in pages.values():
            t = page.get("title", "")
            ii = (page.get("imageinfo") or [{}])[0]
            # Prefer the thumb URL (rate-limit-friendly); fall back to original
            url = ii.get("thumburl") or ii.get("url")
            if not url:
                continue
            mime = ii.get("mime", "")
            if not mime.startswith("image/"):
                continue
            if mime == "image/svg+xml":
                continue
            out.append({
                "title": t,
                "url": url,
                "width": ii.get("thumbwidth") or ii.get("width", 0),
                "height": ii.get("thumbheight") or ii.get("height", 0),
                "size_bytes": ii.get("size", 0),
            })
    return out


def _is_likely_portrait(image_meta):
    """Heuristic filter: skip UI chrome and stubs, keep plausible photos."""
    title_lower = image_meta["title"].lower()
    for blocked in IMAGE_BLOCKLIST:
        if blocked in title_lower:
            return False
    if image_meta.get("size_bytes", 0) < MIN_IMAGE_BYTES:
        return False
    # Reject extremely wide or tall (banners / signature scans)
    w, h = image_meta.get("width", 0), image_meta.get("height", 0)
    if w and h:
        ratio = max(w, h) / max(1, min(w, h))
        if ratio > 4.0:
            return False
    return True


def build_pack(entity_name, max_images=4, force=False):
    """Build (or refresh) the entity pack. Returns the directory path."""
    slug = _slug(entity_name)
    pack_dir = PACKS_DIR / slug
    manifest_path = pack_dir / "pack.json"

    if manifest_path.exists() and not force:
        return pack_dir

    print(f"  📚 Building pack for {entity_name}...")
    titles = _wikipedia_image_titles(entity_name)
    candidates = _resolve_image_urls(titles)
    candidates = [c for c in candidates if _is_likely_portrait(c)]
    # Pick the largest by total pixel area (best quality first)
    candidates.sort(
        key=lambda c: c.get("width", 0) * c.get("height", 0),
        reverse=True,
    )
    candidates = candidates[:max_images]

    if not candidates:
        print(f"      ⚠️  no usable images found for {entity_name}")
        return pack_dir

    pack_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    for i, c in enumerate(candidates, 1):
        ext = Path(c["url"]).suffix.lower() or ".jpg"
        if ext not in (".jpg", ".jpeg", ".png", ".webp"):
            ext = ".jpg"
        local = pack_dir / f"portrait_{i:02d}{ext}"
        try:
            local.write_bytes(_http_bytes(c["url"]))
            time.sleep(1.2)  # rate-limit cushion — wikimedia is strict
            saved.append({
                "path": str(local.resolve()).replace("\\", "/"),
                "filename": local.name,
                "source_title": c["title"],
                "source_url": c["url"],
                "width": c.get("width"),
                "height": c.get("height"),
            })
            print(f"      ✅ {local.name}  "
                  f"({c.get('width', '?')}x{c.get('height', '?')})")
        except Exception as e:
            print(f"      ⚠️  download failed for {c['title']}: {e}")

    manifest = {
        "entity": entity_name,
        "slug": slug,
        "images": saved,
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2),
                             encoding="utf-8")
    print(f"  💾 pack.json → {manifest_path}  ({len(saved)} images)")
    return pack_dir


def pick_pack_image(slug, rng=None):
    """Return a random image Path from a built pack, or None."""
    rng = rng or random
    manifest_path = PACKS_DIR / slug / "pack.json"
    if not manifest_path.exists():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    images = manifest.get("images", [])
    if not images:
        return None
    return Path(rng.choice(images)["path"])


def build_all(entity_names, max_images=4, force=False):
    out = {}
    for name in entity_names:
        out[name] = build_pack(name, max_images=max_images, force=force)
    return out


def main():
    p = argparse.ArgumentParser(description="Phase 20.4 entity pack builder")
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="Build packs for one or more entities")
    b.add_argument("names", nargs="+")
    b.add_argument("--max-images", type=int, default=4)
    b.add_argument("--force", action="store_true",
                   help="Re-download even if manifest exists")

    pi = sub.add_parser("pick", help="Pick a random image from a pack")
    pi.add_argument("slug")

    ls = sub.add_parser("list", help="Show all built packs")

    args = p.parse_args()

    if args.cmd == "build":
        build_all(args.names, max_images=args.max_images, force=args.force)
    elif args.cmd == "pick":
        path = pick_pack_image(args.slug)
        print(path or "<no pack>")
    elif args.cmd == "list":
        if not PACKS_DIR.exists():
            print("no packs built yet")
            return
        for d in sorted(PACKS_DIR.iterdir()):
            if not d.is_dir():
                continue
            mp = d / "pack.json"
            if not mp.exists():
                continue
            m = json.loads(mp.read_text(encoding="utf-8"))
            print(f"  {m['slug']:20s}  ({len(m.get('images', []))} images)")


if __name__ == "__main__":
    main()
