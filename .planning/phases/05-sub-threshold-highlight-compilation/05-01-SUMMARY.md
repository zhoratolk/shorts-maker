---
phase: 05-sub-threshold-highlight-compilation
plan: 01
subsystem: compilation
tags: [python, dataclasses, markdown, pytest, tdd]

# Dependency graph
requires:
  - phase: 04-context-driven-transitions
    provides: transition engine (scripts/transitions.py) that later plans in this phase will stitch through
provides:
  - Candidate dataclass with tag/sub_threshold/group_id/unmatched optional fields (D-01, D-03)
  - append_compilation_sections_markdown(path, groups, unmatched) for CANDIDATES.md surfacing (D-03)
affects: [05-02, 05-03, 05-04]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Optional-field, non-breaking dataclass extension (mirrors existing coherence field)"
    - "Dict-based function params for python -c one-liner SKILL.md invocation (mirrors style_profile.py precedent)"
    - "Read-append-rewrite over an existing markdown file rather than a second document"

key-files:
  created: []
  modified:
    - scripts/candidates.py
    - tests/test_candidates.py

key-decisions:
  - "append_compilation_sections_markdown takes plain dicts (not Candidate) for both groups and unmatched, per the plan's explicit signature — differs slightly from PATTERNS.md's illustrative Candidate-typed sketch, but matches the plan's <action> text and the JSON-round-trip call-site rationale"
  - "No CLI subcommand added for append_compilation_sections_markdown in this plan — SKILL.md (Plan 05-04) will call it via a python -c one-liner, matching style_profile.py's precedent"

patterns-established:
  - "Sub-threshold tagging/grouping metadata is additive-only on Candidate — every existing single-clip JSON/markdown output is byte-identical when the new fields are absent"

requirements-completed: [COMP-01]

coverage:
  - id: D1
    description: "Candidate dataclass carries tag/sub_threshold/group_id/unmatched; merge_candidates threads them through from source dicts via .get(), exactly like the existing coherence field, without changing any existing candidate's shape"
    requirement: "COMP-01"
    verification:
      - kind: unit
        ref: "tests/test_candidates.py#test_merge_candidates_carries_tag_or_sub_threshold_fields_when_present"
        status: pass
      - kind: unit
        ref: "tests/test_candidates.py#test_merge_candidates_tag_or_sub_threshold_fields_default_when_absent"
        status: pass
      - kind: unit
        ref: "tests/test_candidates.py#test_write_candidates_json_round_trips"
        status: pass
    human_judgment: false
  - id: D2
    description: "append_compilation_sections_markdown appends distinct Sub-Threshold Compilations / Unmatched Sub-Threshold sections to an existing CANDIDATES.md, and is a no-op when there is nothing to report"
    requirement: "COMP-01"
    verification:
      - kind: unit
        ref: "tests/test_candidates.py#test_append_compilation_sections_markdown_adds_group_and_unmatched_sections"
        status: pass
      - kind: unit
        ref: "tests/test_candidates.py#test_append_compilation_sections_markdown_noop_when_both_empty"
        status: pass
    human_judgment: false

duration: 5min
completed: 2026-07-10
status: complete
---

# Phase 5 Plan 1: Candidate Tagging & Compilation Sections Summary

**Candidate dataclass gains optional tag/sub_threshold/group_id/unmatched fields, and a new append_compilation_sections_markdown function surfaces grouped/unmatched sub-threshold candidates in CANDIDATES.md without touching the original numbered list**

## Performance

- **Duration:** 5 min
- **Started:** 2026-07-10T00:45:00+03:00
- **Completed:** 2026-07-10T00:48:25+03:00
- **Tasks:** 2 completed
- **Files modified:** 2

## Accomplishments
- `Candidate` (scripts/candidates.py) carries four new optional fields (`tag`, `sub_threshold`, `group_id`, `unmatched`), all defaulted so no existing single-clip candidate's JSON/markdown shape changes
- `merge_candidates` reads the four new fields via `.get()` in the exact same style as the existing `coherence` line, leaving sort/id-assignment logic untouched
- New `append_compilation_sections_markdown(path, groups, unmatched)` appends `## Sub-Threshold Compilations` and `## Unmatched Sub-Threshold` sections to an existing `CANDIDATES.md`, or is a byte-identical no-op when both inputs are empty

## Task Commits

Each task was committed atomically, following RED/GREEN TDD gates:

1. **Task 1: Extend Candidate dataclass with tag/sub_threshold/group_id/unmatched (D-01, D-03)**
   - `3bdbd42` (test) - failing tests for the four new fields, round-trip test updated
   - `ec0822f` (feat) - Candidate + merge_candidates extended
2. **Task 2: append_compilation_sections_markdown for CANDIDATES.md surfacing (D-03, COMP-01)**
   - `79c1a67` (test) - failing tests for the new append function
   - `fe28170` (feat) - append_compilation_sections_markdown implemented

_No REFACTOR commits needed — both implementations matched the plan's mirrored patterns cleanly on first pass._

## Files Created/Modified
- `scripts/candidates.py` - Candidate gains tag/sub_threshold/group_id/unmatched fields; merge_candidates threads them through; new append_compilation_sections_markdown function
- `tests/test_candidates.py` - Updated round-trip test expectation; 4 new tests (2 named `tag_or_sub_threshold`, 2 named `compilation_sections`, per 05-VALIDATION.md's binding test-selection filters)

## Decisions Made
- Followed the plan's explicit `append_compilation_sections_markdown(path, groups, unmatched)` signature with dict-based `unmatched` (not `Candidate`-typed as 05-PATTERNS.md's illustrative sketch showed) — the plan's `<action>`/`<behavior>` text is more specific and explicitly calls out the `python -c` one-liner call-site rationale, so it takes precedence over the pattern-map sketch.
- No CLI subcommand added for the new function, per the plan's explicit instruction — `main()`'s single-command shape stays untouched; Plan 05-04's SKILL.md wiring will call it directly.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- Pre-existing environment quirk (documented in STATE.md, not a regression): the default pytest temp dir (`AppData/Local/Temp/pytest-of-<user>`) is permission-locked on this machine. Worked around with `--basetemp` override, same as established during Plan 03-01. No code change involved.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- `Candidate`'s new fields and `append_compilation_sections_markdown` are ready for Plan 05-04's SKILL.md orchestration wiring to populate/call once step 5's trim decision and the grouping pass exist.
- `scripts/compilation.py` (mechanical grouping validation + PLAN.json entry builder) and `render.py::build_compilation_command` (multi-input fold) remain for subsequent plans in this phase — no blockers identified.

---
*Phase: 05-sub-threshold-highlight-compilation*
*Completed: 2026-07-10*

## Self-Check: PASSED

- FOUND: scripts/candidates.py
- FOUND: tests/test_candidates.py
- FOUND: .planning/phases/05-sub-threshold-highlight-compilation/05-01-SUMMARY.md
- FOUND: 3bdbd42, ec0822f, 79c1a67, fe28170
