---
phase: 04-context-driven-transitions
plan: 05
subsystem: infra
tags: [transitions, render, ffmpeg, xfade, filter-graph, jumpcuts]

# Dependency graph
requires:
  - phase: 04-context-driven-transitions
    provides: "TransitionsConfig + compute_boundary_gaps (04-02); TRANSITION_TYPES canonical enum (04-03); classify_transition/select_boundary_transitions producing boundary_transitions lists (04-04)"
provides:
  - "scripts/render.py: VALID_TRANSITIONS frozenset (drift-guarded against scripts.transitions.TRANSITION_TYPES), build_transition_filter pure helper (xfade fragment per transition type), reworked build_jumpcut_command (hybrid flat-concat / sequential-fold with gap-borrowed overlap), render_clip wiring for plan_entry['boundary_transitions'], --transition-duration/--min-overlap-seconds CLI flags"
  - "tests/test_render.py: per-type filter-fragment tests, enum-drift guard, forced-non-cut fold tests, render_clip wiring tests - 26 new tests, all pre-existing assertions preserved unmodified"
affects: [04-06-skill-orchestration, phase-5-compilation]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "build_transition_filter follows build_video_effects_chain/build_punch_zoom_filter shape exactly: validate up front (RenderError on invalid enum/duration/offset), build the filter string from internally-computed floats + enum-constrained type name only (V5), return None for cut/match_cut"
    - "_build_transition_fold: sequential pairwise fold (concat=n=2 for cut/match_cut/gap-too-small boundaries, xfade+acrossfade for real transitions) replacing the flat N-ary concat only when at least one boundary needs it - the flat path is left byte-identical and untouched for the common all-cut case"
    - "Overlap borrowing: xfade duration is clamp(min(transition_duration, gap), min_overlap_seconds, transition_duration), split symmetrically into the adjacent segments' trims, always <= the boundary's own gap so a transition never eats real kept content"

key-files:
  created: []
  modified:
    - scripts/render.py
    - tests/test_render.py

key-decisions:
  - "VALID_TRANSITIONS is a duplicated frozenset (not an import of scripts.transitions.TRANSITION_TYPES) so render.py stays runnable as a standalone CLI without a sys.path insert; a dedicated drift-guard test imports both and asserts equality"
  - "build_transition_filter takes plain (unbracketed) label names for in_a/in_b/out_label and wraps them in brackets internally, matching the existing trim_stages label convention (v{index}/a{index}) used elsewhere in build_jumpcut_command"
  - "The hybrid branch decision in build_jumpcut_command is `boundary_transitions is not None and any(t not in (cut, match_cut) for t in boundary_transitions)` - explicit all-cut/all-match_cut boundary_transitions lists take the exact same flat-concat code path as boundary_transitions=None, verified by a dedicated equality test against the omitted-param case"
  - "d_eff clamp order is min(transition_duration, gap) then max(min_overlap_seconds, ...) - since a boundary only reaches the fold path when gap >= min_overlap_seconds is already true, the floor clamp is a no-op safety net, not a live branch"
  - "render_clip validates boundary_transitions length against len(keep_segments)-1 before computing gaps, mirroring the fail-loud validation style of the existing punch_zoom/crop_style check a few lines above it"
  - "compute_boundary_gaps is lazily imported inside render_clip using the exact same sys.path-insert pattern already used for scripts.subtitles a few lines up, rather than a module-top-level import - keeps render.py's existing lazy cross-script import convention for this function"

patterns-established:
  - "Sequential-fold filter-graph construction for a mixed cut/xfade boundary list - reusable shape for Phase 5's cross-clip compilation stitching, which the plan's interface contract explicitly calls out as a Phase 5 consumer"

requirements-completed: [TRANS-02, TRANS-03]

coverage:
  - id: D1
    description: "build_transition_filter returns a valid ffmpeg xfade-based video fragment for crossfade/whip_pan/mask_wipe/glitch, None for cut/match_cut, and raises RenderError on any type not in the fixed 6-item enum"
    requirement: "TRANS-02"
    verification:
      - kind: unit
        ref: "tests/test_render.py#test_build_transition_filter_crossfade_returns_xfade_fade_node"
        status: pass
      - kind: unit
        ref: "tests/test_render.py#test_build_transition_filter_whip_pan_returns_xfade_hblur_node"
        status: pass
      - kind: unit
        ref: "tests/test_render.py#test_build_transition_filter_mask_wipe_returns_xfade_wipeleft_node"
        status: pass
      - kind: unit
        ref: "tests/test_render.py#test_build_transition_filter_glitch_returns_pixelize_chain_with_rgbashift_and_noise"
        status: pass
      - kind: unit
        ref: "tests/test_render.py#test_build_transition_filter_cut_returns_none"
        status: pass
      - kind: unit
        ref: "tests/test_render.py#test_build_transition_filter_match_cut_returns_none"
        status: pass
      - kind: unit
        ref: "tests/test_render.py#test_build_transition_filter_rejects_unknown_transition_type"
        status: pass
      - kind: unit
        ref: "tests/test_render.py#test_valid_transitions_matches_transitions_module_canonical_enum"
        status: pass
    human_judgment: false
  - id: D2
    description: "build_jumpcut_command produces byte-identical output to today when boundary_transitions is None or every boundary is cut/match_cut - all pre-existing test_render.py assertions stay green unmodified"
    requirement: "TRANS-02"
    verification:
      - kind: unit
        ref: "tests/test_render.py#test_build_jumpcut_command_single_segment_matches_plain_trim_concat"
        status: pass
      - kind: unit
        ref: "tests/test_render.py#test_build_jumpcut_command_multiple_segments_trims_and_concats_each"
        status: pass
      - kind: unit
        ref: "tests/test_render.py#test_build_jumpcut_command_applies_denoise_loudnorm_and_fade_to_acat"
        status: pass
      - kind: unit
        ref: "tests/test_render.py#test_build_jumpcut_command_all_cut_boundary_transitions_matches_flat_concat"
        status: pass
      - kind: unit
        ref: "tests/test_render.py#test_build_jumpcut_command_all_match_cut_boundary_transitions_matches_flat_concat"
        status: pass
      - kind: unit
        ref: "tests/test_render.py#test_render_clip_uses_jumpcut_command_when_keep_segments_present"
        status: pass
    human_judgment: false
  - id: D3
    description: "A boundary requesting a non-cut transition with sufficient borrowed gap emits xfade+acrossfade whose trims extend into the pause gap, never into real kept content"
    requirement: "TRANS-02"
    verification:
      - kind: unit
        ref: "tests/test_render.py#test_build_jumpcut_command_forced_crossfade_transition_emits_xfade_and_acrossfade"
        status: pass
      - kind: unit
        ref: "tests/test_render.py#test_build_jumpcut_command_forced_whip_pan_transition_emits_hblur"
        status: pass
      - kind: unit
        ref: "tests/test_render.py#test_build_jumpcut_command_forced_glitch_transition_emits_pixelize_and_rgbashift"
        status: pass
      - kind: other
        ref: "manual real-ffmpeg smoke test: crossfade/whip_pan/mask_wipe/glitch boundary_transitions each rendered end-to-end via render_clip against a real synthetic fixture video, ffprobe-verified 4.0s duration (2s+2s segments minus 0.35s borrowed overlap) and correct 1080x1920 dimensions - confirms the filter graph is not just string-shaped correctly but actually valid, executable ffmpeg syntax"
        status: pass
    human_judgment: false
  - id: D4
    description: "A boundary whose borrowable gap is below min_overlap_seconds falls back to a plain cut join even if a non-cut type was requested"
    requirement: "TRANS-03"
    verification:
      - kind: unit
        ref: "tests/test_render.py#test_build_jumpcut_command_transition_falls_back_to_concat_when_gap_below_min_overlap"
        status: pass
      - kind: other
        ref: "manual real-ffmpeg smoke test: render_clip called with min_overlap_seconds=5.0 against a 2.0s real gap - filter_complex confirmed to contain concat=n=2 and no xfade node"
        status: pass
    human_judgment: false
  - id: D5
    description: "render_clip reads plan_entry['boundary_transitions'], computes boundary_gaps via scripts.jumpcuts.compute_boundary_gaps, threads them plus transition_duration/min_overlap_seconds into build_jumpcut_command; a wrong-length boundary_transitions raises RenderError; plans without the key render exactly as before; CLI gains --transition-duration/--min-overlap-seconds"
    requirement: "TRANS-02"
    verification:
      - kind: unit
        ref: "tests/test_render.py#test_render_clip_threads_boundary_transitions_into_jumpcut_command"
        status: pass
      - kind: unit
        ref: "tests/test_render.py#test_render_clip_rejects_boundary_transitions_wrong_length"
        status: pass
      - kind: unit
        ref: "tests/test_render.py#test_render_clip_uses_jumpcut_command_when_keep_segments_present"
        status: pass
    human_judgment: false

# Metrics
duration: 7min
completed: 2026-07-09
status: complete
---

# Phase 4 Plan 05: Render Layer Transition Rendering Summary

**scripts/render.py now renders all 6 transition types via a new build_transition_filter helper and a hybrid flat-concat/sequential-fold build_jumpcut_command that borrows xfade overlap from the boundary's pause gap, with render_clip wiring plan_entry['boundary_transitions'] end to end while leaving today's all-cut render byte-identical.**

## Performance

- **Duration:** ~7 min (from first commit to last)
- **Started:** 2026-07-09T19:20:47+03:00
- **Completed:** 2026-07-09T19:26:52+03:00
- **Tasks:** 3/3 completed
- **Files modified:** 2 (scripts/render.py, tests/test_render.py)

## Accomplishments
- `VALID_TRANSITIONS` — a module-level frozenset in `render.py` mirroring `scripts.transitions.TRANSITION_TYPES`, duplicated (not imported) so `render.py` stays runnable as a standalone CLI without a `sys.path` insert; drift-guarded by `test_valid_transitions_matches_transitions_module_canonical_enum`
- `build_transition_filter` — pure, enum-validated helper returning the ffmpeg xfade video-graph node for `crossfade`/`whip_pan`/`mask_wipe` (native `xfade` transitions `fade`/`hblur`/`wipeleft`) and `glitch` (pixelize xfade + `rgbashift` + `noise` chain per 04-RESEARCH.md Pattern 4); returns `None` for `cut`/`match_cut`; raises `RenderError` on an unknown type or non-positive duration/negative offset
- `_build_transition_fold` — new private helper implementing the sequential pairwise fold: cut/match_cut boundaries (and any non-cut boundary whose gap is below `min_overlap_seconds`) join via `concat=n=2`; a real transition boundary extends the adjacent segments' trims symmetrically into the borrowed pause gap and joins via `build_transition_filter` (video) + `acrossfade=d=<duration>` (audio)
- `build_jumpcut_command` reworked into a hybrid: when `boundary_transitions` is `None` or every entry is `cut`/`match_cut`, the exact original flat trim + `concat=n=N` code path runs untouched — verified byte-identical against both the omitted-param case and against every pre-existing exact-string test assertion (single-segment `concat=n=1`, two-segment `concat=n=2`, denoise/loudnorm/fade-on-`[acat]` placement)
- `render_clip` reads `plan_entry.get("boundary_transitions")`, validates its length against `len(keep_segments) - 1` (`RenderError` on mismatch), lazily imports `scripts.jumpcuts.compute_boundary_gaps`, and threads `boundary_transitions`/`boundary_gaps`/`transition_duration`/`min_overlap_seconds` into `build_jumpcut_command`; plans without the key are unaffected
- `main()` gains `--transition-duration`/`--min-overlap-seconds` CLI flags (defaults 0.35/0.12, matching `TransitionsConfig`) for the 04-06 orchestrator to pass through
- Full TDD RED→GREEN cycle per task (3 test-then-feat commit pairs)
- Beyond the plan's unit-test coverage, ran ad hoc real-ffmpeg smoke tests (not committed as new integration tests — out of this plan's task list) against a real synthetic fixture: crossfade/whip_pan/mask_wipe/glitch boundaries all rendered successfully end-to-end via `render_clip`, ffprobe confirmed correct duration (borrowed-overlap math verified: 2s+2s segments minus 0.35s xfade = 4.0s) and correct 1080x1920 output dimensions; also confirmed the gap-too-small fallback produces a plain `concat=n=2` with no `xfade` node when driven through real ffmpeg

## Task Commits

TDD RED→GREEN per task, matching the 04-02/04-03/04-04 precedent:

1. **Task 1: build_transition_filter helper + VALID_TRANSITIONS enum + drift guard**
   - `0e5cb5a` test(04-05): add failing tests for build_transition_filter + VALID_TRANSITIONS drift guard
   - `3b035af` feat(04-05): implement build_transition_filter + VALID_TRANSITIONS enum
2. **Task 2: build_jumpcut_command hybrid flat-concat / sequential-fold with gap-borrowed overlap**
   - `0aac757` test(04-05): add failing tests for build_jumpcut_command hybrid fold
   - `fdbde36` feat(04-05): implement build_jumpcut_command hybrid flat-concat / sequential-fold
3. **Task 3: render_clip wiring + CLI flags**
   - `ee386f6` test(04-05): add failing tests for render_clip boundary_transitions wiring
   - `5020c47` feat(04-05): wire render_clip + CLI flags for boundary_transitions

**Plan metadata:** committed separately (docs commit) after this SUMMARY.md finalization.

## Files Created/Modified
- `scripts/render.py` — added `VALID_TRANSITIONS`, `_XFADE_TRANSITION_NAMES`, `build_transition_filter`, `_build_transition_fold`; reworked `build_jumpcut_command` (new params `boundary_transitions`/`boundary_gaps`/`transition_duration`/`min_overlap_seconds`, hybrid branch); reworked `render_clip` (reads `plan_entry['boundary_transitions']`, validates length, computes gaps, new params `transition_duration`/`min_overlap_seconds`); `main()` gained two new CLI flags
- `tests/test_render.py` — 26 new tests across the three tasks (10 for `build_transition_filter`/drift-guard, 7 for the hybrid fold including two explicit backward-compat equality tests, 2 for `render_clip` wiring), all pre-existing tests unmodified

## Decisions Made
- `VALID_TRANSITIONS` is a duplicated frozenset rather than an import of `scripts.transitions.TRANSITION_TYPES`, so `render.py` stays runnable as a standalone CLI (`python scripts/render.py`) without a `sys.path` insert to reach `scripts.transitions` — drift-guarded by a dedicated test rather than relying on manual sync discipline
- `build_transition_filter` takes plain (unbracketed) label names for `in_a`/`in_b`/`out_label` and wraps them in brackets internally, matching the existing `trim_stages` label convention (`v{index}`/`a{index}`) already used throughout `build_jumpcut_command`
- The hybrid branch decision is `boundary_transitions is not None and any(t not in (cut, match_cut) for t in boundary_transitions)` — an explicit all-`cut` or all-`match_cut` `boundary_transitions` list takes the exact same flat-concat code path as omitting the parameter entirely, verified by two dedicated equality tests (`test_build_jumpcut_command_all_cut_boundary_transitions_matches_flat_concat`, `..._all_match_cut_...`) rather than just trusting the branch logic
- `d_eff`'s clamp order is `min(transition_duration, gap)` then `max(min_overlap_seconds, ...)` — since the fold path is only reached after confirming `gap >= min_overlap_seconds`, the floor clamp is a defensive no-op rather than a live branch, kept for correctness/readability per the plan's literal `clamp(...)` formula
- `render_clip` validates `boundary_transitions` length against `len(keep_segments) - 1` before computing gaps (fail loud, mirroring the existing `punch_zoom_at`/`crop_style` validation a few lines above it), and lazily imports `compute_boundary_gaps` using the exact same `sys.path`-insert pattern already used for `scripts.subtitles` a few lines up in the same function
- Total output duration for the fold branch is computed as the fold's own accumulated duration (each xfade genuinely shortens the output by its overlap), not the naive sum of segment durations — this feeds `compute_fade_plan` so a trailing fade-out lands at the correct real output timestamp

## Deviations from Plan

None — plan executed exactly as written. All three tasks' `<action>` blocks were implemented per spec: `build_transition_filter`'s dispatch table, the fold's cut/xfade branch structure, and `render_clip`'s validation-then-gap-computation-then-threading sequence all match the plan text precisely.

**Beyond-scope verification (not a deviation, additive only):** ran manual real-ffmpeg smoke tests exercising all 4 xfade-backed transition types plus the gap-fallback path end-to-end (not committed as new automated integration tests, since 04-RESEARCH.md's Wave 0 Gaps lists a real-render integration test as a possible future addition, not a task this plan's `<tasks>` block requires) — done for extra confidence that the filter-graph strings are not just shaped correctly but are genuinely valid, executable ffmpeg syntax before handing this off to 04-06's orchestration wiring.

## Issues Encountered

- Environment quirk (pre-existing, documented in STATE.md Blockers): default pytest temp dir is permission-locked on this machine. Ran every test with `--basetemp=D:/shorts-maker/.pytest-tmp`. Unrelated to any code change in this plan.
- Full non-integration suite run (`pytest -m "not integration"`): 382 passed, 0 new failures. The same 3 pre-existing `tests/test_publish_queue.py` failures (missing `googleapiclient`, documented in `deferred-items.md`, out of scope) remain unchanged.
- Full `tests/test_integration_ffmpeg.py` run (real ffmpeg, `integration`-marked): 7 passed, confirming the untouched flat-concat path still executes correctly against a real fixture video after the rework.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness
- `build_transition_filter` and `_build_transition_fold` are generic pure functions over any `keep_segments`/`boundary_transitions` list — not jumpcut-splice-specific — so Phase 5's cross-clip compilation stitching (which the plan's interface contract explicitly calls out as a consumer) can reuse them unchanged
- 04-06 (SKILL orchestration) can now inject `boundary_transitions` (from 04-04's `select_boundary_transitions`) directly into a `PLAN.json` entry alongside `keep_segments`; `render.py` will thread it through automatically with zero further render.py changes needed, and pass `--transition-duration`/`--min-overlap-seconds` through to `render.py`'s CLI from `config.transitions`
- No blockers. The all-cut/no-transition render path is verified byte-identical to pre-phase behavior (every pre-existing `test_render.py` assertion passes unmodified), so existing plans with `keep_segments` but no `boundary_transitions` key are completely unaffected by this rework

---
*Phase: 04-context-driven-transitions*
*Completed: 2026-07-09*

## Self-Check: PASSED

- FOUND: scripts/render.py, tests/test_render.py, .planning/phases/04-context-driven-transitions/04-05-SUMMARY.md
- FOUND: commits 0e5cb5a, 3b035af, 0aac757, fdbde36, ee386f6, 5020c47 (`git log --oneline --all`)
