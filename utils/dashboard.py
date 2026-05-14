#!/usr/bin/env python3
"""
McNeillium_AI — Agent 51: Dashboard Builder

Generates a single-page HTML dashboard at output/dashboard.html showing
channel health at a glance:

  - Queue status (next 4 upcoming slots from calendar.md)
  - Last 10 videos with view counts (performance_data.json)
  - Latest QC report (knowledge_base/reviews/qc_report.md)
  - Recent retention killers
  - Audience questions → future video ideas

No HTTP server — open the HTML file in a browser. Uses Alpine.js via
CDN for collapsible sections; no build step. Open the file directly
with `start output/dashboard.html` on Windows.
"""

import argparse
import datetime
import io
import json
import re
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower().replace("-", "") != "utf8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8",
                                  errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUT = PROJECT_ROOT / "output" / "dashboard.html"
PERF = PROJECT_ROOT / "knowledge_base" / "performance_data.json"
CAL = PROJECT_ROOT / "knowledge_base" / "calendar.md"
QC = PROJECT_ROOT / "knowledge_base" / "reviews" / "qc_report.md"
KILLERS = PROJECT_ROOT / "knowledge_base" / "retention_killers.md"
INSIGHTS = PROJECT_ROOT / "knowledge_base" / "audience_insights.md"


def _read(path):
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _latest_videos(limit=10):
    if not PERF.exists():
        return []
    try:
        data = json.loads(PERF.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data = [data]
    except Exception:
        return []
    if not data:
        return []
    latest = data[-1].get("videos", [])
    out = []
    for v in latest[:limit]:
        stats = v.get("stats") or {}
        out.append({
            "title": v.get("title", "?"),
            "video_id": v.get("video_id", ""),
            "views": stats.get("views", 0),
            "avd_s": stats.get("averageViewDuration", 0),
        })
    return out


def _calendar_entries():
    text = _read(CAL)
    return re.findall(r"^- \*\*([^*]+)\*\* — (.*)$", text, re.M)


def _retention_killer_blocks(limit=4):
    text = _read(KILLERS)
    blocks = re.split(r"^## ", text, flags=re.M)[1:]
    return blocks[-limit:][::-1]


def _audience_questions(limit=8):
    text = _read(INSIGHTS)
    return re.findall(r"> \*\*question\*\* — _([^_]+)_", text)[-limit:][::-1]


def _qc_snapshot():
    text = _read(QC)
    score = re.search(r"Overall score: \*\*(\d+(?:\.\d+)?)/10\*\*", text)
    return {
        "score": float(score.group(1)) if score else None,
        "text": text or "_no QC report yet_",
    }


def build_html():
    videos = _latest_videos()
    cal = _calendar_entries()
    killers = _retention_killer_blocks()
    questions = _audience_questions()
    qc = _qc_snapshot()
    when = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    rows = "".join(
        f"<tr><td>{v['title']}</td><td>{v['views']}</td>"
        f"<td>{v['avd_s']}s</td>"
        f"<td><a href='https://youtu.be/{v['video_id']}' target='_blank'>watch</a></td></tr>"
        for v in videos
    ) or "<tr><td colspan='4'><em>no analytics yet</em></td></tr>"

    cal_html = "".join(
        f"<li><b>{day}</b> — {topic}</li>"
        for day, topic in cal
    ) or "<li><em>run content_scheduler.py calendar</em></li>"

    killers_html = "".join(
        f"<details><summary>{b.splitlines()[0]}</summary>"
        f"<pre>{('## ' + b).strip()}</pre></details>"
        for b in killers
    ) or "<em>no retention drops logged yet</em>"

    questions_html = "".join(
        f"<li>{q}</li>" for q in questions
    ) or "<li><em>no audience questions yet</em></li>"

    qc_score = qc["score"] if qc["score"] is not None else "—"
    qc_class = ("good" if qc["score"] and qc["score"] >= 8
                else "warn" if qc["score"] else "")

    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>McNeillium_AI Dashboard</title>
<style>
  :root {{
    --bg: #0a0e18; --panel: #131826; --accent: #58a6ff;
    --muted: #95a3b6; --text: #e6edf3; --good: #7ee787; --warn: #ffa657;
    --border: #1f2735;
  }}
  body {{ margin: 0; background: var(--bg); color: var(--text);
         font-family: -apple-system, BlinkMacSystemFont, Segoe UI, Helvetica, sans-serif; }}
  header {{ padding: 24px 36px; border-bottom: 1px solid var(--border); }}
  h1 {{ margin: 0; font-size: 22px; }}
  h1 span {{ color: var(--accent); }}
  main {{ display: grid; grid-template-columns: 1fr 1fr;
          gap: 24px; padding: 24px 36px; }}
  .panel {{ background: var(--panel); border: 1px solid var(--border);
            border-radius: 12px; padding: 20px; }}
  .panel h2 {{ margin-top: 0; font-size: 15px;
               color: var(--muted); text-transform: uppercase;
               letter-spacing: 0.06em; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
  th, td {{ padding: 8px 10px; text-align: left;
            border-bottom: 1px solid var(--border); }}
  th {{ color: var(--muted); font-weight: 500; }}
  a {{ color: var(--accent); text-decoration: none; }}
  ul {{ margin: 0; padding-left: 20px; line-height: 1.6; }}
  details {{ margin: 8px 0; }}
  summary {{ cursor: pointer; color: var(--muted); }}
  pre {{ font-size: 12px; color: var(--text); white-space: pre-wrap;
         background: rgba(255, 255, 255, 0.02); padding: 8px;
         border-radius: 6px; }}
  .score {{ font-size: 48px; font-weight: 700; }}
  .score.good {{ color: var(--good); }}
  .score.warn {{ color: var(--warn); }}
  footer {{ color: var(--muted); font-size: 12px;
            padding: 12px 36px; border-top: 1px solid var(--border); }}
</style>
</head>
<body>
<header>
  <h1>McNeillium_<span>AI</span> dashboard</h1>
</header>
<main>
  <section class="panel">
    <h2>Latest QC score</h2>
    <div class="score {qc_class}">{qc_score}<small style="font-size:18px;color:var(--muted);">/10</small></div>
    <details><summary>Full QC report</summary><pre>{qc['text']}</pre></details>
  </section>
  <section class="panel">
    <h2>Upcoming slots</h2>
    <ul>{cal_html}</ul>
  </section>
  <section class="panel" style="grid-column: 1 / -1;">
    <h2>Last 10 uploads — performance</h2>
    <table>
      <thead><tr><th>Title</th><th>Views</th><th>AVD</th><th></th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </section>
  <section class="panel">
    <h2>Retention killers (recent)</h2>
    {killers_html}
  </section>
  <section class="panel">
    <h2>Audience questions → topic seeds</h2>
    <ul>{questions_html}</ul>
  </section>
</main>
<footer>Generated {when} — refresh by re-running <code>python utils/dashboard.py</code></footer>
</body>
</html>"""
    return html


def run():
    html = build_html()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    print(f"📊 Dashboard → {OUT}")
    return True


def main():
    p = argparse.ArgumentParser()
    args = p.parse_args()
    ok = run()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
