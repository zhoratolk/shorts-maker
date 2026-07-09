---
phase: 04-context-driven-transitions
plan: 02
subsystem: config
tags: [transitions, config, jumpcuts, dataclass, validation]

# Dependency graph
requires:
  - phase: 04-context-driven-transitions
    provides: opencv-python-headless + librosa installed and registered (04-01)
provides:
  - TransitionsConfig dataclass (opt-in, enabled=False default) with transition_duration/min_overlap_seconds/strong_signal_percentile/match_cut_similarity fields
  - Config.transitions wiring through _build/load_config, following the JumpcutsConfig precedent
  - _validate block rejecting out-of-range transitions config values with ConfigError (T-04-CFG mitigation)
  - config.example.yaml transitions: section with documented empirical defaults
  - compute_boundary_gaps(keep_segments) pure function in jumpcuts.py exposing per-boundary pause-gap seconds
affects: [04-03-classifier, 04-04-select, 04-05-render-fold]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "TransitionsConfig mirrors JumpcutsConfig/AudioEnergyConfig: enabled: bool = False first, empirical threshold defaults with why-comments, wired via _build(TransitionsConfig, data.get('transitions', {}), 'transitions')"
    - "compute_boundary_gaps is a pure sibling function to total_kept_duration: no I/O, plain tuples/lists in-out, gap N = keep_segments[N+1][0] - keep_segments[N][1]"

key-files:
  created: []
  modified:
    - scripts/config.py
    - config.example.yaml
    - scripts/jumpcuts.py
    - tests/test_config.py
    - tests/test_jumpcuts.py

key-decisions:
  - "TransitionsConfig field order/defaults follow the plan verbatim: enabled=False, transition_duration=0.35, min_overlap_seconds=0.12, strong_signal_percentile=85.0, match_cut_similarity=0.90 - all documented as empirical starting points to tune after watching real renders (D-02)"
  - "_validate adds a floor check (min_overlap_seconds must be <= transition_duration) alongside the four per-field range checks, mirroring the jumpcuts cut_threshold_seconds >= detect_min_seconds precedent"
  - "No standalone CLI subcommand added for compute_boundary_gaps - it is called internally by future render.py/transitions.py code, per 04-PATTERNS.md guidance"

patterns-established:
  - "One config dataclass + _validate block per feature, enabled: bool = False default for optional features (TransitionsConfig follows this exactly)"

requirements-completed: [TRANS-01, TRANS-03]

coverage:
  - id: D1
    description: "TransitionsConfig loads with enabled=False and documented defaults when transitions: section is absent from config.yaml"
    requirement: "TRANS-01"
    verification:
      - kind: unit
        ref: "tests/test_config.py#test_load_config_transitions_defaults_when_section_missing"
        status: pass
    human_judgment: false
  - id: D2
    description: "_validate rejects out-of-range transitions config values (non-positive duration/overlap, overlap floor above duration, out-of-(0,100) percentile, out-of-[0,1] similarity, unknown fields) with ConfigError"
    requirement: "TRANS-01"
    verification:
      - kind: unit
        ref: "tests/test_config.py#test_load_config_transitions_transition_duration_must_be_positive"
        status: pass
      - kind: unit
        ref: "tests/test_config.py#test_load_config_transitions_min_overlap_seconds_must_be_positive"
        status: pass
      - kind: unit
        ref: "tests/test_config.py#test_load_config_transitions_min_overlap_seconds_exceeding_duration_raises"
        status: pass
      - kind: unit
        ref: "tests/test_config.py#test_load_config_transitions_strong_signal_percentile_out_of_range_raises"
        status: pass
      - kind: unit
        ref: "tests/test_config.py#test_load_config_transitions_strong_signal_percentile_zero_raises"
        status: pass
      - kind: unit
        ref: "tests/test_config.py#test_load_config_transitions_match_cut_similarity_out_of_range_raises"
        status: pass
      - kind: unit
        ref: "tests/test_config.py#test_load_config_transitions_match_cut_similarity_negative_raises"
        status: pass
      - kind: unit
        ref: "tests/test_config.py#test_load_config_transitions_unknown_field_raises"
        status: pass
    human_judgment: false
  - id: D3
    description: "compute_boundary_gaps(keep_segments) returns one gap value per adjacent boundary (len == len(keep_segments) - 1), including zero-gap for abutting segments and empty list for a single segment"
    requirement: "TRANS-03"
    verification:
      - kind: unit
        ref: "tests/test_jumpcuts.py#test_compute_boundary_gap_single_segment_returns_empty"
        status: pass
      - kind: unit
        ref: "tests/test_jumpcuts.py#test_compute_boundary_gap_two_segments_returns_the_cut_pause"
        status: pass
      - kind: unit
        ref: "tests/test_jumpcuts.py#test_compute_boundary_gap_multiple_segments_includes_zero_gap_when_abutting"
        status: pass
      - kind: unit
        ref: "tests/test_jumpcuts.py#test_compute_boundary_gap_length_matches_boundary_count"
        status: pass
    human_judgment: false

# Metrics
duration: 12min
completed: 2026-07-09
status: complete
---

# Phase 4 Plan 02: TransitionsConfig + compute_boundary_gaps Summary

**Added a validated, opt-in TransitionsConfig dataclass (mirroring JumpcutsConfig) and a pure compute_boundary_gaps helper in jumpcuts.py exposing per-boundary cut-gap seconds for the upcoming transition classifier/render fold.**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-07-09T18:50:00Z
- **Completed:** 2026-07-09T18:53:00Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments
- `TransitionsConfig` dataclass added to `scripts/config.py`, wired into the `Config` aggregate and `load_config`'s `_build` dispatch, with a full `_validate` block (5 checks: positive duration, positive overlap, overlap-floor-above-duration, percentile range, similarity range)
- `config.example.yaml` gained a documented `transitions:` section after `jumpcuts:` with the same empirical defaults and tune-after-watching-real-renders framing
- `compute_boundary_gaps(keep_segments)` added to `scripts/jumpcuts.py` as a pure sibling function to `total_kept_duration`, surfacing the same cut-pause data `compute_keep_segments` already computes internally
- Full TDD RED→GREEN cycle for both deliverables: failing tests committed first, then implementation

## Task Commits

Each task was committed atomically (TDD: test → feat):

1. **Task 1: TransitionsConfig dataclass, validation, and config.example.yaml section**
   - `1d13d2b` test(04-02): add failing tests for TransitionsConfig
   - `95d7af1` feat(04-02): add TransitionsConfig dataclass, validation, and config.example.yaml section
2. **Task 2: compute_boundary_gaps pure function in jumpcuts.py**
   - `b6607ea` test(04-02): add failing tests for compute_boundary_gaps
   - `8b55a6c` feat(04-02): add compute_boundary_gaps pure function to jumpcuts.py

## Files Created/Modified
- `scripts/config.py` - New `TransitionsConfig` dataclass, `Config.transitions` field, `_build` wiring in `load_config`, 5-check `_validate` block
- `config.example.yaml` - New `transitions:` section documenting all 5 fields with empirical-default framing
- `scripts/jumpcuts.py` - New `compute_boundary_gaps` pure function
- `tests/test_config.py` - 10 new tests covering defaults, custom values, and all 6 ConfigError-raising cases (including unknown field)
- `tests/test_jumpcuts.py` - 4 new tests covering empty/two-segment/multi-segment-with-zero-gap/length-invariant cases

## Decisions Made
- Field order/defaults for `TransitionsConfig` taken verbatim from the plan's `<action>` block (enabled=False, transition_duration=0.35, min_overlap_seconds=0.12, strong_signal_percentile=85.0, match_cut_similarity=0.90), each with an inline why-comment matching `AudioEnergyConfig`'s tone
- `min_overlap_seconds > transition_duration` is a hard validation error (a floor above the whole window is nonsensical), following the same shape as the jumpcuts `cut_threshold_seconds >= detect_min_seconds` check
- No standalone CLI subcommand for `compute_boundary_gaps` — it's an internal helper for `render.py`/`transitions.py` per 04-PATTERNS.md, consistent with `total_kept_duration` (also CLI-less)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- Environment quirk (pre-existing, documented in STATE.md Blockers): default pytest temp dir is permission-locked on this machine. Worked around with `pytest --basetemp=<scratch dir>` for every test run in this plan; the scratch dir was deleted after use and never committed. Unrelated to any code change in this plan.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- `TransitionsConfig` gives 04-03 (classifier)/04-04 (select) their config thresholds (`strong_signal_percentile`, `match_cut_similarity`, `min_overlap_seconds`, `transition_duration`)
- `compute_boundary_gaps` gives 04-05 (render fold) the per-boundary gap data needed for the TRANS-03 gap-fallback decision (enough borrowable overlap for a non-cut transition vs. plain cut)
- No blockers - both deliverables are pure/config-only and have zero dependency on the cv2/librosa install from 04-01, so they were safely executable in Wave 1 parallel to that plan

---
*Phase: 04-context-driven-transitions*
*Completed: 2026-07-09*

## Self-Check: PASSED

All key files (scripts/config.py, config.example.yaml, scripts/jumpcuts.py, tests/test_config.py, tests/test_jumpcuts.py, this SUMMARY.md) exist on disk. All commits (1d13d2b, 95d7af1, b6607ea, 8b55a6c, e32e626) verified present in `git log --oneline --all`.
