# Phase 7: Profanity Auto-Bleep - Pattern Map

**Mapped:** 2026-07-11
**Files analyzed:** 6 (2 new, 4 modified)
**Analogs found:** 6 / 6

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|-----------------|---------------|
| `scripts/profanity.py` (NEW) | service/utility (detection) | transform (text/timestamps -> spans) | `scripts/monetization_risk.py` | exact (fail-open YAML rule-load + deterministic regex-match shape) |
| `data/profanity_wordlist.yaml` (NEW) | config/data | batch (static reference data) | `data/monetization_rules.yaml` | exact (committed, generic, versioned wordlist data file) |
| `scripts/config.py` (MODIFIED — add `ProfanityConfig`) | config | CRUD (load/validate) | `AudioEnergyConfig` / `DiarizationConfig` dataclasses (same file) | exact (fail-open optional-feature dataclass convention) |
| `scripts/render.py` (MODIFIED — add `build_profanity_mask_filter`, extend `build_audio_filter_chain`, extend `render_clip`) | service (pure filter-string builder + subprocess dispatch) | transform / request-response (ffmpeg command construction) | `build_punch_zoom_filter` / `build_audio_filter_chain` (same file) | exact (validate-then-build pure-string-builder shape) |
| `scripts/jumpcuts.py` (REUSED, not modified) | utility | transform | `remap_words`/`remap_timestamp` | exact — reuse as-is, no new code needed here |
| `tests/test_profanity.py` (NEW) | test | — | `tests/test_monetization_risk.py` | exact (mirrors fail-open load + matcher test structure) |

## Pattern Assignments

### `scripts/profanity.py` (service/utility, transform)

**Analog:** `scripts/monetization_risk.py`

**Imports pattern** (`scripts/monetization_risk.py` lines 1-9):
```python
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml
```
`scripts/profanity.py` should follow this exact import block shape (stdlib first, `yaml` last, `from __future__ import annotations` mandatory per project convention).

**Fail-open YAML load pattern** (`scripts/monetization_risk.py::load_rules`, lines 14-15, 18-35):
```python
_EMPTY_RULES: dict = {"updated": "unknown", "youtube": {}, "tiktok": {}, "instagram": {}}


def load_rules(rules_path: str) -> dict:
    """Loads the per-platform monetization ruleset from YAML.

    Fail-open: a missing/unreadable/malformed rules file warns to stderr and
    returns an empty-but-valid ruleset (no categories, updated="unknown")
    instead of raising - the flag is additive, not a hard dependency of the
    pipeline (see .planning/research/PITFALLS.md Pitfall 2, CONVENTIONS fail-open tier).
    """
    try:
        raw_text = Path(rules_path).read_text(encoding="utf-8")
        rules = yaml.safe_load(raw_text) or {}
    except Exception as error:
        print(
            f"[warn] could not load monetization rules from {rules_path} ({error}); "
            "continuing with an empty ruleset (risk_level will be 'none')",
            file=sys.stderr,
        )
        return dict(_EMPTY_RULES)
    rules.setdefault("updated", "unknown")
    return rules
```
**Copy this shape exactly** for `load_wordlist(path)`: same `_EMPTY_<X>` module constant, same try/except Exception, same `[warn] ...; continuing with ...` stderr message format, same `dict.setdefault("updated", "unknown")` fallback. Never raise.

**Deterministic regex matching pattern** — `monetization_risk.py` uses `re.compile`/`re.escape` per keyword (module-level rank dicts `_SEVERITY_RANK`/`_CONFIDENCE_RANK` at lines 11-12 show the "small lookup dict at module top" convention). `scripts/profanity.py::compile_patterns` should follow the same `re.escape(root)` + `\b...\w*` word-boundary convention (see RESEARCH.md Code Examples for the exact function — already validated live against this codebase's Python `re` engine, safe to copy verbatim).

**CLI wrapper convention** — `monetization_risk.py` uses `argparse` + a `main()` guarded by `if __name__ == "__main__":` (imported at top: `import argparse`). `scripts/profanity.py` must expose the same dual Python-API + CLI shape per project convention ("Each `scripts/*.py` module pairs a Python API with a CLI wrapper").

---

### `data/profanity_wordlist.yaml` (config/data)

**Analog:** `data/monetization_rules.yaml`

Same committed-data-file convention: top-level `updated: "<date>"` key (mirrors `rules.setdefault("updated", "unknown")` handling above), generic/non-channel-specific content only. See RESEARCH.md Code Examples section for the exact drafted wordlist shape (`normalize:` block + `ru:`/`en:` lists of `{root: "..."}` entries) — already designed to match this file's loading contract in `load_wordlist`.

---

### `scripts/config.py` (config, CRUD) — add `ProfanityConfig`

**Analog:** `AudioEnergyConfig` dataclass (lines 118-129) and `DiarizationConfig` (lines 87-94)

**Dataclass pattern** (lines 118-129):
```python
@dataclasses.dataclass
class AudioEnergyConfig:
    enabled: bool = False
    # A momentary-loudness jump at least this many dB above its own local
    # rolling baseline counts as a spike (scream/laugh/hype yell).
    threshold_db: float = 6.0
    # Below this absolute LUFS, a "spike" is just noise floor moving inside
    # near-silence - ignored regardless of the relative jump.
    floor_lufs: float = -35.0
    baseline_window_seconds: float = 20.0
    min_duration: float = 0.3
    merge_gap_seconds: float = 1.0
```
Copy this exact shape for `ProfanityConfig`: `enabled: bool = False` first field (default-off per D-04), inline comments above each numeric tunable explaining *why* that default (matches project's "comments explain why, not what" convention), plain `float`/`int`/`str` fields — no nested dataclasses.

**Validation pattern** (`_validate`, around lines 248-359) — each config invariant is a single `if` + `raise ConfigError(f"...")` line, e.g.:
```python
raise ConfigError(f"effects.punch_zoom_ramp must be > 0, got {config.effects.punch_zoom_ramp}")
```
Add equivalent `ConfigError` checks for `ProfanityConfig` (e.g. `pad_seconds >= 0`, `max_masked_spans_per_clip > 0`, `duck_volume` between 0 and 1) inside `_validate`, following the exact `raise ConfigError(f"<section>.<field> must ..., got {value}")` message format used throughout.

**`ConfigError` type** (line 10):
```python
class ConfigError(ValueError):
    ...
```
No new exception type needed — reuse `ConfigError` for all profanity config validation, consistent with every other section.

---

### `scripts/render.py` (service, transform) — add `build_profanity_mask_filter`, extend `build_audio_filter_chain`

**Analog:** `build_punch_zoom_filter` (lines 246-271) for the new pure-builder function; `build_audio_filter_chain` (lines 315-330) for the extension target.

**Validate-then-build pure-string-builder pattern** (`build_punch_zoom_filter`, lines 246-271):
```python
def build_punch_zoom_filter(punch_at: float, zoom_amount: float = 1.15, ramp: float = 0.25) -> str:
    if zoom_amount <= 1.0:
        raise RenderError(f"zoom_amount must be > 1.0, got {zoom_amount}")
    if ramp <= 0:
        raise RenderError(f"ramp must be > 0, got {ramp}")
    if punch_at < 0:
        raise RenderError(f"punch_at must be >= 0, got {punch_at}")

    ramp_end = punch_at + ramp
    zoom_expr = (
        f"if(lt(t,{punch_at}),1,"
        f"if(lt(t,{ramp_end}),1+({zoom_amount}-1)*(t-{punch_at})/{ramp},{zoom_amount}))"
    )
    return (
        f"crop=w='{TARGET_WIDTH}/({zoom_expr})':h='{TARGET_HEIGHT}/({zoom_expr})':"
        f"x='(in_w-out_w)/2':y='(in_h-out_h)/2',scale={TARGET_WIDTH}:{TARGET_HEIGHT}"
    )
```
`build_profanity_mask_filter(spans, duck_volume, garble_freq, garble_width_octaves, warble_freq, warble_depth)` must follow this exact shape: validate every param up front with `RenderError` (reuse the existing `RenderError(ValueError)` type, line 43 — no new exception class), then return one self-contained f-string, no side effects, no I/O. See RESEARCH.md Code Examples for the drafted implementation (already matches this shape and is live-verified against ffmpeg).

**Extension point — `build_audio_filter_chain`** (current, lines 315-330):
```python
def build_audio_filter_chain(
    denoise: bool, loudnorm: bool, fade_filter: str | None, denoise_strength: float = 6.0
) -> str | None:
    """Combines the optional cleanup filters and the fade into one -af chain.

    Order matters: denoise the raw signal first, normalize loudness on the
    cleaned signal, then fade last so the fade-out isn't undone by loudnorm.
    """
    filters = []
    if denoise:
        filters.append(f"afftdn=nr={denoise_strength}")
    if loudnorm:
        filters.append("loudnorm=I=-16:TP=-1.5:LRA=11")
    if fade_filter:
        filters.append(fade_filter)
    return ",".join(filters) if filters else None
```
Add one new optional parameter `profanity_filter: str | None = None` and one new `if profanity_filter: filters.append(profanity_filter)` block **inserted after the `loudnorm` block, before the `fade_filter` block** — this ordering is load-bearing (RESEARCH.md Pattern 1: the mask must apply after `loudnorm`'s gain-riding, before the tail `afade`). Update the docstring's "Order matters" comment to mention the new stage, matching this file's existing documentation-of-ordering-rationale style.

**Call sites to also update:** `build_ffmpeg_command` (line 333) and `build_jumpcut_command`/`build_compilation_command` both already consume `build_audio_filter_chain`'s return value as a plain `-af` string or embedded `[acat]<chain>[aout]` fragment — per RESEARCH.md, no structural change needed there, only pass the new `profanity_filter` argument through from `render_clip` (line 872), which should read `plan_entry.get("profanity_spans")` the same way it already reads other optional plan fields (e.g. `punch_zoom_at`) — check existing `render_clip` body for the `plan_entry.get(...)` convention to copy exactly.

**`RenderError` type** (line 43):
```python
class RenderError(ValueError):
    ...
```
Reuse as-is; no new exception type.

---

### `scripts/jumpcuts.py::remap_words` (REUSE, no modification)

**Analog / source of truth:** `scripts/jumpcuts.py` lines 59-88:
```python
def remap_timestamp(t: float, keep_segments: list[tuple[float, float]]) -> float | None:
    """Maps an absolute source-file timestamp onto the spliced (concatenated)
    output timeline built from keep_segments, in order. Returns None when t
    falls inside a cut gap - whatever was at that moment (a word, a frame)
    no longer exists in the rendered output.
    """
    elapsed = 0.0
    for seg_start, seg_end in keep_segments:
        if t < seg_start:
            return None
        if t <= seg_end:
            return elapsed + (t - seg_start)
        elapsed += seg_end - seg_start
    return None


def remap_words(words: list[dict], keep_segments: list[tuple[float, float]]) -> list[dict]:
    """Shifts a list of {"word", "start", "end"} entries (absolute
    source-file seconds) onto the spliced timeline built from keep_segments.
    A word is dropped if either endpoint falls inside a cut gap - it no
    longer exists in the rendered output.
    """
    remapped = []
    for word in words:
        new_start = remap_timestamp(word["start"], keep_segments)
        new_end = remap_timestamp(word["end"], keep_segments)
        if new_start is None or new_end is None:
            continue
        remapped.append({"word": word["word"], "start": round(new_start, 3), "end": round(new_end, 3)})
    return remapped
```
**Do not reimplement this in `scripts/profanity.py`.** `find_profane_spans` in the new module must accept an already-remapped, clip-relative `words` list (the caller — `SKILL.md` orchestration or a thin glue step — is responsible for calling `remap_words` first, exactly as the existing subtitle-building step already does). This is an explicit anti-pattern callout in RESEARCH.md.

---

## Shared Patterns

### Fail-open optional-feature convention
**Source:** `scripts/monetization_risk.py::load_rules` + `scripts/config.py` dataclasses (`enabled: bool = False` default) + `SKILL.md` steps 1c/1d (diarization/audio_energy)
**Apply to:** `scripts/profanity.py::load_wordlist`, `ProfanityConfig`, and any orchestration glue that invokes profanity detection.
Rule: missing/malformed config or wordlist file → warn to stderr with `[warn] ...` prefix, degrade to "no masking applied", never raise, never abort the render.

### `RenderError`/`ConfigError` custom-exception convention
**Source:** `scripts/render.py:43` (`class RenderError(ValueError): pass`), `scripts/config.py:10` (`class ConfigError(ValueError): pass`)
**Apply to:** All new validation logic in `render.py` (profanity filter builder) and `config.py` (`ProfanityConfig` validation) — reuse these existing exception types, do not introduce a new one.

### `runner=subprocess.run` injectable pattern
**Source:** `scripts/render.py::probe_video`, `scripts/silence.py::measure_loudness`, `scripts/audio_energy.py::measure_momentary_loudness`
**Apply to:** No new subprocess call is introduced by this phase (masking reuses the existing `render_clip` ffmpeg dispatch) — but if any integration test needs to invoke ffmpeg directly for a `volumedetect` check (per RESEARCH.md Validation Architecture), mirror this injectable-runner shape rather than calling `subprocess.run` inline.

### Test-file-mirrors-module convention
**Source:** `tests/test_monetization_risk.py` (mirrors `scripts/monetization_risk.py` 1:1), project convention "Tests mirror module names 1:1"
**Apply to:** `tests/test_profanity.py` (new, mirrors `scripts/profanity.py`), plus additions to existing `tests/test_render.py` and `tests/test_config.py` (do not create separate new test files for the `render.py`/`config.py` extensions — append to the existing mirrored test files).

## No Analog Found

None — every file in this phase has a strong existing analog in the codebase (see table above). This phase is purely additive glue code layered on already-established conventions (RESEARCH.md's own conclusion: "every piece this phase needs already exists in the codebase or in the ffmpeg binary").

## Metadata

**Analog search scope:** `scripts/`, `data/`, `tests/` (whole-repo relevant subset; no `node_modules`/build-output dirs in this Python project)
**Files scanned:** `scripts/monetization_risk.py`, `scripts/config.py`, `scripts/render.py`, `scripts/jumpcuts.py`, `data/monetization_rules.yaml` (referenced, not re-read — already fully characterized in RESEARCH.md), `tests/test_monetization_risk.py` (referenced by name/convention, not re-read)
**Pattern extraction date:** 2026-07-11
