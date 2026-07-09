---
phase: 05-sub-threshold-highlight-compilation
plan: 02
subsystem: compilation
tags: [python, dataclasses, config, pytest, tdd]

# Dependency graph
requires:
  - phase: 05-sub-threshold-highlight-compilation
    provides: "Plan 05-01's Candidate tag/sub_threshold/group_id/unmatched fields and append_compilation_sections_markdown, which the grouping pass (Plan 05-04) will feed into build_compilation_entry's members argument"
provides:
  - "ClipConfig.compilation_max_seconds config knob (D-05), defaulting to 150s, validated to always exceed clip.max_seconds"
  - "scripts/compilation.py: CompilationError, MIN_GROUP_SIZE, build_compilation_entry(members, compilation_max_seconds, crop_style, ...) - mechanical group validator + PLAN.json 'compilation' entry builder"
affects: [05-03, 05-04]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Mechanical validate-then-build module consuming an already-Claude-decided group (mirrors build_jumpcut_command's guard-first pattern)"
    - "Optional PLAN.json fields omitted entirely (never null/false) when their builder parameter is left at its None default"

key-files:
  created:
    - scripts/compilation.py
    - tests/test_compilation.py
  modified:
    - scripts/config.py
    - tests/test_config.py
    - config.example.yaml

key-decisions:
  - "Capping-below-MIN_GROUP_SIZE error message names the cap and resulting count rather than mirroring Guard 1's exact wording verbatim - plan left the wording to implementer discretion (only Guard 1/Guard 2 messages were prescribed word-for-word)"
  - "build_compilation_entry takes plain member dicts (not a Candidate-typed object) exactly as the plan's signature specifies, matching Plan 05-01's precedent of dict-based params over typed objects at this hand-off boundary"

patterns-established:
  - "compilation.py needs no sys.path insert and imports no sibling scripts.* module - it is the module the grouping pass calls, not a consumer of other scripts/ modules"

requirements-completed: [COMP-01, COMP-02, COMP-03]

coverage:
  - id: D1
    description: "ClipConfig.compilation_max_seconds is a real, validated config knob (D-05), defaulting to 150s and always required to exceed clip.max_seconds"
    requirement: "COMP-01"
    verification:
      - kind: unit
        ref: "tests/test_config.py#test_load_config_applies_defaults"
        status: pass
      - kind: unit
        ref: "tests/test_config.py#test_load_config_compilation_max_seconds_custom_value"
        status: pass
      - kind: unit
        ref: "tests/test_config.py#test_load_config_compilation_max_seconds_must_exceed_max_seconds"
        status: pass
    human_judgment: false
  - id: D2
    description: "build_compilation_entry rejects a group smaller than 2 members and a group spanning more than one video_stem, so no such group can ever become a PLAN.json compilation entry (COMP-02, COMP-03)"
    requirement: "COMP-02"
    verification:
      - kind: unit
        ref: "tests/test_compilation.py#test_build_compilation_entry_rejects_single_member_group"
        status: pass
      - kind: unit
        ref: "tests/test_compilation.py#test_build_compilation_entry_requires_same_video_stem"
        status: pass
    human_judgment: false
  - id: D3
    description: "Length-ceiling capping preserves strongest-first order, drops only the weakest tail that would overflow compilation_max_seconds, and raises when capping alone would leave fewer than 2 members (D-04/D-05)"
    requirement: "COMP-03"
    verification:
      - kind: unit
        ref: "tests/test_compilation.py#test_build_compilation_entry_caps_at_compilation_max_seconds_dropping_weakest"
        status: pass
      - kind: unit
        ref: "tests/test_compilation.py#test_build_compilation_entry_raises_when_capping_leaves_fewer_than_min_group_size"
        status: pass
    human_judgment: false
  - id: D4
    description: "build_compilation_entry validates boundary_transitions length against the flattened segment count and builds a valid, optional-field-omitted PLAN.json 'compilation' entry"
    requirement: "COMP-03"
    verification:
      - kind: unit
        ref: "tests/test_compilation.py#test_build_compilation_entry_rejects_boundary_transitions_length_mismatch"
        status: pass
      - kind: unit
        ref: "tests/test_compilation.py#test_build_compilation_entry_builds_valid_entry_from_two_members"
        status: pass
      - kind: unit
        ref: "tests/test_compilation.py#test_build_compilation_entry_omits_optional_fields_when_none"
        status: pass
    human_judgment: false

duration: 2min
completed: 2026-07-10
status: complete
---

# Phase 5 Plan 2: Compilation Config Knob & Mechanical Group Validator Summary

**ClipConfig.compilation_max_seconds (150s default, D-05) plus scripts/compilation.py's build_compilation_entry - a purely mechanical validator that enforces COMP-02's minimum group size, COMP-03's same-video_stem guard, and D-05's length ceiling (dropping weakest members strongest-first on overflow) before building a PLAN.json "compilation" entry**

## Performance

- **Duration:** 2 min
- **Started:** 2026-07-10T00:53:00+03:00
- **Completed:** 2026-07-10T00:56:00+03:00
- **Tasks:** 2 completed
- **Files modified:** 5

## Accomplishments
- `ClipConfig.compilation_max_seconds` (default 150s) added to `scripts/config.py`, with a `_validate` guard rejecting any value at or below `clip.max_seconds`, and documented in `config.example.yaml`
- New `scripts/compilation.py`: `CompilationError`, `MIN_GROUP_SIZE = 2`, and `build_compilation_entry` - validates group size (COMP-02), single `video_stem` (COMP-03), caps members at `compilation_max_seconds` strongest-first (D-04/D-05), validates `boundary_transitions` length against the flattened segment count, and builds the optional-field-omitted PLAN.json `"compilation"` entry
- CLI wrapper (`main()`) reads a members JSON file + flags, writes the built entry to `output_json`, prints the output path (matches `diarize.py`'s "print the output path" convention)

## Task Commits

Each task was committed atomically, following RED/GREEN TDD gates:

1. **Task 1: ClipConfig.compilation_max_seconds config knob (D-05)**
   - `f105072` (test) - failing tests for the default, override, and ConfigError cases
   - `8178e44` (feat) - compilation_max_seconds field + _validate guard + config.example.yaml docs
2. **Task 2: scripts/compilation.py - mechanical group validation + PLAN.json entry builder (COMP-02, COMP-03, D-04)**
   - `a0b320e` (test) - failing tests for build_compilation_entry (8 tests, ModuleNotFoundError RED)
   - `2711f6c` (feat) - CompilationError, MIN_GROUP_SIZE, build_compilation_entry, CLI main()

_No REFACTOR commits needed - both implementations matched the plan's specified shape cleanly on first pass._

## Files Created/Modified
- `scripts/config.py` - `ClipConfig.compilation_max_seconds: int = 150` field + `_validate` guard requiring it to exceed `max_seconds`
- `tests/test_config.py` - default assertion added to `test_load_config_applies_defaults`, plus 2 new tests for override and the `<= max_seconds` ConfigError
- `config.example.yaml` - `clip.compilation_max_seconds: 150` documented under `clip:`
- `scripts/compilation.py` (new) - `CompilationError`, `MIN_GROUP_SIZE`, `build_compilation_entry`, CLI `main()`
- `tests/test_compilation.py` (new) - 8 tests covering `build_compilation_entry` (7 required by the plan + a `MIN_GROUP_SIZE` constant check)

## Decisions Made
- Followed the plan's exact prescribed error-message wording for Guard 1 (`"a compilation group needs >= {MIN_GROUP_SIZE} members, got {N}"`) and Guard 2 (`"all group members must share one video_stem, got {sorted list}"`); the capping-shortfall error message wording was left to implementer discretion by the plan and was written to clearly name the cap value and resulting member count.
- `build_compilation_entry` takes plain member dicts per the plan's explicit signature (not a `Candidate`-typed object), consistent with Plan 05-01's precedent of dict-based params at this same hand-off boundary.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- Pre-existing environment quirk (documented in STATE.md, not a regression): the default pytest temp dir (`AppData/Local/Temp/pytest-of-<user>`) is permission-locked on this machine. Worked around with `--basetemp=D:/shorts-maker/.pytest-tmp` (gitignored), same as established during Plan 03-01/05-01. No code change involved.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- `compilation_max_seconds` and `build_compilation_entry` are ready for Plan 05-03 (`render.py::build_compilation_command`, the multi-input ffmpeg fold that dispatches on `entry["type"] == "compilation"`) and Plan 05-04 (SKILL.md wiring that calls `build_compilation_entry` once Claude has decided a group and its strongest-first order).
- No blockers identified.

---
*Phase: 05-sub-threshold-highlight-compilation*
*Completed: 2026-07-10*
