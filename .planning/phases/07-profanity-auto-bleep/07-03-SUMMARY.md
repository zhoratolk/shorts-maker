---
phase: 07-profanity-auto-bleep
plan: 03
subsystem: config
tags: [python, dataclasses, yaml, config, profanity, fail-open]

# Dependency graph
requires:
  - phase: 07-profanity-auto-bleep (Plan 01)
    provides: scripts/profanity.py's find_profane_spans parameter names (pad_seconds, max_masked_spans_per_clip)
  - phase: 07-profanity-auto-bleep (Plan 02)
    provides: build_profanity_mask_filter's tunable parameter names (duck_volume, garble_freq, garble_width_octaves, warble_freq, warble_depth)
provides:
  - "scripts/config.py::ProfanityConfig - default-off, fail-open config section with nine fields (enabled, wordlist_path, pad_seconds, max_masked_spans_per_clip, duck_volume, garble_freq, garble_width_octaves, warble_freq, warble_depth)"
  - "scripts/config.py::Config.profanity - wired into the Config aggregate + load_config _build(...) + _validate"
  - "config.example.yaml profanity: section - documented, default-off"
affects: [07-04-detection-glue-and-empirical-validation]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "ProfanityConfig dataclass mirrors AudioEnergyConfig/DiarizationConfig exactly - enabled: bool = False first field, flat float/int/str tunables with inline why-comments, no nested dataclasses"
    - "_validate invariants follow the project's exact 'raise ConfigError(f\"<section>.<field> must ..., got {value}\")' message format"

key-files:
  created: []
  modified:
    - scripts/config.py
    - tests/test_config.py
    - config.example.yaml

key-decisions:
  - "No new decisions beyond the plan's explicit field/default/validation spec - implemented exactly as written, using Plan 07-01/07-02's SUMMARY.md-confirmed parameter names to keep field naming aligned with the consumers (find_profane_spans, build_profanity_mask_filter)"

patterns-established: []

requirements-completed: [AUDIO-01, AUDIO-02, AUDIO-03]

coverage:
  - id: D1
    description: "ProfanityConfig defaults to enabled=False (opt-in, D-04) and exposes wordlist_path, pad_seconds, max_masked_spans_per_clip, and the duck/garble/warble tunables Plans 07-01/07-02 consume"
    requirement: "AUDIO-01"
    verification:
      - kind: unit
        ref: "tests/test_config.py::test_load_config_profanity_defaults_when_section_missing"
        status: pass
      - kind: unit
        ref: "tests/test_config.py::test_load_config_profanity_custom_values_round_trip"
        status: pass
    human_judgment: false
  - id: D2
    description: "Out-of-range profanity config values raise ConfigError with a 'profanity.<field> must ..., got <value>' message for every invariant (pad_seconds, max_masked_spans_per_clip, duck_volume, garble_freq, garble_width_octaves, warble_freq, warble_depth)"
    requirement: "AUDIO-02"
    verification:
      - kind: unit
        ref: "tests/test_config.py::test_load_config_profanity_pad_seconds_negative_raises"
        status: pass
      - kind: unit
        ref: "tests/test_config.py::test_load_config_profanity_max_masked_spans_per_clip_zero_raises"
        status: pass
      - kind: unit
        ref: "tests/test_config.py::test_load_config_profanity_duck_volume_zero_raises"
        status: pass
      - kind: unit
        ref: "tests/test_config.py::test_load_config_profanity_duck_volume_one_raises"
        status: pass
      - kind: unit
        ref: "tests/test_config.py::test_load_config_profanity_garble_freq_zero_raises"
        status: pass
      - kind: unit
        ref: "tests/test_config.py::test_load_config_profanity_garble_width_octaves_zero_raises"
        status: pass
      - kind: unit
        ref: "tests/test_config.py::test_load_config_profanity_warble_freq_zero_raises"
        status: pass
      - kind: unit
        ref: "tests/test_config.py::test_load_config_profanity_warble_depth_zero_raises"
        status: pass
      - kind: unit
        ref: "tests/test_config.py::test_load_config_profanity_warble_depth_above_one_raises"
        status: pass
    human_judgment: false
  - id: D3
    description: "config.example.yaml has a documented profanity: section that loads cleanly with the feature off"
    requirement: "AUDIO-03"
    verification:
      - kind: unit
        ref: "python -c load_config('config.example.yaml') asserts profanity.enabled is False"
        status: pass
    human_judgment: false

duration: 15min
completed: 2026-07-11
status: complete
---

# Phase 7 Plan 3: Profanity Config Toggle Summary

**Added `ProfanityConfig` — the single fail-open, default-off config section (D-04) gating the whole profanity feature — to `scripts/config.py`, wired into `Config`/`load_config`/`_validate`, and documented in `config.example.yaml`.**

## Performance

- **Duration:** ~15 min
- **Completed:** 2026-07-11
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- `ProfanityConfig` dataclass mirroring `AudioEnergyConfig`/`DiarizationConfig` exactly: `enabled: bool = False` first field, then `wordlist_path`, `pad_seconds`, `max_masked_spans_per_clip`, `duck_volume`, `garble_freq`, `garble_width_octaves`, `warble_freq`, `warble_depth`, each with an inline why-comment tying back to 07-RESEARCH.md's Pitfall 2 (timestamp drift padding) and Pitfall 5 (span-count DoS cap)
- Wired into the `Config` aggregate (new `profanity` field), `load_config` (`_build(ProfanityConfig, data.get("profanity", {}), "profanity")`), and `_validate` (seven new `ConfigError` invariants, exact `profanity.<field> must ..., got {value}` message format)
- 11 new tests in `tests/test_config.py`: defaults-when-missing, custom-values round trip, and one raising case per invariant (pad_seconds negative, max_masked_spans_per_clip zero, duck_volume at 0 and at 1, garble_freq zero, garble_width_octaves zero, warble_freq zero, warble_depth at 0 and above 1)
- `config.example.yaml` gained a documented `profanity:` section (all nine fields, default off, fail-open framing per D-04) between `content:`/`diarization:` neighbors and `transitions:`, verified to load via `load_config`

## Task Commits

Each task was committed atomically (Task 1 followed the TDD RED/GREEN cycle):

1. **Task 1: ProfanityConfig dataclass + Config wiring + _validate + tests**
   - `d40a9d4` (test) — 11 failing tests for ProfanityConfig
   - `4272843` (feat) — dataclass + wiring + validation, all tests green
2. **Task 2: document the profanity: section in config.example.yaml** - `b8a2e0a` (docs)

**Plan metadata:** (this commit)

_Note: TDD Task 1 has two commits (test → feat), no refactor needed._

## Files Created/Modified
- `scripts/config.py` - new `ProfanityConfig` dataclass; `Config.profanity` field; `load_config` `_build(...)` wiring; seven new `_validate` invariants
- `tests/test_config.py` - 11 new tests mirroring the `DiarizationConfig`/`AudioEnergyConfig` test structure
- `config.example.yaml` - new documented `profanity:` section, default off

## Decisions Made
None beyond the plan's explicit spec - field names/defaults/validation ranges were prescribed exactly by the plan's `<behavior>` block, cross-checked against Plan 07-01/07-02's SUMMARY.md for parameter-name alignment with `scripts/profanity.py::find_profane_spans` and `scripts/render.py::build_profanity_mask_filter`.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- Local pytest temp dir (`AppData/Local/Temp/pytest-of-<user>`) is permission-locked on this machine (pre-existing, documented environment quirk per STATE.md Blockers/Concerns) - worked around with `--basetemp` override for all test runs in this session, same as prior phases in this project. Not a code issue.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- The whole profanity feature is now gated behind a single opt-in, fail-open, range-validated `config.yaml` section - D-04 satisfied
- `ProfanityConfig`'s field names/defaults are ready for Plan 07-04 to consume when wiring detection output into `PLAN.json`'s `profanity_spans` field and reading the render tunables from config
- Full `pytest -m "not integration" tests/test_config.py -x` green (79/79); full project non-integration suite green (586 passed, 5 skipped, 9 deselected) - no regressions
- No blockers for Plan 07-04

---
*Phase: 07-profanity-auto-bleep*
*Completed: 2026-07-11*

## Self-Check: PASSED
