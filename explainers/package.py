"""Package built explainers for YouTube: video, captions, thumbnail, metadata.

    python explainers/package.py                 # every spec with a built video
    python explainers/package.py 02-river        # one

Reads explainers/specs/<slug>.yaml and explainers/work/<slug>/, writes
explainers/output/<slug>/ (git-ignored):

    <slug>.mp4            the finished video, captions burnt in
    <slug>.srt            the same captions as a separate track
    thumbnail.jpg         1280x720, under 2 MB
    youtube.json          title, description, tags, privacy "private"
    description.txt       the description on its own, for pasting

Nothing is uploaded. Upload is manual and private first (see CLAUDE.md).
"""
import html
import json
import shutil
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
SPECS, WORK, OUT = ROOT / "specs", ROOT / "work", ROOT / "output"

THUMB_HTML = """<!doctype html><html><head><meta charset="utf-8"><style>
html,body{{margin:0;width:1280px;height:720px;background:#101b2c;color:#fff;
font-family:'Inter',sans-serif;overflow:hidden}}
.bar{{position:absolute;left:0;top:0;height:12px;width:100%;background:linear-gradient(90deg,#a78bfa,#6fd3c4)}}
.shot{{position:absolute;right:-40px;top:70px;width:700px;height:580px;border-radius:24px;overflow:hidden;
box-shadow:0 30px 80px rgba(0,0,0,.55);border:3px solid rgba(167,139,250,.55)}}
.shot img{{width:100%;height:100%;object-fit:cover;object-position:{pos}}}
.fade{{position:absolute;inset:0;background:linear-gradient(90deg,#101b2c 0,#101b2c 40%,rgba(16,27,44,.15) 62%,rgba(16,27,44,0) 100%)}}
.text{{position:absolute;left:64px;top:0;bottom:0;width:640px;display:flex;flex-direction:column;justify-content:center}}
.kicker{{display:inline-block;align-self:flex-start;font-size:26px;font-weight:700;letter-spacing:.08em;
text-transform:uppercase;color:#101b2c;background:#a78bfa;padding:8px 16px;border-radius:10px;margin-bottom:26px}}
h1{{font-size:{size}px;line-height:1.02;font-weight:800;margin:0;letter-spacing:-.01em}}
h1 em{{font-style:normal;color:#6fd3c4}}
.foot{{position:absolute;left:64px;bottom:44px;font-size:26px;color:#acbcd0}}
</style></head><body><div class="bar"></div>
<div class="shot"><img src="{img}"></div><div class="fade"></div>
<div class="text"><span class="kicker">{kicker}</span><h1>{text}</h1></div>
<div class="foot">McNeillium AI · Paul McNeill</div></body></html>"""


def thumbnail(spec, slug, out):
    from playwright.sync_api import sync_playwright
    t = spec["youtube"]["thumbnail"]
    img = (ROOT.parent / t["image"]).resolve()
    text = html.escape(t["text"]).replace("*", "<em>", 1).replace("*", "</em>", 1)
    page = THUMB_HTML.format(img=img.as_uri(), text=text, kicker=html.escape(t["kicker"]),
                             size=t.get("size", 92), pos=t.get("position", "left top"))
    chrome = shutil.which("google-chrome")
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=chrome, args=["--no-sandbox", "--allow-file-access-from-files"]) \
            if chrome else p.chromium.launch()
        pg = b.new_page(viewport={"width": 1280, "height": 720})
        tmp = out / "_thumb.html"
        tmp.write_text(page)
        pg.goto(tmp.as_uri())
        pg.wait_for_timeout(400)
        pg.screenshot(path=str(out / "thumbnail.jpg"), type="jpeg", quality=90)
        b.close()
        tmp.unlink()


def description(spec):
    y = spec["youtube"]
    lines = [y["summary"].strip(), ""]
    for label, url in y["links"]:
        lines.append(f"{label}: {url}")
    lines += ["", y.get("note", "").strip()] if y.get("note") else []
    lines += [
        "",
        "About this series: short explainers of Paul McNeill's own projects and research. "
        "Every fact comes from paulmartinmcneill.com and its public code.",
        "",
        "Narrated with an AI voice made with ElevenLabs. It is not Paul's voice. "
        "Captions are on by default and available as a subtitle track.",
    ]
    return "\n".join(l for l in lines if l is not None).strip() + "\n"


def package(slug):
    spec = yaml.safe_load((SPECS / f"{slug}.yaml").read_text())
    work = WORK / slug
    video, srt = work / f"{slug}.mp4", work / f"{slug}.srt"
    if not video.exists():
        print(f"skip {slug}: no video yet")
        return
    out = OUT / slug
    out.mkdir(parents=True, exist_ok=True)
    shutil.copy2(video, out / video.name)
    shutil.copy2(srt, out / srt.name)
    thumbnail(spec, slug, out)
    desc = description(spec)
    (out / "description.txt").write_text(desc)
    meta = {
        "title": spec["youtube"]["title"],
        "description": desc,
        "tags": spec["youtube"]["tags"],
        "category": "Science & Technology",
        "privacy": "private",
        "made_for_kids": False,
        "captions": srt.name,
        "thumbnail": "thumbnail.jpg",
    }
    assert len(meta["title"]) <= 100, f"{slug}: title over 100 characters"
    assert len(desc) <= 5000, f"{slug}: description over 5000 characters"
    (out / "youtube.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n")
    print(f"packaged {slug} -> {out}")


if __name__ == "__main__":
    slugs = sys.argv[1:] or sorted(p.stem for p in SPECS.glob("*.yaml"))
    for s in slugs:
        package(s)
