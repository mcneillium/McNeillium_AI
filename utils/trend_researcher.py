#!/usr/bin/env python3
"""
McNeillium AI — Agent 1: Trend Researcher (Phase 12 pivot)

The most important agent under the news/commentary positioning. Each run
scans free-tier sources for AI stories and writes a ranked queue:

    knowledge_base/news_queue.json

Sources (no auth required):
  - Hacker News: top + new (filter for AI keywords)
  - Reddit JSON:  r/MachineLearning, r/LocalLLaMA, r/OpenAI, r/Anthropic
                  (uses .json endpoints, no OAuth)
  - Hugging Face: trending models endpoint
  - (Optional) RSS feeds from AI newsletters when configured

Scoring per story (0-100):
  recency      = up to 40 pts, decays linearly over 72 hours
  engagement   = up to 30 pts, log-scaled on votes/comments
  conflict     = up to 15 pts, regex match for fight/drama/controversy
  audience_fit = up to 15 pts, AI / dev keyword density

Already-covered topics in knowledge_base/topic_tracker.md are skipped.
"""

import argparse
import datetime
import io
import json
import math
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower().replace("-", "") != "utf8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8",
                                  errors="replace")


PROJECT_ROOT = Path(__file__).resolve().parent.parent
KB = PROJECT_ROOT / "knowledge_base"
QUEUE_PATH = KB / "news_queue.json"
TRACKER_PATH = KB / "topic_tracker.md"

AI_KEYWORDS = re.compile(
    r"\b(ai|llm|llms|gpt|gpt-?\d|chatgpt|claude|anthropic|openai|"
    r"gemini|google\s+deepmind|deepmind|meta\s*ai|llama|mistral|"
    r"transformer|attention|inference|fine[\s-]?tun|"
    r"agent|agentic|copilot|cursor|stable\s*diffusion|midjourney|"
    r"hugging\s*face|"
    r"sam\s+altman|dario\s+amodei|demis\s+hassabis|greg\s+brockman|"
    r"ilya\s+sutskever|yann\s+le\s*cun|"
    r"machine\s+learning|deep\s+learning|reinforcement\s+learning|"
    r"neural\s+net|prompt\s+engineer|rag|embedding|vector)",
    re.I,
)

DEV_KEYWORDS = re.compile(
    r"\b(api|sdk|github|open[\s-]?source|repo|model\s+release|"
    r"benchmark|paper|arxiv|cli|cuda|gpu|tpu|inference|server|"
    r"code|coding|dev|developer)",
    re.I,
)

CONFLICT_RE = re.compile(
    r"\b(fight|sues?|sued|lawsuit|fired|leaves?|quits?|drama|"
    r"controversy|criticis|backlash|leak|scandal|"
    r"vs|versus|beats?|crushes|kills|destroys|cooked|"
    r"banned|removed|withdrawn|rolls?\s+back|resigns?)\b",
    re.I,
)


def _http_json(url, headers=None, timeout=15):
    h = {"User-Agent": "McNeilliumAI-TrendBot/1.0 (+https://github.com/)"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _ts_now():
    return int(datetime.datetime.now(datetime.timezone.utc).timestamp())


# ─── Sources ────────────────────────────────────────────────────

def fetch_hacker_news(limit=40):
    out = []
    try:
        top_ids = _http_json(
            "https://hacker-news.firebaseio.com/v0/topstories.json"
        )[:limit]
    except Exception as e:
        print(f"  ⚠️  HN topstories failed: {e}")
        return out
    for hid in top_ids:
        try:
            item = _http_json(
                f"https://hacker-news.firebaseio.com/v0/item/{hid}.json"
            )
        except Exception:
            continue
        if not item:
            continue
        title = item.get("title") or ""
        if not AI_KEYWORDS.search(title):
            continue
        out.append({
            "source": "hn",
            "title": title,
            "url": item.get("url") or f"https://news.ycombinator.com/item?id={hid}",
            "votes": int(item.get("score", 0)),
            "comments": int(item.get("descendants", 0) or 0),
            "created_ts": int(item.get("time", 0)),
            "id": str(hid),
        })
    return out


def fetch_reddit(subreddit, listing="hot", limit=25):
    url = f"https://www.reddit.com/r/{subreddit}/{listing}.json?limit={limit}"
    try:
        data = _http_json(url)
    except Exception as e:
        print(f"  ⚠️  reddit /r/{subreddit} failed: {e}")
        return []
    out = []
    for child in data.get("data", {}).get("children", []):
        d = child.get("data") or {}
        title = d.get("title") or ""
        if not AI_KEYWORDS.search(title):
            # MachineLearning subreddits are all AI anyway, but the filter
            # protects against off-topic memes
            if subreddit.lower() not in {"machinelearning", "localllama",
                                          "openai", "anthropic"}:
                continue
        out.append({
            "source": f"r/{subreddit}",
            "title": title,
            "url": "https://www.reddit.com" + d.get("permalink", ""),
            "votes": int(d.get("ups", 0)),
            "comments": int(d.get("num_comments", 0)),
            "created_ts": int(d.get("created_utc", 0)),
            "id": d.get("id", ""),
            "external_url": d.get("url_overridden_by_dest")
                            or d.get("url"),
        })
    return out


def fetch_huggingface_trending(limit=20):
    try:
        data = _http_json(
            f"https://huggingface.co/api/models?sort=trending&direction=-1"
            f"&limit={limit}"
        )
    except Exception as e:
        print(f"  ⚠️  HF trending failed: {e}")
        return []
    out = []
    for m in data:
        model_id = m.get("id") or m.get("modelId")
        if not model_id:
            continue
        likes = int(m.get("likes", 0))
        downloads = int(m.get("downloads", 0))
        out.append({
            "source": "hf",
            "title": f"HF trending: {model_id}",
            "url": f"https://huggingface.co/{model_id}",
            "votes": likes,
            "comments": downloads // 1000,  # downloads-as-engagement proxy
            "created_ts": _ts_now() - 3600,  # treat as fresh
            "id": model_id,
        })
    return out


# ─── Scoring ────────────────────────────────────────────────────

def score_story(item):
    now = _ts_now()
    age_h = max(0.0, (now - item["created_ts"]) / 3600.0)
    # Recency: 40 pts at 0h, linearly decays to 0 at 72h
    recency = max(0.0, 40.0 * (1.0 - age_h / 72.0))
    # Engagement: log-scaled votes + comments, capped at 30
    eng_raw = math.log1p(item.get("votes", 0)) * 5 \
              + math.log1p(item.get("comments", 0)) * 3
    engagement = min(30.0, eng_raw)
    # Conflict bonus
    conflict = 15.0 if CONFLICT_RE.search(item.get("title", "")) else 0.0
    # Audience fit: AI density + dev density
    title = item.get("title", "")
    ai_hits = len(AI_KEYWORDS.findall(title))
    dev_hits = len(DEV_KEYWORDS.findall(title))
    audience = min(15.0, ai_hits * 5 + dev_hits * 3)
    total = recency + engagement + conflict + audience
    return round(total, 1), {
        "recency": round(recency, 1),
        "engagement": round(engagement, 1),
        "conflict": conflict,
        "audience": round(audience, 1),
        "age_hours": round(age_h, 1),
    }


# ─── Dedup against topic_tracker.md ────────────────────────────

def load_covered_titles():
    if not TRACKER_PATH.exists():
        return set()
    text = TRACKER_PATH.read_text(encoding="utf-8")
    titles = set()
    for line in text.splitlines():
        # Lines like "- 2026-05-13: Title here" or "- Title here"
        m = re.match(r"^\s*[-*]\s*(?:\d{4}-\d{2}-\d{2}:\s*)?(.+?)$", line)
        if m:
            titles.add(_norm(m.group(1)))
    return titles


def _norm(s):
    return re.sub(r"[^a-z0-9]+", "", s.lower())


# ─── Main ──────────────────────────────────────────────────────

def run(limit=5):
    print("🔎 Trend Researcher — scanning sources...")
    all_items = []

    print("   • Hacker News...")
    all_items.extend(fetch_hacker_news(limit=80))
    print("   • Reddit communities...")
    for sub in ("MachineLearning", "LocalLLaMA", "OpenAI", "Anthropic",
                "singularity"):
        all_items.extend(fetch_reddit(sub, listing="hot", limit=25))
    print("   • Hugging Face trending...")
    all_items.extend(fetch_huggingface_trending(limit=15))

    covered = load_covered_titles()
    print(f"   • {len(covered)} previously-covered titles loaded")

    # Score & dedupe by normalised title
    seen_titles = set()
    scored = []
    for item in all_items:
        title = item.get("title") or ""
        nt = _norm(title)
        if not nt:
            continue
        if nt in seen_titles or nt in covered:
            continue
        seen_titles.add(nt)
        total, breakdown = score_story(item)
        scored.append({**item, "score": total, "breakdown": breakdown})

    scored.sort(key=lambda x: -x["score"])
    top = scored[:limit]

    print(f"\n🏆 Top {len(top)} of {len(scored)} stories:")
    for i, s in enumerate(top, 1):
        print(f"  [{i}] ({s['score']}) {s['title'][:90]}")
        print(f"      {s['source']}  |  {s['breakdown']}")

    KB.mkdir(parents=True, exist_ok=True)
    payload = {
        "captured_at": datetime.datetime.now(
            datetime.timezone.utc).isoformat(),
        "candidates_considered": len(scored),
        "top": top,
    }
    QUEUE_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\n💾 → {QUEUE_PATH}")
    return True


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=5)
    args = p.parse_args()
    sys.exit(0 if run(limit=args.limit) else 1)


if __name__ == "__main__":
    main()
