"""Record a real browser session as video: taps, typing and scrolling, with a
visible touch ripple (mobile) or cursor (desktop) so viewers can follow.

    python explainers/record.py explainers/recordings/voice-board.yaml

A recording spec:

    url: http://localhost:8765/demos/aac-app/
    out: explainers/footage/voice-board.mp4
    viewport: [430, 932]       # CSS pixels
    scale: 2                   # device pixel ratio, so 860x1864 frames
    mobile: true               # touch ripples instead of a cursor
    steps:
      - wait: 1500
      - tap: '[aria-label="Say I want. starter"]'
      - type: {selector: 'textarea', text: 'hello', delay: 90}
      - scroll: {y: 600, ms: 1200}
      - hover: '#thing'
      - eval: "document.body.classList.add('x')"
      - drag: {from: '.card >> nth=0', to: '.column >> nth=1', ms: 900}
      - focus: '#deal-12'          # then press: Alt+ArrowRight
      - mark: board-ready          # writes a timestamp to <out>.marks.json

Frames are DevTools screenshots taken in a loop at full device resolution
(about 17 a second at 2x), so text stays sharp; they are written as a constant
30 fps file with each frame held until the next one arrived. In headless
Chrome there are no speech voices, so speechSynthesis is replaced with a
stand-in that reports a normal start and end.
"""
import asyncio
import base64
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml
from playwright.async_api import async_playwright

FPS = 30
ROOT = Path(__file__).resolve().parents[1]

FAKE_SPEECH_JS = r"""
(() => {
  const ss = window.speechSynthesis; if (!ss) return;
  const voice = {name: 'Voice', lang: 'en-GB', default: true, localService: true, voiceURI: 'voice'};
  let speaking = false, cur = null, timer = null;
  const fire = (u, type) => { try { u.dispatchEvent(new Event(type)); } catch (e) { const h = u['on' + type]; h && h({}); } };
  Object.defineProperty(ss, 'speaking', {get: () => speaking});
  ss.getVoices = () => [voice];
  ss.speak = u => { cur = u; speaking = true; setTimeout(() => fire(u, 'start'), 40);
    const words = String(u.text || '').split(/\s+/).filter(Boolean).length || 1;
    timer = setTimeout(() => { speaking = false; fire(u, 'end'); }, 300 + words * 330); };
  ss.cancel = () => { if (cur && speaking) { clearTimeout(timer); speaking = false; fire(cur, 'end'); } };
})();
"""

OVERLAY_JS = r"""
(() => {
  if (window.__rec) return;
  const style = document.createElement('style');
  style.textContent = `
    .__rec-ripple{position:fixed;z-index:2147483647;pointer-events:none;width:64px;height:64px;
      margin:-32px 0 0 -32px;border-radius:50%;background:rgba(124,92,255,.35);
      border:3px solid rgba(124,92,255,.9);transform:scale(.3);opacity:1;
      transition:transform .45s cubic-bezier(.2,.8,.2,1),opacity .6s ease .15s}
    .__rec-ripple.go{transform:scale(1.15);opacity:0}
    .__rec-cursor{position:fixed;z-index:2147483647;pointer-events:none;width:28px;height:28px;
      left:0;top:0;transform:translate(-4px,-2px);filter:drop-shadow(0 2px 3px rgba(0,0,0,.45))}
    .__rec-halo{position:fixed;z-index:2147483646;pointer-events:none;width:46px;height:46px;
      margin:-23px 0 0 -23px;border-radius:50%;background:rgba(255,214,0,.28);left:0;top:0}`;
  const add = () => {
    document.documentElement.appendChild(style);
    if (window.__recCursor) {
      const halo = document.createElement('div'); halo.className = '__rec-halo';
      const c = document.createElement('div'); c.className = '__rec-cursor';
      c.innerHTML = '<svg viewBox="0 0 24 24" width="28" height="28"><path d="M4 2l16 9.5-7 1.6-3.6 6.7z" fill="#fff" stroke="#111" stroke-width="1.6" stroke-linejoin="round"/></svg>';
      document.documentElement.append(halo, c);
      window.addEventListener('mousemove', e => {
        c.style.left = e.clientX + 'px'; c.style.top = e.clientY + 'px';
        halo.style.left = e.clientX + 'px'; halo.style.top = e.clientY + 'px';
      }, true);
    }
  };
  window.__rec = {
    ripple(x, y) {
      const r = document.createElement('div'); r.className = '__rec-ripple';
      r.style.left = x + 'px'; r.style.top = y + 'px';
      document.documentElement.appendChild(r);
      requestAnimationFrame(() => requestAnimationFrame(() => r.classList.add('go')));
      setTimeout(() => r.remove(), 900);
    }
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', add); else add();
})();
"""


async def record(spec_path):
    spec = yaml.safe_load(Path(spec_path).read_text())
    out = ROOT / spec["out"]
    out.parent.mkdir(parents=True, exist_ok=True)
    vw, vh = spec.get("viewport", [1440, 810])
    scale = spec.get("scale", 1.3333)
    mobile = spec.get("mobile", False)
    frames, marks = [], {}
    t0 = None
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path="/usr/bin/google-chrome",
                                          args=["--no-sandbox", "--hide-scrollbars"])
        ctx = await browser.new_context(viewport={"width": vw, "height": vh}, device_scale_factor=scale,
                                        is_mobile=mobile, has_touch=mobile,
                                        reduced_motion=spec.get("reduced_motion", "no-preference"),
                                        color_scheme=spec.get("color_scheme", "dark"))
        for k, v in (spec.get("local_storage") or {}).items():
            await ctx.add_init_script(f"try{{localStorage.setItem({json.dumps(k)},{json.dumps(v)})}}catch(e){{}}")
        await ctx.add_init_script(f"window.__recCursor={json.dumps(not mobile and spec.get("cursor", True))};" + OVERLAY_JS)
        if spec.get("fake_speech", True):
            await ctx.add_init_script(FAKE_SPEECH_JS)
        page = await ctx.new_page()
        await page.goto(spec["url"], wait_until="networkidle")
        for sel in spec.get("hide", []):
            await page.add_style_tag(content=f"{sel}{{display:none!important}}")
        cdp = await ctx.new_cdp_session(page)

        loop = asyncio.get_running_loop()
        stop = asyncio.Event()

        async def grab():
            nonlocal t0
            while not stop.is_set():
                # the clip is in document coordinates, so follow the scroll position
                pos = await cdp.send("Runtime.evaluate", {"expression": "[visualViewport.pageLeft, visualViewport.pageTop]",
                                                          "returnByValue": True})
                x, y = pos["result"]["value"]
                clip = {"x": x, "y": y, "width": vw, "height": vh, "scale": scale}
                r = await cdp.send("Page.captureScreenshot", {"format": "jpeg", "quality": 90,
                                                              "optimizeForSpeed": True, "clip": clip})
                ts = loop.time()
                if t0 is None:
                    t0 = ts
                frames.append((ts, r["data"]))

        grabber = asyncio.create_task(grab())
        while not frames:
            await asyncio.sleep(0.02)
        mouse = [vw / 2, vh / 2]
        if not mobile:
            await page.mouse.move(*mouse)

        async def centre(sel):
            loc = page.locator(sel).first
            await loc.scroll_into_view_if_needed()
            box = await loc.bounding_box()
            return loc, box["x"] + box["width"] / 2, box["y"] + box["height"] / 2

        async def ripple(x, y):
            if spec.get("ripples", True):
                await page.evaluate(f"window.__rec.ripple({x},{y})")

        async def glide(x, y, ms=650):
            steps = max(8, ms // 16)
            await page.mouse.move(x, y, steps=steps)
            mouse[:] = [x, y]

        for step in spec.get("steps", []):
            (kind, arg), = step.items()
            if kind == "wait":
                await page.wait_for_timeout(arg)
            elif kind == "tap":
                sel, after = (arg, 650) if isinstance(arg, str) else (arg["selector"], arg.get("after", 650))
                loc, x, y = await centre(sel)
                if isinstance(arg, dict) and arg.get("js"):
                    # the element is covered (e.g. by a tab bar): show the tap, press it directly
                    await ripple(x, y)
                    await loc.evaluate("e => e.click()")
                elif mobile:
                    await ripple(x, y)
                    await loc.tap()
                else:
                    await glide(x, y)
                    await page.wait_for_timeout(120)
                    await ripple(x, y)
                    await page.mouse.click(x, y)
                await page.wait_for_timeout(after)
            elif kind == "hover":
                _, x, y = await centre(arg)
                await glide(x, y)
            elif kind == "move":
                await glide(arg[0], arg[1], arg[2] if len(arg) > 2 else 650)
            elif kind == "type":
                loc = page.locator(arg["selector"]).first
                await loc.click()
                await loc.press_sequentially(arg["text"], delay=arg.get("delay", 80))
            elif kind == "scroll":
                y, ms = arg["y"], arg.get("ms", 1000)
                sel = arg.get("selector")
                await page.evaluate(
                    """([dy, ms, sel]) => new Promise(res => { const el = sel ? document.querySelector(sel) : null;
                       const s = el ? el.scrollTop : window.scrollY, t0 = performance.now();
                       const f = now => { const k = Math.min(1, (now - t0) / ms), e = k < .5 ? 2*k*k : 1 - Math.pow(-2*k + 2, 2) / 2;
                       el ? (el.scrollTop = s + dy * e) : window.scrollTo(0, s + dy * e); k < 1 ? requestAnimationFrame(f) : res(); }; requestAnimationFrame(f); })""",
                    [y, ms, sel])
            elif kind == "drag":
                # press on one element, glide to another, release: real mouse events, so HTML5 drag and drop fires
                _, x0, y0 = await centre(arg["from"])
                await glide(x0, y0)
                await page.mouse.down()
                _, x1, y1 = await centre(arg["to"])
                await glide(x1 + arg.get("dx", 0), y1 + arg.get("dy", 0), arg.get("ms", 900))
                await page.wait_for_timeout(150)
                await page.mouse.up()
                await page.wait_for_timeout(arg.get("after", 900))
            elif kind == "focus":
                await page.locator(arg).first.focus()
            elif kind == "eval":
                await page.evaluate(arg)
            elif kind == "press":
                await page.keyboard.press(arg)
            elif kind == "mark":
                marks[arg] = round(frames[-1][0] - t0, 3) if frames else 0.0
            else:
                raise ValueError(f"unknown step {kind}")
        await page.wait_for_timeout(spec.get("tail", 600))
        stop.set()
        await grabber
        end = frames[-1][0] + 1 / FPS
        await browser.close()

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        lines = []
        for i, (ts, data) in enumerate(frames):
            f = tmp / f"{i:05d}.jpg"
            f.write_bytes(base64.b64decode(data))
            nxt = frames[i + 1][0] if i + 1 < len(frames) else end
            lines.append(f"file '{f}'\nduration {max(nxt - ts, 1 / FPS):.4f}")
        lines.append(f"file '{tmp / f'{len(frames) - 1:05d}.jpg'}'")
        (tmp / "list.txt").write_text("\n".join(lines) + "\n")
        part = out.with_suffix(".part.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(tmp / "list.txt"),
                        "-vf", f"fps={FPS},scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p",
                        "-c:v", "libx264", "-crf", "16", "-preset", "veryfast", str(part)], check=True)
        part.replace(out)
    (out.with_suffix(".marks.json")).write_text(json.dumps(marks, indent=2))
    dur = end - t0 if frames else 0
    print(f"recorded {out.relative_to(ROOT)}: {len(frames)} frames, {dur:.1f}s, marks {marks}")


if __name__ == "__main__":
    for s in sys.argv[1:]:
        asyncio.run(record(s))
