#!/usr/bin/env python3
"""Build a narrated explainer video from a YAML spec.

Each spec lists segments. A segment has narration text and one or more shots:
real screenshots of a web page (usually paulmartinmcneill.com), filmed with
Playwright after optional clicks and typing. The narration for each segment is
an MP3 in work/<slug>/audio/NN.mp3; make it with ElevenLabs (see
make_audio_elevenlabs below, which needs ELEVENLABS_API_KEY) or any TTS.

Pipeline, per video:
  1. shots    screenshots (JPEG q92, 1920x1080; zoomed shots use 2x scale)
  2. scenes   one encoded MP4 per segment: its shots, sized to the narration,
              with short crossfades inside the file, plus title and end cards
  3. join     concat demuxer with -c copy, then the narration track
  4. captions an SRT from the script text, timed from the audio; burnt in for
              the final file and also kept as a sidecar for YouTube

Usage:
  python explainers/build.py explainers/specs/01-voice.yaml            # all steps
  python explainers/build.py explainers/specs/01-voice.yaml --step shots
"""
import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
W, H, FPS = 1920, 1080, 30
XFADE = 0.4          # crossfade between shots inside a scene, seconds
CARD_SECONDS = 3.0   # title card length
END_SECONDS = 5.0    # end card length
ENC = ["-c:v", "libx264", "-crf", "18", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-r", str(FPS)]


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"command failed: {' '.join(map(str, cmd))}\n{r.stderr[-2000:]}")
    return r.stdout


def duration(path):
    return float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                      "-of", "csv=p=0", str(path)]).strip())


def atomic_render(cmd_without_out, out):
    """Render to a temporary .mp4 and rename only when ffmpeg succeeds."""
    tmp = out.with_name(out.stem + ".part.mp4")
    run(cmd_without_out + [str(tmp)])
    tmp.replace(out)


# ── 1. shots ────────────────────────────────────────────────────────────────
def take_shots(spec, work):
    from playwright.sync_api import sync_playwright
    shots_dir = work / "shots"
    shots_dir.mkdir(parents=True, exist_ok=True)
    chrome = spec.get("chrome") or shutil.which("google-chrome") or None
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chrome, args=["--no-sandbox"]) if chrome else p.chromium.launch()
        for si, seg in enumerate(spec["segments"]):
            for hi, shot in enumerate(seg.get("shots", [])):
                if shot.get("image") or shot.get("card"):
                    continue
                zoom = float(shot.get("zoom", 1))
                ctx = browser.new_context(viewport={"width": W, "height": H}, device_scale_factor=zoom,
                                          reduced_motion="reduce")
                theme = shot.get("theme", spec.get("theme", "dark"))
                ctx.add_init_script(f"try{{localStorage.setItem('theme','{theme}')}}catch(e){{}}")
                page = ctx.new_page()
                page.goto(shot["url"], wait_until="networkidle")
                page.wait_for_timeout(int(shot.get("settle_ms", 1200)))
                # hide floating widgets that would cover the content
                page.add_style_tag(content=".chat-fab,.back-to-top,.scroll-progress{display:none!important}")
                for act in shot.get("actions", []):
                    kind, arg = next(iter(act.items()))
                    if kind == "click":
                        page.locator(arg).first.click()
                    elif kind == "fill":
                        page.locator(arg[0]).fill(arg[1])
                    elif kind == "check":
                        page.locator(arg).check()
                    elif kind == "press":
                        page.keyboard.press(arg)
                    elif kind == "wait":
                        page.wait_for_timeout(int(arg))
                    elif kind == "eval":
                        page.evaluate(arg)
                    page.wait_for_timeout(150)
                path = shots_dir / f"{si:02d}-{hi:02d}.jpg"
                focus = shot.get("focus")
                if focus:
                    page.locator(focus).first.scroll_into_view_if_needed()
                    page.evaluate("""(sel) => { const el = document.querySelector(sel); if (!el) return;
                        const r = el.getBoundingClientRect();
                        window.scrollBy(0, r.top + r.height / 2 - window.innerHeight / 2); }""", focus)
                    page.wait_for_timeout(500)
                clip = None
                if zoom > 1 and focus:
                    # Crop a (W/zoom x H/zoom) window around the focus element;
                    # the 2x device scale keeps the crop sharp at full size.
                    box = page.locator(focus).first.bounding_box()
                    cw, ch = W / zoom, H / zoom
                    cx = min(max(box["x"] + box["width"] / 2 - cw / 2, 0), W - cw)
                    cy = min(max(box["y"] + box["height"] / 2 - ch / 2, 0), H - ch)
                    clip = {"x": cx, "y": cy, "width": cw, "height": ch}
                page.screenshot(path=str(path), type="jpeg", quality=92, clip=clip)
                if zoom > 1:  # normalise to output size
                    run(["ffmpeg", "-y", "-v", "error", "-i", str(path), "-vf", f"scale={W}:{H}:flags=lanczos",
                         "-q:v", "2", str(path)])
                ctx.close()
                print("shot", path.name)
        browser.close()


# ── cards (title and end) ───────────────────────────────────────────────────
CARD_HTML = """<!doctype html><html><head><meta charset="utf-8"><style>
html,body{{margin:0;width:{w}px;height:{h}px;background:#101b2c;color:#e6edf6;
font-family:'Inter',sans-serif;overflow:hidden}}
.wrap{{position:absolute;inset:0;padding:120px 140px;display:flex;flex-direction:column;justify-content:center}}
.kicker{{font-size:30px;letter-spacing:.12em;text-transform:uppercase;color:#a78bfa;margin-bottom:28px}}
h1{{font-family:'Inter Display','Inter',sans-serif;font-size:{size}px;line-height:1.05;margin:0 0 30px;font-weight:700;max-width:1500px}}
p{{font-size:38px;line-height:1.4;color:#acbcd0;margin:0;max-width:1450px}}
.foot{{position:absolute;left:140px;right:140px;bottom:90px;display:flex;justify-content:space-between;
font-size:28px;color:#acbcd0}}
.bar{{position:absolute;left:0;top:0;height:10px;width:100%;background:linear-gradient(90deg,#a78bfa,#6fd3c4)}}
</style></head><body><div class="bar"></div><div class="wrap">
<div class="kicker">{kicker}</div><h1>{title}</h1><p>{sub}</p></div>
<div class="foot"><span>McNeillium AI</span><span>{foot}</span></div></body></html>"""


def render_card(work, name, kicker, title, sub, foot, size=104):
    from playwright.sync_api import sync_playwright
    page_html = CARD_HTML.format(w=W, h=H, kicker=html.escape(kicker), title=html.escape(title),
                                 sub=html.escape(sub), foot=html.escape(foot), size=size)
    out = work / "shots" / f"{name}.jpg"
    out.parent.mkdir(parents=True, exist_ok=True)
    chrome = shutil.which("google-chrome")
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=chrome, args=["--no-sandbox"]) if chrome else p.chromium.launch()
        pg = b.new_page(viewport={"width": W, "height": H})
        pg.set_content(page_html)
        pg.wait_for_timeout(300)
        pg.screenshot(path=str(out), type="jpeg", quality=92)
        b.close()
    return out


# ── 2. scenes ───────────────────────────────────────────────────────────────
def still_clip(img, seconds, out, fade_in=False, fade_out=False):
    vf = f"format=yuv420p,loop=-1:1,trim=duration={seconds:.3f}"
    if fade_in:
        vf += ",fade=t=in:st=0:d=0.5"
    if fade_out:
        vf += f",fade=t=out:st={max(seconds - 0.6, 0):.3f}:d=0.6"
    atomic_render(["ffmpeg", "-y", "-v", "error", "-framerate", str(FPS), "-i", str(img), "-vf", vf] + ENC, out)


def scene_from_shots(images, weights, total, out):
    """One file for a segment: its shots back to back with crossfades inside."""
    n = len(images)
    usable = total + XFADE * (n - 1)
    wsum = sum(weights)
    lens = [usable * w / wsum for w in weights]
    if n == 1:
        return still_clip(images[0], total, out)
    inputs, chains = [], []
    for i, (img, ln) in enumerate(zip(images, lens)):
        inputs += ["-framerate", str(FPS), "-i", str(img)]
        chains.append(f"[{i}:v]format=yuv420p,loop=-1:1,trim=duration={ln:.3f},setpts=PTS-STARTPTS,fps={FPS}[v{i}]")
    prev, offset = "v0", 0.0
    for i in range(1, n):
        offset += lens[i - 1] - XFADE
        tag = f"x{i}"
        chains.append(f"[{prev}][v{i}]xfade=transition=fade:duration={XFADE}:offset={offset:.3f}[{tag}]")
        prev = tag
    atomic_render(["ffmpeg", "-y", "-v", "error"] + inputs +
                  ["-filter_complex", ";".join(chains), "-map", f"[{prev}]"] + ENC, out)


def build_scenes(spec, work):
    scenes = work / "scenes"
    scenes.mkdir(exist_ok=True)
    title = render_card(work, "title", spec.get("kicker", "Explainer"), spec["title"], spec.get("subtitle", ""),
                        "paulmartinmcneill.com")
    end = render_card(work, "end", "Try it yourself", spec.get("end_title", "paulmartinmcneill.com"),
                      spec.get("end_text", ""), "Narrated with an AI voice", size=88)
    still_clip(title, CARD_SECONDS, scenes / "00-title.mp4", fade_in=True)
    files = [scenes / "00-title.mp4"]
    for si, seg in enumerate(spec["segments"]):
        audio = work / "audio" / f"{si:02d}.mp3"
        total = duration(audio) + float(seg.get("pad", 0.35))
        imgs, weights = [], []
        for hi, shot in enumerate(seg.get("shots", [])):
            if shot.get("image"):
                img = Path(shot["image"])
            elif shot.get("card"):
                c = shot["card"]
                img = render_card(work, f"{si:02d}-{hi:02d}-card", c.get("kicker", ""), c.get("title", ""),
                                  c.get("sub", ""), c.get("foot", "paulmartinmcneill.com"), size=c.get("size", 96))
            else:
                img = work / "shots" / f"{si:02d}-{hi:02d}.jpg"
            imgs.append(img)
            weights.append(float(shot.get("weight", 1)))
        out = scenes / f"{si + 1:02d}.mp4"
        scene_from_shots(imgs, weights, total, out)
        files.append(out)
        print("scene", out.name, f"{total:.1f}s")
    still_clip(end, END_SECONDS, scenes / "99-end.mp4", fade_out=True)
    files.append(scenes / "99-end.mp4")
    (work / "concat.txt").write_text("".join(f"file '{f.resolve()}'\n" for f in files))
    return files


# ── 3. narration track and join ─────────────────────────────────────────────
def build_audio(spec, work):
    """Narration track aligned with the scenes: silence under the title card,
    each segment's MP3 followed by its pad, silence under the end card."""
    parts, filt = [], []
    idx = 0
    def silence(sec):
        nonlocal idx
        parts.extend(["-f", "lavfi", "-t", f"{sec:.3f}", "-i", "anullsrc=r=44100:cl=mono"])
        filt.append(f"[{idx}:a]anull")
        idx += 1
    silence(CARD_SECONDS)
    for si, seg in enumerate(spec["segments"]):
        audio = work / "audio" / f"{si:02d}.mp3"
        parts.extend(["-i", str(audio)])
        filt.append(f"[{idx}:a]aresample=44100,aformat=channel_layouts=mono")
        idx += 1
        silence(float(seg.get("pad", 0.35)))
    silence(END_SECONDS)
    graph = [f"{f}[a{i}]" for i, f in enumerate(filt)]
    labels = "".join(f"[a{i}]" for i in range(len(filt)))
    fc = ";".join(graph) + ";" + labels + f"concat=n={len(filt)}:v=0:a=1[out]"
    out = work / "narration.m4a"
    run(["ffmpeg", "-y", "-v", "error"] + parts + ["-filter_complex", fc, "-map", "[out]",
                                                   "-c:a", "aac", "-b:a", "160k", str(out)])
    return out


def join(spec, work, slug):
    video = work / "video-noaudio.mp4"
    tmp = work / "video-noaudio.part.mp4"
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(work / "concat.txt"),
         "-c", "copy", str(tmp)])
    tmp.replace(video)
    narration = build_audio(spec, work)
    joined = work / f"{slug}-nocaptions.mp4"
    atomic_render(["ffmpeg", "-y", "-v", "error", "-i", str(video), "-i", str(narration),
                   "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "copy", "-shortest"], joined)
    return joined


# ── 4. captions ─────────────────────────────────────────────────────────────
def speech_span(audio):
    """Start and end of speech in a clip, from ffmpeg's silence detector."""
    out = subprocess.run(["ffmpeg", "-v", "info", "-i", str(audio), "-af",
                          "silencedetect=noise=-40dB:d=0.25", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    total = duration(audio)
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", out)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", out)]
    begin = ends[0] if starts and starts[0] < 0.05 and ends else 0.0
    finish = starts[-1] if starts and (not ends or starts[-1] > ends[-1]) else total
    return begin, max(finish, begin + 0.5)


def chunk_words(text, max_chars=42):
    words, lines, cur = text.split(), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > max_chars:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    # two lines per caption
    return ["\n".join(lines[i:i + 2]) for i in range(0, len(lines), 2)]


def ts(t):
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{s:06.3f}".replace(".", ",")


def build_captions(spec, work, slug):
    t0 = CARD_SECONDS
    cues = []
    for si, seg in enumerate(spec["segments"]):
        audio = work / "audio" / f"{si:02d}.mp3"
        b, e = speech_span(audio)
        chunks = chunk_words(seg["text"])
        lens = [len(c) for c in chunks]
        total_chars = sum(lens)
        cur = t0 + b
        for c, ln in zip(chunks, lens):
            span = (e - b) * ln / total_chars
            cues.append((cur, cur + span, c))
            cur += span
        t0 += duration(audio) + float(seg.get("pad", 0.35))
    srt = work / f"{slug}.srt"
    srt.write_text("".join(f"{i}\n{ts(a)} --> {ts(z)}\n{txt}\n\n" for i, (a, z, txt) in enumerate(cues, 1)),
                   encoding="utf-8")
    return srt


def burn(joined, srt, out):
    # BorderStyle=3 draws an opaque box behind each line in OutlineColour
    # (ASS colours are &HAABBGGRR; alpha 30 is about 80% opaque).
    style = ("FontName=Inter,FontSize=15,Bold=0,PrimaryColour=&H00FFFFFF,OutlineColour=&H302C1B10,"
             "BackColour=&H302C1B10,BorderStyle=3,Outline=6,Shadow=0,MarginV=28,Alignment=2")
    srt_arg = str(srt).replace("\\", "/").replace(":", "\\:")
    atomic_render(["ffmpeg", "-y", "-v", "error", "-i", str(joined), "-vf",
                   f"subtitles='{srt_arg}':force_style='{style}'"] + ENC + ["-c:a", "copy"], out)


# ── ElevenLabs (optional, for running on your own machine) ──────────────────
def make_audio_elevenlabs(spec, work):
    """Write work/audio/NN.mp3 for each segment with the ElevenLabs API."""
    import urllib.request
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        sys.exit("Set ELEVENLABS_API_KEY, or put your own MP3s in work/<slug>/audio/.")
    voice = spec.get("voice_id", "op1SmctrthoXFtxUlVpA")
    (work / "audio").mkdir(parents=True, exist_ok=True)
    for si, seg in enumerate(spec["segments"]):
        out = work / "audio" / f"{si:02d}.mp3"
        if out.exists():
            continue
        req = urllib.request.Request(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice}?output_format=mp3_44100_128",
            data=json.dumps({"text": seg["text"], "model_id": spec.get("model_id", "eleven_multilingual_v2")}).encode(),
            headers={"xi-api-key": key, "Content-Type": "application/json"})
        with urllib.request.urlopen(req) as r:
            out.write_bytes(r.read())
        print("audio", out.name)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("spec")
    ap.add_argument("--step", choices=["audio", "shots", "scenes", "join", "all"], default="all")
    ap.add_argument("--work", default=str(ROOT / "work"))
    a = ap.parse_args()
    spec = yaml.safe_load(Path(a.spec).read_text(encoding="utf-8"))
    slug = Path(a.spec).stem
    work = Path(a.work) / slug
    work.mkdir(parents=True, exist_ok=True)
    if a.step == "audio":
        return make_audio_elevenlabs(spec, work)
    if a.step in ("shots", "all"):
        take_shots(spec, work)
    if a.step in ("scenes", "all"):
        build_scenes(spec, work)
    if a.step in ("join", "all"):
        joined = join(spec, work, slug)
        srt = build_captions(spec, work, slug)
        final = work / f"{slug}.mp4"
        burn(joined, srt, final)
        print("done", final, f"{duration(final):.1f}s")


if __name__ == "__main__":
    main()
