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


def _queue_videos():
    """Phase 18: list locally-rendered videos waiting for approval.

    We treat any output/videos/_*.mp4 that's NOT in
    output/videos/_uploaded.txt as queued for review.
    """
    vdir = PROJECT_ROOT / "output" / "videos"
    if not vdir.exists():
        return []
    uploaded_log = vdir / "_uploaded.txt"
    uploaded = set()
    if uploaded_log.exists():
        uploaded = set(uploaded_log.read_text(encoding="utf-8").splitlines())
    out = []
    for p in sorted(vdir.glob("_*.mp4"), key=lambda x: -x.stat().st_mtime):
        if p.name in uploaded:
            continue
        size_mb = p.stat().st_size / (1024 * 1024)
        # Probe duration via ffprobe
        try:
            import subprocess
            r = subprocess.run(
                ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                 "-of", "csv=p=0", str(p)],
                capture_output=True, text=True,
            )
            dur_s = float(r.stdout.strip() or 0)
        except Exception:
            dur_s = 0
        out.append({
            "name": p.name,
            "path": str(p.resolve()).replace("\\", "/"),
            "size_mb": round(size_mb, 1),
            "duration_s": int(dur_s),
        })
    return out


def _cost_snapshot():
    """Read this month's cost-tracker CSV and return per-service totals."""
    today = datetime.datetime.now()
    p = (PROJECT_ROOT / "knowledge_base" / "costs"
         / f"{today.year}-{today.month:02d}.csv")
    if not p.exists():
        return None
    import csv
    totals = {"elevenlabs": 0.0, "fal_kling": 0.0, "assemblyai": 0.0}
    today_total = 0.0
    today_iso = today.date().isoformat()
    with open(p, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            svc = row.get("service", "")
            try:
                c = float(row.get("cost_usd", "0"))
            except Exception:
                c = 0
            if svc in totals:
                totals[svc] += c
            if row.get("timestamp", "")[:10] == today_iso:
                today_total += c
    return {"by_service": totals,
            "today": today_total,
            "month": sum(totals.values())}


def build_html():
    videos = _latest_videos()
    queue = _queue_videos()
    cost = _cost_snapshot()
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

    # Phase 18: Approval queue HTML — local file:// links so user can
    # preview right in the browser, plus copy-paste commands for the
    # approve / reject actions.
    queue_html = ""
    for v in queue:
        dur = f"{v['duration_s'] // 60}m {v['duration_s'] % 60:02d}s"
        queue_html += f"""
        <div class="qv">
          <video controls preload="metadata" width="100%"
                 src="file:///{v['path']}"></video>
          <div class="qv-meta">
            <strong>{v['name']}</strong>
            <span class="dim">{v['size_mb']:.1f} MB · {dur}</span>
          </div>
          <pre class="qv-cmd">python utils/youtube_upload.py --video "{v['path']}" --script output/scripts/latest.json --privacy unlisted
# or reject:  move "{v['path']}" output/videos/_archive/</pre>
        </div>"""
    if not queue:
        queue_html = "<em>No videos queued for review.</em>"

    # Cost snapshot HTML
    if cost:
        cost_html = (
            f"<div class='score' style='font-size:32px'>"
            f"${cost['today']:.2f}<small style='font-size:14px;"
            f"color:var(--muted);'> today</small></div>"
            f"<div class='dim'>Month: ${cost['month']:.2f}  &nbsp;|&nbsp;  "
            f"ElevenLabs ${cost['by_service']['elevenlabs']:.2f}, "
            f"Kling ${cost['by_service']['fal_kling']:.2f}, "
            f"AssemblyAI ${cost['by_service']['assemblyai']:.2f}</div>"
        )
    else:
        cost_html = "<em>No cost snapshot yet.</em>"

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
  .dim {{ color: var(--muted); font-size: 12px; }}
  .qv {{ background: rgba(255,255,255,0.02); border: 1px solid var(--border);
         border-radius: 10px; padding: 12px; margin-bottom: 14px; }}
  .qv video {{ max-width: 100%; border-radius: 6px; background: black; }}
  .qv-meta {{ display: flex; justify-content: space-between;
              padding: 8px 0; align-items: center; }}
  .qv-cmd {{ font-size: 11px; user-select: all; cursor: text; }}
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
    <h2>Cost month-to-date</h2>
    {cost_html}
  </section>
  <section class="panel" style="grid-column: 1 / -1;">
    <h2>Approval queue — local renders awaiting your sign-off</h2>
    {queue_html}
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
