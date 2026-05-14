#!/usr/bin/env python3
"""
McNeillium_AI — Agent 46: Pipeline Orchestrator

Runs the full video pipeline as a state-machine with per-stage
checkpoints. If a stage fails or the process is killed, re-running
the orchestrator picks up at the next un-finished stage — so a 30-min
beat fetch isn't lost when a 2-min Whisper download stalls.

State is persisted to logs/pipeline_state_<run_id>.json:
  {
    "run_id": "20260514_004500_<slug>",
    "topic": "...",
    "completed_stages": ["script", "voice", "audio_quality", ...],
    "current_stage": "video",
    "artifacts": { "script_path": "...", "audio_path": "...", ... }
  }

The stage list is the canonical Phase 1-7 flow plus the new agents.
Each stage is a thin shell-out — no Claude API calls — because Claude
Code itself orchestrates the agentic stages (research, scripting,
review, etc.) before invoking this orchestrator for the build stages.
"""

import argparse
import datetime
import io
import json
import re
import subprocess
import sys
import time
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower().replace("-", "") != "utf8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8",
                                  errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = PROJECT_ROOT / "logs"
PY = sys.executable


STAGES = [
    # (stage_name, command_template) — runs as subprocess
    ("voice",            [PY, "voice/generate_voice.py"]),
    ("audio_quality",    [PY, "utils/audio_quality.py",
                          "output/audio/latest.mp3", "--replace", "--pro"]),
    ("sync_validation",  [PY, "utils/sync_validator.py"]),
    ("illustration",     [PY, "utils/illustration_engineer.py"]),
    ("footage_review",   [PY, "utils/footage_relevance.py"]),
    ("ai_images",        [PY, "utils/ai_image_generator.py"]),
    ("music",            [PY, "voice/music_composer.py"]),
    ("sfx",              [PY, "utils/sound_designer.py"]),
    ("video",            [PY, "video/generate_video.py"]),
    ("qc",               [PY, "utils/qc_director.py"]),
    ("shorts",           [PY, "utils/shorts_producer.py", "--n", "5"]),
    ("blog",             [PY, "utils/blog_writer.py"]),
    ("twitter",          [PY, "utils/twitter_thread.py"]),
]


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:40]


def _state_path(run_id):
    return LOG_DIR / f"pipeline_state_{run_id}.json"


def load_state(run_id):
    p = _state_path(run_id)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def save_state(state):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    p = _state_path(state["run_id"])
    p.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _log(state, msg):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"pipeline_{datetime.date.today().isoformat()}.log"
    stamp = datetime.datetime.now().isoformat(timespec="seconds")
    line = f"[{stamp}] [{state['run_id']}] {msg}"
    print(line)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def run(topic, resume=None, allow_skip=True, skip_stages=None):
    skip_stages = set(skip_stages or [])

    if resume:
        state = load_state(resume)
        if not state:
            print(f"❌ No state for run_id {resume}")
            return False
        _log(state, f"resuming run, completed={state.get('completed_stages')}")
    else:
        run_id = f"{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{_slug(topic or 'run')}"
        state = {
            "run_id": run_id,
            "topic": topic,
            "started_at": datetime.datetime.now().isoformat(),
            "completed_stages": [],
            "artifacts": {},
        }
        save_state(state)
        _log(state, f"started: topic = {topic!r}")

    for name, cmd in STAGES:
        if name in state["completed_stages"]:
            _log(state, f"⏭  {name} already complete")
            continue
        if name in skip_stages:
            _log(state, f"⏭  {name} skipped by flag")
            state["completed_stages"].append(name)
            save_state(state)
            continue
        state["current_stage"] = name
        save_state(state)
        _log(state, f"▶  stage `{name}` starting…")
        t0 = time.time()
        r = subprocess.run(cmd, cwd=PROJECT_ROOT)
        dur = time.time() - t0
        if r.returncode == 0:
            _log(state, f"✅ stage `{name}` ok ({dur:.1f}s)")
            state["completed_stages"].append(name)
            save_state(state)
        else:
            _log(state, f"❌ stage `{name}` exit {r.returncode}")
            if allow_skip:
                _log(state, f"⏭  continuing past failure (--no-skip to halt)")
                state["completed_stages"].append(name)
                save_state(state)
            else:
                _log(state, f"⛔ halting; resume with --resume {state['run_id']}")
                return False

    _log(state, "🎉 pipeline complete")
    state["finished_at"] = datetime.datetime.now().isoformat()
    save_state(state)
    return True


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--topic", default="resume",
                   help="Topic label for new runs")
    p.add_argument("--resume", default=None,
                   help="Run ID to resume from a previous failed run")
    p.add_argument("--no-skip", action="store_true",
                   help="Halt on first stage failure (default: skip + continue)")
    p.add_argument("--skip", nargs="*", default=[],
                   help="Stage names to skip outright")
    args = p.parse_args()
    ok = run(args.topic, resume=args.resume,
             allow_skip=not args.no_skip, skip_stages=args.skip)
    sys.exit(0 if ok else 2)


if __name__ == "__main__":
    main()
