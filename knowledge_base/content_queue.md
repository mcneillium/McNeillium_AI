# McNeillium AI — Content Queue
Generated: 2026-05-14 via WebSearch over the last 7 days (May 7-14)

5 ranked picks below. All reaction mode (default). Each has a hook
angle and suggested publish day. Pick what to produce first — none of
these have been generated as videos yet.

---

## #1 — Microsoft loses its OpenAI lock-in
**Suggested publish: Monday**
**Mode:** reaction (default)

**The story.** Microsoft and OpenAI amended their partnership last week:
Microsoft's license to OpenAI IP is now **non-exclusive**, and OpenAI
can serve products across **any cloud provider**. This is the biggest
re-shaping of the AI cloud market since the original Microsoft deal in
2019.

**Why it matters NOW.** This signals OpenAI prep for the next chapter
(post-IPO? cross-cloud distribution?), it ends Microsoft's privileged
position, and it opens GPT-5.5 to AWS / GCP / Oracle. Every dev who's
been frustrated by Azure-only access just got their wish.

**Hook angle.** "Microsoft just lost the only thing that made it
matter in AI."

**Title candidates:**
- "Microsoft Just Lost Its OpenAI Monopoly"
- "OpenAI Can Now Ship Anywhere — Here's Why That Hurts Microsoft"
- "The Microsoft / OpenAI Deal Quietly Ended"

**Cost estimate:** ~$2.10 (matches Phase 11 baseline)

---

## #2 — Sam Altman vs Musk: the trial testimony
**Suggested publish: Tuesday**
**Mode:** reaction

**The story.** Altman took the witness stand on May 12 in the
Musk v. OpenAI trial in Oakland, testifying for ~4 hours. Among the
fireworks: Altman claimed "Dario has accused me of many things,"
detailed Musk's exit from OpenAI ("the nonprofit was left for dead"),
and walked through the conversion-to-for-profit timeline.

**Why it matters NOW.** Live legal soap opera between the three most
important people in AI (Musk, Altman, Amodei). The Anthropic-OpenAI
feud is now in court records. Massive engagement signal — drama
stories outperform pure tech stories 3-5×.

**Hook angle.** "Altman just told the world what really happened with
Musk and Anthropic — under oath."

**Title candidates:**
- "Sam Altman Spent 4 Hours Under Oath. Here's What He Said."
- "Altman vs Musk vs Amodei — The Court Testimony Recap"
- "What Sam Altman Said About Dario Amodei in Court"

---

## #3 — Anthropic at $950 billion
**Suggested publish: Wednesday**
**Mode:** reaction

**The story.** Anthropic is reportedly in talks to raise $30-50B at a
**$950 billion valuation**. Annualised revenue is $30B run-rate, up
from $9B at the end of 2025. They're now bigger than every public AI
company except Nvidia.

**Why it matters NOW.** Two years ago Anthropic was a research lab.
Now it's the most valuable private company in tech history. The
revenue growth is genuinely unprecedented — this is the strongest
business story in AI.

**Hook angle.** "Anthropic just hit a valuation that makes OpenAI
look reasonably priced."

**Title candidates:**
- "Anthropic Is Worth $950 Billion. Read That Again."
- "How Anthropic Tripled Revenue in 12 Months"
- "The Anthropic Valuation Everyone Missed"

---

## #4 — Google is rebuilding Android around Gemini
**Suggested publish: Thursday**
**Mode:** reaction

**The story.** Google announced Gemini Intelligence will sit at the
**center of Android**, with the ability to move across apps,
understand on-screen context, and complete multi-step tasks (cart
building, reservations, scheduling). Sameer Samat: "We're transitioning
from an operating system to an intelligence system." This drops ahead
of Apple's WWDC AI reboot.

**Why it matters NOW.** First time a major mobile OS has been
fundamentally restructured around an LLM. Either this is the future
or it's the next Google Wave. Either way the take is needed.

**Hook angle.** "Google just admitted Android isn't an operating
system anymore."

**Title candidates:**
- "Android Is Now an AI Agent — Here's What That Means"
- "Google's Gemini-First Android Is a Bet Against Apple"
- "Android Becomes Agentic — Demo Footage Inside"

---

## #5 — Claude Code's new agent view
**Suggested publish: Friday**
**Mode:** reaction (developer angle)

**The story.** Anthropic shipped Claude Code's biggest UX update yet:
**agent view** plus the new `/goal` command and richer transcript
navigation. You can park a session, fork into a quick question, and
return — with peek-previews showing which sessions produced a PR.
Available now in Research Preview on Pro/Max/Team/Enterprise/API.

**Why it matters NOW.** This is the first agent-management UI that
actually feels usable. Direct shot at Cursor's "Composer" workflow and
Cognition's Devin. Friday slot because dev audiences engage Fri-Sat
more than mid-week.

**Hook angle.** "Claude Code just shipped the agent UI Cursor should
have built."

**Title candidates:**
- "Claude Code's New Agent View Is a Cursor Killer"
- "Anthropic Shipped the Agent UX Everyone Else Missed"
- "Try Claude Code's New `/goal` Command Right Now"

---

## Backup / overflow stories (not in top 5 but worth tracking)

- **OpenAI launches self-serve Ads Manager** — $2.5B target this year,
  $100B by 2030. Monetisation play, controversial with privacy crowd.
- **Anthropic + Google + Broadcom compute partnership** — infrastructure
  story, narrower dev appeal but big strategically.
- **Pentagon strikes deals with 8 Big Tech companies** (after shunning
  Anthropic) — government / safety angle.
- **Samsung AI Week 2026** kicks off May 11 — consumer electronics angle.
- **Microsoft Agent 365 + Copilot Cowork** — built with Anthropic /
  Claude, enterprise agent push. Worth a tool review.

## Daily research workflow

Each morning, run:

```
python utils/trend_researcher.py
```

That refreshes `knowledge_base/news_queue.json` with the top 5 stories
across Hacker News, Reddit (r/MachineLearning, r/LocalLLaMA, r/OpenAI,
r/Anthropic, r/singularity), and Hugging Face trending models.

Then ask Claude Code to produce one of them by name. The default mode
is now reaction — fast cuts, viral captions, Brian voice, ~$2/video.

## Cost-per-video baseline (from Phase 11)

| Service | Per news video |
|---|---:|
| ElevenLabs Brian voice | ~$1.15 (5-6K chars at 5-7 min) |
| fal.ai Kling 2-3 hero shots | $0.60 - $0.90 |
| AssemblyAI verification | ~$0.03 |
| Pixabay / FFmpeg / etc. | $0 |
| **Daily total** | **~$1.80 - $2.10** |

At 5 videos/week = **~$10/week, ~$45/month** in API fees, plus
ElevenLabs / AssemblyAI / fal.ai subscription baselines.
