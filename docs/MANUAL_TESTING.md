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
6. Confirm rendered clip in `config.output_dir` is 1080x1920, plays back correctly, and (if `subtitles.enabled: true`) has readable, correctly-synced burned-in subtitles.
7. Re-run once with `analysis.use_subagents: false` and once with `analysis.require_approval: false` — confirm both toggles change behavior as expected.
