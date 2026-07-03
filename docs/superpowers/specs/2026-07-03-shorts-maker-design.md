# shorts-maker — design

## Purpose

A Claude Code skill + script toolkit that turns long gameplay/stream recordings (3-15+ hours) into vertical short clips (9:16), fully local and free: no watermarks, no time limits, no paid "virality score" service. Distributed as an open-source Claude Code skill so anyone running Claude Code can install it and use it on their own recordings.

Source content is typically gameplay with commentary, no facecam overlay, with jokes/highlights that can appear regardless of which game is being played at the time. The tool is general-purpose, though: an optional facecam/avatar-overlay mode (see config below) covers streamers/VTubers whose content does have a camera or avatar in frame.

## Architecture

Pipeline for one video:

1. **Transcribe** — `faster-whisper` runs once per video ever. Output (text + word/segment timestamps) is cached to `transcripts/<video_stem>.json`. Re-running on the same file skips transcription and reuses the cache.

2. **Find candidates (pass 1)** — the transcript is split into chunks (`analysis.chunk_minutes`, default 35). By default (`analysis.use_subagents: true`) one Claude Code subagent per chunk reads that chunk's text + timestamps in parallel and semantically identifies strong moments (jokes, reactions, stories) — not audio-energy heuristics, actual content understanding. With `use_subagents: false`, the same analysis runs as a single sequential pass over the whole transcript instead. Chunk results merge into a single `CANDIDATES.md` (timecode + short reason each).

3. **User approval** — if `analysis.require_approval` is true (default), `CANDIDATES.md` is presented for review and the user picks which candidates to render; if false, the pipeline proceeds straight to the refine pass for all candidates.

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
- `analysis.chunk_minutes` (default 35, recommended range 20-45) — pass-1 chunk size. Smaller chunks give more precise candidates but mean more subagent calls (more time/cost); larger chunks are cheaper but risk missing a short moment inside a big block.
- `analysis.use_subagents` (default true) — parallel subagent analysis per chunk for pass 1. Set false to fall back to a single sequential read-through of the whole transcript instead: simpler and cheaper, but slower and coarser on very long (multi-hour) recordings.
- `analysis.require_approval` (default true) — whether to stop and show `CANDIDATES.md` for the user to pick from before rendering. Set false to skip straight from candidates to render (fully automatic) once you trust the pipeline's picks.
- `clip_length`: min/max seconds (default 30-60s)
- `crop`: mode (auto/zoom/pad/original-16:9)
- `facecam.enabled` (default false) — whether the recording has a camera/avatar overlay to account for when cropping.
- `facecam.mode`: `manual_region` (cheap — fixed pixel/percent coordinates you set once, for a static overlay position) or `auto_detect` (visual face/avatar detection per video or scene — costs meaningfully more compute and tokens; intended for VTubers with multiple models/scenes or a moving camera). Only relevant when `facecam.enabled` is true.
- `facecam.region`: `[x, y, w, h]` as % of frame, used only in `manual_region` mode.
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

## Addendum: clip naming + per-platform metadata (2026-07-04)

Added after the initial implementation shipped. Two related gaps: rendered clips had opaque filenames (`<video_stem>_clip01.mp4`), and there was no generated posting copy (title/description/tags/hooks) for actually publishing a clip.

**Clip naming:** the refine pass (pass 2) already decides a 2-3 word descriptive title per clip as part of its per-clip judgment. That title is converted to a filesystem-safe slug and combined with the clip's sequential index for uniqueness (pure word-slugs collide easily — e.g. two different clips both being "epic fail"): `0001-boss-rage-quit.mp4`. Cyrillic titles are transliterated to Latin so filenames stay portable across upload tools/URLs. Slugging is deterministic and unit-tested (`scripts/naming.py`), not left to the LLM to hand-format.

**Per-platform metadata:** `config.metadata` (new section) controls whether metadata is generated at all (`enabled`, default `true` — cheap, reuses the same transcript window pass 2 already reads) and which platforms to generate blocks for (`platforms`, a list; default `["youtube", "tiktok", "instagram"]`, since the user typically posts the same clip to more than one place and wants everything in one place rather than one platform at a time). Each platform has a different natural shape:
- `youtube`: `title`, `description`, `tags` (plain list, not hashtags).
- `tiktok` / `instagram`: a single `caption` string, hook as its first line, hashtags inline in the text.

The LLM (pass 2) produces this per-clip as a small JSON object keyed by platform name; a deterministic script (`scripts/metadata.py`) renders it into one human-readable text file per clip (one file, all requested platforms as separate `=== PLATFORM ===` sections) for easy copy-paste when posting — not a separate file per platform, since the user posts the same clip to several platforms from one sitting. The metadata file shares the clip's slug (e.g. `0001-boss-rage-quit.txt` next to `0001-boss-rage-quit.mp4`) so the pairing is obvious at a glance.

`METADATA_PLATFORMS` (the set of valid platform keys) lives in `scripts/config.py` alongside the other enum sets (`CROP_MODES`, `FACECAM_MODES`, `WHISPER_DEVICES`) as the single source of truth; `scripts/metadata.py` imports it rather than redefining it.

## Addendum: audio-spike signal, first-run config prompt, natural-language triggers (2026-07-03)

Added after a real end-to-end run surfaced two rough edges (silent env setup, GPU fallback masking a real dependency gap — see below) and the user asked for three usability improvements. This addendum covers only the three new features; the environment/dependency bugs found during that run were fixed directly in code, not as part of this design (missing `scripts.*` absolute-import resolution when scripts are run directly, and the GPU→CPU fallback not catching the ctranslate2 lazy CUDA-library load failure — both already fixed in `scripts/transcribe.py`/`scripts/metadata.py`).

### 1. Audio loudness-spike signal for candidate finding

Pass-1 candidate finding currently judges text alone. Loud audio moments (laughter, exclamations, reactions) are a real signal for "good moment" that pure transcript text can miss or under-represent (e.g. a genuine laugh transcribes as nothing, or as a short interjection easy to skim past).

**`scripts/loudness.py`** (new, mirrors `transcribe.py`'s shape):
- `analyze_loudness(video_path, window_seconds=1.0) -> list[{"start", "end", "rms_db"}]` — decodes the video's audio track via `av` (already an installed dependency of `faster-whisper`/ctranslate2, no new package needed) and computes RMS loudness per fixed window over the whole track.
- `detect_spikes(windows, baseline_seconds=30, z_threshold=2.0) -> list[{"start", "end", "rms_db"}]` — for each window, compares `rms_db` against a trailing rolling average over `baseline_seconds` of preceding windows and flags it as a spike when it exceeds that local baseline by `z_threshold`. Relative to a local rolling baseline, not an absolute dB cutoff, so it works across recordings with different overall mic/game-audio levels. The very first window (no preceding windows yet, so no baseline exists) is never flagged, regardless of its loudness — it takes at least one window of history to establish a baseline. `baseline_seconds`/`z_threshold` are internal constants, not exposed in `config.yaml` — they're implementation tuning, not something a user needs to reach for per-recording.
- CLI: `python scripts/loudness.py "<video>" transcripts` — prints the cache path (`transcripts/<video_stem>.loudness.json`), skips analysis if that file already exists (same caching convention as `transcribe.py`).

**Wiring into the pipeline:**
- `config.yaml` gets `analysis.audio_spikes` (bool, default `true`) — the only new user-facing knob for this feature.
- `SKILL.md`'s prerequisite/pipeline steps: when `analysis.audio_spikes` is true, run `loudness.py` on the video right after transcription, then pass its cache path to `chunker.py`.
- `chunker.py` gains an optional loudness-cache argument; when given, each `chunk_NNNN.json` gets an extra `loud_spikes` list containing every spike whose time range overlaps that chunk's window (absolute timestamps, same coordinate space as the transcript segments already in the chunk). Omitting the argument leaves chunk output unchanged — fully backward compatible.
- Pass-1 instructions in `SKILL.md` gain one rule: a `loud_spikes` entry overlapping or immediately following a transcript segment is a signal that moment is a stronger candidate (reaction, laugh, punchline landing) — but a spike with no corresponding text nearby (silence-adjacent noise, a bump, game explosion sound) does not by itself create a candidate. Audio is a *booster*, never the sole trigger.

### 2. First-run config prompt

Today, first-time setup requires manually copying `config.example.yaml` to `config.yaml` and hand-editing paths — an easy step to get wrong or skip (e.g. a fresh clone's `config.yaml` still pointing at someone else's `F:/...` paths). `scripts/setup.py` becomes the single entry point that also handles this:

- After the existing ffmpeg/deps/GPU checks, `setup.py` checks whether `config.yaml` exists. If not, it prompts for `input_dir` and `output_dir` (via the same `prompt_yes_no`-style helper, extended for free-text answers) and writes `config.yaml` from `config.example.yaml` with just those two values substituted.
- Substitution is a targeted line replace on the copied template text (not a YAML parse/re-dump), so all the explanatory comments in `config.example.yaml` survive into the user's `config.yaml` — round-tripping through the `scripts.config` dataclasses would strip them.
- Non-interactive environments (no stdin, e.g. CI) hit `EOFError` on the prompt — same fallback already added for the ffmpeg/deps prompts: fall back silently to a verbatim copy of the example file and print a note to edit the two paths by hand. Never crashes.
- If `config.yaml` already exists, `setup.py` leaves it untouched — this only runs once, on a fresh clone.

### 3. Natural-language chat triggers

Currently the skill only activates on the literal `/make-shorts <path>` slash command. The user also wants it to trigger from ordinary chat requests — "давай сделаем шортсы", "нарежь тикток", "make a reel out of this", "cut some shorts from this VOD" — in both Russian and English.

Claude Code matches a skill to a request based on the skill's frontmatter `description` field, so this is a documentation-only change, no new Python:
- `SKILL.md`'s frontmatter `description` is expanded from the current single sentence to explicitly list common RU/EN phrasing (шортс/шортсы/рилс/тикток/нарезка/нарезать, "make shorts", "make a reel", "make a tiktok", "cut/clip this VOD") in addition to the literal `/make-shorts` invocation, so the skill surfaces for natural requests, not just the exact command.
- New short section in `SKILL.md`'s body: when invoked from natural phrasing rather than the slash command (i.e. no video path was given), ask the user which file/path to process before doing anything else — never guess or default to "most recent file in `input_dir`".

### Testing

- `tests/test_loudness.py`: `analyze_loudness` tested against a synthetic decoded-audio fixture (mock `av`'s decode output the same way `test_transcribe.py` mocks `faster_whisper` — a fake module returning fixed frames, not real audio files); `detect_spikes` is pure data-in/data-out and tested directly against hand-built window lists (quiet baseline + one deliberate spike, the first window never flagged even if loud, all-quiet track with no spikes).
- `tests/test_chunker.py`: new cases for the optional loudness argument — spikes correctly attributed to the overlapping chunk(s), chunk output unchanged when the argument is omitted (regression guard for backward compatibility).
- `tests/test_setup.py`: new cases for config creation — interactive answers produce a `config.yaml` with substituted paths and preserved comments, missing-stdin (`EOFError`) falls back to a verbatim copy, and an already-existing `config.yaml` is left untouched.
- No test changes needed for the natural-language trigger feature — it's a `SKILL.md` prompt/description change with nothing deterministic to unit test.
