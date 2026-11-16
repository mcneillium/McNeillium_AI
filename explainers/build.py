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
                if shot.get("image") or shot.get("card") or shot.get("clip"):
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


PHONE_HTML = """<!doctype html><html><head><meta charset="utf-8"><style>
html,body{{margin:0;width:{w}px;height:{h}px;overflow:hidden;background:transparent;font-family:'Inter',sans-serif}}
.bg{{position:absolute;inset:0;background:radial-gradient(1200px 800px at 75% 40%,#1d2f4a 0,#101b2c 60%)}}
.bar{{position:absolute;left:0;top:0;height:10px;width:100%;background:linear-gradient(90deg,#a78bfa,#6fd3c4)}}
.txt{{position:absolute;left:140px;top:0;bottom:0;width:{tw}px;display:flex;flex-direction:column;justify-content:center;color:#e6edf6}}
.k{{font-size:28px;letter-spacing:.12em;text-transform:uppercase;color:#a78bfa;margin-bottom:22px}}
.t{{font-size:66px;line-height:1.08;font-weight:700;margin:0 0 22px}}
.s{{font-size:32px;line-height:1.4;color:#acbcd0;margin:0}}
.bezel{{position:absolute;left:{bx}px;top:{by}px;width:{bw}px;height:{bh}px;border-radius:{br}px;
  box-shadow:0 0 0 {bz}px #05080e,0 0 0 {bz2}px #3a4a63,0 40px 90px rgba(0,0,0,.6)}}
</style></head><body>{body}</body></html>"""

LT_HTML = """<!doctype html><html><head><meta charset="utf-8"><style>
html,body{{margin:0;width:{w}px;height:{h}px;background:transparent;font-family:'Inter',sans-serif;overflow:hidden}}
.lt{{position:absolute;left:96px;bottom:200px;padding:18px 30px 20px 26px;background:rgba(16,27,44,.92);
  border-left:8px solid #a78bfa;border-radius:6px}}
.n{{font-size:46px;font-weight:700;color:#fff;line-height:1.1}}.r{{font-size:28px;color:#acbcd0;margin-top:6px}}
</style></head><body><div class="lt"><div class="n">{name}</div><div class="r">{role}</div></div></body></html>"""


def render_html(path, page_html, transparent=False):
    from playwright.sync_api import sync_playwright
    path.parent.mkdir(parents=True, exist_ok=True)
    chrome = shutil.which("google-chrome")
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=chrome, args=["--no-sandbox"]) if chrome else p.chromium.launch()
        pg = b.new_page(viewport={"width": W, "height": H})
        pg.set_content(page_html)
        pg.wait_for_timeout(250)
        pg.screenshot(path=str(path), type="png", omit_background=transparent)
        b.close()
    return path


def phone_layout(clip_w, clip_h):
    """Screen rectangle for a phone recording on the right of the frame."""
    sh = 860
    sw = round(sh * clip_w / clip_h / 2) * 2
    return {"x": 1290 + (430 - sw) // 2, "y": 70, "w": sw, "h": sh}


def render_phone_frames(work, name, label, clip_w, clip_h):
    r = phone_layout(clip_w, clip_h)
    rad, bz = 44, 16
    common = dict(w=W, h=H, tw=1000, bx=r["x"], by=r["y"], bw=r["w"], bh=r["h"], br=rad, bz=bz, bz2=bz + 3)
    txt = ""
    if label:
        txt = (f'<div class="txt"><div class="k">{html.escape(label.get("kicker", ""))}</div>'
               f'<div class="t">{html.escape(label.get("title", ""))}</div>'
               f'<p class="s">{html.escape(label.get("sub", ""))}</p></div>')
    bg = render_html(work / "frames" / f"{name}-bg.png",
                     PHONE_HTML.format(body='<div class="bg"></div><div class="bar"></div>' + txt, **common))
    # bezel: transparent everywhere except the ring, with rounded corners masking the screen
    mask_css = (f'<div style="position:absolute;inset:0;background:#000;'
                f'-webkit-mask:radial-gradient(0 0,#000 0,#000 0);"></div>')
    bezel_body = (f'<svg width="{W}" height="{H}" style="position:absolute;inset:0"><defs><mask id="m">'
                  f'<rect width="{W}" height="{H}" fill="white"/><rect x="{r["x"]}" y="{r["y"]}" width="{r["w"]}" '
                  f'height="{r["h"]}" rx="{rad}" fill="black"/></mask></defs>'
                  f'<rect x="{r["x"] - 40}" y="{r["y"] - 40}" width="{r["w"] + 80}" height="{r["h"] + 80}" '
                  f'fill="#0c111b" mask="url(#m)"/></svg><div class="bezel"></div>')
    bezel = render_html(work / "frames" / f"{name}-bezel.png", PHONE_HTML.format(body=bezel_body, **common),
                        transparent=True)
    return bg, bezel, r


def clip_window(shot):
    """Resolve start/end (seconds or mark names like 'board+0.5') against <clip>.marks.json."""
    clip = ROOT / shot["clip"]
    marks_path = clip.with_suffix(".marks.json")
    marks = json.loads(marks_path.read_text()) if marks_path.exists() else {}

    def t(v, default):
        if v is None:
            return default
        if isinstance(v, (int, float)):
            return float(v)
        m = re.match(r"^([\w-]+)([+-][\d.]+)?$", str(v))
        return marks[m.group(1)] + float(m.group(2) or 0)
    return clip, t(shot.get("start"), 0.0), t(shot.get("end"), duration(clip))


def shot_chain(shot, ln, idx, label, work, name):
    """Inputs and a filter chain giving exactly ln seconds of 1920x1080 video as [label]."""
    inputs, chain = [], []
    z = shot.get("move")
    if shot.get("clip"):
        clip, a, b = clip_window(shot)
        speed = float(shot.get("speed", 1))
        avail = (b - a) / speed
        if avail > ln and shot.get("align") == "end":
            a = b - ln * speed
        inputs += ["-i", str(clip)]
        src = f"[{idx}:v]trim=start={a:.3f}:end={b:.3f},setpts=(PTS-STARTPTS)/{speed},fps={FPS}"
        if shot.get("frame") == "phone":
            cw, ch = (int(x) for x in subprocess.check_output(
                ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                 "-of", "csv=p=0", str(clip)], text=True).strip().split(","))
            bg, bezel, r = render_phone_frames(work, name, shot.get("label"), cw, ch)
            inputs += ["-loop", "1", "-framerate", str(FPS), "-i", str(bg),
                       "-loop", "1", "-framerate", str(FPS), "-i", str(bezel)]
            sm = shot.get("screen_move")
            if sm:  # zoom inside the phone screen, leaving the label and frame still
                sn = max(int(ln * FPS), 1)
                sfx, sfy = shot.get("screen_focus", [0.5, 0.3])
                src += f",tpad=stop_mode=clone:stop_duration={ln + 1:.3f}"
                src += (f",zoompan=z='{sm[0]}+({sm[1]}-{sm[0]})*min(on/{sn}\\,1)':x='(iw-iw/zoom)*{sfx}':"
                        f"y='(ih-ih/zoom)*{sfy}':d=1:s={cw}x{ch}:fps={FPS}")
            chain.append(f"{src},scale={r['w']}:{r['h']}:flags=lanczos[{label}s]")
            chain.append(f"[{idx + 1}:v][{label}s]overlay={r['x']}:{r['y']}:shortest=1[{label}o]")
            chain.append(f"[{label}o][{idx + 2}:v]overlay=0:0:shortest=1[{label}f]")
            cur, used = f"[{label}f]", 3
        else:
            chain.append(f"{src},scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,crop={W}:{H}[{label}f]")
            cur, used = f"[{label}f]", 1
        chain.append(f"{cur}tpad=stop_mode=clone:stop_duration={ln + 1:.3f},trim=duration={ln:.3f},setpts=PTS-STARTPTS[{label}t]")
        cur = f"[{label}t]"
    else:
        img = shot["_img"]
        inputs += ["-loop", "1", "-framerate", str(FPS), "-t", f"{ln + 0.1:.3f}", "-i", str(img)]
        chain.append(f"[{idx}:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},trim=duration={ln:.3f},setpts=PTS-STARTPTS[{label}t]")
        cur, used = f"[{label}t]", 1
        if z is None and shot.get("kenburns", True) and not shot.get("card"):
            z = [1.0, 1.05]
    if z:
        n = max(int(ln * FPS), 1)
        f = shot.get("focus")
        fx, fy = f if isinstance(f, (list, tuple)) else (0.5, 0.5)
        chain.append(f"{cur}scale={W * 2}:{H * 2}:flags=lanczos,zoompan=z='{z[0]}+({z[1]}-{z[0]})*on/{n}':"
                     f"x='(iw-iw/zoom)*{fx}':y='(ih-ih/zoom)*{fy}':d=1:s={W}x{H}:fps={FPS}[{label}z]")
        cur = f"[{label}z]"
    chain.append(f"{cur}format=yuv420p,setsar=1[{label}]")
    return inputs, chain, used


def scene_from_shots(shots, total, out, work, si, lower_third=None):
    """One file for a segment: its shots back to back with crossfades inside."""
    n = len(shots)
    usable = total + XFADE * (n - 1)
    wsum = sum(float(s.get("weight", 1)) for s in shots)
    lens = [usable * float(s.get("weight", 1)) / wsum for s in shots]
    inputs, chains, idx = [], [], 0
    for i, (shot, ln) in enumerate(zip(shots, lens)):
        ins, ch, used = shot_chain(shot, ln, idx, f"v{i}", work, f"{si:02d}-{i:02d}")
        inputs += ins
        chains += ch
        idx += used
    prev, offset = "v0", 0.0
    for i in range(1, n):
        offset += lens[i - 1] - XFADE
        tag = f"x{i}"
        chains.append(f"[{prev}][v{i}]xfade=transition=fade:duration={XFADE}:offset={offset:.3f}[{tag}]")
        prev = tag
    if lower_third:
        lt = render_html(work / "frames" / f"{si:02d}-lt.png",
                         LT_HTML.format(w=W, h=H, name=html.escape(lower_third["name"]),
                                        role=html.escape(lower_third.get("role", ""))), transparent=True)
        at, dur = float(lower_third.get("at", 0.6)), float(lower_third.get("for", 4))
        inputs += ["-loop", "1", "-framerate", str(FPS), "-t", f"{total:.3f}", "-i", str(lt)]
        chains.append(f"[{idx}:v]format=rgba,fade=t=in:st={at}:d=0.4:alpha=1,"
                      f"fade=t=out:st={at + dur}:d=0.4:alpha=1[lt]")
        chains.append(f"[{prev}][lt]overlay=0:0:shortest=1,format=yuv420p[lto]")
        prev = "lto"
    atomic_render(["ffmpeg", "-y", "-v", "error"] + inputs +
                  ["-filter_complex", ";".join(chains), "-map", f"[{prev}]", "-t", f"{total:.3f}"] + ENC, out)


def build_scenes(spec, work, only=None):
    scenes = work / "scenes"
    scenes.mkdir(exist_ok=True)
    title = render_card(work, "title", spec.get("kicker", "Explainer"), spec["title"], spec.get("subtitle", ""),
                        "paulmartinmcneill.com")
    end = render_card(work, "end", "Try it yourself", spec.get("end_title", "paulmartinmcneill.com"),
                      spec.get("end_text", ""), spec.get("voice_note", "Narrated with an AI voice"), size=88)
    files = [scenes / "00-title.mp4"]
    if only is None:
        still_clip(title, CARD_SECONDS, scenes / "00-title.mp4", fade_in=True)
    for si, seg in enumerate(spec["segments"]):
        out = scenes / f"{si + 1:02d}.mp4"
        files.append(out)
        if only is not None and si not in only:
            continue
        audio = work / "audio" / f"{si:02d}.mp3"
        total = duration(audio) + float(seg.get("pad", 0.35))
        shots = []
        for hi, shot in enumerate(seg.get("shots", [])):
            shot = dict(shot)
            if shot.get("clip"):
                pass
            elif shot.get("image"):
                shot["_img"] = Path(shot["image"])
            elif shot.get("card"):
                c = shot["card"]
                shot["_img"] = render_card(work, f"{si:02d}-{hi:02d}-card", c.get("kicker", ""), c.get("title", ""),
                                           c.get("sub", ""), c.get("foot", "paulmartinmcneill.com"),
                                           size=c.get("size", 96))
            else:
                shot["_img"] = work / "shots" / f"{si:02d}-{hi:02d}.jpg"
            shots.append(shot)
        scene_from_shots(shots, total, out, work, si, seg.get("lower_third"))
        print("scene", out.name, f"{total:.1f}s")
    if only is None:
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
    music = spec.get("music")
    if music:
        # quiet bed under the narration, ducked further while the voice speaks, faded at both ends
        total = CARD_SECONDS + END_SECONDS + sum(
            duration(work / "audio" / f"{i:02d}.mp3") + float(sg.get("pad", 0.35))
            for i, sg in enumerate(spec["segments"]))
        parts.extend(["-stream_loop", "-1", "-i", str(ROOT / music["file"])])
        vol = float(music.get("volume", 0.14))
        fc = fc.replace("[out]", "[nar]")
        fc += (f";[nar]aformat=channel_layouts=stereo,asplit=2[narA][narSC]"
               f";[{idx}:a]aresample=44100,aformat=channel_layouts=stereo,atrim=duration={total:.3f},"
               f"volume={vol},afade=t=in:d=1.5,afade=t=out:st={total - 3.5:.3f}:d=3.5[bed]"
               f";[bed][narSC]sidechaincompress=threshold=0.02:ratio=5:attack=30:release=600[duck]"
               f";[narA][duck]amix=inputs=2:normalize=0:duration=first,loudnorm=I=-16:TP=-1.5:LRA=11[out]")
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
    ap.add_argument("--only", help="comma-separated segment numbers to re-render (scenes step)")
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
        build_scenes(spec, work, only={int(x) for x in a.only.split(",")} if a.only else None)
    if a.step in ("join", "all"):
        joined = join(spec, work, slug)
        srt = build_captions(spec, work, slug)
        final = work / f"{slug}.mp4"
        burn(joined, srt, final)
        print("done", final, f"{duration(final):.1f}s")


if __name__ == "__main__":
    main()
