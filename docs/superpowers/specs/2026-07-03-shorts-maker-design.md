# shorts-maker — design

## Purpose

A Claude Code skill + script toolkit that turns long gameplay/stream recordings (3-15+ hours) into vertical short clips (9:16), fully local and free: no watermarks, no time limits, no paid "virality score" service. Distributed as an open-source Claude Code skill so anyone running Claude Code can install it and use it on their own recordings.

Source content is typically gameplay with commentary, no facecam overlay, with jokes/highlights that can appear regardless of which game is being played at the time.

## Architecture

Pipeline for one video:

1. **Transcribe** — `faster-whisper` runs once per video ever. Output (text + word/segment timestamps) is cached to `transcripts/<video_stem>.json`. Re-running on the same file skips transcription and reuses the cache.

2. **Find candidates (pass 1)** — the transcript is split into ~30-45 min chunks (configurable). One Claude Code subagent per chunk reads that chunk's text + timestamps and semantically identifies strong moments (jokes, reactions, stories) — not audio-energy heuristics, actual content understanding. Chunk results merge into a single `CANDIDATES.md` (timecode + short reason each).

3. **User approval** — `CANDIDATES.md` is presented for review; the user picks which candidates to render.

4. **Refine (pass 2)** — for approved candidates only: a closer read of that moment's transcript window determines exact trim points (cut on natural speech pauses, not mid-word/mid-phrase) and a per-clip crop style (zoom/crop for visually dynamic moments, padded frame with reserved caption space for dialogue/jokes where the visual matters less). Written to `PLAN.json`.

5. **Render** — `ffmpeg` cuts, crops/pads, and optionally burns subtitles per `PLAN.json` and `config.yaml`, output to the configured output directory.

**Library-wide search (future capability, enabled by the caching design):** because transcripts persist, the same pass-1/pass-2 analysis can be re-run over any subset of already-transcribed videos, not just the one just processed — e.g. "find moments about X across all past recordings."

## Components / file layout

```
shorts-maker/
  SKILL.md                 # Claude Code skill entry point (e.g. /make-shorts <video>)
  README.md                # GitHub install/usage instructions
  config.example.yaml      # copy to config.yaml and fill in
  requirements.txt
  scripts/
    setup.py               # checks/installs ffmpeg (winget) + python deps, detects GPU
    transcribe.py          # faster-whisper wrapper: video -> transcripts/<stem>.json (cached)
    render.py              # ffmpeg wrapper: cut/crop/zoom/pad/subtitles from an approved plan
  transcripts/              # cached whisper output (gitignored)
  work/<video_stem>/
    CANDIDATES.md           # pass-1 output for user review
    PLAN.json               # pass-2 output: exact trims + crop style per approved clip
```

### config.yaml

- `input_dir` / video path(s)
- `output_dir`
- `whisper`: model size (tiny…large-v3), device (auto/cuda/cpu), language (auto or fixed, e.g. `ru`)
- `chunk_minutes` (default 35) — pass-1 chunk size for parallel subagent analysis
- `clip_length`: min/max seconds (default 30-60s)
- `crop`: mode (auto/zoom/pad/original-16:9)
- `subtitles`: enabled (bool, default false), font, size, color, outline, position

No paths, languages, or content assumptions are hardcoded — everything content- or environment-specific lives in `config.yaml` so the tool works for other users' setups.

## Data flow

```
video file
  -> scripts/transcribe.py (faster-whisper, GPU/CPU per config)
  -> transcripts/<stem>.json   (skipped if already cached)
  -> split into chunk_minutes windows
  -> [parallel] one subagent per chunk reads chunk text+timestamps, proposes candidates
  -> merge -> work/<stem>/CANDIDATES.md
  -> user reviews, approves a subset
  -> for each approved candidate: refine pass (exact trim + crop style) -> PLAN.json
  -> scripts/render.py (ffmpeg): cut, crop/zoom/pad, optional burned subtitles
  -> output files in config.output_dir
```

## Error handling

- Missing ffmpeg/python deps: `setup.py` detects and prompts before installing (does not silently install on someone else's machine).
- Video already transcribed: skip re-transcription, reuse cache.
- GPU too small / OOM for chosen Whisper model: fall back to a smaller model or CPU, log a warning.
- Clip boundaries beyond video duration: clamp before rendering.
- Empty candidate list for a chunk: valid outcome, logged, no error.
- Python 3.13 may lack prebuilt wheels for `faster-whisper`/`ctranslate2` on some platforms at time of writing — `setup.py` should detect this and guide the user to create a venv with a known-compatible Python version rather than failing silently.

## Testing

No end-to-end automated test suite (too much of the pipeline is LLM-driven semantic judgment to assert against). Instead:

- Unit tests for the deterministic parts of `render.py` (crop math, timing clamps).
- A short sample video fixture for a full-pipeline smoke test before running against real multi-hour recordings.
- Manual verification: run once on a real recording, review `CANDIDATES.md` quality and confirm rendered clips play back correctly with correct crop/subtitle sync.
