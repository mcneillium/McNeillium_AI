# CLAUDE.md — McNeillium AI (post-pivot, Phase 12)

## What This Project Does

Daily AI news / commentary channel. One video per day, sometimes two.
Reaction mode is the default. Explainer mode is opt-in for the rare
deep dive.

We are **not** a tutorials channel and we are **not** a deep-explainer
channel. We are a **fast, opinionated daily AI news show** that takes
positions and ships before the news goes stale.

## Daily workflow

```
Morning (you):  ask Claude Code "what should we cover today?"
  →             Trend Researcher (Agent 1) scans HN/Reddit/HF and
                refreshes knowledge_base/news_queue.json
  →             You pick a topic from the top 5
Afternoon:      Claude Code runs the reaction pipeline (below)
                → output/videos/_<date>_<slug>.mp4 sits ready
Review:         You watch the local MP4
Upload:         When you say so:
                python utils/youtube_upload.py --video <path> --privacy private
```

Expected wall time per video: ~25 min (3 Kling clips + voice + render).
Expected cost per video: **~$1.80 - $2.10** (ElevenLabs + Kling + AssemblyAI).

## Modes

Three modes survive the pivot. The Mode Selector picks one from the
script title + metadata:

| Mode | When | Caption style | Music | Illustrations |
|---|---|---|---|---|
| **reaction** | DEFAULT — all news/commentary | word-by-word viral | dramatic, music_vol 0.10 | none |
| **tutorial** | Title starts with "Build" / "How to" / "Tutorial:" | phrase + code | focused calm | minimal |
| **explainer** | Title starts with "Explainer:" or pillar=deep_dive | phrase semantic | minimal ambient | Manim + equations + concept evolution |

Reaction is the default for everything unless the user explicitly
chooses otherwise. The explainer pipeline (Phase 4-11) is still
intact — just dormant unless triggered.

## Reaction-mode pipeline (the default daily flow)

When you ask "make a video about X", I play these roles in order:

1. **Trend Researcher (Agent 1)** — confirm the story is hot, pull
   sources. `utils/trend_researcher.py` for the raw feed.
2. **Script Writer (Agent 2)** — 5-7 minute reaction script following
   `knowledge_base/style_guide.md` (post-pivot version: hook / context
   / story / my take / implications / close).
3. **Hook Engineer (Agent 3D)** — punchy first 10 seconds.
4. **SEO Optimizer (Agent 4)** — clickable news title, description,
   tags. Front-load the company name.
5. **Mode Selector (Agent 52)** — should pick `reaction` unless title
   includes "Explainer:" / "Build" / "Tutorial:".
6. **Colour System (Agent 57)** — palette from script.
7. **Voice Producer (ElevenLabs, Agent 5A)** —
   `python voice/generate_voice_elevenlabs.py`. Brian voice, ~$1.15.
8. **Audio Quality Director (Agent 5B, --pro)** —
   `python utils/audio_quality.py output/audio/latest.mp3 --replace --pro`.
9. **AssemblyAI Verifier (Agent 26b)** —
   `python utils/assemblyai_verify.py`. Replaces drift > 100ms.
10. **Visual Director (Agent 3B)** — shot list with **2-3 Kling hero
    beats** + lots of Pixabay b-roll. NO Manim. NO concept evolution.
11. **Kling Hero Pre-fetch (Agent 28b)** —
    `python utils/kling_via_fal.py batch`. ~$0.60-0.90.
12. **Footage Relevance (Agent 25)** — score and rewrite weak queries.
13. **Video Producer (Agent 6A)** — `python video/generate_video.py`.
    Viral captions (Impact 96pt), music ducking at reaction settings
    (vol 0.10 / duck 10 / -14 LUFS), 2-pass loudnorm baked in.
14. **QC Director (Agent 27)** — threshold 8.0 for reaction. APPROVE or
    REJECT.
15. **Shorts + Blog + Twitter (Agents 34/37/38)** — auto via pipeline.py
    STAGE 4, or run individually.
16. **Publisher (Agent 7A)** — only on your "upload it" command. Always
    PRIVATE first.

## What's dormant (still here, just not invoked by default)

Phase 4-11 added a full explainer kit. It's all still in the repo and
will run when explainer mode is invoked. The mode-skip guards added in
Phase 12 mean the following silently no-op in reaction mode:

- **Illustration Engineer (Agent 24)** — Manim diagrams
- **Concept Evolution Designer (Agent 56)** — held-shot evolving illustrations
- **Animated Equation Renderer (Agent 55)** — formula animations

If you ever want the full explainer treatment again, prefix the topic
with **`Explainer:`** in your request — e.g. "Explainer: How RAG
Actually Works". That unlocks the full Phase 4-11 stack and costs
~$2-4 per video (illustrations + held shots + equations).

## Trend Researcher (Agent 1) — upgraded

Run: `python utils/trend_researcher.py`

Pulls from (no auth needed):
- Hacker News top stories (AI-keyword filter)
- Reddit JSON: r/MachineLearning, r/LocalLLaMA, r/OpenAI, r/Anthropic,
  r/singularity
- Hugging Face trending models

Scoring (per story, 0-100):
- **Recency** up to 40 pts (linear decay over 72h)
- **Engagement** up to 30 pts (log-scaled votes + comments)
- **Conflict** up to 15 pts (regex: lawsuit, leaves, fired, drama, vs)
- **Audience fit** up to 15 pts (AI + developer keyword density)

Already-covered titles in `knowledge_base/topic_tracker.md` get
filtered out. Top 5 stories saved to
`knowledge_base/news_queue.json`.

The current `knowledge_base/content_queue.md` was hand-curated via
WebSearch on 2026-05-14 and contains 5 picks ranked by news heat.

## Quick commands

| You say | I do |
|---|---|
| "What should we cover today?" | Run trend researcher, read top 5 |
| "Make a video about [X]" | Full reaction pipeline → local MP4 |
| "Explainer: [X]" | Full explainer pipeline (Phase 4-11) |
| "Build a [X]" or "Tutorial: [X]" | Tutorial mode pipeline |
| "Upload the latest video" | YouTube as PRIVATE, then commit |
| "Cost so far this month?" | `python utils/cost_tracker.py` |

## Project structure (post-pivot snapshot)

- `niche_profile.yaml` — Channel identity, audience, content pillars
- `agents.yaml` — Agent role definitions (40+ agents)
- `knowledge_base/style_guide.md` — Post-pivot writing rules
- `knowledge_base/content_queue.md` — Hand-curated 5-pick queue
- `knowledge_base/news_queue.json` — Auto-refreshed by trend_researcher
- `knowledge_base/topic_tracker.md` — Already-covered titles
- `voice/generate_voice_elevenlabs.py` — Primary voice (Brian)
- `voice/generate_voice.py` — Edge TTS fallback
- `utils/trend_researcher.py` — Daily news scanner (Phase 12)
- `utils/assemblyai_verify.py` — Caption ground-truth
- `utils/kling_via_fal.py` — Hero shot generator
- `utils/cost_tracker.py` — Per-video billing log
- `video/captions_v2.py` — Viral captions (Impact 96pt)
- `video/generate_video.py` — Video assembly (mode-aware mix)
- `utils/qc_director.py` — Final gate (mode-aware threshold + loudness)
- `utils/shorts_producer.py` — Vertical reframe for YouTube Shorts
- `utils/blog_writer.py` — Script → markdown article
- `utils/twitter_thread.py` — Script → 6-8 tweets

## Key design decisions (post-pivot)

- **Reaction is the default**. Every reflex assumes news/commentary.
- **5-7 min sweet spot**. Anything longer drags for news content.
- **2-3 Kling hero shots** + Pixabay b-roll. No Manim.
- **Viral captions** (Impact 96pt, yellow active word, dark blob).
- **ElevenLabs Brian** is the default voice, Edge TTS is fallback.
- **AssemblyAI** is the ground truth for captions (Whisper-tiny is fallback).
- **2-pass loudnorm** in the final mix — hit target ±1 dB.
- **Mode-aware loudness target**: reaction -14 LUFS, explainer -16.
- **Upload is always manual**. PRIVATE first, you watch, you publish.
- **Cost is tracked**: every API call logs to
  `knowledge_base/costs/YYYY-MM.csv`.

## Phase history (for context)

- Phases 1-3: original pipeline (Edge TTS, basic shot lists, Pillow text)
- Phase 4: beat-level footage, stripped overlays, Manim illustrations,
  Whisper sync validator, QC director
- Phase 5: HF SDXL AI image generator, style director
- Phase 6: Voice director (multi-Edge), Music composer, Sound designer
- Phase 7: Shorts producer, Blog writer, Twitter thread
- Phase 8: Analytics monitor, Retention decoder, Comment analyzer
- Phase 9: Pipeline orchestrator, error recovery, scheduler, dashboard
- Phase 10: Mode selector, phrase captions, concept evolution, equations
- Phase 11: ElevenLabs primary, AssemblyAI, Kling hero, viral captions,
  cost tracker
- **Phase 12 (pivot)**: AI news/commentary channel. Reaction default.
  Explainer opt-in. Trend Researcher upgraded with real source scraping.

The whole Phase 4-11 explainer stack is still there. It's just sleeping.
