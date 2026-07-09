---
phase: 04-context-driven-transitions
plan: 04
subsystem: infra
tags: [transitions, classifier, adaptive-threshold, cli, fail-open]

# Dependency graph
requires:
  - phase: 04-context-driven-transitions
    provides: "TransitionsConfig + compute_boundary_gaps (04-02); TRANSITION_TYPES enum + analyze_motion_at_boundary/analyze_similarity_at_boundary/analyze_audio_onset_at_boundary/extract_audio_window (04-03)"
provides:
  - "scripts/transitions.py: compute_signal_threshold (adaptive per-video percentile), classify_transition (conservative 6-way decision tree), select_boundary_transitions (orchestration with gap fallback and full fail-open), select-transitions CLI subcommand"
  - "tests/test_transitions.py: 34 tests (up from 14) covering classify/fallback/select/CLI-handler behavior"
affects: [04-05-render-fold, 04-06-skill-orchestration]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "compute_signal_threshold: stdlib-only linear-interpolation percentile (mirrors numpy.percentile's default method) over a per-video score distribution - no numpy import needed, keeps the module's cv2/librosa-free top-level import-safety contract (04-03) intact"
    - "classify_transition: pure function, mutually-exclusive branch order, every return path a literal TRANSITION_TYPES member - documented decision order in the docstring per D-01/D-02/D-04"
    - "select_boundary_transitions is the first cross-script import in this codebase (scripts.frames.extract_frames, scripts.jumpcuts.compute_boundary_gaps) - both are stdlib-only pure/injectable-runner modules, so no cv2/librosa risk is introduced by the import"
    - "CLI subcommand follows jumpcuts.py's exact add_subparsers/set_defaults(func=...) shape; handler takes an injectable runner=subprocess.run parameter (beyond the jumpcuts.py precedent) specifically so it is directly unit-testable without a subprocess"

key-files:
  created: []
  modified:
    - scripts/transitions.py
    - tests/test_transitions.py

key-decisions:
  - "classify_transition's 'moderate motion' band (motion_threshold/2 <= motion < motion_threshold) is a deliberate discretionary construct (D-04) - it's what makes crossfade/whip_pan/glitch/mask_wipe mutually exclusive and each independently reachable, since a literal reading of 04-RESEARCH.md's suggested mapping (Assumption A3) has overlapping conditions that would make 'crossfade' unreachable if 'glitch' is checked first with a moderate-or-strong motion floor"
  - "mask_wipe's 'low similarity' framing is structural, not a second magic-number threshold: by the time the moderate-motion+weak-audio branch is reached, similarity (if present) already scored below match_cut_similarity, since step 1 would have already returned match_cut otherwise - no extra threshold parameter needed"
  - "select_boundary_transitions imports scripts.frames.extract_frames and scripts.jumpcuts.compute_boundary_gaps at module top level (first cross-script import in this codebase) rather than lazily - both source modules are themselves stdlib-only with no optional-dependency risk, so this doesn't compromise transitions.py's cv2/librosa-free import-safety contract from 04-03"
  - "config_fields is a plain dict of the 4 tunable knobs (transition_duration, min_overlap_seconds, strong_signal_percentile, match_cut_similarity), not a TransitionsConfig instance - scripts/config.py is never imported at runtime by scripts/*.py modules (project Anti-Pattern), so the CLI subcommand duplicates TransitionsConfig's literal default values as module-level constants instead"
  - "_cmd_select_transitions accepts an injectable runner=subprocess.run parameter beyond jumpcuts.py's/audio_energy.py's main() precedent, specifically so the CLI handler is unit-testable by direct invocation (per plan Task 3 action) without shelling out to a real subprocess"

patterns-established:
  - "Adaptive per-video threshold via stdlib percentile interpolation (compute_signal_threshold) - reusable shape for any future 'strong relative to this video's own distribution' decision, not just transitions"

requirements-completed: [TRANS-02, TRANS-03]

coverage:
  - id: D1
    description: "classify_transition maps (motion, audio, similarity) scores to exactly one of the 6 TRANSITION_TYPES strings, and returns each of the 6 for constructed inputs; weak signals and None motion/audio/threshold inputs return 'cut'"
    requirement: "TRANS-02"
    verification:
      - kind: unit
        ref: "tests/test_transitions.py#test_classify_transition_all_six_types_are_reachable"
        status: pass
      - kind: unit
        ref: "tests/test_transitions.py#test_classify_transition_weak_signals_returns_cut"
        status: pass
      - kind: unit
        ref: "tests/test_transitions.py#test_classify_transition_fallback_none_motion_returns_cut"
        status: pass
      - kind: unit
        ref: "tests/test_transitions.py#test_classify_transition_fallback_none_motion_threshold_returns_cut"
        status: pass
    human_judgment: false
  - id: D2
    description: "compute_signal_threshold returns the adaptive percentile of a video's own non-None boundary scores, dropping None entries, and returns None for an all-None list"
    requirement: "TRANS-03"
    verification:
      - kind: unit
        ref: "tests/test_transitions.py#test_compute_signal_threshold_drops_none_and_returns_percentile"
        status: pass
      - kind: unit
        ref: "tests/test_transitions.py#test_compute_signal_threshold_all_none_returns_none"
        status: pass
      - kind: unit
        ref: "tests/test_transitions.py#test_compute_signal_threshold_interpolates_high_percentile"
        status: pass
    human_judgment: false
  - id: D3
    description: "select_boundary_transitions returns len(keep_segments)-1 transition types, is fully fail-open to all-'cut' when analysis is unavailable, and forces 'cut' on any boundary whose gap is below min_overlap_seconds regardless of classification"
    requirement: "TRANS-03"
    verification:
      - kind: unit
        ref: "tests/test_transitions.py#test_select_boundary_transitions_single_segment_returns_empty_list"
        status: pass
      - kind: unit
        ref: "tests/test_transitions.py#test_select_boundary_transitions_fallback_all_cut_when_analyses_none"
        status: pass
      - kind: unit
        ref: "tests/test_transitions.py#test_select_boundary_transitions_forces_cut_below_min_overlap_gap"
        status: pass
    human_judgment: false
  - id: D4
    description: "select-transitions CLI subcommand reads keep_segments JSON, writes a length-correct boundary_transitions JSON list, prints the out path last, and degrades to all-'cut' when deps are absent"
    requirement: "TRANS-03"
    verification:
      - kind: unit
        ref: "tests/test_transitions.py#test_select_transitions_cli_handler_writes_all_cut_when_analyses_none"
        status: pass
      - kind: unit
        ref: "tests/test_transitions.py#test_select_transitions_cli_defaults_match_transitions_config"
        status: pass
      - kind: other
        ref: "python -m scripts.transitions select-transitions --help (manual CLI wiring smoke check)"
        status: pass
    human_judgment: false

# Metrics
duration: 4min
completed: 2026-07-09
status: complete
---

# Phase 4 Plan 04: Transitions Decision Layer Summary

**scripts/transitions.py gains classify_transition (conservative 6-way decision tree, all types independently reachable), compute_signal_threshold (stdlib adaptive per-video percentile), select_boundary_transitions (orchestration with gap and full fail-open fallback), and the select-transitions CLI subcommand, completing the "chooses a transition type at each boundary" half of TRANS-01.**

## Performance

- **Duration:** ~4 min (from first commit to last)
- **Started:** 2026-07-09T19:12:48+03:00
- **Completed:** 2026-07-09T19:16:42+03:00
- **Tasks:** 3/3 completed
- **Files modified:** 2 (scripts/transitions.py, tests/test_transitions.py)

## Accomplishments
- `compute_signal_threshold` — stdlib-only linear-interpolation percentile (mirrors `numpy.percentile`'s default) over a video's own non-None boundary scores; drops None entries, returns None when nothing remains
- `classify_transition` — pure, mutually-exclusive, documented decision tree over motion/audio/similarity vs adaptive thresholds; every return value is a literal `TRANSITION_TYPES` member; all 6 types independently reachable (TRANS-02), weak/None-input conservative fallback to `"cut"` (D-01, TRANS-03)
- `select_boundary_transitions` — orchestrates frame + audio-window extraction per boundary (`scripts.frames.extract_frames`, `extract_audio_window`), scores each boundary, derives this video's own adaptive motion/audio thresholds, classifies, then forces `"cut"` on any boundary whose `compute_boundary_gaps` pause-gap is below `min_overlap_seconds`; length-invariant (`len(keep_segments) - 1`, `[]` for one segment); fully fail-open to all-`"cut"` when cv2/librosa are unavailable
- `select-transitions` CLI subcommand — `python -m scripts.transitions select-transitions <video> <keep_segments_json> <out_json>` plus threshold/duration/overlap flags defaulting to `TransitionsConfig`'s literal values; writes the `boundary_transitions` JSON list, prints the out path last; handler takes an injectable `runner` so it's directly unit-testable
- `tests/test_transitions.py` grew from 14 to 34 tests: 15 for `compute_signal_threshold`/`classify_transition` (4 + all-6-reachable + 4 fallback), 3 for `select_boundary_transitions` (length-invariant, fail-open, gap-force), 2 for the CLI handler
- Full non-integration project suite (`pytest -m "not integration"`): 363 passed, 0 new failures; the same 3 pre-existing `test_publish_queue.py` failures (missing `googleapiclient`, out of scope) remain, unchanged from 04-03

## Task Commits

TDD RED→GREEN per task, matching the 04-02/04-03 precedent:

1. **Task 1: compute_signal_threshold + classify_transition**
   - `72850db` test(04-04): add failing tests for compute_signal_threshold and classify_transition
   - `1240b28` feat(04-04): implement compute_signal_threshold and classify_transition
2. **Task 2: select_boundary_transitions orchestration**
   - `99593be` test(04-04): add failing tests for select_boundary_transitions orchestration
   - `fc8d907` feat(04-04): implement select_boundary_transitions orchestration
3. **Task 3: select-transitions CLI subcommand**
   - `3bf9de9` test(04-04): add failing tests for select-transitions CLI subcommand
   - `7fda3f0` feat(04-04): add select-transitions CLI subcommand

**Plan metadata:** committed separately (docs commit) after this SUMMARY.md finalization.

## Files Created/Modified
- `scripts/transitions.py` — added `compute_signal_threshold`, `classify_transition`, `select_boundary_transitions`, `_cmd_select_transitions`, and the `select-transitions` argparse subcommand; `main()` reworked from a single `parse_args()` call into the `add_subparsers`/`set_defaults(func=...)` pattern (jumpcuts.py precedent)
- `tests/test_transitions.py` — 20 new tests across the three tasks

## Decisions Made
- `classify_transition`'s "moderate motion" band (`motion_threshold/2 <= motion < motion_threshold`) is a deliberate discretionary construct (D-04): it's what makes `crossfade`/`whip_pan`/`glitch`/`mask_wipe` mutually exclusive and each independently reachable — a literal reading of 04-RESEARCH.md's suggested signal-to-type mapping (Assumption A3) has overlapping conditions that would leave `crossfade` unreachable if "glitch" only required "at least moderate" (i.e. moderate-or-strong) motion
- `mask_wipe`'s "low similarity" framing needs no second magic-number threshold: by the time the moderate-motion+weak-audio branch is reached, similarity (if present) already scored below `match_cut_similarity`, since step 1 (`similarity >= match_cut_similarity -> match_cut`) would have already returned otherwise
- `select_boundary_transitions` imports `scripts.frames.extract_frames` and `scripts.jumpcuts.compute_boundary_gaps` at module top level — the first cross-script import in this codebase — since the plan's interface contract explicitly requires both; safe because both source modules are themselves stdlib-only with no optional-dependency risk, preserving transitions.py's cv2/librosa-free import-safety contract from 04-03
- `config_fields` is a plain dict of the 4 tunable knobs rather than a `TransitionsConfig` instance, since `scripts/*.py` modules never import `scripts/config.py` at runtime (project Anti-Pattern) — the CLI subcommand duplicates `TransitionsConfig`'s literal defaults as module-level constants instead, with a comment noting the duplication and why
- `_cmd_select_transitions` accepts an injectable `runner=subprocess.run` parameter beyond the jumpcuts.py/audio_energy.py `main()` precedent, specifically so the CLI handler is directly unit-testable by calling it with a stub `argparse.Namespace` (per the plan's Task 3 action), without shelling out to a real subprocess

## Deviations from Plan

None — plan executed exactly as written. All three functions and the CLI subcommand match the plan's `<action>` blocks; the only implementation-detail choices made were the ones D-02/D-04 explicitly delegated to planner/implementer discretion (percentile algorithm, exact decision-tree branch shape, CLI flag defaults).

## Issues Encountered
- Environment quirk (pre-existing, documented in STATE.md Blockers): default pytest temp dir is permission-locked on this machine; ran every test with `--basetemp=D:/shorts-maker/.pytest-tmp`. Unrelated to any code change in this plan.
- System `python` on PATH is not the project's `.venv` (cv2/librosa import successfully under `.venv/Scripts/python.exe` but not under the bare `python` command) — all test runs in this plan used `.venv/Scripts/python.exe -m pytest` explicitly to exercise the real-score code paths rather than skip them.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness
- 04-05 (render fold) can now call `select_boundary_transitions` to get a `boundary_transitions` list per clip and fold it into `build_jumpcut_command`'s concat/xfade restructuring — the function is generic over any `keep_segments` list, not jumpcut-splice-specific, so Phase 5's cross-clip compilation can reuse it unchanged
- 04-06 (SKILL orchestration) can invoke the `select-transitions` CLI subcommand exactly per the plan's interface contract: `python -m scripts.transitions select-transitions <video> <keep_segments_json> <out_json>`, capturing the printed `out_json` path and reading the written JSON list as `boundary_transitions` for `PLAN.json`
- No blockers. The classifier/orchestrator/CLI are fully import-safe and fail-open without cv2/librosa, consistent with every other optional feature in this codebase

---
*Phase: 04-context-driven-transitions*
*Completed: 2026-07-09*

## Self-Check: PASSED

- FOUND: scripts/transitions.py, tests/test_transitions.py, .planning/phases/04-context-driven-transitions/04-04-SUMMARY.md
- FOUND: commits 72850db, 1240b28, 99593be, fc8d907, 3bf9de9, 7fda3f0 (`git log --oneline --all`)
