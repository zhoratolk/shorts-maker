# Codebase Structure

**Analysis Date:** 2026-07-07

## Directory Layout

```
shorts-maker/
├── scripts/              # Deterministic building blocks (Python API + CLI wrapper each)
│   ├── __init__.py       # Package marker (empty)
│   ├── config.py         # config.yaml schema (dataclasses) + loader + validation
│   ├── transcribe.py     # faster-whisper transcription (cached)
│   ├── silence.py        # ffmpeg loudnorm-based pause detection (cached)
│   ├── diarize.py        # pyannote.audio speaker diarization (in-place transcript labeling)
│   ├── audio_energy.py   # ffmpeg loudness spike detection (cached)
│   ├── frames.py         # ffmpeg still-frame extraction per chunk (visual pass)
│   ├── chunker.py        # split transcript into chunk_NNNN.json windows
│   ├── candidates.py     # merge candidates_chunk_*.json -> CANDIDATES.md + candidates.json
│   ├── jumpcuts.py        # keep-segment math + word-timestamp remap for pause cuts
│   ├── subtitles.py       # word list -> synced cue groups -> .srt (+ parse back)
│   ├── naming.py          # slugify title -> filesystem-safe clip filename
│   ├── metadata.py        # per-platform metadata JSON -> flat .txt file
│   ├── render.py          # ffmpeg filter-graph construction + execution (final .mp4)
│   ├── setup.py           # environment bootstrap (ffmpeg/deps/GPU check)
│   └── youtube_analytics.py  # optional OAuth pull of channel performance stats
├── tests/                # pytest suite, one test_<module>.py per scripts/ module
│   ├── __init__.py
│   ├── test_*.py          # unit tests (mocked subprocess via runner= injection)
│   └── test_integration_ffmpeg.py  # real-ffmpeg smoke tests, marked `integration`
├── docs/                  # Reference material read by the skill during semantic passes
│   ├── viral-clips-ru.md      # short-form virality research (candidate-finding/trim lens)
│   ├── metadata-writing-ru.md # title/description/caption writing guide (Russian)
│   ├── register-ru.md         # register/anti-AI-tone rules for generated copy (Russian)
│   ├── MANUAL_TESTING.md       # manual QA checklist
│   └── superpowers/            # planning artifacts (plans/specs) from the superpowers skill
├── .claude/
│   └── skills/make-shorts/SKILL.md   # deployed copy of root SKILL.md Claude Code discovers
├── .planning/             # GSD planning artifacts (this document's home)
│   └── codebase/           # codebase-mapper output (ARCHITECTURE.md, STRUCTURE.md, ...)
├── .superpowers/           # superpowers-skill working state (task briefs/reports, diffs)
├── work/                   # per-video working files (gitignored)
│   └── <video_stem>/       # one dir per processed video/session
│       ├── chunks/              # chunk_NNNN.json
│       ├── candidates/          # candidates_chunk_NNNN.json
│       ├── candidates.json      # merged machine-readable candidates
│       ├── CANDIDATES.md        # merged human-readable review doc
│       ├── frames/              # chunk_NNNN/frame_*.jpg + game_context.txt (visual pass)
│       ├── jumpcuts/             # <clip>_keep.json keep-segment lists
│       ├── subtitles/            # <clip>_words*.json, <clip>.srt
│       ├── metadata_data/        # <clip>.json per-platform metadata (pre-render)
│       └── PLAN.json             # final render plan (list of clip entries)
├── SKILL.md                # source of truth for the Claude Code skill (root copy)
├── README.md                # setup, usage, troubleshooting, project layout
├── config.example.yaml      # documented config template (copy to config.yaml)
├── config.yaml              # actual local config (gitignored paths/settings)
├── pyproject.toml           # pytest config (testpaths, integration marker)
├── requirements.txt          # runtime Python deps
├── requirements-dev.txt      # dev/test-only deps
├── client_secret.json        # OAuth client (gitignored, optional, YouTube analytics)
└── token.json                 # cached OAuth token (gitignored, optional)
```

## Directory Purposes

**`scripts/`:**
- Purpose: all deterministic/mechanical logic — no LLM/semantic reasoning lives here
- Contains: one module per pipeline stage, each with a small set of pure functions plus an `argparse`-based `main()`
- Key files: `render.py` (largest, 607 lines — ffmpeg filter-graph construction), `config.py` (308 lines — schema/validation), `diarize.py`, `subtitles.py`, `audio_energy.py`, `jumpcuts.py`

**`tests/`:**
- Purpose: unit + integration coverage for every `scripts/` module
- Contains: one `test_<module>.py` per corresponding `scripts/<module>.py`, plus `test_integration.py` (broader pipeline) and `test_integration_ffmpeg.py` (real ffmpeg, marked `integration`)
- Key files: `tests/test_render.py`, `tests/test_config_example.py` (validates `config.example.yaml` itself parses/validates)

**`docs/`:**
- Purpose: reference material the orchestrating Claude reads mid-pipeline, not developer docs
- Contains: Russian-language virality/writing-style guides consumed by `SKILL.md` steps 3/5, plus a manual testing checklist
- Key files: `docs/viral-clips-ru.md`, `docs/metadata-writing-ru.md`, `docs/register-ru.md`

**`work/`:**
- Purpose: ephemeral per-video pipeline state (gitignored)
- Contains: chunked transcripts, candidate lists, jump-cut/subtitle intermediates, the final `PLAN.json`
- Key files: `work/<video_stem>/PLAN.json` is the hand-off artifact into `render.py`

**`.claude/skills/make-shorts/`:**
- Purpose: the actual discovery location Claude Code scans (`.claude/skills/<name>/SKILL.md`) — root `SKILL.md` alone is not auto-discovered
- Contains: a copy (or symlink) of the root `SKILL.md`
- Key files: `.claude/skills/make-shorts/SKILL.md` — must be kept in sync manually with root `SKILL.md` if not symlinked

## Key File Locations

**Entry Points:**
- `SKILL.md` / `.claude/skills/make-shorts/SKILL.md`: the `/make-shorts` skill definition, orchestrates every stage
- `scripts/<name>.py` `main()`: CLI entry per stage, invoked via Bash by the orchestrator

**Configuration:**
- `config.yaml`: active local config (gitignored, holds real `input_dir`/`output_dir` paths)
- `config.example.yaml`: documented template, copy to `config.yaml`
- `scripts/config.py`: schema dataclasses + `load_config`/`_validate`

**Core Logic:**
- `scripts/render.py`: ffmpeg command/filter-graph construction — the most complex module
- `scripts/config.py`: config schema and validation
- `scripts/jumpcuts.py` + `scripts/subtitles.py`: timeline math for jump cuts and caption sync

**Testing:**
- `tests/test_<module>.py`: mirrors each `scripts/<module>.py` 1:1
- `pyproject.toml`: `testpaths = ["tests"]`, `integration` marker for real-ffmpeg tests

## Naming Conventions

**Files:**
- `scripts/<verb_or_noun>.py`: one file per pipeline stage, named after its function (`transcribe.py`, `chunker.py`, `candidates.py`)
- `tests/test_<module>.py`: exact 1:1 mirror of the module under test
- `chunk_NNNN.json` / `candidates_chunk_NNNN.json`: zero-padded 4-digit ordinal suffix ties chunk/candidate/frame files together across directories
- `<video_stem>-NNNN-<slug-title>.mp4`: final render filename pattern (`scripts/naming.py:build_clip_filename`), e.g. `mystream-0001-boss-rage-quit.mp4`
- `<clip_filename_stem>_words.json`, `_words_absolute.json`, `_keep.json`: suffix convention distinguishing raw/absolute vs. remapped/clip-relative intermediates

**Directories:**
- `work/<video_stem>/`: one directory per source video/session, mirrors the video's filename stem
- `work/<video_stem>/<stage>/`: one subdirectory per intermediate artifact type (`chunks/`, `candidates/`, `jumpcuts/`, `subtitles/`, `frames/`, `metadata_data/`)

## Where to Add New Code

**New pipeline stage/script:**
- Primary code: new `scripts/<name>.py` following the existing pattern — pure function(s) + thin `argparse` `main()`, accept a `runner=subprocess.run` parameter if it shells out
- Tests: matching `tests/test_<name>.py`, mock the `runner` for unit tests; add a real-ffmpeg case to `tests/test_integration_ffmpeg.py` only if it meaningfully needs a real filter-graph check
- Wire into orchestration: add the invocation + explanation as a new step in `SKILL.md` (both root and, if not symlinked, the `.claude/skills/make-shorts/` copy), and add any new tunables to both `scripts/config.py` and `config.example.yaml`

**New config option:**
- Add the field to the relevant dataclass in `scripts/config.py`, add validation in `_validate` if needed
- Document it with inline comments in `config.example.yaml` (the only place options are explained to users)
- Reference it from `SKILL.md` wherever the corresponding step reads it

**New render/ffmpeg effect:**
- Implementation: add a filter-graph builder function in `scripts/render.py` (follow the `build_*_filter`/`build_*_chain` naming pattern) and thread it through `build_ffmpeg_command`
- Expose as a CLI flag in `render.py`'s `main()` `argparse` setup, then reference the new flag from `SKILL.md` step 6's `render.py` invocation

**Reference/writing-style material:**
- Add new `docs/*.md` guides the orchestrator should read during a specific `SKILL.md` step; link them explicitly from that step's prose (Claude only reads what `SKILL.md` tells it to)

## Special Directories

**`work/`:**
- Purpose: ephemeral per-run pipeline artifacts
- Generated: Yes (by every pipeline stage)
- Committed: No (gitignored)

**`.superpowers/`:**
- Purpose: working state for the `superpowers` skill (task briefs/reports, review diffs) used during this project's own development
- Generated: Yes
- Committed: Partially — check `.superpowers/sdd/.gitignore` before assuming

**`.venv/`:**
- Purpose: local Python virtual environment
- Generated: Yes
- Committed: No

**`<output_dir>/transcripts/`** (external, path from `config.yaml`, e.g. `F:/Готовое/Шортс/transcripts/`):
- Purpose: long-lived cache of Whisper transcripts/pauses/energy-spikes, keyed by video stem, shared across all runs against that video (library-wide search relies on this)
- Generated: Yes
- Committed: No (outside the repo entirely, path is user-configured)

---

*Structure analysis: 2026-07-07*
