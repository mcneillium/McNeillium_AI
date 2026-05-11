# CLAUDE.md — McNeillium_AI Project Guide

## What This Project Does
Autonomous YouTube content pipeline for the McNeillium_AI channel.
Generates AI/tech educational videos: script → voice → video → git push.

## Quick Commands

### Generate a full video (all 4 stages):
```bash
python pipeline.py --topic "Your topic here"
```

### Run individual stages:
```bash
python scripts/generate_script.py --topic "Your topic"
python voice/generate_voice.py --script output/scripts/latest.json
python video/generate_video.py --script output/scripts/latest.json --audio output/audio/latest.mp3
python utils/git_push.py --message "Your commit message"
```

### Skip stages:
```bash
python pipeline.py --topic "Topic" --skip-git
python pipeline.py --topic "Topic" --skip-video
```

## Project Structure
- `pipeline.py` — Main orchestrator
- `scripts/generate_script.py` — Claude API script generation (outputs JSON)
- `voice/generate_voice.py` — Edge TTS narration (outputs MP3)
- `video/generate_video.py` — Screen-recording style video (outputs MP4)
- `utils/git_push.py` — Auto git commit and push
- `config.yaml` — All settings (voice, video style, colours, channel branding)
- `output/` — All generated content goes here (scripts/, audio/, videos/)

## Environment Setup
- Requires: Python 3.10+, FFmpeg
- API key in `.env`: `ANTHROPIC_API_KEY=sk-ant-...`
- GitHub URL in `.env`: `GITHUB_REPO_URL=https://github.com/...`
- Install deps: `pip install -r requirements.txt`

## Key Design Decisions
- Scripts are structured JSON (title, sections with narration + screen_text)
- Video style: dark terminal/screen-recording aesthetic with typing animation
- Edge TTS voice: en-GB-RyanNeural (configurable in config.yaml)
- FFmpeg assembles frames + audio into final MP4
- Each stage saves a `latest.*` file so stages can chain without args

## Common Tasks for Claude Code
- "Generate a video about [topic]" → run pipeline.py
- "Change the voice" → edit voice.voice_id in config.yaml
- "Make videos longer/shorter" → edit script.target_duration_minutes in config.yaml
- "Change colours" → edit video section in config.yaml
- "List available voices" → run `edge-tts --list-voices`
- "Add a new section type" → edit SYSTEM_PROMPT in scripts/generate_script.py
