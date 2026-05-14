#!/usr/bin/env python3
"""
McNeillium_AI — Agent 56: Concept Evolution Designer (Phase 10)

For explainer-mode sections that describe how something works step by
step, this agent emits ONE evolving illustration clip that runs for the
full section. Boxes and arrows appear in sync with the narration's
phrase boundaries — the camera never cuts, the diagram just keeps
growing.

This is the 3Blue1Brown signature move. Held shot, voice carries the
story, visuals evolve underneath.

Output:
  - One MP4 per eligible section in output/illustrations/evolution_<sid>.mp4
  - A patch to the shot list — that section's beats are replaced by a
    single "illustration" beat covering the whole section duration.

Eligibility:
  - Section narration contains at least 3 step-cue phrases ("first",
    "then", "next", "finally", "step 1/2/3", "after that").
  - Mode config is "explainer".
  - Section duration >= 25 seconds.
"""

import argparse
import io
import json
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower().replace("-", "") != "utf8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8",
                                  errors="replace")

from PIL import Image, ImageDraw, ImageFont

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = PROJECT_ROOT / "output" / "scripts" / "latest.json"
SHOT_LIST_PATH = PROJECT_ROOT / "output" / "shot_list.json"
PALETTE_PATH = PROJECT_ROOT / "output" / "color_palette.json"
MODE_CONFIG_PATH = PROJECT_ROOT / "output" / "mode_config.json"
OUT_DIR = PROJECT_ROOT / "output" / "illustrations"

W, H = 1920, 1080
FPS = 30


STEP_CUES = re.compile(
    r"\b(step\s+(?:one|two|three|four|five|1|2|3|4|5)|"
    r"first(?:ly|,)?|second(?:ly|,)?|third(?:ly|,)?|"
    r"then,?|next,?|after that|finally|"
    r"so how does .* work)\b",
    re.I,
)


def _find_ffmpeg():
    r = shutil.which("ffmpeg")
    if r:
        return r
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return "ffmpeg"


FFMPEG = _find_ffmpeg()


def _font(size, bold=False):
    candidates = []
    if bold:
        candidates.append("C:/Windows/Fonts/arialbd.ttf")
    candidates.extend([
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ])
    for fp in candidates:
        if Path(fp).exists():
            return ImageFont.truetype(fp, size)
    return ImageFont.load_default()


def _ease_out(t):
    return 1 - (1 - t) ** 3


def _hex_to_rgb(s):
    s = s.lstrip("#")
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))


# ═══════════════════════════════════════════════════════════════
# Step extraction
# ═══════════════════════════════════════════════════════════════

def extract_steps(narration, max_steps=6):
    """Pull labelled step phrases out of a section's narration."""
    # Split sentences and tag the ones that introduce a step
    sentences = re.split(r"(?<=[.!?])\s+", narration.strip())
    steps = []
    for s in sentences:
        m = STEP_CUES.search(s)
        if not m:
            continue
        # Use the first 3-4 content words after the cue as the label
        rest = s[m.end():].strip(" ,.")
        words = re.findall(r"[A-Za-z'-]+", rest)
        content = [w for w in words if w.lower() not in {
            "the", "a", "an", "you", "we", "i", "to", "of", "is", "are",
            "this", "that", "it", "for", "with", "and", "or", "but",
            "in", "on",
        }][:4]
        label = " ".join(w for w in content).title() or "Step"
        if label not in steps:
            steps.append(label[:20])
        if len(steps) >= max_steps:
            break
    return steps


# ═══════════════════════════════════════════════════════════════
# Evolving-flowchart renderer
# ═══════════════════════════════════════════════════════════════

def _gradient_bg(draw):
    for y in range(0, H, 2):
        shade = int(8 + 14 * (y / H))
        draw.rectangle([0, y, W, y + 2],
                       fill=(8, 12, 22 + shade // 4))


def render_evolving_flowchart(steps, total_duration, output_path,
                               palette_terms=None, title=""):
    """Render ONE held shot where each step box fades in at its cue.

    Step i becomes visible at fraction i / len(steps) of total_duration,
    with a 0.6s ease-in animation.
    """
    steps = steps or ["Concept"]
    n = len(steps)
    fps = FPS
    total_frames = int(total_duration * fps)
    frames_dir = output_path.parent / f"{output_path.stem}_frames"
    if frames_dir.exists():
        shutil.rmtree(frames_dir)
    frames_dir.mkdir(parents=True)

    # Step colours pulled from palette in slot order
    palette_terms = palette_terms or {}
    palette_order = ["#5BA3F5", "#7EE787", "#FFA657", "#BC8CFF",
                     "#FFDC6E", "#FF7B72"]
    step_colours = [palette_terms.get(s.lower(), palette_order[i % len(palette_order)])
                    for i, s in enumerate(steps)]
    step_rgbs = [_hex_to_rgb(c) for c in step_colours]

    box_w, box_h = 280, 130
    gap = 90
    total_w = n * box_w + (n - 1) * gap
    if total_w > W - 160:
        scale = (W - 160) / total_w
        box_w = int(box_w * scale)
        gap = int(gap * scale)
        total_w = n * box_w + (n - 1) * gap
    start_x = (W - total_w) // 2
    cy = H // 2 + 30

    appear_frames = [int(total_frames * i / max(1, n)) for i in range(n)]
    transition_frames = int(0.6 * fps)

    f_title = _font(56, bold=True)
    f_label = _font(34, bold=True)
    f_step = _font(22)

    for f_idx in range(total_frames):
        img = Image.new("RGB", (W, H), (8, 12, 22))
        d = ImageDraw.Draw(img)
        _gradient_bg(d)

        # Section title
        if title:
            d.text((W // 2 + 2, 142), title, font=f_title,
                   fill=(0, 0, 0), anchor="mm")
            d.text((W // 2, 140), title, font=f_title,
                   fill=(230, 237, 243), anchor="mm")
            d.rectangle([W // 2 - 130, 180, W // 2 + 130, 183],
                        fill=(91, 163, 245))

        # Each step
        for i in range(n):
            x0 = start_x + i * (box_w + gap)
            y0 = cy - box_h // 2
            x1 = x0 + box_w
            y1 = y0 + box_h
            appear = appear_frames[i]
            if f_idx < appear:
                continue
            local = min(1.0, (f_idx - appear) / max(1, transition_frames))
            eased = _ease_out(local)
            offset = int(25 * (1 - eased))
            colour = step_rgbs[i]
            fill = (colour[0] // 6, colour[1] // 6, colour[2] // 6)
            d.rounded_rectangle(
                [x0, y0 - offset, x1, y1 - offset],
                radius=16, outline=colour, width=4, fill=fill,
            )
            d.text(((x0 + x1) // 2, (y0 + y1) // 2 - offset),
                   steps[i], font=f_label,
                   fill=(230, 237, 243), anchor="mm")
            d.text(((x0 + x1) // 2, y1 + 18 - offset),
                   f"step {i + 1}", font=f_step,
                   fill=(140, 150, 165), anchor="mm")

            # Arrow from previous box (drawn after the box appears)
            if i > 0:
                prev_x1 = start_x + (i - 1) * (box_w + gap) + box_w
                arrow_appear = appear_frames[i] - int(0.2 * fps)
                if f_idx >= arrow_appear:
                    d.line(
                        [(prev_x1 + 12, cy), (x0 - 14, cy)],
                        fill=(230, 237, 243), width=4,
                    )
                    head = [
                        (x0 - 2, cy),
                        (x0 - 16, cy - 9),
                        (x0 - 16, cy + 9),
                    ]
                    d.polygon(head, fill=(230, 237, 243))

        img.save(str(frames_dir / f"frame_{f_idx:06d}.png"), "PNG")

    cmd = [
        FFMPEG, "-y", "-framerate", str(fps),
        "-i", str(frames_dir / "frame_%06d.png"),
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "20",
        "-pix_fmt", "yuv420p",
        str(output_path),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    shutil.rmtree(frames_dir, ignore_errors=True)
    return r.returncode == 0


# ═══════════════════════════════════════════════════════════════
# Shot list rewriting
# ═══════════════════════════════════════════════════════════════

def section_duration_estimate(narration, full_durations_by_id):
    """If we know section durations from elsewhere, use that.
    Otherwise estimate from narration length (Edge TTS ~5 chars/word, 2.5 wps).
    """
    if narration is None:
        return 30.0
    if full_durations_by_id:
        return None  # caller supplies
    words = len(re.findall(r"\w+", narration))
    return max(20.0, words / 2.5)


def replace_section_with_evolution(shot_list, section_id, illustration_path,
                                    duration):
    """Replace all shots in a section with a single illustration beat."""
    for section in shot_list.get("sections", []):
        if section.get("section_id") != section_id:
            continue
        section["shots"] = [{
            "type": "illustration",
            "path": str(illustration_path),
            "duration": duration,
            "motion": "static",
            "trigger": "concept_evolution",
            "label": "evolving_flowchart",
        }]
        return True
    return False


def run(script_path, shot_list_path, mode_config_path, palette_path,
        min_steps=3, min_section_seconds=25):
    if not Path(script_path).exists():
        print(f"❌ Script missing: {script_path}")
        return False
    with open(script_path, encoding="utf-8") as f:
        script = json.load(f)

    mode = "fireship"
    if Path(mode_config_path).exists():
        try:
            mode = json.loads(Path(mode_config_path).read_text(encoding="utf-8")).get("mode", "fireship")
        except Exception:
            pass
    if mode != "explainer":
        print(f"⏭  Mode is {mode!r} — Concept Evolution skipped.")
        return True

    palette_terms = {}
    if Path(palette_path).exists():
        try:
            pdata = json.loads(Path(palette_path).read_text(encoding="utf-8"))
            palette_terms = pdata.get("term_colours", {})
            palette_terms = {k.lower(): v for k, v in palette_terms.items()}
        except Exception:
            pass

    shot_list = None
    if Path(shot_list_path).exists():
        shot_list = json.loads(Path(shot_list_path).read_text(encoding="utf-8"))

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Estimate section durations from char counts (mirror generate_video's split)
    sections = script.get("sections", [])
    chars = [len(s.get("narration", "")) for s in sections]
    total = sum(chars) or 1
    # Assume audio_dur ≈ words / 2.5 wps
    words = sum(len(re.findall(r"\w+", s.get("narration", ""))) for s in sections)
    est_audio = words / 2.5
    intro_outro = 7.0
    content = max(1.0, est_audio - intro_outro)
    durations = [(c / total) * content for c in chars]

    eligible = 0
    rendered = 0
    for sec, dur in zip(sections, durations):
        sid = sec.get("id")
        if dur < min_section_seconds:
            continue
        steps = extract_steps(sec.get("narration", ""))
        if len(steps) < min_steps:
            continue
        eligible += 1

        out_path = OUT_DIR / f"evolution_{sid}.mp4"
        title = sec.get("title") or sid
        print(f"  🪄 evolution: {sid} ({dur:.1f}s, {len(steps)} steps)")
        for s in steps:
            print(f"       • {s}")
        ok = render_evolving_flowchart(steps, dur, out_path,
                                       palette_terms=palette_terms,
                                       title=title)
        if ok:
            rendered += 1
            if shot_list:
                replace_section_with_evolution(shot_list, sid, out_path, dur)

    if shot_list and rendered:
        with open(shot_list_path, "w", encoding="utf-8") as f:
            json.dump(shot_list, f, indent=2)
    print(f"🌀 Concept Evolution — eligible {eligible}, rendered {rendered}")
    return True


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--script", default=str(SCRIPT_PATH))
    p.add_argument("--shot-list", default=str(SHOT_LIST_PATH))
    p.add_argument("--mode-config", default=str(MODE_CONFIG_PATH))
    p.add_argument("--palette", default=str(PALETTE_PATH))
    p.add_argument("--min-steps", type=int, default=3)
    p.add_argument("--min-seconds", type=int, default=25)
    args = p.parse_args()
    ok = run(args.script, args.shot_list, args.mode_config, args.palette,
             min_steps=args.min_steps, min_section_seconds=args.min_seconds)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
