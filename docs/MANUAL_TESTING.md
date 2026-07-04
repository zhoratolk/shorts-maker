# Manual verification

Automated tests cover deterministic building blocks (config, chunking, candidate merging, crop math, command building) — not the LLM-driven analysis passes or actual ffmpeg/Whisper execution. Verify those by hand before trusting the pipeline on a real multi-hour recording:

1. Get a short (2-3 min) sample video with a couple of clearly funny/interesting moments. Place it somewhere convenient, e.g. `test_video.mp4`.
2. Run `python scripts/setup.py`, confirm ffmpeg found and reported GPU/CPU device correct.
3. Copy `config.example.yaml` to `config.yaml`, point `input_dir`/`output_dir` at test folders, set `whisper.model: small` (faster for a quick check).
4. In Claude Code, run `/make-shorts test_video.mp4` with `analysis.use_subagents: true` and `analysis.require_approval: true`. Confirm:
   - Transcript cached under `transcripts/test_video.json`.
   - `work/test_video/CANDIDATES.md` lists timecodes landing on genuinely interesting moments.
   - Re-running `/make-shorts test_video.mp4` skips transcription (no Whisper re-run).
5. Approve one candidate, confirm `work/test_video/PLAN.json` has plausible trim points and a resolved (non-`auto`) `crop_style`.
6. Confirm rendered clip in `config.output_dir` is 1080x1920, plays back correctly, and (if `subtitles.enabled: true`) has readable, correctly-synced burned-in subtitles with no stray leading/trailing punctuation (commas/periods) sitting alone in a caption burst — check `subtitles.strip_punctuation: false` once too, to confirm the toggle actually restores it.
7. Re-run once with `analysis.use_subagents: false` and once with `analysis.require_approval: false` — confirm both toggles change behavior as expected.
8. Metadata (`config.metadata.enabled: true`): confirm a `.txt` lands in `config.output_dir` next to the rendered clip (not under `work/`), and that the title/caption reads like a hook from `docs/metadata-writing-ru.md`'s table, not "в этом видео я покажу..." — spot-check for leftover канцелярит/AI-tone phrasing from the ban list. If you approve 2+ candidates in one run, confirm their hooks use *different* formulas (see SKILL.md's hook rotation rule).
9. Audio cleanup (`audio.denoise` / `audio.loudnorm`, both default `true`): listen for reduced hiss/hum vs. a run with both set `false`, and confirm volume is consistent across clips from a source with uneven mic levels.
10. Effects (`effects.vignette` / `effects.grain_strength`, both default off): enable one clip's config with `vignette: true, grain_strength: 25`, confirm the rendered frame is visibly darkened at the edges and has visible grain, without the burned-in captions becoming unreadable.
11. Jump cuts (`jumpcuts.enabled: true`, needs a source with a genuine long pause — mid-sentence silence, dead air): confirm the rendered clip is visibly shorter than `end - start` in `CANDIDATES.md` by roughly the cut pause length, playback has no jarring audio pop at the splice point, and (if subtitles are on) no caption is dangling on a dropped word.
12. Visual pass (`visual.enabled: true` on a source where the game/topic changes partway through): confirm `work/test_video/frames/chunk_NNNN/game_context.txt` names the right game per chunk, and — if `visual.detect_visual_candidates: true` — that `CANDIDATES.md` includes at least one moment whose `reason` cites something only visible on screen (not paraphrasable from the transcript alone).
