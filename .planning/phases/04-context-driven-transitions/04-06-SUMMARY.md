---
phase: 04-context-driven-transitions
plan: 06
subsystem: infra
tags: [transitions, orchestration, integration, end-to-end]

# Dependency graph
requires:
  - phase: 04-context-driven-transitions
    provides: "select-transitions CLI + select_boundary_transitions fail-open orchestration (04-04); render_clip boundary_transitions wiring + --transition-duration/--min-overlap-seconds CLI flags (04-05)"
provides:
  - ".claude/skills/make-shorts/SKILL.md: Context-driven transitions orchestration step (automatic, config-gated, fail-open) between the Jump cuts and Punch-zoom steps; boundary_transitions in the PLAN.json schema; render.py invocation gains --transition-duration/--min-overlap-seconds"
  - "tests/test_integration_ffmpeg.py: test_forced_crossfade_transition_renders_playable_output - real-ffmpeg proof that a forced non-cut boundary renders a playable, correctly-dimensioned clip"
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "SKILL.md orchestration step follows the exact 1c/1d fail-open wording pattern (diarization/audio-energy): tell the user why in one line, omit the optional field, continue - never abort the clip"

key-files:
  created: []
  modified:
    - .claude/skills/make-shorts/SKILL.md
    - tests/test_integration_ffmpeg.py

key-decisions:
  - ".claude/ is gitignored project-wide (confirmed via git check-ignore), so the SKILL.md edit lives on disk only, not in git history - same pre-existing repo convention documented in 02-01-SUMMARY.md, not a regression introduced by this plan"
  - "Test forces boundary_transitions=[\"crossfade\"] directly on the plan_entry rather than calling select_boundary_transitions/cv2/librosa - isolates the render-layer xfade fold path (04-05) from the analysis layer (04-04), per the plan's explicit instruction not to import cv2/librosa in this test"
  - "Test asserts both filter-graph shape (xfade=transition=fade present, proving the fold branch was taken instead of a plain concat) and real-encode output (1080x1920 video stream + an audio stream) - a string assertion alone can't catch a malformed xfade offset, only a real ffmpeg encode can"

patterns-established: []

requirements-completed: [TRANS-01, TRANS-02, TRANS-03]

coverage:
  - id: D1
    description: "SKILL.md's transition step is gated on config.transitions.enabled AND multi-segment keep_segments, calls select-transitions with all four threshold flags, injects boundary_transitions into PLAN.json as a documented optional field, and is fully automatic (no CANDIDATES.md review gate, D-03)"
    requirement: "TRANS-01"
    verification:
      - kind: other
        ref: "SKILL.md review: Context-driven transitions step (Jump cuts step, boundary between it and Punch-zoom) gated on config.transitions.enabled + len(keep_segments) > 1; select-transitions invocation with --transition-duration/--min-overlap-seconds/--strong-signal-percentile/--match-cut-similarity; boundary_transitions recorded verbatim in the plan entry; PLAN.json schema block documents boundary_transitions as optional with the len(keep_segments)-1 invariant; render.py invocation gains --transition-duration/--min-overlap-seconds"
        status: pass
    human_judgment: true
  - id: D2
    description: "SKILL.md's transition step is fail-open: an error omits boundary_transitions and logs, never aborts the clip"
    requirement: "TRANS-03"
    verification:
      - kind: other
        ref: "SKILL.md review: 'Fail open, do not abort the clip' paragraph mirrors the 1c/1d diarization/audio-energy wording exactly - tell the user why in one line, omit boundary_transitions, continue render as all-cut for this clip"
        status: pass
    human_judgment: true
  - id: D3
    description: "A real ffmpeg render of a forced non-cut boundary (crossfade) produces a playable 1080x1920 output with the xfade fold path actually taken"
    requirement: "TRANS-01"
    verification:
      - kind: integration
        ref: "tests/test_integration_ffmpeg.py::test_forced_crossfade_transition_renders_playable_output"
        status: pass
    human_judgment: false

# Metrics
duration: 6min
completed: 2026-07-09
status: complete
---

# Phase 4 Plan 06: Skill Orchestration & Integration Verification Summary

**SKILL.md now automatically runs select-transitions (fail-open, no review gate) on every multi-segment clip when config.transitions.enabled, injecting boundary_transitions into PLAN.json and passing the two threshold flags to render.py; a new real-ffmpeg integration test proves a forced crossfade boundary renders a playable 1080x1920 clip via the actual xfade fold path — closing TRANS-01/02/03 end-to-end and completing Phase 4.**

## Performance

- **Duration:** ~6 min
- **Started:** 2026-07-09T19:28:00+03:00 (approx.)
- **Completed:** 2026-07-09T19:34:00+03:00
- **Tasks:** 2/2 completed
- **Files modified:** 2 (.claude/skills/make-shorts/SKILL.md, tests/test_integration_ffmpeg.py)

## Accomplishments
- **SKILL.md** gained a "Context-driven transitions" step, inserted between the existing Jump cuts and Punch-zoom steps in the Refine (pass 2) section — gated on `config.transitions.enabled` **and** the clip's `keep_segments` having more than one `[start, end]` pair. It calls `python scripts/transitions.py select-transitions "<video>" <keep_json> <out_json>` with all four threshold flags (`--transition-duration`, `--min-overlap-seconds`, `--strong-signal-percentile`, `--match-cut-similarity`), then records the resulting JSON list verbatim as `boundary_transitions` in the plan entry — fully automatic, no `CANDIDATES.md` review/approval gate (D-03).
- The step is explicitly fail-open, worded to match the existing 1c/1d diarization/audio-energy pattern exactly: on any command error (cv2/librosa absent, ffmpeg analysis failure, etc.) tell the user why in one line, omit `boundary_transitions` from the plan entry, and continue — never abort the clip. `render.py` then falls back to today's all-cut splice for that clip (TRANS-03).
- The `PLAN.json` object schema (step 5's JSON block) gained `boundary_transitions` as an optional field, documented alongside `keep_segments`/`punch_zoom_at`/`subtitles_path`/`metadata_path` as omitted when unused, with an explicit note that it must have exactly one entry per boundary (`len(keep_segments) - 1`).
- The step 6 render invocation now appends `--transition-duration <config.transitions.transition_duration> --min-overlap-seconds <config.transitions.min_overlap_seconds>` (both flags already existed on `render.py`'s CLI from 04-05) — harmless for clips without `boundary_transitions`, meaningful for clips that have it.
- `tests/test_integration_ffmpeg.py` gained `test_forced_crossfade_transition_renders_playable_output`: renders `keep_segments=[[0.0, 2.0], [4.0, 6.0]]` with `boundary_transitions=["crossfade"]` against the fixture's real 2s silence gap via `render_clip` (real ffmpeg, no stub runner, no cv2/librosa — the transition type is forced directly), asserts the returned command's `-filter_complex` contains `xfade=transition=fade` (proving the sequential-fold path was taken, not a plain concat), and asserts the real rendered output is 1080x1920 with both a video and an audio stream (playable, via the `acrossfade` audio join). Selected by `pytest tests/test_integration_ffmpeg.py -x -m integration -k transition`.
- Full `tests/test_integration_ffmpeg.py` (real ffmpeg, `integration`-marked): 8 passed (7 pre-existing + 1 new), confirming no regression to the existing flat-concat/punch-zoom/vignette/full-pipeline paths.
- Full non-integration suite (`pytest -m "not integration"`): 382 passed, 0 new failures — same count as 04-05's baseline (the new test is `integration`-marked, so it doesn't add to this count). The same 3 pre-existing `test_publish_queue.py` failures (missing `googleapiclient`, documented in `deferred-items.md`, out of scope) remain unchanged.

## Task Commits

1. **Task 1: SKILL.md transition-selection orchestration step**
   - No commit — `.claude/` is gitignored project-wide (confirmed via `git check-ignore -v`), so this edit lives on disk only, not in git history. Same pre-existing repo convention as 02-01 (see 02-01-SUMMARY.md Deviations), not a regression.
2. **Task 2: End-to-end real-ffmpeg integration test for a rendered transition**
   - `e62fcd6` test(04-06): add real-ffmpeg integration test for forced crossfade boundary

**Plan metadata:** committed separately (docs commit) after this SUMMARY.md finalization.

## Files Created/Modified
- `.claude/skills/make-shorts/SKILL.md` — added the "Context-driven transitions" step (gated, fail-open, automatic, no review gate); added `boundary_transitions` to the `PLAN.json` schema block; appended `--transition-duration`/`--min-overlap-seconds` to the step 6 render invocation. Gitignored — disk-only, no git diff.
- `tests/test_integration_ffmpeg.py` — added `test_forced_crossfade_transition_renders_playable_output`

## Decisions Made
- `.claude/` is gitignored project-wide (verified with `git check-ignore -v .claude/skills/make-shorts/SKILL.md`), so the SKILL.md edit for Task 1 lives on disk only, not in git history — same pre-existing repo convention documented in 02-01-SUMMARY.md, not a regression introduced by this plan.
- The integration test forces `boundary_transitions=["crossfade"]` directly on the `plan_entry` rather than calling `select_boundary_transitions` (which needs cv2/librosa) — isolates the render-layer xfade fold path (04-05) from the analysis layer (04-04), per the plan's explicit instruction to avoid a cv2/librosa dependency in this test so it stays skippable purely on ffmpeg presence.
- The test asserts both the filter-graph shape (`xfade=transition=fade` present in `-filter_complex`, proving the fold branch — not a plain `concat` — was taken) and the real-encode output (1080x1920 video stream + an audio stream present) — a string assertion alone can't catch a malformed xfade offset/filter syntax, only a real ffmpeg encode can, which is exactly why this test exists per the plan's objective.

## Deviations from Plan

None — plan executed exactly as written. Both tasks' `<action>` blocks were implemented per spec: the SKILL.md step's gating/invocation/injection/fail-open wording, the PLAN.json schema addition, the render.py invocation update, and the integration test's plan_entry/assertions all match the plan text precisely.

## Issues Encountered
- Environment quirk (pre-existing, documented in STATE.md Blockers): default pytest temp dir is permission-locked on this machine. Ran every test with `--basetemp=D:/shorts-maker/.pytest-tmp`. Unrelated to any code change in this plan.
- The 3 pre-existing `tests/test_publish_queue.py` failures (missing `googleapiclient`, documented in `deferred-items.md`) remain, unrelated to this plan's changes — not attempted, per plan notes.

## User Setup Required

None — no external service configuration required. The `config.transitions.enabled` toggle remains off by default (D-01/conservative-by-default), so no behavior changes for existing users until they opt in.

## Next Phase Readiness
- Phase 4 (context-driven-transitions) is now complete: TRANS-01 (analyze + select a transition type at each boundary, wired into the real pipeline automatically) closes with this plan's SKILL.md orchestration step; TRANS-02 (6 transition types render correctly) and TRANS-03 (fail-open degradation) both have real-ffmpeg integration coverage on top of 04-04/04-05's unit coverage.
- Phase 5 (Compilation) can consume this same transition engine (`select_boundary_transitions`, `build_transition_filter`, `_build_transition_fold`) for cross-clip stitching — 04-04/04-05's SUMMARY.md both note these are generic pure functions over any `keep_segments`/`boundary_transitions` list, not jumpcut-splice-specific.
- No blockers.

---
*Phase: 04-context-driven-transitions*
*Completed: 2026-07-09*

## Self-Check: PASSED

- FOUND: .claude/skills/make-shorts/SKILL.md, tests/test_integration_ffmpeg.py, .planning/phases/04-context-driven-transitions/04-06-SUMMARY.md
- FOUND: commit e62fcd6 (`git log --oneline --all`)
