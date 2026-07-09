# Phase 4: Context-Driven Transitions - Pattern Map

**Mapped:** 2026-07-08
**Files analyzed:** 6 (2 new, 3 modified, 1 new test file + 1 extended test file)
**Analogs found:** 6 / 6

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|--------------------|------|-----------|-----------------|----------------|
| `scripts/transitions.py` (NEW) | service/analysis | transform (signal-in → decision-out) | `scripts/audio_energy.py` + `scripts/diarize.py` (lazy-import half) | role-match (composite of two analogs) |
| `scripts/jumpcuts.py` (EXTEND — expose pause-gap size at each boundary) | utility | transform (pure function) | itself, `compute_keep_segments`/`total_kept_duration` | exact (extend in place) |
| `scripts/render.py` (EXTEND — `build_jumpcut_command` concat→fold, new `build_transition_filter`-style helpers) | service (ffmpeg filter-graph builder) | transform → file I/O (subprocess) | itself, `build_video_effects_chain` / `build_punch_zoom_filter` / `build_jumpcut_command` | exact (extend in place) |
| `scripts/config.py` (EXTEND — new `TransitionsConfig` dataclass + `_validate` block) | config | CRUD (load/validate) | itself, `JumpcutsConfig`/`AudioEnergyConfig` + their `_validate` blocks | exact (extend in place) |
| `tests/test_transitions.py` (NEW) | test | request-response (pure function assertions) | `tests/test_jumpcuts.py`, `tests/test_audio_energy.py` | exact |
| `tests/test_integration_ffmpeg.py` (EXTEND — new transition render test) | test | file I/O (real ffmpeg) | itself, `test_jumpcut_splices_out_silence_gap` | exact |

## Pattern Assignments

### `scripts/transitions.py` (service/analysis, transform) — NEW FILE

**Analogs:** `scripts/diarize.py` (lazy-import fail-open shape) + `scripts/audio_energy.py` (pure-function decomposition + adaptive-baseline scoring) + `scripts/frames.py` (ffmpeg still-extraction call shape, `runner=` injectable)

**Module header / import pattern** (mirror every `scripts/*.py` file):
```python
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
```
(No top-level `cv2`/`librosa` import — see lazy-import pattern below.)

**Lazy-import fail-open pattern** — `scripts/diarize.py:72-78`:
```python
def load_diarization_pipeline(hf_token: str, device: str = "auto"):
    from pyannote.audio import Pipeline

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from scripts.setup import check_gpu

    pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1", use_auth_token=hf_token)
    ...
```
Apply the same shape in `transitions.py`, e.g.:
```python
def analyze_motion_at_boundary(frame_a_path: str, frame_b_path: str) -> float | None:
    try:
        import cv2
    except ImportError:
        return None  # fail-open: caller treats None as "inconclusive" -> TRANS-03 fallback
    ...
```

**ffmpeg still-extraction reuse** — `scripts/frames.py:31-53` (`extract_frames`, injectable `runner=subprocess.run`, `-ss` before `-i` for fast seek, raises a module-specific `*Error(ValueError)` on nonzero returncode):
```python
def extract_frames(
    video_path: str, timestamps: list[float], output_dir: str, prefix: str = "frame", runner=subprocess.run
) -> list[str]:
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    paths = []
    for index, timestamp in enumerate(timestamps):
        output_path = str(Path(output_dir) / f"{prefix}_{index:03d}.jpg")
        command = ["ffmpeg", "-y", "-ss", str(timestamp), "-i", video_path, "-frames:v", "1", "-q:v", "2", output_path]
        result = runner(command, capture_output=True, text=True)
        if result.returncode != 0:
            raise FrameExtractionError(f"ffmpeg failed extracting frame at {timestamp}s: {result.stderr}")
        paths.append(output_path)
    return paths
```
`transitions.py` should call this directly (import `from scripts.frames import extract_frames`) to get the 2-3 boundary frames rather than reimplementing ffmpeg still extraction.

**Adaptive-baseline scoring pattern (mirror, not reuse code)** — `scripts/audio_energy.py:28-92` (`compute_rolling_baseline` + `detect_energy_spikes`): computes a per-point rolling-median baseline, flags points that exceed baseline by a relative `threshold_db` AND clear an absolute `floor_lufs`, then merges adjacent flagged windows with a `merge_gap_seconds` tolerance and drops sub-`min_duration` blips. This exact two-tier "relative-to-own-distribution AND absolute floor" shape is the recommended template for `classify_transition`'s conservative-bias thresholding (per D-01/D-02, Pitfall 4 in RESEARCH.md) — compute motion/audio/similarity scores across all boundaries first, then trigger non-cut only when a boundary's score clearly exceeds the video's own distribution, not a fixed number.

**Error-type convention:** define `class TransitionError(ValueError): pass` at module top, following `RenderError`/`ConfigError`/`FrameExtractionError`/`SilenceDetectionError` — all subclass a builtin directly, never bare `Exception`.

**CLI wrapper convention** — every module pairs its Python API with an `argparse`-based `main()` (see `scripts/audio_energy.py:115-140`, `scripts/frames.py:56-78`). `transitions.py` should follow the same shape: a `main()` with subcommands or flags that print/write JSON, guarded by `if __name__ == "__main__":`.

---

### `scripts/jumpcuts.py` (utility, transform) — EXTEND

**Analog:** itself — `compute_keep_segments` (lines 8-37), `total_kept_duration` (40-41)

**Current shape to extend** (`scripts/jumpcuts.py:8-37`):
```python
def compute_keep_segments(
    clip_start: float, clip_end: float, pauses: list[dict], max_pause_seconds: float
) -> list[tuple[float, float]]:
    ...
    segments: list[tuple[float, float]] = []
    cursor = clip_start
    for cut_start, cut_end in cuts:
        if cut_start > cursor:
            segments.append((cursor, cut_start))
        cursor = max(cursor, cut_end)
    if cursor < clip_end:
        segments.append((cursor, clip_end))
    return segments
```
Per RESEARCH.md Pitfall 1, add a sibling pure function (e.g. `compute_boundary_gaps(keep_segments) -> list[float]`) that exposes `next_segment_start - this_segment_end` for each adjacent pair — the same `cuts`/pause data this function already computes internally, just surfaced instead of discarded. Follow the existing style: no I/O, plain tuples/lists in-out, a docstring explaining *why* (mirrors the "why" commenting convention — see `remap_timestamp`'s docstring at line 44-49 for tone).

**CLI subcommand pattern to extend** — `scripts/jumpcuts.py:94-124` (`main()` with `add_subparsers`, one subparser per operation, `set_defaults(func=...)`). Add a new subcommand only if the planner decides the gap-exposure function needs a standalone CLI entry point; otherwise it's fine as an internal function called by `render.py`.

---

### `scripts/render.py` (service, transform → subprocess) — EXTEND

**Analog:** itself — `build_video_effects_chain` (201-213), `build_punch_zoom_filter` (216-241), `build_jumpcut_command` (326-414)

**Pure filter-fragment-builder pattern** — `scripts/render.py:201-213`:
```python
def build_video_effects_chain(vignette: bool, grain_strength: int) -> str | None:
    if grain_strength < 0 or grain_strength > 100:
        raise RenderError(f"grain_strength must be between 0 and 100, got {grain_strength}")

    filters = []
    if vignette:
        filters.append("vignette")
    if grain_strength > 0:
        filters.append(f"noise=alls={grain_strength}:allf=t")
    return ",".join(filters) if filters else None
```
New `build_transition_filter(transition_type, duration, ...)`-style helper(s) should follow this exact shape: validate inputs up front raising `RenderError`, return a filter-string fragment (or `None`/plain pass-through for `cut`), no subprocess call inside.

**Current concat stage to restructure (Pitfall 2)** — `scripts/render.py:363-369`:
```python
trim_stages = []
concat_refs = []
for index, (seg_start, seg_end) in enumerate(relative_segments):
    trim_stages.append(f"[0:v]trim=start={seg_start}:end={seg_end},setpts=PTS-STARTPTS[v{index}]")
    trim_stages.append(f"[0:a]atrim=start={seg_start}:end={seg_end},asetpts=PTS-STARTPTS[a{index}]")
    concat_refs.append(f"[v{index}][a{index}]")
concat_stage = f"{''.join(concat_refs)}concat=n={len(relative_segments)}:v=1:a=1[vcat][acat]"
```
Per RESEARCH.md Pattern 3/Pitfall 2, replace this flat N-ary concat with a sequential fold: seed `[v0][a0]`, then for each subsequent segment either 2-input `concat=n=2` (cut/match-cut boundary) or `xfade`+`acrossfade` (fancy-transition boundary, using gap-borrowed overlap from `jumpcuts.py`'s new gap-exposure function). Keep the existing `trim`/`setpts=PTS-STARTPTS` per-segment pattern unchanged — only the joining stage changes shape.

**xfade/acrossfade filter string shape** (RESEARCH.md Pattern 3, verified against local ffmpeg 8.1.2):
```text
[vA][vB]xfade=transition=fade:duration=0.35:offset=<A_len - 0.35>[vout]
[aA][aB]acrossfade=d=0.35[aout]
```

**Validation-up-front pattern to mirror** — `scripts/render.py:456-466` (`render_clip`'s punch_zoom/crop_style incompatibility check): raise `RenderError` with an explanatory message *before* building a broken filter graph, don't let ffmpeg fail with an opaque error. Apply the same idea to transition-type validation (V5 in RESEARCH.md's Security Domain: validate transition-type strings against the fixed 6-item enum before using them to key into any filter-string dispatch table).

**`runner=subprocess.run` injectable pattern** — `scripts/render.py:417-432` (`probe_video`) and `render_clip`'s own `runner=subprocess.run` parameter (line 451) — any new subprocess-invoking function in `transitions.py` (frame/audio-window extraction) must take the same injectable parameter for unit-testability without a real ffmpeg binary.

---

### `scripts/config.py` (config, CRUD) — EXTEND

**Analog:** itself — `JumpcutsConfig` (127-130) + its `_validate` block (279-289), `AudioEnergyConfig` (113-123)

**Dataclass pattern to copy** — `scripts/config.py:126-130`:
```python
@dataclasses.dataclass
class JumpcutsConfig:
    enabled: bool = False
    detect_min_seconds: float = 0.15
    cut_threshold_seconds: float = 0.4
```
New `TransitionsConfig` should follow this exact shape: an `enabled: bool = False` flag first (matches the fail-open/opt-in convention for every optional feature: `DiarizationConfig`, `AudioEnergyConfig`, `JumpcutsConfig` all default `enabled=False`), then threshold fields with sensible numeric defaults and inline comments explaining *why* the default was chosen (see `AudioEnergyConfig`'s `threshold_db`/`floor_lufs` comments at lines 115-120 for the tone/style to match).

**`_validate` block pattern to copy** — `scripts/config.py:279-289`:
```python
if config.jumpcuts.detect_min_seconds <= 0:
    raise ConfigError(
        f"jumpcuts.detect_min_seconds must be > 0, got {config.jumpcuts.detect_min_seconds}"
    )
if config.jumpcuts.cut_threshold_seconds <= 0:
    raise ConfigError(
        f"jumpcuts.cut_threshold_seconds must be > 0, got {config.jumpcuts.cut_threshold_seconds}"
    )
if config.jumpcuts.cut_threshold_seconds < config.jumpcuts.detect_min_seconds:
    raise ConfigError(
        "jumpcuts.cut_threshold_seconds must be >= jumpcuts.detect_min_seconds"
    )
```
Add the equivalent for `TransitionsConfig`'s new threshold fields, wired into `Config`'s aggregate dataclass (`scripts/config.py:179-197`, add `transitions: TransitionsConfig = dataclasses.field(default_factory=TransitionsConfig)`) and the `_build(...)` dispatch (line 232 pattern: `transitions=_build(TransitionsConfig, data.get("transitions", {}), "transitions")`).

---

### `tests/test_transitions.py` (test) — NEW FILE

**Analog:** `tests/test_jumpcuts.py` (1-40 shown) and `tests/test_audio_energy.py` (not read in full, same module-per-test-file convention)

**Test-file shape to copy** — `tests/test_jumpcuts.py:1-22`:
```python
import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.jumpcuts import compute_keep_segments, remap_timestamp, remap_words, total_kept_duration


def test_compute_keep_segments_no_long_pauses_returns_single_segment():
    result = compute_keep_segments(10.0, 40.0, pauses=[], max_pause_seconds=0.4)

    assert result == [(10.0, 40.0)]
```
Mirror for `test_transitions.py`: plain top-level `test_*` functions (no test classes), one behavior per test, descriptive snake_case names stating the exact scenario (`test_analyze_motion_returns_none_when_cv2_missing`, `test_classify_transition_picks_cut_when_signals_weak`, etc.), asserting on pure-function return values — no mocking framework beyond stdlib/pytest fixtures.

---

### `tests/test_integration_ffmpeg.py` (test) — EXTEND

**Analog:** itself — `test_jumpcut_splices_out_silence_gap` pattern (real-ffmpeg fixture-video test, `integration` marker)

Follow the existing file's established pattern (module docstring explaining why `integration`-marked tests exist and self-skip when ffmpeg/ffprobe aren't on `PATH`) to add a new test asserting a forced non-cut boundary produces a playable, correctly-dimensioned output via `probe_video`.

## Shared Patterns

### Lazy-import + fail-open for optional heavy dependencies
**Source:** `scripts/diarize.py:72-78` (`load_diarization_pipeline`'s `from pyannote.audio import Pipeline` inside the function body)
**Apply to:** `scripts/transitions.py`'s `analyze_motion_at_boundary` (`cv2`) and `analyze_audio_onset_at_boundary` (`librosa`) — both must import inside the function, return `None`/sentinel on `ImportError`, and never appear at module top level, so the whole module (and thus the whole optional feature) stays importable without either dependency installed.

### `runner=subprocess.run` injectable parameter
**Source:** `scripts/render.py:417` (`probe_video`), `scripts/frames.py:32` (`extract_frames`), `scripts/audio_energy.py:13` (`measure_momentary_loudness`), `scripts/diarize.py:60` (`extract_audio_wav`)
**Apply to:** Any new ffmpeg-invoking function in `transitions.py` (boundary frame/audio-window extraction) — always accept `runner=subprocess.run` as the last parameter so tests can substitute a stub without touching a real binary.

### Module-specific error type subclassing a builtin directly
**Source:** `class RenderError(ValueError): pass` (`render.py:26`), `class ConfigError(ValueError): pass` (`config.py:10`), `class FrameExtractionError(ValueError): pass` (`frames.py:8`)
**Apply to:** New `class TransitionError(ValueError): pass` in `transitions.py` for invalid transition-type strings, threshold config errors, etc.

### Adaptive/relative thresholding over fixed magic numbers
**Source:** `scripts/audio_energy.py:28-92` (`compute_rolling_baseline` + `detect_energy_spikes`'s combined relative-threshold + absolute-floor gate), `scripts/silence.py` (adaptive loudness threshold, not read in full this pass but referenced identically in RESEARCH.md)
**Apply to:** `classify_transition`'s conservative-bias decision tree (D-01/D-02) — compute scores across all boundaries in a video first, trigger non-cut only when a boundary's score clearly exceeds that video's own distribution.

### One config dataclass + `_validate` block per feature, `enabled: bool = False` default for optional features
**Source:** `JumpcutsConfig`/`AudioEnergyConfig`/`DiarizationConfig` dataclasses + their `_validate` blocks in `scripts/config.py`
**Apply to:** New `TransitionsConfig` dataclass and its validation block, following the exact structural template shown above.

### Never interpolate unvalidated strings into a `filter_complex`
**Source:** Existing convention across all of `render.py` — every subprocess call builds an argument **list**, never `shell=True`/string interpolation; filter fragments are built from internally-computed floats/enum-constrained strings.
**Apply to:** `build_transition_filter`-style helpers must validate the `transition_type` string against the fixed 6-item enum (`cut`, `crossfade`, `whip_pan`, `mask_wipe`, `glitch`, `match_cut`) before using it to key into any filter-string dispatch table, raising `RenderError`/`TransitionError` on an unexpected value.

## No Analog Found

None — every file in scope has a strong existing analog in this codebase (this project's one-module-per-concern convention and consistent pure-function/subprocess-injectable style made every new piece a direct extension of an existing shape).

## Metadata

**Analog search scope:** `scripts/render.py`, `scripts/jumpcuts.py`, `scripts/diarize.py`, `scripts/audio_energy.py`, `scripts/frames.py`, `scripts/config.py`, `tests/test_jumpcuts.py`
**Files scanned:** 7 source files + 2 test files (line counts checked via `wc -l` first to size each read)
**Pattern extraction date:** 2026-07-08
