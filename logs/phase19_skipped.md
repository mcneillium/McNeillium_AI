# Phase 19 — skipped / partial features

This file is appended to whenever a Phase 19 step is skipped or shipped at
reduced fidelity. Format:

## Step N: <name>
- **Status**: skipped | partial
- **Reason**: ...
- **Followup**: what would be needed to fully ship

## Step 5: L/J cuts — partial
- **Status**: partial
- **Reason**: Pipeline architecture has continuous narration audio + beat
  visuals — there's no parallel diegetic audio to L/J-cut against. Helper
  ships (utils/editorial_cuts.py) and produces a per-boundary cut plan,
  but `generate_video.py`'s 1500-line beat assembler isn't refactored to
  apply visual offsets at section boundaries.
- **What ships**: choose_cut_type(), apply_section_cut_offsets(),
  shift_video_only(). CLI generates a plan to knowledge_base/reviews/cut_plan.json.
- **Followup**: Step needs to land inside `generate_video.py`'s section-clip
  builder — when joining clip[i] to clip[i+1], shift the cut point by
  `plan[i+1].visual_offset_s`. Risk: changes to the central assembly path
  can break the entire render. Recommend a feature flag.

## Step 4: Lottie pipeline — partial (pivot)
- **Status**: partial
- **Reason**: Python `lottie` 0.7.2 only exports JSON / SVG / HTML / TGS;
  no direct MP4 or PNG-sequence exporter. Building a full Lottie render
  loop would require cairosvg + custom keyframe-aware text substitution
  + FFmpeg-side image2-sequence assembly — bigger than one step.
- **What ships instead**: utils/motion_graphics.py with FFmpeg-native
  `lower_third()`, `title_card()`, `logo_reveal()`, `composite()`. Same
  visible outcome (animated overlays) without the Lottie dependency. All
  three render to MOV-with-alpha (qtrle/argb) and composite cleanly.
- **Followup**: If brand-specific Lottie templates from LottieFiles are
  needed, add cairosvg + render-loop in a follow-up. Also: Visual
  Director integration (auto-call lower_third when person photo cards
  appear) deferred to Step 10.

## Step 3: Coverr — skipped
- **Status**: skipped
- **Reason**: Coverr has no public API; the integration would require HTML
  scraping which breaks the moment they redesign. Pexels + Pixabay + Pixabay-AI
  cover the same use case with stable APIs. Diversity bonus in the scorer
  already biases toward non-Pixabay results.
- **Followup**: If Coverr is materially better for hero shots, add a small
  Selenium/Playwright fetcher behind a feature flag.

## Step 2: yt-dlp real footage — partial
- **Status**: partial — module ships, no live download verified
- **Reason**: yt-dlp + automated YouTube downloading is in tension with
  YouTube's ToS. Module defaults to a manual `--from-list` workflow with
  a verified-channel whitelist and 15s cap, but no test download was
  attempted from this session. Smoke test exercised import + shot-entry
  builder without network calls.
- **Followup**: User should hand-curate a JSON spec for the next video
  and run `python utils/real_footage_collector.py --from-list <spec>`
  once before depending on it in the main pipeline. Also: the Visual
  Director was NOT modified to splice real_footage shots into its shot
  list — that integration is left for a future step (would need to land
  in `utils/visual_director*.py` if/when present).
