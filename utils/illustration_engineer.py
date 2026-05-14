#!/usr/bin/env python3
"""
McNeillium_AI — Agent 24: Illustration Engineer

Scans the script for moments that need a custom diagram (where stock footage
can't communicate the concept), generates Manim Python code for each, renders
to MP4, and injects illustration beats into the shot list.

Trigger phrases:
  - "how X works" / "the way X works"          → flowchart
  - "step 1", "step 2", ordered process        → flowchart
  - "X vs Y", "compared to"                    → comparison
  - "N%", "N times", numeric stat              → stat_grow
  - "architecture", "system of", "consists of" → architecture
  - dates / years in sequence                  → timeline

Manim rendering is OPTIONAL — if the manim package isn't importable, the
engineer still emits .py scene files and adds illustration beats marked
`pending`. A later pass (or a re-run after install) can render them.
"""

import argparse
import io
import json
import math
import os
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
ILL_DIR = PROJECT_ROOT / "output" / "illustrations"
KB_DIR = PROJECT_ROOT / "knowledge_base" / "illustrations"


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
        if os.path.exists(fp):
            return ImageFont.truetype(fp, size)
    return ImageFont.load_default()


BG_COLOR = (10, 14, 24)
ACCENT_BLUE = (88, 166, 255)
ACCENT_GREEN = (126, 231, 135)
ACCENT_ORANGE = (255, 166, 87)
ACCENT_PURPLE = (188, 140, 255)
ACCENT_YELLOW = (255, 220, 110)
TEXT_PRIMARY = (230, 237, 243)
TEXT_DIM = (140, 150, 165)
PALETTE = [ACCENT_BLUE, ACCENT_GREEN, ACCENT_ORANGE, ACCENT_PURPLE, ACCENT_YELLOW]


def _encode_frames(frames_dir, output_path, fps):
    """Encode PNG frame sequence to MP4 with FFmpeg."""
    cmd = [
        FFMPEG, "-y", "-framerate", str(fps),
        "-i", str(frames_dir / "frame_%06d.png"),
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "20",
        "-pix_fmt", "yuv420p",
        str(output_path),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        return False
    return True


def _ease_out(t):
    return 1 - (1 - t) ** 3


VENV_MANIM_PY = PROJECT_ROOT / "venv_manim" / "Scripts" / "python.exe"


def _manim_available():
    """Manim is available either via the current Python OR via venv_manim."""
    if VENV_MANIM_PY.exists():
        r = subprocess.run(
            [str(VENV_MANIM_PY), "-c", "import manim"],
            capture_output=True,
        )
        if r.returncode == 0:
            return True
    try:
        import manim  # noqa: F401
        return True
    except Exception:
        return False


def _manim_python():
    """Return the Python interpreter that has Manim installed."""
    if VENV_MANIM_PY.exists():
        r = subprocess.run(
            [str(VENV_MANIM_PY), "-c", "import manim"],
            capture_output=True,
        )
        if r.returncode == 0:
            return str(VENV_MANIM_PY)
    return sys.executable


# ═══════════════════════════════════════════════════════════════
# Trigger detection
# ═══════════════════════════════════════════════════════════════

FLOW_PATTERNS = [
    re.compile(r"\bhow\s+(?:it|this|that|\w+)\s+works?\b", re.I),
    re.compile(r"\bthe way\s+(?:it|this|\w+)\s+works?\b", re.I),
    re.compile(r"\bstep\s+(?:one|1|two|2|three|3|four|4)\b", re.I),
    re.compile(r"\bfirst,?\s+\w+.*\bthen,?\s+\w+.*\bfinally\b", re.I),
    re.compile(r"\bprocess\s+(?:of|is|works)\b", re.I),
    re.compile(r"\bpipeline\b", re.I),
    re.compile(r"\bworkflow\b", re.I),
]
COMPARE_PATTERNS = [
    re.compile(r"\b(\w+)\s+vs\.?\s+(\w+)\b", re.I),
    re.compile(r"\bcompared to\b", re.I),
    re.compile(r"\bunlike\s+(\w+)\b", re.I),
    re.compile(r"\bdifference between\b", re.I),
    re.compile(r"\binstead of\b", re.I),
    re.compile(r"\brather than\b", re.I),
]
STAT_PATTERN = re.compile(
    r"\b(\d+(?:\.\d+)?\s*(?:%|percent|x|times|million|billion|trillion|k|m|b))\b",
    re.I,
)
ARCH_PATTERNS = [
    re.compile(r"\barchitecture\b", re.I),
    re.compile(r"\bconsists of\b", re.I),
    re.compile(r"\bmade up of\b", re.I),
    re.compile(r"\b(?:three|four|five)\s+(?:components?|parts?|stages?|layers?)\b", re.I),
    re.compile(r"\bsystem of\b", re.I),
    re.compile(r"\bbuilt on top of\b", re.I),
]
TIMELINE_PATTERN = re.compile(r"\b(19|20)\d{2}\b")

# Phase 10 density boosters
DEFINITION_PATTERN = re.compile(
    r"\b(\w+)\s+(?:is|stands for|means|refers to)\s+([a-z].+?)(?:[.,;]|$)",
    re.I,
)
RELATIONSHIP_PATTERN = re.compile(
    r"\b(?:goes through|sends?\s+to|passes to|connects to|"
    r"talks to|hands off to|feeds into|returns to)\b",
    re.I,
)
TRANSFORMATION_PATTERN = re.compile(
    r"\b(?:becomes|turns into|transforms into|converts to|gets converted|"
    r"changes into|morphs into)\b",
    re.I,
)
ENTITY_PATTERN = re.compile(
    r"\b(OpenAI|Anthropic|Google|Meta|Microsoft|Apple|"
    r"Claude|GPT-?\d?|Gemini|Llama|"
    r"Pinecone|Weaviate|Qdrant|pgvector|"
    r"Harvey|Hebbia|Netflix|Tesla|"
    r"Stripe|Vercel|GitHub|Cursor)\b"
)


def detect_triggers(narration, aggressive=False):
    """Return a list of detected illustration triggers in order of priority.

    aggressive=True (Phase 10) returns multiple instances per pattern and
    catches definitions / relationships / transformations / entities.
    Used in explainer mode for higher illustration density.
    """
    triggers = []

    # Flowchart triggers — multiple in aggressive mode
    for p in FLOW_PATTERNS:
        for m in p.finditer(narration):
            triggers.append(("flowchart", m.group(0)))
            if not aggressive:
                break
        if not aggressive and triggers and triggers[-1][0] == "flowchart":
            break

    # Architecture triggers
    for p in ARCH_PATTERNS:
        for m in p.finditer(narration):
            triggers.append(("architecture", m.group(0)))
            if not aggressive:
                break
        if not aggressive and any(t[0] == "architecture" for t in triggers):
            break

    # Comparisons
    for p in COMPARE_PATTERNS:
        for m in p.finditer(narration):
            triggers.append(("comparison", m.group(0)))
            if not aggressive:
                break
        if not aggressive and any(t[0] == "comparison" for t in triggers):
            break

    # Stats — multiple in aggressive mode
    stat_matches = STAT_PATTERN.findall(narration)
    if stat_matches:
        if aggressive:
            for s in stat_matches[:4]:
                triggers.append(("stat_grow", s))
        else:
            triggers.append(("stat_grow", stat_matches[0]))

    years = TIMELINE_PATTERN.findall(narration)
    if len(set(years)) >= 3:
        triggers.append(("timeline", ", ".join(sorted(set(years))[:5])))

    if aggressive:
        # Definitions become Definition flowcharts ("term" → "meaning")
        for m in DEFINITION_PATTERN.finditer(narration):
            triggers.append(("comparison", f"{m.group(1)} vs {m.group(2)[:30]}"))

        # Relationships / transformations imply a flow
        for p in (RELATIONSHIP_PATTERN, TRANSFORMATION_PATTERN):
            for m in p.finditer(narration):
                triggers.append(("flowchart", m.group(0)))

        # Named entities → architecture-style card so the entity gets its
        # own visible moment on screen
        entities = list({m.group(0) for m in ENTITY_PATTERN.finditer(narration)})
        for ent in entities[:3]:
            triggers.append(("architecture", ent))

    return triggers


# ═══════════════════════════════════════════════════════════════
# Manim scene templates
# ═══════════════════════════════════════════════════════════════

def _safe_text(s, max_len=18):
    s = re.sub(r"[^A-Za-z0-9 ]", " ", str(s)).strip()
    return s[:max_len].title() if s else "Step"


def manim_flowchart(class_name, steps):
    """Generate Manim code for a horizontal flowchart with 3-5 labelled boxes."""
    steps = steps[:5] if steps else ["Input", "Process", "Output"]
    safe_steps = [_safe_text(s) for s in steps]
    n = len(safe_steps)
    spacing = 3.2 if n <= 3 else 2.6 if n == 4 else 2.2
    start_x = -(n - 1) * spacing / 2

    lines = [
        "from manim import *",
        "",
        f"class {class_name}(Scene):",
        "    def construct(self):",
        "        self.camera.background_color = '#0A0E18'",
        f"        steps = {safe_steps!r}",
        f"        spacing = {spacing}",
        f"        start_x = {start_x}",
        "        colours = [BLUE, GREEN, YELLOW, ORANGE, PURPLE]",
        "        boxes = []",
        "        labels = []",
        "        for i, s in enumerate(steps):",
        "            box = Rectangle(width=2.3, height=1.1, color=colours[i % len(colours)],",
        "                            stroke_width=4, fill_opacity=0.15,",
        "                            fill_color=colours[i % len(colours)])",
        "            box.move_to([start_x + i * spacing, 0, 0])",
        "            label = Text(s, font_size=28, color=WHITE).move_to(box.get_center())",
        "            boxes.append(box)",
        "            labels.append(label)",
        "        for i, (box, label) in enumerate(zip(boxes, labels)):",
        "            self.play(FadeIn(box, shift=UP * 0.3), Write(label), run_time=0.45)",
        "            if i < len(boxes) - 1:",
        "                arrow = Arrow(box.get_right(), boxes[i + 1].get_left(),",
        "                              buff=0.05, color=WHITE, stroke_width=4,",
        "                              max_tip_length_to_length_ratio=0.2)",
        "                self.play(GrowArrow(arrow), run_time=0.3)",
        "        self.wait(1.0)",
        "",
    ]
    return "\n".join(lines)


def manim_comparison(class_name, left, right):
    """Generate Manim code for a side-by-side X vs Y panel."""
    safe_l, safe_r = _safe_text(left), _safe_text(right)
    lines = [
        "from manim import *",
        "",
        f"class {class_name}(Scene):",
        "    def construct(self):",
        "        self.camera.background_color = '#0A0E18'",
        "        divider = Line(UP * 3.5, DOWN * 3.5, color=WHITE, stroke_width=2)",
        f"        left_title = Text({safe_l!r}, font_size=46, color=BLUE).move_to([-3.3, 2.5, 0])",
        f"        right_title = Text({safe_r!r}, font_size=46, color=ORANGE).move_to([3.3, 2.5, 0])",
        "        left_box = Rectangle(width=5, height=4, color=BLUE,",
        "                             stroke_width=3, fill_opacity=0.1).move_to([-3.3, -0.3, 0])",
        "        right_box = Rectangle(width=5, height=4, color=ORANGE,",
        "                              stroke_width=3, fill_opacity=0.1).move_to([3.3, -0.3, 0])",
        "        self.play(Create(divider), run_time=0.5)",
        "        self.play(Write(left_title), Write(right_title), run_time=0.6)",
        "        self.play(Create(left_box), Create(right_box), run_time=0.6)",
        "        self.wait(1.2)",
        "",
    ]
    return "\n".join(lines)


def manim_stat_grow(class_name, stat, label):
    """Generate Manim code for a stat that grows in dramatically."""
    safe_stat = _safe_text(stat, 12) or stat
    safe_label = _safe_text(label, 36) or "Annual Growth"
    lines = [
        "from manim import *",
        "",
        f"class {class_name}(Scene):",
        "    def construct(self):",
        "        self.camera.background_color = '#0A0E18'",
        f"        stat = Text({safe_stat!r}, font_size=180, color=BLUE, weight=BOLD)",
        f"        label = Text({safe_label!r}, font_size=36, color=WHITE).next_to(stat, DOWN, buff=0.6)",
        "        underline = Line(LEFT * 2.5, RIGHT * 2.5, color=BLUE,",
        "                         stroke_width=4).next_to(stat, UP, buff=0.4)",
        "        stat.scale(0.3)",
        "        self.play(GrowFromCenter(stat), run_time=0.5)",
        "        self.play(stat.animate.scale(3.0), run_time=0.7)",
        "        self.play(Create(underline), FadeIn(label, shift=UP * 0.2), run_time=0.5)",
        "        self.wait(1.5)",
        "",
    ]
    return "\n".join(lines)


def manim_architecture(class_name, components):
    """Generate Manim code for a system architecture diagram."""
    components = components[:5] if components else ["Frontend", "API", "Database"]
    safe = [_safe_text(c, 14) for c in components]
    lines = [
        "from manim import *",
        "",
        f"class {class_name}(Scene):",
        "    def construct(self):",
        "        self.camera.background_color = '#0A0E18'",
        f"        names = {safe!r}",
        "        colours = [BLUE, GREEN, ORANGE, PURPLE, YELLOW]",
        "        nodes = []",
        "        import math",
        "        n = len(names)",
        "        radius = 2.5",
        "        for i, name in enumerate(names):",
        "            angle = math.pi / 2 - i * (2 * math.pi / n)",
        "            x = radius * math.cos(angle)",
        "            y = radius * math.sin(angle)",
        "            colour = colours[i % len(colours)]",
        "            circle = Circle(radius=0.9, color=colour, stroke_width=3,",
        "                            fill_opacity=0.15, fill_color=colour).move_to([x, y, 0])",
        "            label = Text(name, font_size=22, color=WHITE).move_to(circle.get_center())",
        "            nodes.append((circle, label))",
        "        for circle, label in nodes:",
        "            self.play(FadeIn(circle, scale=0.6), Write(label), run_time=0.35)",
        "        for i, (c1, _) in enumerate(nodes):",
        "            c2, _ = nodes[(i + 1) % len(nodes)]",
        "            line = Line(c1.get_center(), c2.get_center(),",
        "                        stroke_width=2, color=GREY_C).set_z_index(-1)",
        "            self.play(Create(line), run_time=0.2)",
        "        self.wait(1.0)",
        "",
    ]
    return "\n".join(lines)


def manim_timeline(class_name, years):
    """Generate Manim code for an animated horizontal timeline."""
    years = sorted({str(y) for y in years})[:5] or ["2020", "2023", "2026"]
    lines = [
        "from manim import *",
        "",
        f"class {class_name}(Scene):",
        "    def construct(self):",
        "        self.camera.background_color = '#0A0E18'",
        f"        years = {years!r}",
        "        line = Line(LEFT * 5.5, RIGHT * 5.5, color=WHITE, stroke_width=3)",
        "        self.play(Create(line), run_time=0.7)",
        "        for i, year in enumerate(years):",
        "            x = -5 + i * (10 / max(1, len(years) - 1))",
        "            dot = Dot([x, 0, 0], radius=0.18, color=BLUE)",
        "            label = Text(year, font_size=32, color=WHITE).move_to([x, 0.7, 0])",
        "            self.play(FadeIn(dot, scale=0.5), Write(label), run_time=0.4)",
        "        self.wait(1.0)",
        "",
    ]
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# Generation
# ═══════════════════════════════════════════════════════════════

def generate_scene_code(trigger_type, trigger_match, narration, class_name):
    """Build Manim scene code for a given trigger."""
    if trigger_type == "flowchart":
        steps = re.findall(r"\b(?:step\s+\w+|first|then|next|finally)\b[^.]*",
                           narration, re.I)[:4]
        labels = [s.split(",")[0][:18] for s in steps] if steps else [
            "Input", "Process", "Output",
        ]
        return manim_flowchart(class_name, labels)

    if trigger_type == "comparison":
        m = re.search(r"\b(\w+)\s+vs\.?\s+(\w+)\b", trigger_match, re.I)
        if m:
            return manim_comparison(class_name, m.group(1), m.group(2))
        m = re.search(r"\b(\w+)\s+vs\.?\s+(\w+)\b", narration, re.I)
        if m:
            return manim_comparison(class_name, m.group(1), m.group(2))
        return manim_comparison(class_name, "Before", "After")

    if trigger_type == "stat_grow":
        stat = trigger_match.strip()
        label_match = re.search(rf"{re.escape(stat)}\s+(\w+(?:\s+\w+){{0,4}})",
                                narration)
        label = label_match.group(1) if label_match else "Significant growth"
        return manim_stat_grow(class_name, stat, label)

    if trigger_type == "architecture":
        comps = re.findall(r"\b(?:three|four|five)\s+(\w+)\b", narration, re.I)
        if comps:
            base = comps[0].rstrip("s").capitalize()
            comp_list = [f"{base} A", f"{base} B", f"{base} C"]
        else:
            comp_list = ["Frontend", "Backend", "Database"]
        return manim_architecture(class_name, comp_list)

    if trigger_type == "timeline":
        years = re.findall(r"\b((?:19|20)\d{2})\b", narration)
        return manim_timeline(class_name, years)

    return None


def render_manim_scene(scene_py_path, class_name, output_path):
    """Run manim CLI to render the scene to MP4. Returns True on success."""
    if not _manim_available():
        return False

    out_dir = output_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        _manim_python(), "-m", "manim",
        "-qm",
        "--format=mp4",
        "--media_dir", str(out_dir / "_manim_cache"),
        "--output_file", output_path.stem,
        str(scene_py_path), class_name,
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        print(f"        ⏱  Manim render timeout for {class_name}")
        return False

    if r.returncode != 0:
        print(f"        ⚠️  Manim render failed: {r.stderr[-300:]}")
        return False

    cache = out_dir / "_manim_cache"
    if cache.exists():
        for mp4 in cache.rglob(f"{output_path.stem}.mp4"):
            shutil.copy2(mp4, output_path)
            break
        shutil.rmtree(cache, ignore_errors=True)
    return output_path.exists()


# ═══════════════════════════════════════════════════════════════
# PIL-based fallback renderer (used when Manim is unavailable)
# Produces clean 1080p animated illustrations using only Pillow + FFmpeg.
# ═══════════════════════════════════════════════════════════════

W, H = 1920, 1080


def _draw_arrow_h(draw, x1, y, x2, color, width=4):
    """Horizontal arrow from x1,y to x2,y (x2 > x1)."""
    draw.line([(x1, y), (x2 - 14, y)], fill=color, width=width)
    head = [(x2, y), (x2 - 16, y - 9), (x2 - 16, y + 9)]
    draw.polygon(head, fill=color)


def _draw_text_centered(draw, xy, text, font, color):
    draw.text(xy, text, font=font, fill=color, anchor="mm")


def _new_frame():
    img = Image.new("RGB", (W, H), BG_COLOR)
    d = ImageDraw.Draw(img)
    for y in range(0, H, 4):
        shade = int(2 + 8 * (y / H))
        d.rectangle([0, y, W, y + 4],
                    fill=(BG_COLOR[0] + shade // 2,
                          BG_COLOR[1] + shade // 2,
                          BG_COLOR[2] + shade))
    return img, ImageDraw.Draw(img)


def _render_pil_flowchart(steps, output_path, fps=30, duration=6.0):
    """Animated horizontal flowchart of 3-5 labelled boxes with arrows."""
    steps = [s for s in (steps or ["Input", "Process", "Output"]) if s][:5]
    n = len(steps)
    total = int(duration * fps)
    frames_dir = output_path.parent / f"{output_path.stem}_frames"
    if frames_dir.exists():
        shutil.rmtree(frames_dir)
    frames_dir.mkdir(parents=True)

    box_w, box_h = 280, 130
    gap = 80
    total_w = n * box_w + (n - 1) * gap
    start_x = (W - total_w) // 2
    cy = H // 2

    f_title = _font(48, bold=True)
    f_label = _font(34, bold=True)

    # Each step has its own appearance frame
    step_frames = [int(total * (i + 1) / (n + 1.5)) for i in range(n)]

    for f_idx in range(total):
        img, draw = _new_frame()
        _draw_text_centered(draw, (W // 2, 110), "How it works",
                            f_title, TEXT_PRIMARY)
        draw.rectangle([W // 2 - 110, 150, W // 2 + 110, 153],
                       fill=ACCENT_BLUE)

        for i, step in enumerate(steps):
            colour = PALETTE[i % len(PALETTE)]
            x0 = start_x + i * (box_w + gap)
            x1 = x0 + box_w
            y0, y1 = cy - box_h // 2, cy + box_h // 2

            appear_at = step_frames[i] - int(0.4 * fps)
            if f_idx < appear_at:
                continue
            local = min(1.0, (f_idx - appear_at) / max(1, int(0.5 * fps)))
            eased = _ease_out(local)
            offset_y = int(20 * (1 - eased))

            draw.rounded_rectangle(
                [x0, y0 - offset_y, x1, y1 - offset_y],
                radius=14, outline=colour, width=4,
                fill=(colour[0] // 6, colour[1] // 6, colour[2] // 6),
            )
            _draw_text_centered(
                draw, ((x0 + x1) // 2, (y0 + y1) // 2 - offset_y),
                step, f_label, TEXT_PRIMARY,
            )

            if i > 0:
                prev_x1 = start_x + (i - 1) * (box_w + gap) + box_w
                arrow_appear = step_frames[i] - int(0.2 * fps)
                if f_idx >= arrow_appear:
                    _draw_arrow_h(draw, prev_x1 + 8, cy, x0 - 8, TEXT_PRIMARY, 4)

        img.save(str(frames_dir / f"frame_{f_idx:06d}.png"), "PNG")

    ok = _encode_frames(frames_dir, output_path, fps)
    shutil.rmtree(frames_dir, ignore_errors=True)
    return ok


def _render_pil_comparison(left, right, output_path, fps=30, duration=6.0):
    """Side-by-side comparison panel."""
    total = int(duration * fps)
    frames_dir = output_path.parent / f"{output_path.stem}_frames"
    if frames_dir.exists():
        shutil.rmtree(frames_dir)
    frames_dir.mkdir(parents=True)

    f_title = _font(72, bold=True)
    f_label = _font(28)

    panel_w = 720
    panel_h = 540
    panel_y = (H - panel_h) // 2 + 40
    left_x = W // 4 - panel_w // 2
    right_x = 3 * W // 4 - panel_w // 2

    reveal_frames = int(0.6 * fps)
    pause_frames = int(0.3 * fps)

    for f_idx in range(total):
        img, draw = _new_frame()

        # Centre divider
        div_progress = min(1.0, f_idx / reveal_frames)
        div_h = int(panel_h * _ease_out(div_progress))
        draw.rectangle([W // 2 - 1, panel_y + (panel_h - div_h) // 2,
                        W // 2 + 1, panel_y + (panel_h + div_h) // 2],
                       fill=TEXT_DIM)

        # VS label
        if f_idx > reveal_frames:
            _draw_text_centered(draw, (W // 2, 110), "vs",
                                _font(56, bold=True), TEXT_PRIMARY)

        # Left panel
        left_t = max(0, f_idx - reveal_frames - pause_frames)
        if left_t > 0:
            p = min(1.0, left_t / reveal_frames)
            eased = _ease_out(p)
            offset_x = int(60 * (1 - eased))
            draw.rounded_rectangle(
                [left_x - offset_x, panel_y,
                 left_x + panel_w - offset_x, panel_y + panel_h],
                radius=16, outline=ACCENT_BLUE, width=4,
                fill=(ACCENT_BLUE[0] // 7, ACCENT_BLUE[1] // 7,
                      ACCENT_BLUE[2] // 7),
            )
            _draw_text_centered(
                draw,
                (left_x + panel_w // 2 - offset_x, panel_y + panel_h // 2),
                str(left)[:18], f_title, ACCENT_BLUE,
            )

        right_t = max(0, f_idx - reveal_frames - pause_frames * 2)
        if right_t > 0:
            p = min(1.0, right_t / reveal_frames)
            eased = _ease_out(p)
            offset_x = int(60 * (1 - eased))
            draw.rounded_rectangle(
                [right_x + offset_x, panel_y,
                 right_x + panel_w + offset_x, panel_y + panel_h],
                radius=16, outline=ACCENT_ORANGE, width=4,
                fill=(ACCENT_ORANGE[0] // 7, ACCENT_ORANGE[1] // 7,
                      ACCENT_ORANGE[2] // 7),
            )
            _draw_text_centered(
                draw,
                (right_x + panel_w // 2 + offset_x, panel_y + panel_h // 2),
                str(right)[:18], f_title, ACCENT_ORANGE,
            )

        img.save(str(frames_dir / f"frame_{f_idx:06d}.png"), "PNG")

    ok = _encode_frames(frames_dir, output_path, fps)
    shutil.rmtree(frames_dir, ignore_errors=True)
    return ok


def _render_pil_stat_grow(stat, label, output_path, fps=30, duration=6.0):
    """Big number that scales in, then label fades in below."""
    total = int(duration * fps)
    frames_dir = output_path.parent / f"{output_path.stem}_frames"
    if frames_dir.exists():
        shutil.rmtree(frames_dir)
    frames_dir.mkdir(parents=True)

    grow_frames = int(0.7 * fps)
    label_appear = grow_frames + int(0.2 * fps)
    label_frames = int(0.5 * fps)

    cx, cy = W // 2, H // 2

    for f_idx in range(total):
        img, draw = _new_frame()

        if f_idx <= grow_frames:
            p = f_idx / max(1, grow_frames)
            scale = 0.2 + 1.0 * _ease_out(p)
        else:
            scale = 1.2 + 0.04 * math.sin(f_idx * 0.08)

        size = max(60, int(280 * scale))
        f_stat = _font(size, bold=True)
        # Shadow
        _draw_text_centered(draw, (cx + 6, cy - 60 + 6), str(stat),
                            f_stat, (0, 0, 0))
        _draw_text_centered(draw, (cx, cy - 60), str(stat),
                            f_stat, ACCENT_BLUE)

        if f_idx > label_appear and label:
            lp = min(1.0, (f_idx - label_appear) / max(1, label_frames))
            eased = _ease_out(lp)
            offset_y = int(20 * (1 - eased))
            f_label = _font(46, bold=True)
            _draw_text_centered(
                draw, (cx, cy + 160 + offset_y),
                str(label)[:48], f_label, TEXT_PRIMARY,
            )
            # underline
            uw = int(220 * eased)
            draw.rectangle([cx - uw, cy + 100, cx + uw, cy + 103],
                           fill=ACCENT_BLUE)

        img.save(str(frames_dir / f"frame_{f_idx:06d}.png"), "PNG")

    ok = _encode_frames(frames_dir, output_path, fps)
    shutil.rmtree(frames_dir, ignore_errors=True)
    return ok


def _render_pil_architecture(components, output_path, fps=30, duration=6.0):
    """Circular system architecture with nodes + connecting lines."""
    components = (components or ["Frontend", "API", "Database"])[:5]
    n = len(components)
    total = int(duration * fps)
    frames_dir = output_path.parent / f"{output_path.stem}_frames"
    if frames_dir.exists():
        shutil.rmtree(frames_dir)
    frames_dir.mkdir(parents=True)

    cx, cy = W // 2, H // 2 + 30
    radius = 300
    node_r = 95
    f_title = _font(48, bold=True)
    f_label = _font(26, bold=True)

    node_positions = []
    for i in range(n):
        angle = -math.pi / 2 + i * (2 * math.pi / n)
        nx = cx + int(radius * math.cos(angle))
        ny = cy + int(radius * math.sin(angle))
        node_positions.append((nx, ny))

    node_appear = [int(total * (i + 1) / (n + 2)) for i in range(n)]
    line_appear_start = node_appear[-1] + int(0.2 * fps)

    for f_idx in range(total):
        img, draw = _new_frame()
        _draw_text_centered(draw, (cx, 110), "Architecture",
                            f_title, TEXT_PRIMARY)
        draw.rectangle([cx - 130, 150, cx + 130, 153], fill=ACCENT_BLUE)

        # Lines between adjacent nodes (drawn after all nodes are visible)
        if f_idx > line_appear_start:
            lp = min(1.0, (f_idx - line_appear_start) / max(1, int(0.5 * fps)))
            for i in range(n):
                x1, y1 = node_positions[i]
                x2, y2 = node_positions[(i + 1) % n]
                ix = int(x1 + (x2 - x1) * lp)
                iy = int(y1 + (y2 - y1) * lp)
                draw.line([(x1, y1), (ix, iy)], fill=TEXT_DIM, width=3)

        for i, (nx, ny) in enumerate(node_positions):
            if f_idx < node_appear[i]:
                continue
            colour = PALETTE[i % len(PALETTE)]
            local = min(1.0, (f_idx - node_appear[i]) / max(1, int(0.4 * fps)))
            scale = 0.4 + 0.6 * _ease_out(local)
            r = int(node_r * scale)
            draw.ellipse([nx - r, ny - r, nx + r, ny + r],
                         outline=colour, width=4,
                         fill=(colour[0] // 6, colour[1] // 6, colour[2] // 6))
            if local > 0.6:
                _draw_text_centered(
                    draw, (nx, ny),
                    components[i][:14], f_label, TEXT_PRIMARY,
                )

        img.save(str(frames_dir / f"frame_{f_idx:06d}.png"), "PNG")

    ok = _encode_frames(frames_dir, output_path, fps)
    shutil.rmtree(frames_dir, ignore_errors=True)
    return ok


def _render_pil_timeline(years, output_path, fps=30, duration=6.0):
    """Horizontal timeline that fills left-to-right with year dots."""
    years = sorted({str(y) for y in (years or ["2020", "2023", "2026"])})[:6]
    n = len(years)
    total = int(duration * fps)
    frames_dir = output_path.parent / f"{output_path.stem}_frames"
    if frames_dir.exists():
        shutil.rmtree(frames_dir)
    frames_dir.mkdir(parents=True)

    f_title = _font(48, bold=True)
    f_year = _font(44, bold=True)

    margin = 220
    cy = H // 2 + 60
    line_x1, line_x2 = margin, W - margin

    line_fill_frames = int(1.0 * fps)
    dot_appear = [
        line_fill_frames + int((i + 1) * 0.3 * fps) for i in range(n)
    ]

    for f_idx in range(total):
        img, draw = _new_frame()
        _draw_text_centered(draw, (W // 2, 200), "Timeline",
                            f_title, TEXT_PRIMARY)
        draw.rectangle([W // 2 - 100, 240, W // 2 + 100, 243],
                       fill=ACCENT_BLUE)

        # Fill line left-to-right
        fill_p = min(1.0, f_idx / max(1, line_fill_frames))
        fill_x = int(line_x1 + (line_x2 - line_x1) * _ease_out(fill_p))
        draw.line([(line_x1, cy), (line_x2, cy)], fill=TEXT_DIM, width=3)
        draw.line([(line_x1, cy), (fill_x, cy)], fill=ACCENT_BLUE, width=4)

        for i, year in enumerate(years):
            if f_idx < dot_appear[i]:
                continue
            local = min(1.0, (f_idx - dot_appear[i]) / max(1, int(0.4 * fps)))
            scale = 0.5 + 0.5 * _ease_out(local)
            r = int(18 * scale)
            x = line_x1 + i * (line_x2 - line_x1) // max(1, n - 1)
            draw.ellipse([x - r, cy - r, x + r, cy + r],
                         outline=ACCENT_BLUE, width=3,
                         fill=BG_COLOR)
            if local > 0.5:
                _draw_text_centered(draw, (x, cy - 70), str(year),
                                    f_year, TEXT_PRIMARY)

        img.save(str(frames_dir / f"frame_{f_idx:06d}.png"), "PNG")

    ok = _encode_frames(frames_dir, output_path, fps)
    shutil.rmtree(frames_dir, ignore_errors=True)
    return ok


def render_pil_illustration(trigger_type, narration, trigger_match,
                             output_path, fps=30, duration=6.0):
    """Dispatch to the appropriate PIL renderer based on trigger type."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if trigger_type == "flowchart":
        steps = re.findall(
            r"\b(?:step\s+\w+|first|then|next|finally)\b[^.,;]{2,40}",
            narration, re.I,
        )[:4]
        labels = [_safe_text(s.split(",")[0], 16) for s in steps] if steps \
            else ["Input", "Process", "Output"]
        return _render_pil_flowchart(labels, output_path, fps, duration)

    if trigger_type == "comparison":
        m = re.search(r"\b(\w+)\s+vs\.?\s+(\w+)\b", trigger_match or "", re.I)
        if not m:
            m = re.search(r"\b(\w+)\s+vs\.?\s+(\w+)\b", narration, re.I)
        left = m.group(1) if m else "Before"
        right = m.group(2) if m else "After"
        return _render_pil_comparison(left, right, output_path, fps, duration)

    if trigger_type == "stat_grow":
        stat = trigger_match.strip() if trigger_match else "100%"
        label_match = re.search(
            rf"{re.escape(stat)}\s+(\w+(?:\s+\w+){{0,5}})", narration,
        )
        label = label_match.group(1) if label_match else "Significant growth"
        return _render_pil_stat_grow(stat, label, output_path, fps, duration)

    if trigger_type == "architecture":
        comps = re.findall(
            r"\b(?:three|four|five)\s+(\w+)\b", narration, re.I,
        )
        comp_list = ["Frontend", "Backend", "Database"]
        if comps:
            comp_list = [c.title() for c in comps[:3]]
        return _render_pil_architecture(comp_list, output_path, fps, duration)

    if trigger_type == "timeline":
        years = re.findall(r"\b((?:19|20)\d{2})\b", narration)
        return _render_pil_timeline(years, output_path, fps, duration)

    return False


# ═══════════════════════════════════════════════════════════════
# Shot list injection
# ═══════════════════════════════════════════════════════════════

def inject_illustration_beats(shot_list, plan):
    """
    plan: list of dicts with section_id, illustration_path, trigger_type, duration
    For each plan entry, insert an illustration beat at the start of the matching section.
    """
    if not shot_list:
        return shot_list

    by_section = {}
    for entry in plan:
        by_section.setdefault(entry["section_id"], []).append(entry)

    for section in shot_list.get("sections", []):
        sid = section.get("section_id")
        if sid not in by_section:
            continue
        new_shots = []
        inserted = False
        for entry in by_section[sid]:
            new_shots.append({
                "type": "illustration",
                "path": entry["illustration_path"],
                "duration": entry.get("duration", 6.0),
                "motion": "static",
                "trigger": entry.get("trigger_type"),
            })
            inserted = True
        if inserted:
            mid = len(section.get("shots", [])) // 2
            section["shots"] = (
                section.get("shots", [])[:mid]
                + new_shots
                + section.get("shots", [])[mid:]
            )

    return shot_list


# ═══════════════════════════════════════════════════════════════
# Main entry
# ═══════════════════════════════════════════════════════════════

def run(script_path, shot_list_path, max_per_section=2, render=True,
        mode_config_path=None):
    if not Path(script_path).exists():
        print(f"❌ Script not found: {script_path}")
        return False

    with open(script_path, encoding="utf-8") as f:
        script = json.load(f)

    # Phase 10: mode-aware density. Phase 12: skip outright in news modes.
    mode = "reaction"
    if mode_config_path and Path(mode_config_path).exists():
        try:
            cfg = json.loads(Path(mode_config_path).read_text(encoding="utf-8"))
            mode = cfg.get("mode", "reaction")
        except Exception:
            pass
    # Phase 12 pivot: reaction / fireship videos use stock + Kling hero only.
    # No Manim illustrations unless explicitly in explainer or tutorial.
    if mode not in {"explainer", "tutorial"}:
        print(f"   mode={mode!r} — Illustration Engineer disabled "
              f"(Phase 12: explainer/tutorial only)")
        return True
    aggressive = mode in {"explainer", "tutorial"}
    if aggressive:
        max_per_section = max(max_per_section, 5)
    print(f"   mode={mode!r}, aggressive={aggressive}, "
          f"max_per_section={max_per_section}")

    shot_list = None
    if Path(shot_list_path).exists():
        with open(shot_list_path, encoding="utf-8") as f:
            shot_list = json.load(f)

    ILL_DIR.mkdir(parents=True, exist_ok=True)
    KB_DIR.mkdir(parents=True, exist_ok=True)

    plan = []
    manim_ok = _manim_available()
    print(f"🎨 Illustration Engineer — Manim available: {manim_ok}")

    counter = 0
    for sec in script.get("sections", []):
        sid = sec.get("id", "")
        narration = sec.get("narration", "")
        triggers = detect_triggers(narration, aggressive=aggressive)
        if not triggers:
            continue

        for trigger_type, match_text in triggers[:max_per_section]:
            counter += 1
            class_name = f"Illustration{counter:03d}"
            scene_py = ILL_DIR / f"illustration_{counter:03d}.py"
            scene_mp4 = ILL_DIR / f"illustration_{counter:03d}.mp4"

            code = generate_scene_code(trigger_type, match_text,
                                       narration, class_name)
            if not code:
                continue
            scene_py.write_text(code, encoding="utf-8")
            print(f"  [{counter}] {sid}: {trigger_type}  ({scene_py.name})")

            rendered = False
            renderer = ""
            if render:
                if manim_ok:
                    rendered = render_manim_scene(scene_py, class_name, scene_mp4)
                    renderer = "manim" if rendered else ""
                if not rendered:
                    rendered = render_pil_illustration(
                        trigger_type, narration, match_text, scene_mp4,
                    )
                    renderer = "pil" if rendered else ""
                if rendered:
                    print(f"        🎞  rendered ({renderer}) → {scene_mp4.name}")
                else:
                    print(f"        ⚠️  render failed for {trigger_type}")

            plan_entry = {
                "section_id": sid,
                "trigger_type": trigger_type,
                "scene_py": str(scene_py),
                "illustration_path": str(scene_mp4) if rendered else "",
                "rendered": rendered,
                "renderer": renderer,
                "duration": 6.0,
            }
            plan.append(plan_entry)

    # Save plan to knowledge base for review
    plan_file = KB_DIR / "latest_plan.json"
    with open(plan_file, "w", encoding="utf-8") as f:
        json.dump(plan, f, indent=2)

    # Only inject beats that successfully rendered
    rendered_plan = [p for p in plan if p["rendered"]]
    if rendered_plan and shot_list:
        shot_list = inject_illustration_beats(shot_list, rendered_plan)
        with open(shot_list_path, "w", encoding="utf-8") as f:
            json.dump(shot_list, f, indent=2)
        print(f"  ✅ Injected {len(rendered_plan)} illustration beat(s) "
              f"into shot list")
    else:
        print(f"  ⚠️  No rendered illustrations to inject "
              f"(planned: {len(plan)}, rendered: {len(rendered_plan)})")

    return True


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--script", default=str(SCRIPT_PATH))
    p.add_argument("--shot-list", default=str(SHOT_LIST_PATH))
    p.add_argument("--no-render", action="store_true",
                   help="Skip Manim rendering (write .py files only)")
    p.add_argument("--max-per-section", type=int, default=2)
    p.add_argument("--mode-config",
                   default=str(PROJECT_ROOT / "output" / "mode_config.json"))
    args = p.parse_args()

    ok = run(args.script, args.shot_list,
             max_per_section=args.max_per_section,
             render=not args.no_render,
             mode_config_path=args.mode_config)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
