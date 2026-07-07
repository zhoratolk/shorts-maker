# Coding Conventions

**Analysis Date:** 2026-07-07

## Naming Patterns

**Files:**
- One module per pipeline concern in `scripts/`: `config.py`, `transcribe.py`, `diarize.py`, `audio_energy.py`, `chunker.py`, `candidates.py`, `jumpcuts.py`, `silence.py`, `frames.py`, `render.py`, `subtitles.py`, `metadata.py`, `naming.py`, `youtube_analytics.py`, `setup.py`.
- Each `scripts/*.py` module pairs a Python API (importable functions) with a CLI wrapper (`argparse`-based `main()` + `if __name__ == "__main__":`), so the same logic is both testable in-process and runnable standalone.
- Tests mirror module names 1:1: `scripts/diarize.py` → `tests/test_diarize.py`, `scripts/audio_energy.py` → `tests/test_audio_energy.py`, etc.

**Functions:**
- `snake_case`, verb-first and descriptive: `check_ffmpeg`, `load_diarization_pipeline`, `run_diarization_pipeline`, `diarize_transcript`, `assign_speaker_to_segment`, `attach_speakers_to_segments`, `label_speakers_by_first_appearance`.
- Private/internal helpers prefixed with a single underscore: `_overlap_seconds`, `_register_nvidia_dll_dirs`.
- Boolean-returning functions read as predicates: `is_cached`, `is_diarized`.

**Variables:**
- `snake_case` throughout; no Hungarian notation.
- Paths are consistently named `*_path` or `*_dir` (`video_path`, `transcript_path`, `transcripts_dir`, `output_wav_path`) and passed/stored as `str`, converted via `pathlib.Path` only where filesystem operations are needed.

**Types:**
- `dataclasses.dataclass` for all config sections in `scripts/config.py` (`WhisperConfig`, `AnalysisConfig`, `ClipConfig`, `CropConfig`, `FacecamConfig`, `SubtitlesConfig`, etc.) — one dataclass per YAML config section, with field defaults matching documented pipeline defaults (e.g. `chunk_minutes: int = 35`).
- Custom exception types subclass a builtin, not `Exception` directly: `class ConfigError(ValueError): pass` in `scripts/config.py`.

## Code Style

**Formatting:**
- No formatter/linter config detected (no `.flake8`, `pyproject.toml` `[tool.black]`/`[tool.ruff]`, `.pre-commit-config.yaml`). Style is enforced by convention/review, not tooling.
- `from __future__ import annotations` at the top of every module — lets code use `list[dict]`, `str | None`, etc. type hints under older runtimes.
- Type hints used pervasively on function signatures, including `Optional`-style unions via `X | None` (PEP 604 syntax, not `typing.Optional`).

**Linting:**
- None configured (`requirements-dev.txt` contains only `pytest>=7.4.0`).

## Import Organization

**Order:**
1. `from __future__ import annotations` (always first, own line)
2. Standard library imports (`argparse`, `json`, `os`, `subprocess`, `sys`, `tempfile`, `pathlib.Path`)
3. Third-party/local imports, often deferred (see below)

**Lazy/deferred imports:**
- Heavy or optional dependencies are imported inside the function that needs them, not at module top level, so importing the module never fails just because an optional extra isn't installed:
  - `scripts/diarize.py`: `from pyannote.audio import Pipeline` inside `load_diarization_pipeline`; `import torch` inside the `if resolved_device == "cuda":` branch.
  - `scripts/transcribe.py`: `import nvidia` wrapped in `try/except ImportError` inside `_register_nvidia_dll_dirs`; `import numpy as np` inside the warm-up closure.
- This is a deliberate pattern for optional-feature modules — keep the top of the file import-safe, push the "may not be installed" dependency down to the one call site that actually needs it.

**Path Aliases:**
- None. `pythonpath = ["."]` in `pyproject.toml` `[tool.pytest.ini_options]` makes `scripts.*` importable as a package from the repo root; no aliasing beyond that.

## Error Handling

**Two distinct error-handling tiers in this codebase — know which one you're in:**

### 1. Hard failures (let them raise / `parser.error`)
Core pipeline steps that are required for correctness use normal exceptions or `argparse`'s `parser.error(...)` (prints usage + exits 2) for missing required input:
```python
# scripts/diarize.py main()
if not args.hf_token:
    parser.error("HuggingFace token required: pass --hf-token or set $HF_TOKEN")
if not Path(transcript_path).exists():
    parser.error(f"no cached transcript found at {transcript_path} - run scripts/transcribe.py first")
```
`scripts/config.py` raises `ConfigError` (a `ValueError` subclass) for invalid/missing config rather than silently defaulting.

### 2. Fail-open pattern for optional/best-effort features (IMPORTANT — recurring pattern, follow it for any new optional integration)
Three features in this codebase are explicitly optional and degrade gracefully instead of aborting the pipeline when they fail: **speaker diarization**, **audio-energy spike detection**, and the **YouTube Analytics API** call in `scripts/youtube_analytics.py`. The shape is: catch broadly, print a one-line `[warn] ...` message explaining what happened and what's degraded, then continue with an empty/partial result rather than propagating the exception.

**In-process example** (`scripts/youtube_analytics.py`, around the Analytics API call):
```python
try:
    analytics = fetch_analytics_for_videos(...)
    traffic_sources = fetch_traffic_sources_for_videos(...)
except Exception as error:
    print(
        f"[warn] YouTube Analytics API unreachable ({error}); continuing with view/like/comment "
        "counts only, no retention/traffic-source data this run",
        file=sys.stderr,
    )
    analytics, traffic_sources = {}, {}
```
Note: `Exception` (not a narrow type) is caught deliberately here — the comment in `scripts/transcribe.py`'s analogous GPU-fallback catch explains why: *"ctranslate2/CUDA can fail with several different exception types on OOM or missing runtime libraries; catch broadly here since this is a best-effort fallback, not error handling for a known failure mode."* Apply the same reasoning before broadening any other `except`: only acceptable when the code path is explicitly best-effort/optional, not for core logic.

**GPU→CPU fallback follows the identical shape** (`scripts/transcribe.py`):
```python
try:
    return build_and_warm_up(resolved_device, compute_type)
except Exception as error:
    if resolved_device != "cuda":
        raise  # already on CPU - nothing to fall back to, this is a real failure
    print(f"[warn] failed to load Whisper model on GPU ({error}); falling back to CPU")
    return build_and_warm_up("cpu", "int8")
```

**Orchestration-level fail-open (not Python try/except):** diarization and audio-energy don't catch their own CLI failures in Python — instead, `SKILL.md` (the Claude Code orchestration layer that shells out to these scripts) is the one that treats a nonzero exit / error from `scripts/diarize.py` or the audio-energy step as non-fatal:
> *"Fail open, do not abort the run. If this command errors for any reason (missing `HF_TOKEN`, `pyannote` not installed, a 403/gated-repo error, no GPU/out-of-memory, etc.), tell the user why in one line and continue the pipeline exactly as if `config.diarization.enabled` were `false` for this run ... Never let a diarization failure block transcription/chunking/candidate-finding/rendering; it's a purely additive signal, not a dependency the rest of the pipeline needs."* (`SKILL.md`)

The audio-energy step is documented identically: *"Fails open the same way diarization does — if the command errors, tell the user in one line and continue with an empty spike list for this run rather than aborting the pipeline."* (`SKILL.md`)

**When adding a new optional/best-effort integration:** decide up front whether the fail-open boundary belongs inside the Python script (catch there, return an empty/degraded result, print `[warn] ...`) or at the orchestration layer in `SKILL.md` (let the script exit non-zero, have the skill instructions say to swallow that and continue). Both are used in this codebase depending on whether the failure mode is "the Python function has a well-defined empty/degraded return value" (in-process catch) or "the whole external step either fully succeeds or should be skipped" (orchestration-level catch).

## Logging

**Framework:** None — plain `print()`.

**Patterns:**
- Warnings use a consistent `[warn] ...` prefix, written to `sys.stderr` when the call site has one available (`scripts/youtube_analytics.py`), or plain `print()` to stdout for warnings closer to the CLI's normal output (`scripts/transcribe.py`'s GPU-fallback message).
- Cache/output paths are printed as the last line of `main()` in CLI wrappers so shell pipelines can capture them, e.g. `scripts/diarize.py main()` ends with `print(transcript_path)`.

## Comments

**When to Comment:**
- Comments explain *why*, not *what* — especially around non-obvious platform/library quirks: DLL loading behavior on Windows (`scripts/transcribe.py`), lazy CUDA runtime loading in ctranslate2, Google's two-separate-services network quirk (`scripts/youtube_analytics.py`), gap-filling logic in `assign_speaker_to_segment` (`scripts/diarize.py`).
- Inline comments are used liberally right above the tricky line/block rather than as file-header essays.

**Docstrings:**
- Sparse on individual functions (names + type hints do most of the work). Module-level docstrings appear where the file's *purpose* needs explaining, e.g. `tests/test_integration_ffmpeg.py`'s docstring explains why the file exists and why it's marked `integration`.

## Function Design

**Size:** Small, single-purpose functions — each pipeline step is decomposed into several testable functions (e.g. diarization: `extract_audio_wav` → `run_diarization_pipeline` → `label_speakers_by_first_appearance` → `attach_speakers_to_segments` → `diarize_transcript` composes all of them).

**Parameters:** Optional tunables use keyword args with `None` defaults and are conditionally added to a `kwargs` dict before delegating to a third-party call, e.g. `run_diarization_pipeline`'s handling of `num_speakers`/`min_speakers`/`max_speakers`.

**Dependency injection for testability:** functions that shell out or call unpredictable system state accept an injectable callable defaulting to the real implementation, so tests can substitute a fake without monkeypatching the module:
```python
def extract_audio_wav(video_path: str, output_wav_path: str, runner=subprocess.run) -> None: ...
def check_gpu(runner=subprocess.run): ...
```

**Return Values:** Functions that mutate-and-return prefer building a new list/dict rather than mutating in place, e.g. `attach_speakers_to_segments` builds a new list of `{**segment, "speaker": speaker}` rather than mutating `segment` directly.

## Module Design

**Exports:** No `__all__`; everything importable is public by convention (leading underscore signals "internal", e.g. `_overlap_seconds`).

**CLI + library duality:** Every `scripts/*.py` file is designed to be both `import`ed (functions called directly, as tests do) and run as `python scripts/x.py ...` (via `argparse` + `main()`). Keep this shape for any new script: pure functions first, thin `argparse` wiring in `main()` last.

**Idempotency by design:** Cache-producing scripts check for existing state before doing the expensive/external work and no-op if it's already done: `is_cached`/`is_diarized` guard `transcribe_video`/`diarize_transcript` respectively; the audio-energy step is documented as skipping itself if `<video_stem>_energy_spikes.json` already exists.

---

*Convention analysis: 2026-07-07*
