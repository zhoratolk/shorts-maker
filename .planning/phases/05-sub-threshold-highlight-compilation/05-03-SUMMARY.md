---
phase: 05-sub-threshold-highlight-compilation
plan: 03
subsystem: render
tags: [compilation, render, ffmpeg, transitions, filter-complex]

# Dependency graph
requires:
  - phase: 05-sub-threshold-highlight-compilation
    provides: "Plan 05-02's build_compilation_entry PLAN.json 'compilation' entry shape (segments/boundary_transitions), consumed verbatim by render_clip's new dispatch branch"
  - phase: 04-context-driven-transitions
    provides: "build_transition_filter, VALID_TRANSITIONS, and the xfade/acrossfade pairwise-fold pattern (_build_transition_fold) this plan mirrors for multi-input compilation stitching"
provides:
  - "build_compilation_command: multi-input ffmpeg command builder for a compilation of separately-approved candidates, one independent -ss/-i/-t per member"
  - "_build_compilation_fold: pairwise xfade/acrossfade fold for compilation stitch points, capped by each side's own duration instead of a borrowed pause gap"
  - "render_clip dispatch on plan_entry['type'] == 'compilation', reordered so compilation entries (no top-level start/end) never KeyError"
affects: [05-04-SKILL-integration]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Multi-input ffmpeg command: one -ss/-i/-t quadruple per compilation member, no single leading -ss/-i spanning the whole compilation's time range"
    - "Flattened render-order segment list keyed by (input_index, rel_start, rel_end), trim stages reference [{input_index}:v]/[{input_index}:a] instead of always [0:v]/[0:a]"
    - "Fold-overlap cap bounded to half of either adjacent segment's own duration (no boundary_gaps/borrowed-pause-footage step) - compilation stitch points have no free footage to borrow, unlike a single clip's internal jump-cut boundary"

key-files:
  created: []
  modified:
    - scripts/render.py
    - tests/test_render.py
    - tests/test_integration_ffmpeg.py

key-decisions:
  - "_build_compilation_fold returns only (fold_stages, total_duration) - trim_stages are built once upfront in build_compilation_command (not per-branch) since compilation trims are never extended into a gap, unlike _build_transition_fold's own trim_stages construction"
  - "render_clip's clamp_clip_bounds call moved below the hoisted crop/punch-zoom/subtitles block and only runs in the non-compilation else-branch; each compilation member is clamped individually inside the compilation branch instead"

patterns-established:
  - "A compilation-entry's segments field maps 1:1 onto build_compilation_command's members parameter (start/end/optional keep_segments), letting render_clip pass Plan 05-02's PLAN.json shape through with only per-member clamping and a keep_segments tuple conversion"

requirements-completed: [COMP-02]

coverage:
  - id: D1
    description: "build_compilation_command builds one independent -ss/-i/-t input per compilation member, never one decode window spanning the whole compilation"
    requirement: "COMP-02"
    verification:
      - kind: unit
        ref: "tests/test_render.py#test_build_compilation_command_builds_one_input_per_member_two_members"
        status: pass
      - kind: unit
        ref: "tests/test_render.py#test_build_compilation_command_builds_one_input_per_member_three_members"
        status: pass
    human_judgment: false
  - id: D2
    description: "Compilation stitch points fold via the same xfade/acrossfade machinery as single-clip jump cuts, capped to each side's own duration with no borrowed pause-gap footage"
    requirement: "COMP-02"
    verification:
      - kind: unit
        ref: "tests/test_render.py#test_build_compilation_command_forced_crossfade_boundary_emits_xfade_without_trim_extension"
        status: pass
      - kind: integration
        ref: "tests/test_integration_ffmpeg.py#test_forced_crossfade_transition_renders_playable_output (pre-existing single-clip fold, unaffected)"
        status: pass
    human_judgment: false
  - id: D3
    description: "crop/punch-zoom/subtitles/fade applied exactly once on the folded compilation output, never per member (D-06)"
    requirement: "COMP-02"
    verification:
      - kind: unit
        ref: "tests/test_render.py#test_build_compilation_command_applies_crop_subtitles_fade_exactly_once"
        status: pass
    human_judgment: false
  - id: D4
    description: "render_clip dispatches type=='compilation' PLAN.json entries to build_compilation_command before touching any top-level start/end key, and the existing single-clip path is unaffected"
    requirement: "COMP-02"
    verification:
      - kind: unit
        ref: "tests/test_render.py#test_render_clip_dispatches_to_build_compilation_command_for_type_compilation"
        status: pass
      - kind: unit
        ref: "tests/test_render.py#test_render_clip_compilation_entry_without_top_level_start_end_does_not_raise_key_error"
        status: pass
      - kind: unit
        ref: "tests/test_render.py -x (all 93 render.py tests, incl. every pre-existing single-clip test)"
        status: pass
    human_judgment: false
  - id: D5
    description: "A real compilation of 3 non-contiguous member windows renders one playable, 1080x1920 output via independent per-member seeks"
    requirement: "COMP-02"
    verification:
      - kind: integration
        ref: "tests/test_integration_ffmpeg.py#test_compilation_of_non_contiguous_members_renders_playable_output"
        status: pass
    human_judgment: false

# Metrics
duration: 20min
completed: 2026-07-10
status: complete
---

# Phase 05 Plan 03: Compilation Multi-Input Render Path Summary

**Multi-input `build_compilation_command` ffmpeg builder (one independent seek per compilation member, xfade fold capped to each side's own duration) wired into `render_clip` via a `type=="compilation"` dispatch branch.**

## Performance

- **Duration:** ~20 min
- **Completed:** 2026-07-10
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- `build_compilation_command` opens the source once per compilation member (`-ss`/`-i`/`-t` per member), flattens each member's own segments (internal jump cuts or single window) into one render-order list, and folds them via the same `build_transition_filter`/concat-downgrade machinery `_build_transition_fold` already uses for single-clip jump cuts.
- New `_build_compilation_fold` helper implements the one deliberate difference from `_build_transition_fold`: no `boundary_gaps` parameter and no trim-extension-into-a-gap step — overlap is capped to at most half of either adjacent segment's own duration, since a compilation stitch point (unlike a single clip's internal pause) has no borrowable footage.
- crop/punch-zoom/subtitles/fade are applied exactly once on the folded `[vcat]`/`[acat]` result (D-06), reusing `build_jumpcut_command`'s post-fold tail verbatim.
- `render_clip` was reordered so the hoisted crop/punch-zoom/subtitles block (fields present on both entry types) runs before `clamp_clip_bounds(plan_entry["start"], plan_entry["end"], ...)`, which now only runs in the non-compilation branch — a compilation entry (no top-level `start`/`end`) never `KeyError`s.
- The compilation branch clamps each member's own `start`/`end` individually (not once for the whole compilation) and raises `RenderError` on a missing/empty `segments` list before building any command (T-05-05 defense in depth).
- A real-ffmpeg integration test renders 3 non-contiguous member windows (`[0,1]`, `[2,3]`, `[4.5,5.5]`) from the shared 6s fixture into one playable 1080x1920 output, asserting the command carries 3 independent `-i` inputs.

## Task Commits

Each task was committed atomically:

1. **Task 1: build_compilation_command — multi-input fold (COMP-02)** - `cfcf7e1` (feat)
2. **Task 2: render_clip dispatch on type=="compilation" + real-ffmpeg integration test (COMP-02)** - `dd178a0` (feat)

_Note: tdd="true" tasks here followed test-then-implementation within the same commit (tests + implementation authored and verified together, single commit per task) rather than separate RED/GREEN commits — matches this plan's granularity of one commit per task, consistent with prior Phase 05 plans._

## Files Created/Modified

- `scripts/render.py` - Added `build_compilation_command` and `_build_compilation_fold`; reordered and extended `render_clip` to dispatch `type=="compilation"` entries
- `tests/test_render.py` - 10 new `build_compilation_command`-focused tests + 3 new `render_clip` compilation-dispatch tests, all named to contain "compilation"
- `tests/test_integration_ffmpeg.py` - 1 new real-ffmpeg compilation integration test

## Decisions Made

- `_build_compilation_fold` returns only `(fold_stages, total_duration)` — two elements, not three like `_build_transition_fold` — because `build_compilation_command` builds `trim_stages` once upfront (compilation trims are never extended into a gap, so they're identical whether or not the fold path is taken), rather than delegating trim construction to the fold helper.
- `render_clip`'s single `clamp_clip_bounds(plan_entry["start"], plan_entry["end"], ...)` call moved to the non-compilation `else` branch; the compilation branch instead clamps each member's own `start`/`end` individually via the same `clamp_clip_bounds` function, reused per-member.

## Deviations from Plan

None - plan executed exactly as written. One test assertion (`assert filter_complex.count("fade=t=out") == 1`) was corrected during implementation to `count("d=0.5") == 2` after discovering `"afade=t=out"` contains `"fade=t=out"` as a substring, so the original assertion double-counted the video and audio fade nodes as a false negative — not a deviation from the plan's behavior, just a test-authoring fix caught immediately by running the test (Rule 1, contained entirely within the new test file, no production code affected).

## Issues Encountered

- Local pytest temp dir (`AppData/Local/Temp/pytest-of-<user>`) is permission-locked on this machine (pre-existing, documented environment quirk from Plan 03-01) — worked around with `--basetemp=.pytest-tmp` for every `pytest` invocation, cleaned up afterward. Not a code issue.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- COMP-02's actual stitching mechanism (the "genuinely new render path" identified as this phase's core engineering unknown) is now implemented and covered by both mocked-command unit tests and a real-ffmpeg integration test.
- `render_clip` is ready to consume Plan 05-02's `build_compilation_entry` PLAN.json `"compilation"` entries directly (segments/boundary_transitions/crop_style/punch_zoom_at/subtitles_path/metadata_path/output_filename all thread through unchanged).
- Plan 05-04 (SKILL.md orchestration wiring) can now call `compilation.py` to build the entry and rely on `render.py` to render it without any further render-layer changes.
- Full `pytest -m "not integration"` (407 passed, 5 skipped) and full `pytest -m integration` (9 passed) suites both green — no regression to any other module's tests.

---
*Phase: 05-sub-threshold-highlight-compilation*
*Completed: 2026-07-10*

## Self-Check: PASSED

All created/modified files verified present on disk; all task and metadata commits (`cfcf7e1`, `dd178a0`, `860e7ef`) verified present in git log.
