# CLAUDE.md — McNeillium_AI Multi-Agent System

## What This Project Does
Autonomous YouTube content pipeline for the McNeillium_AI channel.
19 AI agents collaborate to produce professional AI/tech educational videos.

## The Agents (YOU play each role sequentially)

### When asked to produce a video, follow these 19 stages:

**AGENT 1 — Trend Researcher**
Search the web for the latest AI news. Check knowledge_base/topic_tracker.md
to avoid repeats. Read niche_profile.yaml for content pillars and audience.
Find a timely, compelling angle. Save research to
knowledge_base/research/YYYY-MM-DD_topic-slug.md with facts and sources.

**AGENT 2 — Script Writer**
Read the research, niche_profile.yaml, AND knowledge_base/style_guide.md.
Write a structured JSON script to output/scripts/latest.json. Follow the
style guide strictly: hook in 10 seconds, analogies for every concept,
no filler, natural TTS text. Target 1800-2200 words narration across 8 sections.

**AGENT 3A — Quality Reviewer**
Review the script against the quality rubric in agents.yaml. Score each section.
Rewrite anything below 7/10. Add pattern interrupts every 90 seconds.
Fix TTS issues (abbreviations, symbols). Save review to knowledge_base/reviews/.

**AGENT 3B — Visual Director**
Read the reviewed script. Design a BEAT-LEVEL shot list — 12-15 beats per
section (one every 5-8 seconds). Each beat is footage / stat_card / comparison
/ illustration with a specific Pixabay-style query, duration, and motion.
Generic queries banned (technology, innovation, data flowing). Save to
output/shot_list.json.

**AGENT 24 — Illustration Engineer (Phase 4)**
Run: python utils/illustration_engineer.py
Scans the script for moments stock footage can't show ("how X works",
"step by step", "X vs Y", statistics, architecture, timelines) and renders
custom diagrams using Manim (when MSVC is available) or a PIL-based
fallback renderer. Injects illustration beats into the shot list.

**AGENT 25 — Footage Relevance Checker (Phase 4)**
Run: python utils/footage_relevance.py
Scores every beat's query 1-10. Rewrites anything below 7 using concrete
nouns extracted from the narration. Banned generic queries are auto-rejected.

**AGENT 3C — Engagement Writer**
Add strategic hooks, open loops, pattern interrupts, and CTAs at 60-90 second
intervals. Strengthen the hook and outro CTA. Update the script JSON.

**AGENT 3D — Hook Engineer**
Rewrite the first 10 seconds using a proven hook framework:
QUESTION / CONTRARIAN / SHOCK STAT / IN MEDIAS RES / END-FIRST.
Confirm the video's promise in 3 seconds. Zero filler words. Update script JSON.

**AGENT 3E — Subconscious Loop Specialist**
Insert open loops at section boundaries. Rewrite 30% of section endings for
forward momentum. Add mid-video re-hooks at 25/50/75% marks. Apply the
"earn the next second" filter — cut any sentence that doesn't advance the story.

**AGENT 4 — SEO Optimizer**
Read knowledge_base/seo/description_template.md. Generate 5 title options,
pick the best. Write a YouTube description with timestamps. Generate 15-20 tags.
Write thumbnail text (max 4 words). Update output/scripts/latest.json metadata.

**AGENT 5A — Voice Producer**
Run: python voice/generate_voice.py --script output/scripts/latest.json
This generates audio + word-level caption timestamps for animated captions.

**AGENT 5B — Audio Quality Director**
Run: python utils/audio_quality.py output/audio/latest.mp3 --replace
Applies broadcast audio chain: highpass → presence EQ → compression → loudnorm.
Scores output quality (0-10). Reprocesses if score < 7.

**AGENT 26 — Sync Validator (Phase 4)**
Run: python utils/sync_validator.py
Re-transcribes the narration audio with whisper-timestamped. For any word
where Edge TTS timestamps drift >200ms from Whisper, replaces with Whisper's.
Writes output/audio/latest_words_verified.json. The Video Producer auto-picks
this up via captions.load_verified_words().

**AGENT 6A — Video Producer**
Run: python video/generate_video.py --script output/scripts/latest.json --audio output/audio/latest.mp3
Run: python utils/generate_thumbnail.py --title "[THUMBNAIL TEXT]" --query "[relevant image query]"

**AGENT 6B — End Screen Strategist**
Add end_screen metadata to the script JSON: teaser_text (max 8 words) for
the next video topic, curiosity-driven CTA. The video generator automatically
burns this as an ASS overlay in the last 15 seconds.

**AGENT 6C — Post-Production Director**
Check audio loudness of the final video. If not -14 LUFS, re-normalize.
Verify 1080p/30fps output, reasonable file size, duration match.

**AGENT 27 — QC Director (Phase 4)**
Run: python utils/qc_director.py output/videos/latest.mp4
Final gate before upload. Samples 20 frames + runs deterministic checks:
visual variety, caption legibility, brightness, loudness, duration. Weighted
score → pass/fail (threshold 8). NO upload without QC approval. Exits non-zero
on failure so Agent 7A can decide whether to re-render.

**AGENT 7A — Publisher**
Run: python utils/youtube_upload.py --video output/videos/latest.mp4 --script output/scripts/latest.json --privacy private
Archive the script to knowledge_base/scripts/
Update knowledge_base/topic_tracker.md
Git commit and push.

**AGENT 7B — Community Engagement Bot**
Run: python utils/community_engage.py VIDEO_ID --script output/scripts/latest.json
Posts a pinned comment with timestamps + engagement question.
Replies to the first 30 commenters with personalized responses.

## Quick Commands

### Full pipeline (all 15 agents):
Just tell me: "Make a video about [topic]"

### Individual agents:
- "Research trending AI topics" -> Agent 1 only
- "Write a script about [topic]" -> Agents 1-4
- "Generate voice and video for the current script" -> Agents 5-6B
- "Upload the latest video" -> Agent 7

### Knowledge base:
- "Add [topic] to the knowledge base" -> Create knowledge_base/topics/topic.md
- "What topics have we covered?" -> Read knowledge_base/topic_tracker.md
- "What should our next video be about?" -> Agent 1 research + topic_tracker check

## Knowledge Base Location
knowledge_base/ — Contains topics encyclopedia, research, past scripts,
SEO patterns, competitor analysis, style guide, and topic tracker.
Read from it before writing. Write to it after every video.

## Project Structure
- niche_profile.yaml — Channel identity, audience, content pillars, visual brand
- agents.yaml — Agent role definitions and processes (15 agents)
- utils/audio_quality.py — Broadcast audio processing chain (Agent 5B)
- utils/community_engage.py — YouTube comment engagement bot (Agent 7B)
- utils/illustration_engineer.py — Custom diagram generator (Agent 24, Phase 4)
- utils/footage_relevance.py — Shot-list query auditor (Agent 25, Phase 4)
- utils/sync_validator.py — Whisper-verified caption timestamps (Agent 26, Phase 4)
- utils/qc_director.py — Final quality gate before upload (Agent 27, Phase 4)
- video/captions.py — ASS subtitle generator with karaoke word highlights
- video/logo_intro.py — 3-second branded logo animation intro
- voice/generate_voice.py — Edge TTS narration + word-level caption timestamps
- video/generate_video.py — Video assembly v6 (shot lists, animated captions, voice ducking)
- utils/generate_thumbnail.py — YouTube thumbnail generator
- utils/youtube_upload.py — YouTube upload with OAuth
- utils/git_push.py — Auto git commit and push
- knowledge_base/ — AI knowledge base (grows with every video)
- output/shot_list.json — Visual Director's shot plan (generated per video)
- output/audio/captions/ — Word-level timestamps for animated captions

## Key Design Decisions
- Claude Code IS the orchestrator — no external agent framework needed
- Knowledge base is local markdown/JSON — simple, fast, version-controlled
- Each agent stage reads from and writes to the knowledge base
- Quality reviewer creates a feedback loop — scripts get revised before production
- Visual Director designs shot lists before video generation
- Engagement Writer adds retention hooks before production
- SEO happens BEFORE production — titles and metadata inform the video
- Voice producer generates word-level timestamps for animated captions
- Video producer reads shot lists for multi-clip sections and stat cards
- Voice ducking auto-ducks music when narration is active
- Audio normalized to -14 LUFS broadcast standard
- Audio quality chain: highpass → presence EQ → compression → loudnorm
- End screen teaser overlay burns into last 15 seconds automatically
- Hook Engineer rewrites first 10 seconds using proven frameworks
- Loop Specialist adds open loops and re-hooks at 25/50/75% marks
- Community engagement bot posts pinned comment + replies to 30 commenters
- Videos upload as PRIVATE by default — review before publishing
- (Phase 4) Stripped duplicate text overlays — captions are the only text
- (Phase 4) Beat-level footage — every 5-8s a new clip, not one per section
- (Phase 4) Custom illustrations via Manim (or PIL fallback) for diagrams
- (Phase 4) Whisper-verified word timestamps catch any TTS drift &gt;200ms
- (Phase 4) QC Director blocks upload on any objective quality failure
