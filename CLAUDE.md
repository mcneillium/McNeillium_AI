# CLAUDE.md — McNeillium_AI Project Guide

## What This Project Does
Autonomous YouTube content pipeline for the McNeillium_AI channel.
Generates AI/tech educational videos: script → voice → video → YouTube upload → git push.

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
python utils/youtube_upload.py --video output/videos/latest.mp4 --script output/scripts/latest.json --privacy private
python utils/git_push.py --message "Your commit message"
```

### YouTube upload options:
```bash
python utils/youtube_upload.py --privacy private   # Upload as private (default, for review)
python utils/youtube_upload.py --privacy unlisted   # Upload as unlisted (shareable link)
python utils/youtube_upload.py --privacy public     # Upload as public (live on channel)
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
- `utils/youtube_upload.py` — YouTube upload via Data API v3 (OAuth, resumable)
- `utils/git_push.py` — Auto git commit and push
- `config.yaml` — All settings (voice, video style, colours, channel branding)
- `output/` — All generated content goes here (scripts/, audio/, videos/)
- `client_secrets.json` — Google OAuth credentials (gitignored, see setup below)
- `.youtube_token.json` — Saved OAuth token (gitignored, auto-created on first upload)

## Environment Setup
- Requires: Python 3.10+, FFmpeg
- API key in `.env`: `ANTHROPIC_API_KEY=sk-ant-...` (optional if writing scripts manually)
- GitHub URL in `.env`: `GITHUB_REPO_URL=https://github.com/...`
- Install deps: `pip install -r requirements.txt`

### YouTube Upload Setup (one-time)
1. Go to https://console.cloud.google.com/
2. Create project "McNeillium_AI"
3. Enable "YouTube Data API v3" (APIs & Services → Library)
4. Create OAuth Client ID (APIs & Services → Credentials → Desktop App)
5. Download JSON → save as `client_secrets.json` in project root
6. First upload opens a browser for OAuth consent — token is saved for future use

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
