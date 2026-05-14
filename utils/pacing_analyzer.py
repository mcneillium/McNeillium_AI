#!/usr/bin/env python3
"""
McNeillium AI — Pacing Analyzer (Phase 16, Agent 31)

Pre-render analysis of the script + estimated audio durations. Flags
sections that will drag, sections that race past too fast, sections
without emotional beats, and gaps where the visuals don't change.

Inputs:
  output/scripts/latest.json
  output/shot_list.json     (optional — used for visual-change checks)
  output/audio/latest_words_verified.json (optional — when available
                                            real word timestamps drive
                                            wpm; otherwise we estimate)

Output:
  knowledge_base/reviews/pacing_report.json
  knowledge_base/reviews/pacing_report.md

Heuristic thresholds:
  - WPM < 150 → too slow
  - WPM > 250 → too fast (Brian sounds rushed)
  - Visual change gap > 8s → static section, viewer disengages
  - Section duration > 90s without any hook phrase → "earn the next
    second" violation

Auto-tighten (utils.pacing_analyzer.tighten_section_text):
  Removes filler phrases ("you know", "basically", "essentially",
  "as I was saying", "in other words", "kind of", "sort of",
  "really", "literally"). Returns (tightened_text, removed_count).
"""

import argparse
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
SCRIPT_PATH = PROJECT_ROOT / "output" / "scripts" / "latest.json"
SHOT_LIST_PATH = PROJECT_ROOT / "output" / "shot_list.json"
VERIFIED_WORDS = PROJECT_ROOT / "output" / "audio" / "latest_words_verified.json"
REPORT_DIR = PROJECT_ROOT / "knowledge_base" / "reviews"
REPORT_JSON = REPORT_DIR / "pacing_report.json"
REPORT_MD = REPORT_DIR / "pacing_report.md"

# wpm thresholds
WPM_SLOW = 150
WPM_FAST = 250
VISUAL_GAP_S = 8.0
HOOK_INTERVAL_S = 60.0

FILLER_PATTERNS = [
    re.compile(r"\byou know,?\s*", re.I),
    re.compile(r"\bbasically,?\s*", re.I),
    re.compile(r"\bessentially,?\s*", re.I),
    re.compile(r"\bas i was saying,?\s*", re.I),
    re.compile(r"\bin other words,?\s*", re.I),
    re.compile(r"\bkind of,?\s*", re.I),
    re.compile(r"\bsort of,?\s*", re.I),
    re.compile(r"\b(?:really|literally|honestly|actually) really,?\s*", re.I),
    re.compile(r"\bit'?s? worth noting that,?\s*", re.I),
    re.compile(r"\bif you will,?\s*", re.I),
    re.compile(r"\bif that makes sense,?\s*", re.I),
    re.compile(r"\bat the end of the day,?\s*", re.I),
]

HOOK_PHRASES = re.compile(
    r"\b(here'?s the (wild|crazy|interesting|smartest|biggest) part|"
    r"but here'?s the thing|but here'?s why|"
    r"and that'?s where it gets|"
    r"here'?s my take|i'?ll tell you the part|"
    r"watch this|watch what happens|"
    r"and this is the part nobody|"
    r"now here'?s what|the catch is)\b",
    re.I,
)


# ─── WPM estimation ─────────────────────────────────────────────

def _section_word_counts(script):
    """Return [(section_id, word_count, narration), ...]."""
    out = []
    for sec in script.get("sections", []):
        sid = sec.get("id", "")
        narration = sec.get("narration", "")
        words = len(re.findall(r"[A-Za-z][A-Za-z'-]*", narration))
        out.append((sid, words, narration))
    return out


def _section_durations_from_words(script, total_dur_s=None):
    """Estimate per-section duration from character counts (mirrors
    generate_video.py's allocation). If total_dur_s is None we use
    ~2.5 wps to estimate."""
    sections = script.get("sections", [])
    chars = [len(s.get("narration", "")) for s in sections]
    total_chars = sum(chars) or 1
    if total_dur_s is None:
        total_words = sum(
            len(re.findall(r"\w+", s.get("narration", "")))
            for s in sections
        )
        total_dur_s = max(1.0, total_words / 2.5)
    intro_outro = 7.0
    content = max(1.0, total_dur_s - intro_outro)
    durs = [(c / total_chars) * content for c in chars]
    return [(s.get("id"), d) for s, d in zip(sections, durs)]


# ─── Visual gap detector ────────────────────────────────────────

def _visual_gap_seconds(shot_list, section_id):
    """Compute the longest contiguous gap without a visual change in a section.

    If the section has N beats summing to T seconds, longest single
    beat duration is the gap.
    """
    if not shot_list:
        return 0.0
    for sec in shot_list.get("sections", []):
        if sec.get("section_id") != section_id:
            continue
        shots = sec.get("shots", [])
        if not shots:
            return 0.0
        durs = [float(s.get("duration", 5)) for s in shots]
        return max(durs)
    return 0.0


# ─── Per-section scoring ────────────────────────────────────────

def score_section(sid, narration, duration_s, visual_gap_s):
    """Return dict of pacing diagnostics for one section."""
    words = len(re.findall(r"[A-Za-z][A-Za-z'-]*", narration))
    wpm = (words / max(0.1, duration_s)) * 60
    hooks = len(HOOK_PHRASES.findall(narration))
    issues = []
    if wpm < WPM_SLOW:
        issues.append(f"too slow ({wpm:.0f} wpm)")
    elif wpm > WPM_FAST:
        issues.append(f"too fast ({wpm:.0f} wpm)")
    if visual_gap_s > VISUAL_GAP_S:
        issues.append(f"static visual ({visual_gap_s:.1f}s without change)")
    if duration_s > HOOK_INTERVAL_S and hooks == 0:
        issues.append(f"no hook phrase in {duration_s:.0f}s section")
    return {
        "section_id": sid,
        "duration_s": round(duration_s, 1),
        "words": words,
        "wpm": round(wpm, 0),
        "visual_gap_s": round(visual_gap_s, 1),
        "hooks": hooks,
        "issues": issues,
        "ok": len(issues) == 0,
    }


# ─── Auto-tighten ───────────────────────────────────────────────

def tighten_section_text(text):
    """Strip filler phrases. Returns (tightened, removed_count)."""
    removed = 0
    for pat in FILLER_PATTERNS:
        text, n = pat.subn("", text)
        removed += n
    # collapse double spaces created by removal
    text = re.sub(r"\s{2,}", " ", text).strip()
    return text, removed


def tighten_script(script):
    """Walk all sections and return a tightened script + total removed count."""
    out_script = dict(script)
    out_script["sections"] = []
    total_removed = 0
    for sec in script.get("sections", []):
        new_sec = dict(sec)
        new_sec["narration"], removed = tighten_section_text(
            sec.get("narration", ""))
        new_sec["narration_original_chars"] = len(sec.get("narration", ""))
        new_sec["narration_tightened_chars"] = len(new_sec["narration"])
        new_sec["fillers_removed"] = removed
        total_removed += removed
        out_script["sections"].append(new_sec)
    return out_script, total_removed


# ─── Main ──────────────────────────────────────────────────────

def run(script_path, shot_list_path, verified_words_path, write=True):
    if not Path(script_path).exists():
        print(f"❌ Script not found: {script_path}")
        return False
    script = json.loads(Path(script_path).read_text(encoding="utf-8"))
    shot_list = None
    if Path(shot_list_path).exists():
        try:
            shot_list = json.loads(
                Path(shot_list_path).read_text(encoding="utf-8"))
        except Exception:
            shot_list = None

    # Total duration: if verified words exist, use them
    total_dur_s = None
    if Path(verified_words_path).exists():
        try:
            d = json.loads(
                Path(verified_words_path).read_text(encoding="utf-8"))
            words = d.get("words", [])
            if words:
                last = words[-1]
                total_dur_s = (float(last["offset_ms"])
                               + float(last["duration_ms"])) / 1000.0
        except Exception:
            total_dur_s = None

    durations = _section_durations_from_words(script, total_dur_s)
    flagged = []
    healthy = []
    diagnostics = []

    for sid, dur in durations:
        sec = next((s for s in script.get("sections", [])
                    if s.get("id") == sid), None)
        if not sec:
            continue
        narration = sec.get("narration", "")
        gap = _visual_gap_seconds(shot_list, sid)
        diag = score_section(sid, narration, dur, gap)
        diagnostics.append(diag)
        if diag["ok"]:
            healthy.append(sid)
        else:
            flagged.append(diag)

    avg_wpm = sum(d["wpm"] for d in diagnostics) / max(1, len(diagnostics))
    pacing_score = 10
    pacing_score -= len(flagged) * 1.0
    pacing_score = max(0, min(10, pacing_score))

    print(f"⏱  Pacing Analyzer — {len(diagnostics)} sections")
    print(f"   total est duration: "
          f"{sum(d['duration_s'] for d in diagnostics):.0f}s")
    print(f"   avg wpm: {avg_wpm:.0f}")
    print(f"   flagged: {len(flagged)} of {len(diagnostics)}")
    for d in diagnostics:
        flag = "✅" if d["ok"] else "⚠️ "
        issues = "; ".join(d["issues"]) if d["issues"] else "ok"
        print(f"     {flag} {d['section_id']:14s} "
              f"{d['duration_s']:5.1f}s  {d['wpm']:.0f} wpm — {issues}")
    print(f"   pacing score: {pacing_score:.1f}/10")

    if write:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        REPORT_JSON.write_text(json.dumps({
            "average_wpm": round(avg_wpm, 1),
            "pacing_score": pacing_score,
            "sections": diagnostics,
        }, indent=2), encoding="utf-8")
        # Markdown
        lines = [f"# Pacing report — {script.get('title','(untitled)')}", "",
                 f"- Total est duration: "
                 f"{sum(d['duration_s'] for d in diagnostics):.0f}s",
                 f"- Average wpm: {avg_wpm:.0f}",
                 f"- Pacing score: **{pacing_score:.1f}/10**",
                 "",
                 "## Section diagnostics", ""]
        lines.append("| section | dur | wpm | gap | hooks | issues |")
        lines.append("|---|---:|---:|---:|---:|---|")
        for d in diagnostics:
            issues = ", ".join(d["issues"]) if d["issues"] else "ok"
            lines.append(
                f"| {d['section_id']} | {d['duration_s']:.1f}s | "
                f"{d['wpm']:.0f} | {d['visual_gap_s']:.1f}s | "
                f"{d['hooks']} | {issues} |"
            )
        REPORT_MD.write_text("\n".join(lines), encoding="utf-8")
        print(f"   📝 → {REPORT_MD}")
    return pacing_score >= 7


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--script", default=str(SCRIPT_PATH))
    p.add_argument("--shot-list", default=str(SHOT_LIST_PATH))
    p.add_argument("--verified", default=str(VERIFIED_WORDS))
    p.add_argument("--tighten", action="store_true",
                   help="Auto-tighten filler phrases (overwrites latest.json)")
    args = p.parse_args()

    if args.tighten:
        script = json.loads(Path(args.script).read_text(encoding="utf-8"))
        tightened, removed = tighten_script(script)
        Path(args.script).write_text(
            json.dumps(tightened, indent=2), encoding="utf-8")
        print(f"✂️  Tightened script — {removed} filler phrases removed")

    ok = run(args.script, args.shot_list, args.verified)
    sys.exit(0 if ok else 2)


if __name__ == "__main__":
    main()
