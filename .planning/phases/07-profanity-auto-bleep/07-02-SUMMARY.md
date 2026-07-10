---
phase: 07-profanity-auto-bleep
plan: 02
subsystem: media-render
tags: [ffmpeg, audio-filter, timeline-enable, render.py, duck-garble]

# Dependency graph
requires:
  - phase: 07-profanity-auto-bleep (Plan 01)
    provides: data/profanity_wordlist.yaml + detection module groundwork
provides:
  - build_profanity_mask_filter — pure ffmpeg filter-string builder for a time-windowed duck+garble mask (volume+bandreject+tremolo, enable-gated)
  - build_audio_filter_chain extended with an optional profanity_filter stage, inserted after loudnorm and before the tail fade
  - build_ffmpeg_command / build_jumpcut_command / build_compilation_command each pass a profanity_filter through to the audio chain
  - render_clip reads plan_entry["profanity_spans"] and threads the mask through the plain, jumpcut, and compilation branches
  - render.py CLI flags --profanity-duck-volume/--profanity-garble-freq/--profanity-garble-width-octaves/--profanity-warble-freq/--profanity-warble-depth
affects: [07-03 (detection glue / SKILL.md integration), 07-04 (real-ffmpeg loudness/STT validation)]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "ffmpeg timeline (enable) filter gating for sub-span (time-windowed) audio effects — first use of this technique in the codebase, established as a reusable pattern for future sub-span audio/video work"
    - "OR-summed enable expression (between(t,s1,e1)+between(t,s2,e2)+...) keeps filter node count flat regardless of span count"

key-files:
  created: []
  modified:
    - scripts/render.py
    - tests/test_render.py

key-decisions:
  - "build_profanity_mask_filter placed immediately before build_audio_filter_chain in render.py, grouping it with the audio-chain builder it feeds rather than near build_punch_zoom_filter (its structural analog), since both mask-builder and chain-extension are read together at the mask's one call site"
  - "profanity_filter param added as the last positional param on build_ffmpeg_command/build_jumpcut_command/build_compilation_command to avoid disturbing any existing positional call site in the codebase"

patterns-established:
  - "Pattern: time-windowed duck+garble mask (volume+bandreject+tremolo, one shared `enable` timeline expression) as a single-input -af clause — no filter_complex/second-input restructuring needed"

requirements-completed: [AUDIO-02, AUDIO-03]

coverage:
  - id: D1
    description: "build_profanity_mask_filter returns a single-input -af clause that ducks + garbles (bandreject + tremolo) only inside the named spans, returns None for empty spans, and raises RenderError on bad duck_volume or invalid spans"
    requirement: "AUDIO-02"
    verification:
      - kind: unit
        ref: "tests/test_render.py#test_build_profanity_mask_filter_two_spans_shape"
        status: pass
      - kind: unit
        ref: "tests/test_render.py#test_build_profanity_mask_filter_returns_none_for_empty_spans"
        status: pass
      - kind: unit
        ref: "tests/test_render.py#test_build_profanity_mask_filter_rejects_duck_volume_out_of_range"
        status: pass
      - kind: unit
        ref: "tests/test_render.py#test_build_profanity_mask_filter_rejects_negative_span_start"
        status: pass
    human_judgment: false
  - id: D2
    description: "build_audio_filter_chain inserts the mask clause after loudnorm and before afade, and profanity_filter=None leaves the chain byte-identical to today"
    requirement: "AUDIO-02"
    verification:
      - kind: unit
        ref: "tests/test_render.py#test_build_audio_filter_chain_profanity_filter_order_after_loudnorm_before_fade"
        status: pass
      - kind: unit
        ref: "tests/test_render.py#test_build_audio_filter_chain_none_profanity_filter_unchanged"
        status: pass
    human_judgment: false
  - id: D3
    description: "render_clip reads plan_entry.get('profanity_spans') and threads the mask through the plain, jumpcut, and compilation branches; a plan entry without profanity_spans renders unchanged"
    requirement: "AUDIO-02"
    verification:
      - kind: unit
        ref: "tests/test_render.py#test_render_clip_masks_profanity_spans_in_plain_branch"
        status: pass
      - kind: unit
        ref: "tests/test_render.py#test_render_clip_without_profanity_spans_has_no_mask_in_plain_branch"
        status: pass
      - kind: unit
        ref: "tests/test_render.py#test_render_clip_masks_profanity_spans_in_jumpcut_branch"
        status: pass
      - kind: unit
        ref: "tests/test_render.py#test_render_clip_without_profanity_spans_jumpcut_branch_unchanged"
        status: pass
      - kind: unit
        ref: "tests/test_render.py#test_render_clip_masks_profanity_spans_in_compilation_branch"
        status: pass
    human_judgment: false
  - id: D4
    description: "AUDIO-03 STT-defeat mechanism (bandreject centered ~1800Hz wide-Q formant removal + tremolo warble, not silence/beep) is wired into the mask clause per D-03; real-ffmpeg loudness/STT proof is explicitly deferred to Plan 07-04 per this plan's own success_criteria"
    requirement: "AUDIO-03"
    verification: []
    human_judgment: true
    rationale: "This plan only builds/wires the filter-string mechanics (unit-tested via exact-string assertions); actual STT-defeat and perceptual-garble validation against a real rendered clip requires real ffmpeg + real audio and is explicitly scoped to Plan 07-04 per 07-02-PLAN.md's success_criteria ('real-ffmpeg loudness/STT proof lands in Plan 07-04')."

duration: 20min
completed: 2026-07-11
status: complete
---

# Phase 7 Plan 2: Profanity Mask Filter Mechanics Summary

**Added the codebase's first time-windowed (sub-span) audio filter — `build_profanity_mask_filter` (duck+bandreject+tremolo, `enable`-gated) — wired into `build_audio_filter_chain` after `loudnorm`/before `afade`, and threaded through all three `render.py` command-builder branches plus five new `--profanity-*` CLI flags.**

## Performance

- **Duration:** ~20 min
- **Completed:** 2026-07-11
- **Tasks:** 3
- **Files modified:** 2

## Accomplishments
- `build_profanity_mask_filter` — pure validate-then-build string builder (mirrors `build_punch_zoom_filter`'s shape) producing the live-verified `volume=enable=...,bandreject=enable=...,tremolo=enable=...` clause; returns `None` for empty spans, raises `RenderError` on out-of-range `duck_volume` or invalid spans
- `build_audio_filter_chain` extended with an optional `profanity_filter` param, inserted after `loudnorm` and before the tail fade — ordering is load-bearing so `loudnorm`'s gain-riding can't undo the duck (RESEARCH Pattern 1); `profanity_filter=None` preserves the exact pre-existing chain
- `build_ffmpeg_command`, `build_jumpcut_command`, and `build_compilation_command` each gained a `profanity_filter` pass-through param, and `render_clip` now reads `plan_entry.get("profanity_spans")`, builds the mask via the five new tunables, and threads it through the plain, jumpcut (keep_segments), and compilation branches
- `render.py` CLI exposes `--profanity-duck-volume`, `--profanity-garble-freq`, `--profanity-garble-width-octaves`, `--profanity-warble-freq`, `--profanity-warble-depth`, all threaded to `render_clip` in `main()`

## Task Commits

Each task was committed atomically:

1. **Task 1: build_profanity_mask_filter (new pure builder)** - `c7026be` (feat)
2. **Task 2: extend build_audio_filter_chain with the mask stage (ordering-critical)** - `55c7062` (feat)
3. **Task 3: thread profanity_spans through the command builders, render_clip, and CLI** - `25ca6b6` (feat)

**Plan metadata:** (this commit)

## Files Created/Modified
- `scripts/render.py` - new `build_profanity_mask_filter`; extended `build_audio_filter_chain`, `build_ffmpeg_command`, `build_jumpcut_command`, `build_compilation_command`, `render_clip`; five new CLI flags in `main()`
- `tests/test_render.py` - 6 exact-string/raises tests for `build_profanity_mask_filter`, 2 ordering tests for `build_audio_filter_chain`, 5 `render_clip` masking tests across all three render branches

## Decisions Made
- `build_profanity_mask_filter` placed immediately before `build_audio_filter_chain` (rather than next to its structural analog `build_punch_zoom_filter`) since the two are read together at the mask's single call site inside `render_clip`
- The new `profanity_filter` param was appended as the last positional parameter on each of the three command builders to avoid disturbing any existing positional call site elsewhere in the codebase (all existing call sites already used a mix of positional/keyword args ending before this point)

## Deviations from Plan

None - plan executed exactly as written. All three tasks' `<behavior>` and `<acceptance_criteria>` were implemented as specified, using the exact drafted implementation from 07-RESEARCH.md's Code Examples section.

## Issues Encountered
- Local pytest temp dir (`AppData/Local/Temp/pytest-of-<user>`) is permission-locked on this machine (pre-existing, documented environment quirk in STATE.md Blockers/Concerns, not a code regression) — worked around with `--basetemp` override for the two full-suite regression runs (106/106 `tests/test_render.py`, 575/575 project-wide non-integration tests, both green).

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Filter mechanics (AUDIO-02 masking + AUDIO-03 garble wiring) are complete and unit-tested; `PLAN.json`'s `profanity_spans` field is now a fully consumed optional field on both single-clip and compilation entries
- Plan 07-03 (detection glue: wiring `scripts/profanity.py` output into `PLAN.json`'s `profanity_spans` field via `SKILL.md`) can proceed against this exact field contract
- Plan 07-04 (real-ffmpeg loudness/STT empirical validation, D-03's explicit "validate against a real clip" requirement) is unblocked — the mask clause this plan builds is exactly the one Plan 07-04 needs to render and measure

---
*Phase: 07-profanity-auto-bleep*
*Completed: 2026-07-11*
