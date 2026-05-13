# CLAUDE.md — McNeillium_AI Multi-Agent System

## What This Project Does
Autonomous YouTube content pipeline for the McNeillium_AI channel.
10 AI agents collaborate to produce professional AI/tech educational videos.

## The Agents (YOU play each role sequentially)

### When asked to produce a video, follow these 10 stages:

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
Read the reviewed script. Design a shot list with 3-5 shots per section:
footage clips, stat cards, comparison splits. Specify motion types (Ken Burns
variants, pans) and layouts (A/B/C/D). Save to output/shot_list.json.

**AGENT 3C — Engagement Writer**
Add strategic hooks, open loops, pattern interrupts, and CTAs at 60-90 second
intervals. Strengthen the hook and outro CTA. Update the script JSON.

**AGENT 4 — SEO Optimizer**
Read knowledge_base/seo/description_template.md. Generate 5 title options,
pick the best. Write a YouTube description with timestamps. Generate 15-20 tags.
Write thumbnail text (max 4 words). Update output/scripts/latest.json metadata.

**AGENT 5 — Voice Producer**
Run: python voice/generate_voice.py --script output/scripts/latest.json
This generates audio + word-level caption timestamps for animated captions.

**AGENT 6A — Video Producer**
Run: python video/generate_video.py --script output/scripts/latest.json --audio output/audio/latest.mp3
Run: python utils/generate_thumbnail.py --title "[THUMBNAIL TEXT]" --query "[relevant image query]"

**AGENT 6B — Post-Production Director**
Check audio loudness of the final video. If not -14 LUFS, re-normalize.
Verify 1080p/30fps output, reasonable file size, duration match.

**AGENT 7 — Publisher**
Run: python utils/youtube_upload.py --video output/videos/latest.mp4 --script output/scripts/latest.json --privacy private
Archive the script to knowledge_base/scripts/
Update knowledge_base/topic_tracker.md
Git commit and push.

## Quick Commands

### Full pipeline (all 10 agents):
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
- agents.yaml — Agent role definitions and processes (10 agents)
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
- Videos upload as PRIVATE by default — review before publishing
