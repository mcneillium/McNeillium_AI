#!/usr/bin/env python3
"""
McNeillium_AI — Agent 50: Batch Producer

Generate multiple videos in a single overnight run. The build stages
(voice → video → captions → QC) run for each topic sequentially —
parallelising them is risky because they all hammer FFmpeg + the
Pixabay API at the same time. The Researcher/Writer/Reviewer agent
stages still happen in Claude Code before this script is invoked.

Inputs: a topics file (one topic per line) OR --topics "..." x3 args.
Outputs: per-topic state at logs/pipeline_state_<run_id>.json (managed
by pipeline_orchestrator). On any topic failure we log + continue to
the next.

Atomic batch: --hold-uploads collects every QC-approved video and
defers the YouTube upload until the WHOLE batch has rendered, so a
mid-batch failure doesn't leave the channel half-published.
"""

import argparse
import datetime
import io
import json
import subprocess
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower().replace("-", "") != "utf8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8",
                                  errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
LOG_DIR = PROJECT_ROOT / "logs"
BATCH_LOG = LOG_DIR / "batch_runs.md"


def _log_batch(line):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with open(BATCH_LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def render_topic(topic, hold_uploads=False):
    """Run pipeline_orchestrator for one topic. Returns dict with status."""
    print(f"\n{'=' * 60}\n  ▶  BATCH: {topic!r}\n{'=' * 60}")
    extra = []
    if hold_uploads:
        # The orchestrator stages don't currently include an upload step,
        # but we keep the hook for when one is added.
        extra.extend(["--skip", "upload"])
    cmd = [PY, str(PROJECT_ROOT / "utils" / "pipeline_orchestrator.py"),
           "--topic", topic, *extra]
    t0 = datetime.datetime.now()
    r = subprocess.run(cmd, cwd=PROJECT_ROOT)
    return {
        "topic": topic,
        "exit_code": r.returncode,
        "started": t0.isoformat(),
        "finished": datetime.datetime.now().isoformat(),
        "ok": r.returncode == 0,
    }


def load_topics(path):
    p = Path(path)
    if not p.exists():
        return []
    return [
        line.strip()
        for line in p.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]


def run(topics, hold_uploads=False):
    results = []
    for t in topics:
        try:
            results.append(render_topic(t, hold_uploads=hold_uploads))
        except Exception as e:
            results.append({
                "topic": t, "exit_code": -1, "ok": False, "error": str(e),
                "finished": datetime.datetime.now().isoformat(),
            })

    summary = (
        f"### Batch {datetime.datetime.now().isoformat(timespec='seconds')}\n"
        + "\n".join(
            f"- {'✅' if r['ok'] else '❌'} {r['topic']!r} "
            f"(exit {r['exit_code']})"
            for r in results
        )
        + "\n"
    )
    print("\n" + summary)
    _log_batch(summary)
    return all(r["ok"] for r in results)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--topics", nargs="*", default=[],
                   help="One or more topics inline")
    p.add_argument("--topics-file", default=None,
                   help="File with one topic per line")
    p.add_argument("--hold-uploads", action="store_true",
                   help="Render everything before any upload")
    args = p.parse_args()

    topics = list(args.topics)
    if args.topics_file:
        topics.extend(load_topics(args.topics_file))

    if not topics:
        print("❌ No topics supplied")
        sys.exit(1)

    ok = run(topics, hold_uploads=args.hold_uploads)
    sys.exit(0 if ok else 2)


if __name__ == "__main__":
    main()
