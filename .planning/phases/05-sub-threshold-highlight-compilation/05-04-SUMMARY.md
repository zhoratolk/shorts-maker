---
phase: 05-sub-threshold-highlight-compilation
plan: 04
subsystem: infra
tags: [orchestration, skill-md, compilation, documentation]

# Dependency graph
requires:
  - phase: 05-sub-threshold-highlight-compilation
    provides: "Plan 05-01's Candidate tag/sub_threshold/group_id/unmatched fields and append_compilation_sections_markdown; Plan 05-02's build_compilation_entry + ClipConfig.compilation_max_seconds; Plan 05-03's build_compilation_command/render_clip dispatch on type=='compilation'"
provides:
  - "SKILL.md step 5: sub-threshold detection/tagging bullet, gated on the existing trim-decision logic (COMP-01, D-01)"
  - "SKILL.md new step 5b: one-shot grouping pass, strongest-first ordering, once-per-compilation crop/punch-zoom/subtitles/metadata, flattened-segment transitions reuse, compilation.py CLI invocation, CANDIDATES.md append wiring (COMP-01/02/03, D-02/03/04/06)"
  - "SKILL.md PLAN.json schema block: compilation entry shape documented alongside single-clip shape; step 6 render note confirms no new CLI flags needed"
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "SKILL.md orchestration-only wiring plan: no scripts/*.py changes, purely documents how existing mechanics (05-01/02/03) get invoked from a real run"

key-files:
  created: []
  modified:
    - .claude/skills/make-shorts/SKILL.md

key-decisions:
  - ".claude/ is gitignored project-wide (confirmed via git check-ignore), so both tasks' SKILL.md edits live on disk only, not in git history - same pre-existing repo convention documented in 02-01-SUMMARY.md and 04-06-SUMMARY.md, not a regression introduced by this plan"
  - "The compilation PLAN.json entry (scripts/compilation.py's CLI) is documented as being built once, at the end of the new step 5b, after crop_style/punch-zoom/title/subtitles/metadata are all decided - mirrors how a single clip's plan entry is only assembled at the very end ('Write the merged results to PLAN.json'), rather than invoking compilation.py mid-subsection before all its optional fields are known"

patterns-established:
  - "A 'once per compilation, never per member' framing (D-06) is applied consistently across crop_style, punch_zoom_at, title/filename, subtitles, and metadata in the new step 5b - all five reuse the exact same script/CLI a single clip already uses, just invoked once over the group instead of per member"

requirements-completed: [COMP-01, COMP-02, COMP-03]

coverage:
  - id: D1
    description: "Step 5 documents sub-threshold detection/tagging as a per-candidate outcome of the existing trim decision (COMP-01, D-01): a candidate whose tightest trim is still below config.clip.min_seconds is marked sub_threshold + tagged instead of force-padded, and skips the rest of step 5's per-candidate finishing work for this run"
    requirement: "COMP-01"
    verification:
      - kind: other
        ref: "grep -c 'sub_threshold\\|sub-threshold' .claude/skills/make-shorts/SKILL.md -> 2 (non-zero)"
        status: pass
    human_judgment: true
    rationale: "SKILL.md is orchestration prose consumed by Claude at run time, not executable code - correctness is a documentation-quality judgment (gating logic, D-01 tag-register wording, fail-open framing), not something a unit test can assert"
  - id: D2
    description: "New step 5b: an automatic, fail-open sub-threshold grouping pass (D-02/D-03/D-04/D-06) builds a compilation PLAN.json entry via scripts/compilation.py, reuses scripts/transitions.py's select-transitions CLI unchanged for stitch-point analysis, and surfaces every group/unmatched candidate in CANDIDATES.md via append_compilation_sections_markdown; the PLAN.json schema block and step 6 render note both document the new entry shape"
    requirement: "COMP-02"
    verification:
      - kind: other
        ref: "grep -c 'compilation.py' .claude/skills/make-shorts/SKILL.md -> 3; grep -c 'append_compilation_sections_markdown' -> 2 (both non-zero)"
        status: pass
      - kind: unit
        ref: "python -m pytest -m 'not integration' -q -> 407 passed, 5 skipped (unchanged from Plan 05-03's baseline, confirms no code regression from this doc-only plan)"
        status: pass
    human_judgment: true
    rationale: "The seven-item human-check in the plan's Task 2 verify block (gating, semantic-not-string-match grouping scoped to one video_stem, strongest-first ordering, once-per-compilation decisions, fail-open transitions/compilation.py, CANDIDATES.md wiring, schema/step-6 updates, no other step altered) requires reading the new prose subsection, not a mechanical check"

# Metrics
duration: 15min
completed: 2026-07-10
status: complete
---

# Phase 05 Plan 04: Skill Orchestration Wiring for Sub-Threshold Compilation Summary

**SKILL.md now drives Plans 05-01/02/03's mechanics end-to-end: step 5 gains sub-threshold detection/tagging, a new step 5b runs a fail-open Claude grouping pass into a `compilation.py`-built PLAN.json entry (reusing `transitions.py`'s select-transitions CLI unchanged), and the PLAN.json schema + step 6 render note document the new `"type": "compilation"` entry shape.**

## Performance

- **Duration:** ~15 min
- **Completed:** 2026-07-10
- **Tasks:** 2
- **Files modified:** 1 (`.claude/skills/make-shorts/SKILL.md`, gitignored — disk-only)

## Accomplishments

- Step 5's "Refine (pass 2)" section gained a new bullet immediately after "Exact trim points": once a candidate's tightest trim is decided, if the result is still below `config.clip.min_seconds`, it is marked `sub_threshold` with a free-form `tag` (never a fixed enum) instead of being force-padded — and skips the rest of step 5's per-candidate finishing work for this run (crop_style/jump cuts/transitions/punch-zoom/subtitles/title/metadata), except jump-cut computation which still runs normally since removing dead air is orthogonal to whether the candidate ends up standalone or in a compilation.
- New "5b. Group sub-threshold candidates into compilations" subsection, gated on at least one sub-threshold candidate existing this run, documents: a one-shot Claude semantic grouping pass scoped to one `video_stem`'s own candidate pool (COMP-03, never cross-video); strongest-first member ordering (D-04); crop_style/punch_zoom/title/subtitles/metadata each decided exactly once per compilation, never per member (D-06); a flattened cross-member render-order segment list (Pattern 2) fed unchanged into `transitions.py select-transitions` (fail-open — omits `boundary_transitions` on any error, never aborts); the compilation's PLAN.json entry built via `scripts/compilation.py`'s CLI once every field is known; and a closing `append_compilation_sections_markdown` call surfacing every group and every unmatched sub-threshold candidate in `CANDIDATES.md` (D-03, no re-approval gate).
- The PLAN.json object-schema code block gained a second example showing the compilation entry shape (`"type": "compilation"`, `"segments"` replacing `start`/`end`/`keep_segments`, everything else following the same optional-field-omitted convention as a single clip).
- Step 6's render paragraph gained one sentence: `render.py` renders `"type": "compilation"` entries automatically via the exact same invocation — no new CLI flags required.
- Full non-integration test suite re-run to confirm this doc-only plan introduced zero code regression: 407 passed, 5 skipped (byte-identical to Plan 05-03's baseline).

## Task Commits

Both tasks' SKILL.md edits live on disk only — no git commit was possible or attempted for either task's file change.

1. **Task 1: Step 5 sub-threshold detection + tagging bullet (COMP-01, D-01)**
   - No commit — `.claude/` is gitignored project-wide (confirmed via `git check-ignore -v`), so this edit lives on disk only, not in git history. Same pre-existing repo convention as 02-01/04-06 (see those SUMMARYs' Deviations).
2. **Task 2: Step 5b grouping pass + PLAN.json schema + CANDIDATES.md append + step 6 note (COMP-02, COMP-03, D-02, D-03, D-04, D-06)**
   - No commit — same gitignore reason as Task 1.

**Plan metadata:** attempted via `gsd-tools query commit`; see Deviations/Issues below for the actual outcome (this repo's `.planning/` is tracked, not gitignored, but this section's changed files are the SKILL.md edit which cannot be staged).

## Files Created/Modified

- `.claude/skills/make-shorts/SKILL.md` — added the sub-threshold detection/tagging bullet to step 5; added the new "5b. Group sub-threshold candidates into compilations" subsection (9 numbered sub-steps); added the compilation entry example to the PLAN.json schema block; added the step 6 no-new-flags note. Gitignored — disk-only, no git diff.

## Decisions Made

- `.claude/` is gitignored project-wide (verified with `git check-ignore -v .claude/skills/make-shorts/SKILL.md`), so both tasks' SKILL.md edits live on disk only, not in git history — same pre-existing repo convention documented in 02-01-SUMMARY.md and 04-06-SUMMARY.md, not a regression introduced by this plan.
- The compilation `PLAN.json` entry (`scripts/compilation.py`'s CLI call) is documented as being built once, at the very end of the new step 5b — after crop_style, punch_zoom_at, title/output_filename, subtitles_path, and metadata_path are all already decided — rather than invoking `compilation.py` mid-subsection per the plan's raw bullet listing order. This mirrors how a single clip's `PLAN.json` entry is only assembled at the very end ("Write the merged results to PLAN.json") after every individual decision bullet has run; invoking `compilation.py` before `subtitles_path`/`metadata_path`/`output_filename` were known would have produced an incomplete entry with no documented way to add those fields afterward, since `compilation.py` has no "update an existing entry" CLI mode. All of the plan's required content (COMP-01/02/03, D-01/02/03/04/06) is present; only the narrative ordering of the "build entry" bullet relative to "title/filename" and "subtitles/metadata" bullets was adjusted for coherence.

## Deviations from Plan

None — plan executed exactly as written; content-wise every `<behavior>` bullet in both tasks is represented in the new SKILL.md text (see Decisions Made above for the one narrative-ordering adjustment, which does not change what gets documented, only the sequence it's described in).

## Issues Encountered

- `.claude/skills/make-shorts/SKILL.md` cannot be `git add`ed at all — attempting it returns "The following paths are ignored by one of your .gitignore files: .claude". This is expected (see Decisions Made) and matches the exact same situation Plans 02-01 and 04-06 hit; not a new issue introduced by this plan.
- Local pytest temp dir (`AppData/Local/Temp/pytest-of-<user>`) is permission-locked on this machine (pre-existing, documented environment quirk from Plan 03-01). Ran with `--basetemp=D:/shorts-maker/.pytest-tmp`. Unrelated to any change in this plan (this plan touched no test files).

## User Setup Required

None — no external service configuration required. Every feature this plan wires (sub-threshold detection, grouping, compilation rendering) only activates when a candidate is actually sub-threshold; existing single-clip runs are byte-identical in behavior.

## Next Phase Readiness

- Phase 05 (sub-threshold-highlight-compilation) is now complete: COMP-01 (sub-threshold candidates are tagged, never force-padded/silently skipped), COMP-02 (automatic grouping + stitching into one compilation short via the real render path), and COMP-03 (same-video_stem-only grouping) are all closed end-to-end — a real `/make-shorts` run with sub-threshold candidates present will now automatically tag, group, and render them into a compilation, with zero new manual approval steps.
- A sub-threshold candidate that never matches anyone this run stays visibly named in `CANDIDATES.md`'s new "Unmatched Sub-Threshold" section, per the plan's success criteria.
- No blockers. This is the last plan in Phase 05; STATE.md/ROADMAP.md are updated below to reflect phase completion.

---
*Phase: 05-sub-threshold-highlight-compilation*
*Completed: 2026-07-10*

## Self-Check: PASSED

- FOUND: .claude/skills/make-shorts/SKILL.md (edits present on disk, verified via grep counts above)
- FOUND: .planning/phases/05-sub-threshold-highlight-compilation/05-04-SUMMARY.md
- N/A: no task commits exist to verify (both tasks' only modified file is gitignored — see Task Commits/Deviations above)
