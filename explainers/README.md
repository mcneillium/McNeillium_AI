# Explainers of Paul's own work

Short (1 to 2 minute) narrated explainers of Paul McNeill's projects and
research, filmed from the live site, paulmartinmcneill.com. This is separate
from the daily news pipeline: no stock footage, no generated imagery, and every
fact comes from the site or its public repositories.

| Spec | Video |
|---|---|
| `specs/01-voice.yaml` | Voice, the AAC app that explains its predictions |
| `specs/02-river.yaml` | River flood warnings without the weather forecast |
| `specs/03-drug.yaml` | Why most of cancer drug response stays unexplained |
| `specs/04-method.yaml` | Six rules for machine learning research you can check |
| `specs/05-voice-site.yaml` | A portfolio you can listen to and talk to |
| `specs/06-lab.yaml` | Four AI demos in one web page |

## Making one

1. Write a spec: title card, segments (narration text plus shots), end card,
   YouTube metadata. A shot is a page (`url`, `focus` selector, `zoom`,
   optional `actions`), an `image`, or a text `card`.
2. Narration: one MP3 per segment in `work/<slug>/audio/NN.mp3`. With
   `ELEVENLABS_API_KEY` set, `--step audio` makes them.
3. `python explainers/build.py explainers/specs/<slug>.yaml` takes the
   screenshots, renders one file per scene, joins them, times captions to
   the speech and burns them in.
4. `python explainers/package.py <slug>` writes `output/<slug>/`: the video,
   an SRT track, a thumbnail and `youtube.json` with privacy `private`.

Needs Python 3, Playwright with Chrome, ffmpeg with libass, and PyYAML.

## Rules

- Facts only from the site or the public repositories. Research videos say
  the work has not been peer reviewed.
- Third person: the narrator is an AI voice (ElevenLabs) and every
  description says it is not Paul's voice.
- Check each clip with speech-to-text and look at the frames before
  packaging.
- Upload is manual and private first. Paul watches, then publishes.
