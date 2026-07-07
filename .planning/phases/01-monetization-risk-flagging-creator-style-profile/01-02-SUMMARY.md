---
phase: 01-monetization-risk-flagging-creator-style-profile
plan: 02
subsystem: audio-fingerprint
tags: [python, chromaprint, fpcalc, monetization-risk, tdd]

# Dependency graph
requires: ["01-01"]
provides:
  - "scripts/monetization_audio.py: generate_fingerprint/lookup_fingerprint/to_risk_flag/merge_audio_flag/main, fail-open on missing fpcalc"
  - "scripts/setup.py: check_fpcalc() dependency-check + dependency-report line"
  - "MonetizationConfig.audio_fingerprint_enabled / enable_lookup fields (config.py), opt-in/off by default"
affects: [phase-6-scheduled-publish]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Injectable runner=subprocess.run pattern for the fpcalc subprocess call, mirroring scripts/audio_energy.py's measure_momentary_loudness"
    - "Lazy import of the optional pyacoustid/acoustid dependency inside lookup_fingerprint() only - importing scripts.monetization_audio never requires it to be installed"
    - "Merge-not-replace: merge_audio_flag folds the copyright flag into Plan 01's existing per-platform risk dict shape (flags/flagged_spans/risk_level), never constructing a competing risk shape"

key-files:
  created:
    - scripts/monetization_audio.py
    - tests/test_monetization_audio.py
  modified:
    - scripts/setup.py
    - scripts/config.py
    - config.example.yaml
    - tests/test_setup.py
    - tests/test_config.py

key-decisions:
  - "check_fpcalc() takes no runner param and calls shutil.which directly, matching check_ffmpeg's actual signature in this codebase (the plan text mentioned an optional runner param, but the real check_ffmpeg it says to mirror has none - followed the existing code over the plan's wording)"
  - "AcoustID network lookup requires an explicit api_key argument and is completely separate from the audio_fingerprint_enabled config flag - the config flag gates whether the pipeline runs fingerprinting at all, enable_lookup additionally gates the one network call within it"
  - "merge_audio_flag raises risk_level via the shared _SEVERITY_RANK ordering (none<low<medium<high) already established in monetization_risk.py, never introducing a second severity vocabulary"

patterns-established:
  - "A second monetization sub-feature (audio) merges into the first (keyword) via a pure merge function rather than a shared class/registry - keeps both modules independently testable and fail-open"

requirements-completed: [MONET-01, MONET-03]

coverage:
  - id: D1
    description: "generate_fingerprint() parses fpcalc output into duration+fingerprint via an injected runner; fails open (returns None, warns) on FileNotFoundError or subprocess error - no real binary needed for tests"
    requirement: "MONET-01"
    verification:
      - kind: unit
        ref: "tests/test_monetization_audio.py::test_generate_fingerprint_parses_fpcalc_output"
        status: pass
      - kind: unit
        ref: "tests/test_monetization_audio.py::test_generate_fingerprint_fails_open_when_binary_missing"
        status: pass
      - kind: unit
        ref: "tests/test_monetization_audio.py::test_generate_fingerprint_fails_open_on_subprocess_error"
        status: pass
    human_judgment: false
  - id: D2
    description: "to_risk_flag/merge_audio_flag produce and merge an advisory copyrighted_audio flag (confidence + last_checked) into Plan 01's risk dict without dropping keyword flags, raising risk_level to the max severity"
    requirement: "MONET-03"
    verification:
      - kind: unit
        ref: "tests/test_monetization_audio.py::test_to_risk_flag_positive_match_returns_advisory_flag"
        status: pass
      - kind: unit
        ref: "tests/test_monetization_audio.py::test_merge_audio_flag_adds_flag_without_dropping_keyword_flags"
        status: pass
      - kind: unit
        ref: "tests/test_monetization_audio.py::test_merge_audio_flag_none_returns_risk_dict_unchanged"
        status: pass
    human_judgment: false
  - id: D3
    description: "fpcalc is discoverable via setup.py's dependency check like ffmpeg; audio-fingerprint config defaults to disabled so the base install works without Chromaprint"
    requirement: "MONET-01"
    verification:
      - kind: unit
        ref: "tests/test_setup.py::test_check_fpcalc_found"
        status: pass
      - kind: unit
        ref: "tests/test_setup.py::test_check_fpcalc_missing"
        status: pass
      - kind: unit
        ref: "tests/test_config.py::test_load_config_monetization_audio_fingerprint_defaults_disabled"
        status: pass
      - kind: unit
        ref: "tests/test_config.py::test_load_config_monetization_audio_fingerprint_custom_values_round_trip"
        status: pass
    human_judgment: false

duration: ~40min
completed: 2026-07-07
status: complete
---

# Phase 1 Plan 2: Audio-Fingerprint Copyright Flagging (MONET-01) Summary

**Local Chromaprint/fpcalc audio fingerprinting (scripts/monetization_audio.py) that flags likely-licensed music as an advisory "copyrighted_audio" flag merged into Plan 01's per-platform risk dict, fully fail-open when fpcalc/pyacoustid/network are unavailable.**

## Performance

- **Duration:** ~40 min
- **Tasks:** 3
- **Files modified:** 7 (2 created, 5 modified)

## Accomplishments

- `scripts/monetization_audio.py`: `generate_fingerprint()` (injectable-runner fpcalc subprocess wrapper, fails open to `None` + `[warn]` on missing binary or subprocess error), `lookup_fingerprint()` (optional AcoustID network call, lazy-imports `acoustid`, fails open on any error, off unless an API key is passed), `to_risk_flag()` (builds the advisory `copyrighted_audio` flag using the same field vocabulary as Plan 01's keyword flags), `merge_audio_flag()` (folds the flag into an existing risk dict without dropping keyword flags, raises `risk_level` to the max severity), CLI `main()`.
- `scripts/setup.py`: `check_fpcalc()` (shutil.which, mirrors `check_ffmpeg`'s actual signature) plus a dependency-report line with an install hint.
- `scripts/config.py`: `MonetizationConfig` gained `audio_fingerprint_enabled` and `enable_lookup`, both `False` by default.
- `config.example.yaml`: documented both new fields under the existing `monetization:` block.

## Task Commits

1. **Task 1: Failing test — fingerprint a clip's audio into a copyright-risk flag** - `e4cd8c2` (test)
2. **Task 2: Implement the fingerprint step + merge into the risk dict (MONET-01, MONET-03)** - `106e252` (feat)
3. **Task 3: Add fpcalc to setup.py dependency check + audio_fingerprint config (MONET-01)** - `0fa18e0` (test) + `3451975` (feat)

## Files Created/Modified

- `scripts/monetization_audio.py` - fingerprint/lookup/flag/merge functions + CLI `main()`
- `tests/test_monetization_audio.py` - 6 tests covering parse, fail-open paths, flag construction, merge-with/without existing flags
- `scripts/setup.py` - `check_fpcalc()` + dependency-report line
- `scripts/config.py` - `audio_fingerprint_enabled` / `enable_lookup` fields on `MonetizationConfig`
- `config.example.yaml` - documented the two new fields
- `tests/test_setup.py` - 2 new tests for `check_fpcalc`
- `tests/test_config.py` - 2 new tests for the audio-fingerprint config defaults/round-trip

## Decisions Made

- `check_fpcalc()` has no `runner` parameter, matching `check_ffmpeg`'s real signature in this codebase (uses `shutil.which` directly) rather than the plan text's mention of `runner=subprocess.run` — followed the existing sibling function's actual code over a plan-comment inconsistency, since the plan's own instruction was "mirror check_ffmpeg exactly."
- `enable_lookup` is a separate flag from `audio_fingerprint_enabled`: the latter gates whether fingerprinting runs at all, the former additionally gates the one network call inside it — keeps the local-first default explicit at two independent layers.
- `merge_audio_flag` reuses `monetization_risk.py`'s severity ordering (`none < low < medium < high`) rather than inventing a second scale, so a merged risk dict stays comparable across both flag sources.

## Deviations from Plan

None of substance beyond the `check_fpcalc` signature note above (a plan-wording inconsistency, not a design change — the actual `check_ffmpeg` function it says to mirror takes no `runner`).

## Issues Encountered

- Same environment-only pytest temp-dir `PermissionError` (Cyrillic Windows username) as Plans 01-01/01-03 — worked around with `TMPDIR`/`TEMP`/`TMP` pointed at the session scratchpad for verification; no code changes needed.

## User Setup Required

- To actually use audio fingerprinting: install the Chromaprint `fpcalc` binary (e.g. `winget install -e --id Chromaprint.Chromaprint`) and set `monetization.audio_fingerprint_enabled: true` in `config.yaml`. Optional AcoustID lookup additionally needs an API key passed via `--acoustid-api-key` and `enable_lookup: true`. Neither is required for the base pipeline to work.

## Next Phase Readiness

- Phase 1 is now feature-complete: all 3 plans (01-01 monetization keyword scorer, 01-02 audio fingerprint, 01-03 creator style profile) are done. MONET-01/02/03/04 and STYLE-01/02/03 are all satisfied.
- No blockers for Phase 2 (LLM title/tag generation), which will consume `work/_profile/style_profile.json`'s few-shot examples.
- SKILL.md orchestration wiring (actually invoking these scripts during a live `/make-shorts` run) remains out of scope for Phase 1's plans, consistent with Plan 01-01's note — that wiring is a separate concern from building the scorers/config themselves.

---
*Phase: 01-monetization-risk-flagging-creator-style-profile*
*Completed: 2026-07-07*

## Self-Check: PASSED

All created files and commit hashes verified present on disk / in git log.
