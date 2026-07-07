<!-- refreshed: 2026-07-07 -->
# Architecture

**Analysis Date:** 2026-07-07

## System Overview

```text
┌─────────────────────────────────────────────────────────────────────┐
│              Orchestrator: Claude Code + `SKILL.md`                  │
│   `SKILL.md` (root) / `.claude/skills/make-shorts/SKILL.md` (copy)   │
│   Reads `config.yaml`, drives every step below, does the semantic     │
│   reasoning (moment-finding, trimming, titles) — not a Python file.  │
└───────────────────────────────┬───────────────────────────────────────┘
                                 │ invokes CLI scripts, reads/writes JSON
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│  STAGE 1 — Transcription & Signal Extraction  (cached, deterministic) │
├───────────────┬───────────────┬───────────────┬─────────────────────┤
│ transcribe.py │  silence.py   │  diarize.py    │  audio_energy.py     │
│ faster-whisper│ ffmpeg        │ pyannote.audio │  ffmpeg loudnorm     │
│ → transcript  │ loudnorm→     │ → speaker      │  → energy_spikes     │
│   JSON        │ pauses JSON   │   labels       │    JSON              │
└───────┬───────┴───────┬───────┴───────┬────────┴───────────┬─────────┘
        │               │               │                    │
        │ (1c writes speaker labels IN PLACE into transcript) │
        ▼                                                     │
┌─────────────────────────────────────────────────────────────────────┐
│  STAGE 2 — Chunking            `scripts/chunker.py`                   │
│  Splits transcript segments into `chunk_NNNN.json` windows            │
│  (`config.analysis.chunk_minutes`), optionally also                   │
│  `scripts/frames.py` sampling stills per chunk for the visual pass    │
└───────────────────────────────┬───────────────────────────────────────┘
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│  STAGE 3 — Moment-Finding / Scoring (pass 1, semantic — Claude, NOT   │
│  a script). One Task subagent per chunk (parallel) reads its chunk    │
│  JSON + game_context.txt + energy_spikes + viral-clips-ru.md and      │
│  writes `candidates_chunk_NNNN.json`: {start,end,reason,coherence?}   │
└───────────────────────────────┬───────────────────────────────────────┘
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│  STAGE 4 — Merge & Approval     `scripts/candidates.py`               │
│  Merges all `candidates_chunk_*.json` → `CANDIDATES.md` (human review)│
│  + `candidates.json` (machine). User approves subset (config-gated).  │
└───────────────────────────────┬───────────────────────────────────────┘
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│  STAGE 5 — Refine / Trim / Plan (pass 2, semantic — Claude)           │
│  Per approved candidate: exact trim, crop_style, jump cuts            │
│  (`scripts/jumpcuts.py`), punch-zoom timing, subtitles                │
│  (`scripts/subtitles.py`), filename (`scripts/naming.py`), metadata   │
│  (`scripts/metadata.py`) → writes `work/<video>/PLAN.json`            │
└───────────────────────────────┬───────────────────────────────────────┘
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│  STAGE 6 — Render         `scripts/render.py`                        │
│  ffmpeg: crop/pad/letterbox, jump-cut splice+concat, denoise,         │
│  loudnorm, vignette/grain, punch-zoom, burned-in ASS subtitles,       │
│  fade-out → final .mp4 in `config.output_dir`, sits beside .txt       │
│  metadata (`scripts/metadata.py` output)                              │
└─────────────────────────────────────────────────────────────────────┘
```

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| Skill orchestration | Drives the whole pipeline, all semantic judgment (candidate scoring, trimming, titling) | `SKILL.md` |
| Config schema + loader | Typed dataclasses for every `config.yaml` section, validation | `scripts/config.py` |
| Transcription | faster-whisper (CTranslate2) inference, GPU DLL bootstrap, caching by video stem | `scripts/transcribe.py` |
| Pause detection | ffmpeg `loudnorm`-derived adaptive silence threshold → pause windows | `scripts/silence.py` |
| Speaker diarization | pyannote.audio pipeline, in-place transcript labeling, idempotent | `scripts/diarize.py` |
| Audio energy spikes | ffmpeg EBU R128 momentary loudness, rolling baseline, spike merge | `scripts/audio_energy.py` |
| Frame sampling | ffmpeg still extraction per chunk for visual pass | `scripts/frames.py` |
| Chunking | Splits transcript into time-bounded analysis windows | `scripts/chunker.py` |
| Candidate merge | Combine per-chunk candidate JSON → markdown review doc + JSON | `scripts/candidates.py` |
| Jump cuts | Compute keep-segments around long pauses; remap word timestamps onto spliced timeline | `scripts/jumpcuts.py` |
| Subtitles | Group word-level timestamps into cues; render/parse `.srt` | `scripts/subtitles.py` |
| Filename generation | Slugify title + video stem + index → safe filename | `scripts/naming.py` |
| Metadata rendering | Per-platform JSON → flat `.txt` file next to the clip | `scripts/metadata.py` |
| Rendering | ffmpeg filter graph construction + execution: crop, splice, effects, ASS subtitles, fades | `scripts/render.py` |
| Environment setup | ffmpeg/dep install check, GPU detection | `scripts/setup.py` |
| Channel analytics | YouTube Data/Analytics API OAuth pull (optional, run manually) | `scripts/youtube_analytics.py` |

## Pattern Overview

**Overall:** Claude-orchestrated ETL pipeline. Every script is a pure, testable, deterministic building block (function + thin argparse CLI wrapper); all subjective/semantic decisions (what's a good moment, how to trim, what to title it) are made by the orchestrating Claude Code instance reading `SKILL.md`, never encoded in Python. There is no long-running process, server, or app — each stage is a one-shot CLI invocation chained by file I/O.

**Key Characteristics:**
- Filesystem-as-message-bus: every stage reads/writes JSON files under `work/<video_stem>/` or `<output_dir>/transcripts/`; there is no in-memory pipeline object passed between stages.
- Aggressive caching by construction: transcript, pauses, and energy-spike JSON are named by video stem and skipped if already present — reruns are idempotent and cheap.
- Fail-open optional features: diarization and audio-energy both degrade silently (log + continue) rather than aborting the pipeline on error (see `SKILL.md` steps 1c/1d).
- Parallelism via subagents, not threads/async: `config.analysis.use_subagents=true` fans out one Task subagent per chunk file for candidate-finding; the Python layer itself is single-process/synchronous.
- CLI-first design: every `scripts/*.py` module exposes both a plain Python function (unit-testable, used directly by `tests/`) and an `argparse` `main()` (used by the orchestrator via subprocess/Bash).

## Layers

**Config layer:**
- Purpose: parse and validate `config.yaml` into typed dataclasses; single source of truth for every tunable
- Location: `scripts/config.py`
- Contains: `WhisperConfig`, `AnalysisConfig`, `ClipConfig`, `CropConfig`, `FacecamConfig`, `SubtitlesConfig`, `ContentConfig`, `DiarizationConfig`, `AudioConfig`, `VisualConfig`, `AudioEnergyConfig`, `JumpcutsConfig`, `EffectsConfig`, `MetadataConfig`, aggregate `Config`
- Depends on: `yaml`
- Used by: read directly by the orchestrator (Claude reads `config.yaml`, not this module, at runtime) and by `tests/test_config.py`; scripts themselves take resolved values as CLI flags rather than importing `Config` at runtime (decouples script CLIs from the config schema)

**Signal-extraction layer (Stage 1):**
- Purpose: turn raw video into structured, cacheable JSON signals (transcript, pauses, speakers, energy spikes)
- Location: `scripts/transcribe.py`, `scripts/silence.py`, `scripts/diarize.py`, `scripts/audio_energy.py`, `scripts/frames.py`
- Contains: ffmpeg/whisper/pyannote subprocess wrappers, each with a `runner=subprocess.run` injectable parameter for testability
- Depends on: ffmpeg/ffprobe on PATH, faster-whisper, optionally pyannote.audio
- Used by: consumed as cached files by Stage 2/3, never imported cross-script

**Structuring layer (Stage 2/4):**
- Purpose: reshape transcript/candidate JSON between stages
- Location: `scripts/chunker.py`, `scripts/candidates.py`
- Contains: pure data transforms, no subprocess calls
- Depends on: nothing external (stdlib json only)
- Used by: orchestrator CLI calls; also unit-tested directly

**Editing-primitives layer (Stage 5 support):**
- Purpose: compute the mechanical edit decisions once Claude has picked a moment
- Location: `scripts/jumpcuts.py` (keep-segment math + word remap), `scripts/subtitles.py` (cue grouping + `.srt` I/O), `scripts/naming.py` (filename slugify), `scripts/metadata.py` (platform text rendering)
- Contains: pure functions + small CLI subcommands
- Depends on: stdlib only
- Used by: orchestrator during pass 2, and directly by `render.py` output expectations (subtitles path, keep_segments)

**Rendering layer (Stage 6):**
- Purpose: turn a `PLAN.json` entry into a final ffmpeg-encoded `.mp4`
- Location: `scripts/render.py`
- Contains: ffmpeg filter-graph builders (`compute_crop_filter`, `build_subtitle_force_style`, `build_ass_content`, `build_video_effects_chain`, `build_punch_zoom_filter`, `build_audio_filter_chain`, `build_ffmpeg_command`, `build_jumpcut_command`), `probe_video`, `render_clip` (the actual subprocess dispatch), CLI `main()`
- Depends on: ffmpeg/ffprobe, `jumpcuts.py`-produced keep-segments, `subtitles.py`-produced `.srt`
- Used by: final stage; terminal in the pipeline

## Data Flow

### Primary Request Path (single video → clips)

1. Orchestrator loads `config.yaml`, checks `<output_dir>/transcripts/<stem>.json` cache (`SKILL.md` step 1; `scripts/transcribe.py:transcript_cache_path`, `is_cached`)
2. If uncached, `scripts/transcribe.py:transcribe_video` runs faster-whisper, writes transcript JSON with segment + word-level timestamps
3. Optional: `scripts/silence.py:find_pauses` → `<stem>_pauses.json`; `scripts/diarize.py:diarize_transcript` labels segments in place; `scripts/audio_energy.py:find_energy_spikes` → `<stem>_energy_spikes.json`
4. `scripts/chunker.py:split_into_chunks` + `write_chunks` → `work/<stem>/chunks/chunk_NNNN.json`
5. Claude subagents (or sequential self) read each chunk + optional signals → write `work/<stem>/candidates/candidates_chunk_NNNN.json`
6. `scripts/candidates.py:merge_candidate_files` + `render_candidates_markdown` + `write_candidates_json` → `work/<stem>/CANDIDATES.md`, `candidates.json`
7. User approves a subset (or auto-approved if `require_approval: false`)
8. Per approved candidate, Claude computes trim/crop/jumpcuts (`scripts/jumpcuts.py:compute_keep_segments`)/punch-zoom/subtitles (`scripts/subtitles.py:group_words_into_cues`, `render_srt`)/filename (`scripts/naming.py:build_clip_filename`)/metadata (`scripts/metadata.py:render_metadata_text`) → appended to `work/<stem>/PLAN.json`
9. `scripts/render.py:main` → `probe_video` once, then `render_clip` per plan entry → final `.mp4` + sibling `.txt` in `config.output_dir`

### Word-timestamp remap flow (jump cuts + subtitles)

1. Absolute (full-source-seconds) word list extracted from transcript segments covering the clip window
2. If `keep_segments` present: `scripts/jumpcuts.py:remap_words` shifts + drops words falling in cut pauses, onto the spliced timeline
3. Else: orchestrator manually subtracts clip `start` from every word (`render.py` uses `-ss` before `-i`, so rendered timeline starts at 0)
4. Claude lightly proofreads mis-transcribed words in place (never touches hype-phrase/slang/game-name tokens)
5. `scripts/subtitles.py:group_words_into_cues` + `render_srt` → `.srt`; same corrected words JSON also drives `render.py`'s karaoke highlight

**State Management:**
- No persistent process state. All state lives in files under `work/<video_stem>/` (gitignored, ephemeral per-run) and `<output_dir>/transcripts/` (long-lived cache, keyed by video stem).
- `PLAN.json` is the single hand-off artifact between the semantic planning stage (5) and the mechanical rendering stage (6) — `render.py` never reasons about content, only executes the plan.

## Key Abstractions

**Plan entry (`PLAN.json` object):**
- Purpose: fully resolved, mechanical instructions for one output clip — the contract between Claude's judgment and `render.py`'s execution
- Examples: `work/<video_stem>/PLAN.json` (schema documented in `SKILL.md` step 5)
- Pattern: optional fields (`keep_segments`, `punch_zoom_at`, `subtitles_path`, `metadata_path`) are omitted entirely rather than null/false when the feature is unused for that clip

**Cached signal JSON (transcript / pauses / energy spikes):**
- Purpose: expensive-to-compute, video-stem-keyed artifacts that make library-wide re-analysis (across already-processed videos) cheap
- Examples: `<output_dir>/transcripts/<stem>.json`, `<stem>_pauses.json`, `<stem>_energy_spikes.json`
- Pattern: existence-check-before-compute; diarization additionally uses field-presence (`"speaker" in segment`) as its own idempotency check (`scripts/diarize.py:is_diarized`)

**Injectable `runner` parameter:**
- Purpose: makes every subprocess-calling function (ffmpeg/ffprobe/whisper wrappers) unit-testable without a real binary
- Examples: `runner=subprocess.run` default parameter in `scripts/silence.py:measure_loudness`, `scripts/audio_energy.py:measure_momentary_loudness`, `scripts/render.py:probe_video`, `scripts/diarize.py:extract_audio_wav`
- Pattern: tests pass a stub/mock callable; only `tests/test_integration_ffmpeg.py` (marked `integration`) uses the real binary

**Chunk (`Chunk` dataclass / `chunk_NNNN.json`):**
- Purpose: bounds the semantic-analysis window so a subagent's context stays manageable and parallelizable
- Examples: `scripts/chunker.py:Chunk`, `work/<stem>/chunks/chunk_0000.json`
- Pattern: index-suffixed filenames (`_NNNN`) tie chunk/candidate/frame directories together by ordinal

## Entry Points

**`SKILL.md` (root, mirrored into `.claude/skills/make-shorts/SKILL.md`):**
- Location: `SKILL.md`
- Triggers: `/make-shorts <path-to-video>` inside Claude Code, run from this repo's directory
- Responsibilities: the only true "entry point" — every script below is invoked from here, never run standalone in production use

**Each `scripts/*.py` `main()`:**
- Location: `scripts/transcribe.py`, `scripts/silence.py`, `scripts/diarize.py`, `scripts/audio_energy.py`, `scripts/frames.py`, `scripts/chunker.py`, `scripts/candidates.py`, `scripts/jumpcuts.py`, `scripts/subtitles.py`, `scripts/naming.py`, `scripts/metadata.py`, `scripts/render.py`, `scripts/setup.py`, `scripts/youtube_analytics.py`
- Triggers: invoked via Bash/subprocess by the orchestrator (or manually for debugging/library-wide search)
- Responsibilities: thin `argparse` CLI wrapper around the module's core function(s); no script imports another script's `main`

## Architectural Constraints

- **Threading:** Single-threaded/synchronous throughout the Python layer. "Parallelism" (per-chunk candidate search) happens at the Claude Code subagent (Task tool) level, outside the Python process — not Python threads/async.
- **Global state:** None of note — `scripts/transcribe.py` calls `os.add_dll_directory` once at import/runtime to register CUDA DLL paths (`_register_nvidia_dll_dirs`), the only process-wide side effect outside file I/O.
- **Circular imports:** None — scripts are siblings under `scripts/`, each importable independently; none imports another `scripts.*` module (only `scripts/__init__.py` exists as a package marker).
- **Windows-first:** `scripts/setup.py` uses `winget` for ffmpeg install; `README.md`/`SKILL.md` assume PowerShell/Windows paths (`F:\Recordings\...`, `setx`), though the ffmpeg/Python logic itself is cross-platform.
- **No server/app process:** Nothing listens on a port or runs continuously; this is a CLI-script pipeline invoked per video.

## Anti-Patterns

### Encoding semantic judgment in Python

**What happens:** N/A currently observed as violated, but worth guarding — the design intentionally keeps "is this moment good/funny/coherent" logic entirely in `SKILL.md` prose, not in `scripts/candidates.py` or `scripts/chunker.py`.
**Why it's wrong:** Baking heuristics into Python would require redeploying code for every prompt-tuning iteration and lose the LLM's contextual judgment (game context, slang, hook placement).
**Do this instead:** Keep `scripts/*.py` limited to mechanical/deterministic transforms; put all "what makes a good clip" reasoning in `SKILL.md` and the `docs/*.md` reference material.

### Importing config.py at runtime inside scripts

**What happens:** Scripts take fully-resolved values as CLI flags (`--model`, `--device`, etc.) rather than loading `config.yaml` themselves via `scripts/config.py`.
**Why it's wrong:** would be redundant — worth calling out as intentional, not an oversight, so future contributors don't "fix" it by adding `load_config()` calls inside e.g. `transcribe.py`.
**Do this instead:** Continue passing config values explicitly via CLI args from the orchestrator; keep `config.py` as the schema/validation module used by the orchestrator's read and by `tests/test_config.py`, not by other scripts.

## Error Handling

**Strategy:** Two-tier — required steps raise/exit loudly (e.g. `RenderError` in `render.py`, `ConfigError`/`SilenceDetectionError`/`FrameExtractionError`); optional/additive steps (diarization, audio-energy) fail open per `SKILL.md`'s explicit instruction to the orchestrator (catch, log one line, continue with the feature simply absent).

**Patterns:**
- Custom `ValueError` subclasses per module for domain-specific failures (`RenderError`, `ConfigError`, `SilenceDetectionError`, `FrameExtractionError`)
- `render.py` validates plan-entry/crop-style combinations up front (e.g. rejects `punch_zoom_at` on `pad`/`original-16:9` crop styles) rather than producing a broken filter graph

## Cross-Cutting Concerns

**Logging:** No structured logging framework — scripts print plain `[warn] ...` lines to stdout/stderr for fail-open conditions (GPU fallback, diarization failure, YouTube Analytics unreachable); orchestrator relays these to the user.
**Validation:** `scripts/config.py:_validate` centralizes config-shape validation; individual scripts validate their own CLI args via `argparse` types/choices and raise their custom errors for domain-specific bad input (e.g. `render.py` crop/punch-zoom incompatibility).
**Authentication:** Only `scripts/youtube_analytics.py` (OAuth via `client_secret.json`/`token.json`, both gitignored) and `scripts/diarize.py` (`HF_TOKEN` env var for gated HuggingFace models) touch external auth — both optional, both outside the core render pipeline.

---

*Architecture analysis: 2026-07-07*
