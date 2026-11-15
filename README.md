# McNeillium_AI: a checked video pipeline

A Python pipeline (about 24,000 lines, 43 defined roles in `agents.yaml`) that
turns a topic into a narrated, captioned video: Claude writes the script,
ElevenLabs or Edge TTS narrates it, visuals are captured or assembled, FFmpeg
renders and syncs captions to the speech, and the result is packaged for a
private upload. Audio quality checks, speech-to-text comparison against the
script and a cost governor run along the way.

Its main use so far is an explainer series of my own work, filmed from
[paulmartinmcneill.com](https://paulmartinmcneill.com): every fact traced to
the site or a public repository, every clip transcribed and checked, uploads
private until reviewed. That work is on the branch `explainers/own-work-series`
(see `explainers/README.md` there).

Case study: [paulmartinmcneill.com/projects/mcneillium-ai-video-pipeline](https://paulmartinmcneill.com/projects/mcneillium-ai-video-pipeline/)

The sections below describe the first version (script, voice, video, push),
which still runs from `pipeline.py`.

## Architecture

```
Topic Idea
    │
    ▼
┌─────────────────┐
│  Script Writer   │  Claude API generates structured video scripts
│  (Claude Sonnet) │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Voice Generator │  Edge TTS converts script to natural narration
│  (Edge TTS)      │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Video Assembler │  FFmpeg + Pillow create screen-recording style video
│  (FFmpeg/Pillow) │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Git Auto-Push   │  Commits output and pushes to GitHub
│  (GitPython)     │
└─────────────────┘
```

## Quick Start

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure
```bash
cp .env.example .env
# Edit .env with your Anthropic API key and GitHub details
```

### 3. Run the Pipeline
```bash
# Generate a full video on any AI topic
python pipeline.py --topic "What are AI Agents and why they matter in 2026"

# Or run individual stages
python scripts/generate_script.py --topic "Your topic here"
python voice/generate_voice.py --script output/scripts/latest.json
python video/generate_video.py --script output/scripts/latest.json --audio output/audio/latest.mp3
```

### 4. Claude Code Usage
From Claude Code terminal, just tell it:
```
"Generate a video about transformer architecture"
```
Claude Code will run the full pipeline autonomously.

## Project Structure

```
McNeillium_AI/
├── pipeline.py              # Main orchestrator — runs all stages
├── config.yaml              # Channel settings, styles, voices
├── scripts/
│   └── generate_script.py   # Claude API script generation
├── voice/
│   └── generate_voice.py    # Edge TTS narration
├── video/
│   └── generate_video.py    # Screen-recording style video assembly
├── utils/
│   └── git_push.py          # Auto commit & push to GitHub
├── output/
│   ├── scripts/             # Generated JSON scripts
│   ├── audio/               # Generated MP3 narration
│   └── videos/              # Final MP4 videos
└── assets/
    ├── fonts/               # Custom fonts (optional)
    └── backgrounds/         # Background images (optional)
```

## Configuration

Edit `config.yaml` to customise:
- **Voice**: Choose from 100+ Edge TTS voices
- **Style**: Colours, fonts, typing speed
- **Channel**: Intro/outro text, branding
- **Video**: Resolution, FPS, duration limits

## Voices

Run `edge-tts --list-voices` to see all available voices.
Recommended for tech content:
- `en-GB-RyanNeural` (British male — great for tech)
- `en-US-GuyNeural` (American male)
- `en-US-JennyNeural` (American female)

## License
MIT
