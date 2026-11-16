"""Build self-playing HTML scenes from real artefacts, for record.py to film.

    python explainers/scenes/make_scenes.py

terminal: replays a captured command run (footage/<name>.json: [[seconds, line], ...])
          at its real pace, scaled to fit, showing only the lines asked for.
code:     a real source file in an editor view, syntax-highlighted, with chosen
          lines highlighted in turn and a slow scroll.
Pages land in explainers/scenes/out/ and are filmed from file:// URLs.
"""
import html
import json
from pathlib import Path

from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_for_filename

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
FOOT = HERE.parent / "footage"

BASE_CSS = """
html,body{margin:0;height:100%;background:#0d1117;color:#e6edf3;overflow:hidden}
body{font-family:'JetBrains Mono','DejaVu Sans Mono',monospace}
.win{position:absolute;inset:36px 48px;border-radius:14px;background:#0d1117;border:1px solid #30363d;
  box-shadow:0 30px 80px rgba(0,0,0,.6);overflow:hidden;display:flex;flex-direction:column}
.bar{height:44px;display:flex;align-items:center;gap:10px;padding:0 18px;background:#161b22;border-bottom:1px solid #30363d;
  font:500 17px Inter,'DejaVu Sans',sans-serif;color:#9da7b3}
.dot{width:13px;height:13px;border-radius:50%}
.bar .t{margin-left:14px}
"""

TERMINAL = """<!doctype html><html><head><meta charset="utf-8"><style>{css}
.term{{flex:1;padding:22px 28px;font-size:21px;line-height:1.5;overflow:hidden;white-space:pre}}
.p{{color:#7ee787}}.c{{color:#e6edf3}}.pass{{background:#2ea043;color:#fff;font-weight:700;padding:0 6px;border-radius:3px}}
.dim{{color:#8b949e}}.ok{{color:#7ee787;font-weight:700}}.cur{{display:inline-block;width:11px;height:24px;background:#e6edf3;vertical-align:-4px;animation:b 1s steps(1) infinite}}
@keyframes b{{50%{{opacity:0}}}}
</style></head><body><div class="win"><div class="bar"><span class="dot" style="background:#ff5f57"></span>
<span class="dot" style="background:#febc2e"></span><span class="dot" style="background:#28c840"></span><span class="t">{title}</span></div>
<div class="term" id="t"></div></div>
<script>
const prompt = {prompt}, cmd = {cmd}, lines = {lines}, total = {total};
const t = document.getElementById('t');
const esc = s => s.replace(/[&<>]/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;'}}[c]));
function fmt(l) {{
  if (l.startsWith('PASS ')) return '<span class="pass">PASS</span> <span class="dim">' + esc(l.slice(5)) + '</span>';
  if (/^(Tests|Test Suites):/.test(l)) return esc(l).replace(/(\\d+ passed)/, '<span class="ok">$1</span>');
  return esc(l);
}}
let shown = '<span class="p">' + esc(prompt) + '</span> ';
const render = (extra) => {{ t.innerHTML = shown + (extra || '') + '<span class="cur"></span>'; t.scrollTop = t.scrollHeight; }};
render();
let i = 0;
setTimeout(function type() {{
  if (i < cmd.length) {{ shown += esc(cmd[i++]); render(); setTimeout(type, 55); return; }}
  shown += '\\n'; render();
  const start = performance.now();
  lines.forEach(([at, l]) => setTimeout(() => {{ shown += fmt(l) + '\\n'; render(); }}, 400 + at * total * 1000));
}}, 700);
</script></body></html>"""

CODE = """<!doctype html><html><head><meta charset="utf-8"><style>{css}
{pyg}
.code{{flex:1;overflow:hidden;position:relative}}
.scroller{{position:absolute;left:0;right:0;top:0;transition:transform {scroll_ms}ms cubic-bezier(.45,0,.2,1)}}
table.highlighttable{{border-spacing:0;font-size:21px;line-height:1.55}}
.linenos{{color:#6e7681;text-align:right;padding:0 18px 0 22px;user-select:none}}
.linenos pre,.code pre{{margin:0}}
td.code{{padding:0 24px 0 0}}
.hl-band{{position:absolute;left:0;right:0;background:rgba(124,92,255,.18);border-left:4px solid #8b7bff;
  transition:top .6s cubic-bezier(.45,0,.2,1),height .6s cubic-bezier(.45,0,.2,1),opacity .4s;opacity:0}}
.highlight{{background:transparent}}
.tabs{{display:flex;gap:2px;background:#010409;padding:0 10px}}
.tab{{padding:10px 18px;font:500 16px Inter,'DejaVu Sans',sans-serif;color:#9da7b3;background:#010409}}
.tab.on{{color:#e6edf3;background:#0d1117;border-top:2px solid #8b7bff}}
</style></head><body><div class="win"><div class="bar"><span class="dot" style="background:#ff5f57"></span>
<span class="dot" style="background:#febc2e"></span><span class="dot" style="background:#28c840"></span><span class="t">{repo}</span></div>
<div class="tabs"><div class="tab on">{fname}</div></div>
<div class="code"><div class="scroller" id="s"><div class="hl-band" id="b"></div>{body}</div></div></div>
<script>
const steps = {steps};
const s = document.getElementById('s'), b = document.getElementById('b');
const lh = () => {{ const r = document.querySelector('td.code pre'); return r.getBoundingClientRect().height / {nlines}; }};
steps.forEach(st => setTimeout(() => {{
  const h = lh();
  if (st.scroll !== undefined) s.style.transform = `translateY(${{-st.scroll * h}}px)`;
  if (st.lines) {{ b.style.top = ((st.lines[0] - {first}) * h) + 'px'; b.style.height = ((st.lines[1] - st.lines[0] + 1) * h) + 'px'; b.style.opacity = 1; }}
  if (st.clear) b.style.opacity = 0;
}}, st.at * 1000));
</script></body></html>"""


def terminal(name, title, prompt, cmd, source, keep=("PASS ", "Test Suites:", "Tests:", "Time:"), seconds=5.0):
    data = json.loads((FOOT / source).read_text())
    last = data[-1][0] or 1
    lines = [[at / last, l] for at, l in data if l.startswith(keep)]
    page = TERMINAL.format(css=BASE_CSS, title=html.escape(title), prompt=json.dumps(prompt), cmd=json.dumps(cmd),
                           lines=json.dumps(lines), total=seconds)
    (OUT / f"{name}.html").write_text(page)


def code(name, path, repo, first, last, steps, scroll_ms=2200):
    src = Path(path).read_text().splitlines()[first - 1:last]
    fmt = HtmlFormatter(style="github-dark", linenos="table", linenostart=first, nowrap=False)
    body = highlight("\n".join(src) + "\n", get_lexer_for_filename(path), fmt)
    page = CODE.format(css=BASE_CSS, pyg=fmt.get_style_defs(".highlight"), body=body, repo=html.escape(repo),
                       fname=html.escape(Path(path).name), steps=json.dumps(steps), nlines=len(src), first=first,
                       scroll_ms=scroll_ms)
    (OUT / f"{name}.html").write_text(page)


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    terminal("voice-tests", "ai-powered-aac-app: npx jest", "paul@voice:~/ai-powered-aac-app$", "npx jest",
             "voice-tests.json", seconds=5.5)
    code("voice-predictor", "/home/claude/ai-powered-aac-app/src/services/prediction/predictor.js",
         "ai-powered-aac-app / src / services / prediction", 1, 60,
         [{"at": 1.2, "lines": [2, 3]}, {"at": 3.6, "lines": [5, 8]}, {"at": 6.0, "lines": [10, 13]},
          {"at": 8.6, "lines": [17, 18]}, {"at": 11.0, "clear": True, "scroll": 30},
          {"at": 12.4, "lines": [51, 59]}])
    terminal("crm-tests", "custom-crm: npm test", "paul@crm:~/custom-crm$", "npm test", "crm-tests.json",
             keep=("✓ ", "Tests "), seconds=6.5)
    code("crm-core", "/home/claude/custom-crm/packages/core/src/index.ts", "custom-crm / packages / core / src", 30, 48,
         [{"at": 0.8, "lines": [30, 31]}, {"at": 3.4, "lines": [36, 44]}])
    code("crm-pool", "/home/claude/custom-crm/apps/server/src/db.ts", "custom-crm / apps / server / src", 1, 27,
         [{"at": 0.8, "lines": [11, 13]}, {"at": 3.6, "lines": [15, 17]}, {"at": 6.2, "lines": [22, 24]}])
    print("scenes:", ", ".join(p.name for p in sorted(OUT.glob("*.html"))))
