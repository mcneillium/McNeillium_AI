#!/usr/bin/env python3
"""
McNeillium_AI — Phase 19 Step 4: Motion Graphics

Produces lower thirds, animated title cards, and logo reveals as
transparent (alpha-channel) WebM/MOV clips that the Video Producer
overlays on top of the main video.

Implementation note — Lottie pivot
──────────────────────────────────
The Phase 19 brief asked for a Lottie-backed pipeline. The Python
`lottie` package (0.7.2) only exports JSON / SVG / HTML / TGS; there
is NO direct MP4 or PNG-sequence exporter. Building a full Lottie
render loop would require cairosvg + manual template curation +
text-substitution that respects keyframes.

For Phase 19 we ship the user-visible outcome with a smaller surface:
FFmpeg-native lower thirds, title cards, and logo reveals via
drawbox / drawtext / fade filters. They render to MOV with alpha
(qtrle) and composite cleanly via FFmpeg's overlay filter.

Public API
──────────
  lower_third(name, sublabel, out_path, **opts) -> Path
      Animated bottom-left name card. Slides in, holds, slides out.

  title_card(text, out_path, accent="#58a6ff", **opts) -> Path
      Animated section-title card. Top-band drop-in with text.

  logo_reveal(text, out_path, **opts) -> Path
      Channel logo + tagline reveal for outros.

  composite(base_video, overlay, output, x=0, y=0, t_start=0.0)
      Overlay an alpha clip on top of a base video at (x, y) starting
      at t_start seconds. Wraps FFmpeg overlay+enable.

Coords are top-left = (0, 0). For 1920x1080 reaction-mode video,
defaults are tuned for safe-area placement.
"""

import argparse
import io
import shutil
import subprocess
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower().replace("-", "") != "utf8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8",
                                  errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ASSETS_LOTTIE = PROJECT_ROOT / "assets" / "lottie"


def _ffmpeg():
    return shutil.which("ffmpeg") or "ffmpeg"


# drawtext needs an explicit fontfile on Windows where fontconfig is
# typically absent. Mirror the font-discovery logic used by
# video/generate_video.py.
_FONT_CANDIDATES = [
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/HelveticaNeue.ttc",
]


def _font_file():
    for f in _FONT_CANDIDATES:
        if Path(f).exists():
            return f
    return None


def _font_arg():
    f = _font_file()
    if not f:
        return ""
    # Escape the colon in Windows paths AND wrap in single quotes so
    # FFmpeg's filter argument parser doesn't treat the colon as a
    # key/value separator. Belt-and-braces — either alone works in
    # bash but Python's argv passing seems to need both.
    f_esc = f.replace(":", r"\:")
    return f"fontfile='{f_esc}':"


def _shell_escape(text):
    return (text.replace("\\", "\\\\")
                .replace("'", "\\'")
                .replace(":", r"\:")
                .replace(",", r"\,"))


# ───────────────────────────── lower third ─────────────────────────────

def lower_third(name, sublabel, out_path, *,
                duration=4.0, fps=30, w=1920, h=1080,
                bar_h=110, bar_color="0x0d1117@0.92",
                accent="#58a6ff",
                margin_x=80, margin_y_from_bottom=140):
    """Animated lower-third name card → MOV with alpha (qtrle).

    Slides in left→right (0.4s), holds, slides out (0.4s).
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    bar_y = h - margin_y_from_bottom
    name_safe = _shell_escape(name)
    sub_safe = _shell_escape(sublabel)
    bar_w = 760
    accent_hex = accent.lstrip("#")

    # We render onto an alpha source (color=0x000000@0.0) and slide
    # both the bar and the text in/out via x= expression.
    # x animates: -bar_w  →  margin_x  (in 0..0.4s)
    #             holds  margin_x       (0.4..duration-0.4)
    #             margin_x → -bar_w     (duration-0.4..duration)
    slide_in = 0.4
    slide_out = 0.4
    hold_end = duration - slide_out

    # Bar x position expression — kept on one line; FFmpeg's expression
    # parser objects to embedded newlines/indentation in filter args.
    bar_x = (
        f"if(lt(t,{slide_in}),"
        f"-{bar_w}+(t/{slide_in})*({bar_w}+{margin_x}),"
        f"if(gt(t,{hold_end}),"
        f"{margin_x}-((t-{hold_end})/{slide_out})*({bar_w}+{margin_x}),"
        f"{margin_x}))"
    )

    # Build filter graph:
    #  1. base alpha layer
    #  2. drawbox for the dark bar (with accent stripe on the left)
    #  3. drawtext for name (large) + sublabel (small)
    font = _font_arg()
    fc = (
        f"color=c=0x000000@0.0:s={w}x{h}:r={fps}:d={duration}[bg];"
        f"[bg]drawbox=x='{bar_x}':y={bar_y}:w={bar_w}:h={bar_h}:"
        f"color={bar_color}:t=fill[bar1];"
        f"[bar1]drawbox=x='{bar_x}':y={bar_y}:w=8:h={bar_h}:"
        f"color=0x{accent_hex}@1.0:t=fill[bar2];"
        f"[bar2]drawtext={font}text='{name_safe}':"
        f"fontsize=48:fontcolor=white:"
        f"x='{bar_x}+30':y={bar_y + 18}[t1];"
        f"[t1]drawtext={font}text='{sub_safe}':"
        f"fontsize=22:fontcolor=0xa0aec0:"
        f"x='{bar_x}+32':y={bar_y + 78}[out]"
    )

    cmd = [
        _ffmpeg(), "-y",
        "-f", "lavfi", "-i", f"color=c=0x000000@0.0:s={w}x{h}:r={fps}:d={duration}",
        "-filter_complex", fc,
        "-map", "[out]",
        "-c:v", "qtrle",   # MOV with alpha
        "-pix_fmt", "argb",
        str(out_path.with_suffix(".mov")),
    ]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        sys.stderr.write(r.stderr.decode("utf-8", "replace")[-1500:])
        raise subprocess.CalledProcessError(r.returncode, cmd)
    return out_path.with_suffix(".mov")


# ───────────────────────────── title card ──────────────────────────────

def title_card(text, out_path, *,
               accent="#58a6ff",
               duration=2.5, fps=30, w=1920, h=1080):
    """Section title card: dark band slides down from top, text fades in."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    accent_hex = accent.lstrip("#")
    text_safe = _shell_escape(text)

    band_h = 140
    slide_in = 0.45
    slide_out = 0.45
    hold_end = duration - slide_out

    # Band y animates from -band_h → 0 (slide-in) → -band_h (slide-out)
    band_y = (
        f"if(lt(t,{slide_in}),"
        f"-{band_h}+(t/{slide_in})*{band_h},"
        f"if(gt(t,{hold_end}),"
        f"-((t-{hold_end})/{slide_out})*{band_h},"
        f"0))"
    )

    font = _font_arg()
    fc = (
        f"color=c=0x000000@0.0:s={w}x{h}:r={fps}:d={duration}[bg];"
        f"[bg]drawbox=x=0:y='{band_y}':w={w}:h={band_h}:"
        f"color=0x0d1117@0.95:t=fill[b1];"
        f"[b1]drawbox=x=0:y='{band_y}+{band_h - 6}':w={w}:h=6:"
        f"color=0x{accent_hex}@1.0:t=fill[b2];"
        f"[b2]drawtext={font}text='{text_safe}':"
        f"fontsize=64:fontcolor=white:"
        f"x=(w-text_w)/2:y='{band_y}+30'[out]"
    )

    cmd = [
        _ffmpeg(), "-y",
        "-f", "lavfi", "-i", f"color=c=0x000000@0.0:s={w}x{h}:r={fps}:d={duration}",
        "-filter_complex", fc,
        "-map", "[out]",
        "-c:v", "qtrle", "-pix_fmt", "argb",
        str(out_path.with_suffix(".mov")),
    ]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        sys.stderr.write(r.stderr.decode("utf-8", "replace")[-1500:])
        raise subprocess.CalledProcessError(r.returncode, cmd)
    return out_path.with_suffix(".mov")


# ───────────────────────────── logo reveal ─────────────────────────────

def logo_reveal(channel="McNeillium_AI", tagline="AI & Emerging Tech",
                out_path=None, *, accent="#58a6ff",
                duration=3.0, fps=30, w=1920, h=1080):
    """Outro-style logo reveal — channel name + tagline fade in centered."""
    out_path = Path(out_path)
    accent_hex = accent.lstrip("#")
    ch = _shell_escape(channel)
    tg = _shell_escape(tagline)

    # alpha grows from 0 → 1 over the first second, holds, fades over last 0.5s
    alpha_expr = (
        f"if(lt(t,1.0),t,"
        f"if(gt(t,{duration - 0.5}),max(0,1-((t-{duration - 0.5})/0.5)),1))"
    )

    font = _font_arg()
    fc = (
        f"color=c=0x000000@0.0:s={w}x{h}:r={fps}:d={duration}[bg];"
        f"[bg]drawtext={font}text='{ch}':"
        f"fontsize=110:fontcolor=white:alpha='{alpha_expr}':"
        f"x=(w-text_w)/2:y=(h/2)-90[t1];"
        f"[t1]drawtext={font}text='{tg}':"
        f"fontsize=40:fontcolor=0x{accent_hex}:alpha='{alpha_expr}':"
        f"x=(w-text_w)/2:y=(h/2)+40[out]"
    )

    cmd = [
        _ffmpeg(), "-y",
        "-f", "lavfi", "-i", f"color=c=0x000000@0.0:s={w}x{h}:r={fps}:d={duration}",
        "-filter_complex", fc,
        "-map", "[out]",
        "-c:v", "qtrle", "-pix_fmt", "argb",
        str(out_path.with_suffix(".mov")),
    ]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        sys.stderr.write(r.stderr.decode("utf-8", "replace")[-1500:])
        raise subprocess.CalledProcessError(r.returncode, cmd)
    return out_path.with_suffix(".mov")


# ─────────────────────────── compositing helper ───────────────────────

def composite(base_video, overlay, output, x=0, y=0, t_start=0.0):
    """Overlay an alpha clip onto a base video starting at t_start."""
    fc = (
        f"[1:v]setpts=PTS-STARTPTS+{t_start}/TB[ov];"
        f"[0:v][ov]overlay=x={x}:y={y}:enable='gte(t,{t_start})'[v]"
    )
    cmd = [
        _ffmpeg(), "-y",
        "-i", str(base_video), "-i", str(overlay),
        "-filter_complex", fc,
        "-map", "[v]", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "copy",
        str(output),
    ]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        sys.stderr.write(r.stderr.decode("utf-8", "replace")[-1500:])
        raise subprocess.CalledProcessError(r.returncode, cmd)
    return Path(output)


def main():
    p = argparse.ArgumentParser(description="Phase 19 motion graphics")
    p.add_argument("kind", choices=["lower-third", "title-card", "logo-reveal"])
    p.add_argument("--text", default="McNeillium_AI")
    p.add_argument("--sub", default="AI & Emerging Tech")
    p.add_argument("--out", default="output/_mg_test/sample.mov")
    args = p.parse_args()

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)

    if args.kind == "lower-third":
        out = lower_third(args.text, args.sub, args.out)
    elif args.kind == "title-card":
        out = title_card(args.text, args.out)
    else:
        out = logo_reveal(args.text, args.sub, args.out)

    print(f"✅ {args.kind} → {out}  ({out.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
