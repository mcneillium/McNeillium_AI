# Phase 19 — skipped / partial features

This file is appended to whenever a Phase 19 step is skipped or shipped at
reduced fidelity. Format:

## Step N: <name>
- **Status**: skipped | partial
- **Reason**: ...
- **Followup**: what would be needed to fully ship

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
