#!/usr/bin/env python3
"""
McNeillium_AI — Agent 55: Animated Equation Renderer (Phase 10)

Detects equation-like fragments in the script narration and produces a
held-shot MP4 that types the equation in piece by piece. Each piece
fades in at the time its term is mentioned in the audio.

Detection is regex-based — looks for tokens that read like an equation:
softmax(QK^T/√d)V, output = f(x), attention = ..., probabilities = ...

The render is PIL-based (no LaTeX required). Manim Tex would look nicer
but needs MiKTeX on Windows; this renderer uses Unicode math symbols
which are clear enough for tech YouTube.

Output:
  - One MP4 per detected equation at output/illustrations/equation_NN.mp4
  - Plan file at knowledge_base/illustrations/equation_plan.json
  - When a shot list exists AND the section narration matches, an
    "illustration" beat is injected at the start of that section.
"""

import argparse
import io
import json
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
OUT_DIR = PROJECT_ROOT / "output" / "illustrations"
PLAN_PATH = PROJECT_ROOT / "knowledge_base" / "illustrations" / "equation_plan.json"

W, H = 1920, 1080
FPS = 30


# ─── Equation patterns ────────────────────────────────────────────
# We're not parsing math — just detecting that a chunk of text reads
# like a formula worth rendering.
INLINE_EQ_PATTERN = re.compile(
    r"\b(softmax|sigmoid|relu|attention|loss|gradient|probabilities?|"
    r"output|logits|weights?)\s*"
    r"(?:=|equals|is)\s*"
    r"([^\.\n,]{6,80})",
    re.I,
)
KEYWORD_EQ_PATTERN = re.compile(
    r"\b(softmax\s*\(?Q\s*K\^?T?\s*[/÷]?\s*[√]?\s*d_?k?\s*\)?\s*V?|"
    r"Q\s*K\^?T?|"
    r"y\s*=\s*Wx\s*\+\s*b)",
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


def _font(size, bold=False, mono=False):
    candidates = []
    if mono:
        candidates += [
            "C:/Windows/Fonts/consola.ttf",
            "C:/Windows/Fonts/cour.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        ]
    if bold:
        candidates.append("C:/Windows/Fonts/arialbd.ttf")
    candidates += [
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for fp in candidates:
        if Path(fp).exists():
            return ImageFont.truetype(fp, size)
    return ImageFont.load_default()


def _ease_out(t):
    return 1 - (1 - t) ** 3


# ─── Equation decomposition ──────────────────────────────────────
# Hand-picked iconic equations get pre-decomposed token lists.
ICONIC_EQUATIONS = {
    "attention": {
        "title": "Scaled Dot-Product Attention",
        "tokens": [
            ("Attention(Q, K, V) = ", "#7EE787"),
            ("softmax", "#5BA3F5"),
            ("(", "#E6EDF3"),
            ("QK", "#FFA657"),
            ("ᵀ", "#FFA657"),
            (" / ", "#E6EDF3"),
            ("√d", "#BC8CFF"),
            ("ₖ", "#BC8CFF"),
            (")", "#E6EDF3"),
            (" V", "#FFDC6E"),
        ],
        "term_keys": ["q", "k", "v", "softmax", "scaled", "dimension"],
    },
    "y_eq_wxb": {
        "title": "Linear Transform",
        "tokens": [
            ("y = ", "#E6EDF3"),
            ("W", "#5BA3F5"),
            ("x", "#7EE787"),
            (" + ", "#E6EDF3"),
            ("b", "#FFA657"),
        ],
        "term_keys": ["w", "x", "b", "weight", "bias"],
    },
}


def _hex_to_rgb(s):
    s = s.lstrip("#")
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))


def render_equation_clip(equation_key, total_duration, output_path,
                          subtitle=""):
    """Render a held-shot equation that types in piece by piece."""
    spec = ICONIC_EQUATIONS.get(equation_key)
    if not spec:
        return False

    tokens = spec["tokens"]
    n = len(tokens)
    total_frames = int(total_duration * FPS)
    frames_dir = output_path.parent / f"{output_path.stem}_frames"
    if frames_dir.exists():
        shutil.rmtree(frames_dir)
    frames_dir.mkdir(parents=True)

    title_font = _font(58, bold=True)
    eq_font = _font(140, bold=False, mono=False)
    sub_font = _font(28)

    # Time slices: each token appears at fraction i / (n+1)
    appear_frames = [
        int(total_frames * (i + 1) / (n + 2)) for i in range(n)
    ]
    fade_frames = int(0.4 * FPS)

    # Pre-measure token widths so we can centre the line
    dummy = Image.new("RGB", (10, 10))
    dd = ImageDraw.Draw(dummy)
    token_widths = []
    for text, _ in tokens:
        bbox = dd.textbbox((0, 0), text, font=eq_font)
        token_widths.append(bbox[2] - bbox[0])
    total_w = sum(token_widths)
    start_x = (W - total_w) // 2
    cy = H // 2 + 20

    for f_idx in range(total_frames):
        img = Image.new("RGB", (W, H), (10, 14, 24))
        d = ImageDraw.Draw(img)
        # Gradient
        for y in range(0, H, 4):
            shade = int(2 + 12 * (y / H))
            d.rectangle([0, y, W, y + 4],
                        fill=(10 + shade // 2, 14 + shade // 2, 24 + shade))

        # Title
        d.text((W // 2, 180), spec["title"], font=title_font,
               fill=(230, 237, 243), anchor="mm")
        d.rectangle([W // 2 - 220, 230, W // 2 + 220, 233],
                    fill=(91, 163, 245))

        # Equation tokens
        x = start_x
        for i, (text, colour) in enumerate(tokens):
            tw = token_widths[i]
            appear = appear_frames[i]
            if f_idx < appear:
                x += tw
                continue
            local = min(1.0, (f_idx - appear) / max(1, fade_frames))
            alpha = _ease_out(local)
            # The colour we draw shifts from low brightness to full
            rgb = _hex_to_rgb(colour)
            faded = tuple(int(c * (0.3 + 0.7 * alpha)) for c in rgb)
            # Shadow
            d.text((x + 4, cy + 4), text, font=eq_font,
                   fill=(0, 0, 0), anchor="lm")
            d.text((x, cy), text, font=eq_font, fill=faded, anchor="lm")
            x += tw

        if subtitle:
            d.text((W // 2, H - 140), subtitle, font=sub_font,
                   fill=(140, 150, 165), anchor="mm")

        img.save(str(frames_dir / f"frame_{f_idx:06d}.png"), "PNG")

    cmd = [
        FFMPEG, "-y", "-framerate", str(FPS),
        "-i", str(frames_dir / "frame_%06d.png"),
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "20",
        "-pix_fmt", "yuv420p",
        str(output_path),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    shutil.rmtree(frames_dir, ignore_errors=True)
    return r.returncode == 0


# ─── Detection ──────────────────────────────────────────────────

def detect_equations(script):
    """Return a list of {section_id, equation_key, hint}."""
    found = []
    for sec in script.get("sections", []):
        sid = sec.get("id", "")
        narration = sec.get("narration", "")
        # iconic equations by keyword density
        lower = narration.lower()
        if (("softmax" in lower or "attention" in lower)
            and ("q" in lower.split() or " k " in lower or "key" in lower)):
            found.append({
                "section_id": sid,
                "equation_key": "attention",
                "hint": "Attention(Q, K, V)",
            })
        elif "wx + b" in lower or " w x " in lower:
            found.append({
                "section_id": sid,
                "equation_key": "y_eq_wxb",
                "hint": "y = Wx + b",
            })
    # Dedupe by (section_id, equation_key)
    seen = set()
    unique = []
    for f in found:
        key = (f["section_id"], f["equation_key"])
        if key not in seen:
            seen.add(key)
            unique.append(f)
    return unique


def inject_equation_beat(shot_list, section_id, equation_path, duration=6.0):
    for section in shot_list.get("sections", []):
        if section.get("section_id") != section_id:
            continue
        # Insert near the start so the equation sets up the section
        beat = {
            "type": "illustration",
            "path": str(equation_path),
            "duration": duration,
            "motion": "static",
            "trigger": "equation",
            "label": "animated_equation",
        }
        section.setdefault("shots", []).insert(1, beat)
        return True
    return False


# ─── Main ──────────────────────────────────────────────────────

def run(script_path, shot_list_path, out_dir, plan_path):
    if not Path(script_path).exists():
        print(f"❌ Script not found: {script_path}")
        return False
    with open(script_path, encoding="utf-8") as f:
        script = json.load(f)

    Path(out_dir).mkdir(parents=True, exist_ok=True)

    plan = []
    counter = 0
    for entry in detect_equations(script):
        counter += 1
        sid = entry["section_id"]
        key = entry["equation_key"]
        out_path = Path(out_dir) / f"equation_{counter:02d}_{sid}.mp4"
        print(f"  📐 equation: {sid} ({key})")
        ok = render_equation_clip(key, total_duration=6.0,
                                  output_path=out_path,
                                  subtitle=entry["hint"])
        if ok:
            plan.append({**entry,
                         "path": str(out_path),
                         "duration": 6.0})
            if Path(shot_list_path).exists():
                shot_list = json.loads(Path(shot_list_path).read_text(encoding="utf-8"))
                if inject_equation_beat(shot_list, sid, out_path):
                    Path(shot_list_path).write_text(json.dumps(shot_list, indent=2),
                                                    encoding="utf-8")

    Path(plan_path).parent.mkdir(parents=True, exist_ok=True)
    Path(plan_path).write_text(json.dumps(plan, indent=2), encoding="utf-8")
    print(f"💾 Equation plan ({len(plan)} entries) → {plan_path}")
    return True


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--script", default=str(SCRIPT_PATH))
    p.add_argument("--shot-list", default=str(SHOT_LIST_PATH))
    p.add_argument("--out-dir", default=str(OUT_DIR))
    p.add_argument("--plan", default=str(PLAN_PATH))
    args = p.parse_args()
    ok = run(args.script, args.shot_list, args.out_dir, args.plan)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
