#!/usr/bin/env python3
"""
McNeillium_AI — Agent 37: Blog Writer

Converts the script JSON into a 1500-word markdown article suitable for
Medium / dev.to / Substack. Adds SEO-friendly headings (H1 + H2 per
section), a TL;DR pulled from the hook + summary, references to the
thumbnail + illustrations, and a CTA back to the YouTube video.

The article is NOT auto-published — it's saved to
`output/blog/<slug>.md` for manual review + paste. Auto-publishing to
specific platforms requires per-platform API tokens (Medium, Substack)
that aren't configured here.
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
SCRIPT_PATH = PROJECT_ROOT / "output" / "scripts" / "latest.json"
BLOG_DIR = PROJECT_ROOT / "output" / "blog"


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60]


def _para_split(text, sentences_per_para=3):
    """Re-flow narration into short readable paragraphs."""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    paras = []
    buf = []
    for s in sentences:
        if not s.strip():
            continue
        buf.append(s.strip())
        if len(buf) >= sentences_per_para:
            paras.append(" ".join(buf))
            buf = []
    if buf:
        paras.append(" ".join(buf))
    return paras


def script_to_markdown(script, video_url=None):
    title = script.get("title", "Untitled")
    sections = script.get("sections", [])
    meta = script.get("metadata", {}) or {}
    tags = meta.get("tags") or []
    description = meta.get("description", "") or ""

    hook = next((s for s in sections if s.get("id") == "hook"), None)
    summary = next((s for s in sections if s.get("id") == "summary"), None)

    lines = [f"# {title}", ""]
    if tags:
        lines.append(
            "**Tags:** " + ", ".join(t.lstrip("#") for t in tags[:8]))
        lines.append("")
    if video_url:
        lines.append(f"📺 **Watch the video:** [YouTube]({video_url})")
        lines.append("")

    # TL;DR (~80 words)
    tldr_pieces = []
    if hook:
        tldr_pieces.append(hook.get("narration", "")[:280])
    if summary:
        tldr_pieces.append(summary.get("narration", "")[:280])
    if tldr_pieces:
        lines.append("## TL;DR")
        lines.append("")
        lines.append(" ".join(tldr_pieces).strip())
        lines.append("")

    if description:
        lines.append("## Why this matters")
        lines.append("")
        lines.append(description.strip())
        lines.append("")

    body_sections = [s for s in sections
                     if s.get("id") not in {"hook", "outro"}]
    for sec in body_sections:
        heading = sec.get("heading") or sec.get("id", "").replace("_", " ").title()
        lines.append(f"## {heading}")
        lines.append("")
        for para in _para_split(sec.get("narration", "")):
            lines.append(para)
            lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("*Subscribe to McNeillium_AI for more AI & emerging tech deep dives.*")
    if video_url:
        lines.append(f"*Full video: {video_url}*")
    lines.append("")
    return "\n".join(lines)


def run(script_path, out_dir, video_url=None):
    if not Path(script_path).exists():
        print(f"❌ Script not found: {script_path}")
        return False
    with open(script_path, encoding="utf-8") as f:
        script = json.load(f)

    md = script_to_markdown(script, video_url=video_url)
    word_count = len(re.findall(r"\w+", md))

    slug = _slug(script.get("title", "untitled"))
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    out_path = Path(out_dir) / f"{slug}.md"
    out_path.write_text(md, encoding="utf-8")
    print(f"📝 Blog post: {out_path}")
    print(f"   word count: {word_count} (target 1200-1800)")
    return True


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--script", default=str(SCRIPT_PATH))
    p.add_argument("--out-dir", default=str(BLOG_DIR))
    p.add_argument("--video-url", default="")
    args = p.parse_args()
    ok = run(args.script, args.out_dir,
             video_url=args.video_url or None)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
