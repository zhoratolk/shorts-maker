---
phase: quick-260711-id0
plan: 01
subsystem: media-pipeline
tags: [ffmpeg, profanity-masking, config, python, pytest]

requires:
  - phase: 07-profanity-auto-bleep
    provides: ProfanityConfig, find_profane_spans, build_profanity_mask_filter, build_ffmpeg_command/build_jumpcut_command/build_compilation_command, render_clip's profanity_spans handling
provides:
  - "ProfanityConfig.mask_mode/mask_sound_path/mask_onset_seconds fields with load-time validation"
  - "find_profane_spans onset_seconds parameter (+ --onset-seconds CLI flag) with degenerate whole-word fallback"
  - "build_profanity_sound_filter: mute-clause + amix censor-branch construction for a custom censor sound"
  - "build_ffmpeg_command/build_jumpcut_command/build_compilation_command optional profanity_sound wiring (extra -i input, filter_complex amix, RenderError on missing file)"
  - "render_clip fail-open sound-mode -> garble-mask fallback on a missing/empty censor sound path"
  - "--profanity-mask-mode/--profanity-mask-sound-path render.py CLI flags"
affects: [profanity-auto-bleep, render-pipeline]

tech-stack:
  added: []
  patterns:
    - "ffmpeg filter_complex amix pattern for muting a main track and overlaying a looped/trimmed/delayed custom sound clip inside timeline enable() spans"
    - "fail-open sound->garble mask fallback mirrors the project's established diarization/audio_energy degrade-not-crash convention"

key-files:
  created: []
  modified:
    - scripts/config.py
    - config.example.yaml
    - scripts/profanity.py
    - scripts/render.py
    - tests/test_config.py
    - tests/test_profanity.py
    - tests/test_render.py

key-decisions:
  - "profanity_sound builder param shaped as a single (sound_path, mute_clause, censor_branches) tuple appended last on all three build_*_command functions, rather than three separate params, per the plan's explicit 'pick a single clean parameter shape' instruction"
  - "build_ffmpeg_command's sound-mode branch folds both video and audio into one -filter_complex (mirroring build_jumpcut_command's [vout]/[aout] structure) since -vf cannot coexist with -filter_complex; the no-sound-mode path is untouched and stays on plain -vf/-af"
  - "span_count for the amix inputs=N+1 count is derived by counting censor_branches entries containing 'adelay=' rather than threading a separate count, since the asplit stage (present only when N>1) doesn't carry that marker"
  - "Local operator config.yaml/SKILL.md changes (Task 3) are disk-only per repo convention (both gitignored) - not committed"

patterns-established:
  - "Config field addition + CLI flag + fail-open fallback + byte-identical-default guarantee, verified via a real RED (git stash the implementation, confirm new tests fail) / GREEN (restore, confirm all pass) TDD cycle across two feat commits"

requirements-completed: [PROF-ONSET, PROF-SOUND-MODE, PROF-MASK-CONFIG]

coverage:
  - id: D1
    description: "ProfanityConfig gains mask_mode/mask_sound_path/mask_onset_seconds with validation (invalid mode, negative onset, sound mode requiring a non-empty path)"
    requirement: "PROF-MASK-CONFIG"
    verification:
      - kind: unit
        ref: "tests/test_config.py#test_load_config_profanity_mask_mode_invalid_raises"
        status: pass
      - kind: unit
        ref: "tests/test_config.py#test_load_config_profanity_mask_onset_seconds_negative_raises"
        status: pass
      - kind: unit
        ref: "tests/test_config.py#test_load_config_profanity_mask_mode_sound_requires_sound_path"
        status: pass
      - kind: unit
        ref: "tests/test_config.py#test_load_config_profanity_defaults_when_section_missing"
        status: pass
    human_judgment: false
  - id: D2
    description: "find_profane_spans supports onset_seconds (word-onset-delayed mask start, no pad subtraction) with a degenerate whole-word fallback and a threaded --onset-seconds CLI flag; onset=0 stays byte-identical to prior spans"
    requirement: "PROF-ONSET"
    verification:
      - kind: unit
        ref: "tests/test_profanity.py#test_find_profane_spans_onset_zero_matches_default_behavior"
        status: pass
      - kind: unit
        ref: "tests/test_profanity.py#test_find_profane_spans_onset_shifts_start_no_pad_subtraction"
        status: pass
      - kind: unit
        ref: "tests/test_profanity.py#test_find_profane_spans_onset_degenerate_masks_whole_word"
        status: pass
      - kind: unit
        ref: "tests/test_profanity.py#test_cli_threads_onset_seconds_into_find_profane_spans"
        status: pass
    human_judgment: false
  - id: D3
    description: "build_profanity_sound_filter + the three ffmpeg command builders wire a custom censor-sound overlay (mute main track, loop/trim/delay the censor clip, amix) and raise RenderError on a missing sound file; garble/default output stays byte-identical when no censor sound is passed"
    requirement: "PROF-SOUND-MODE"
    verification:
      - kind: unit
        ref: "tests/test_render.py#test_build_profanity_sound_filter_single_span_shape"
        status: pass
      - kind: unit
        ref: "tests/test_render.py#test_build_profanity_sound_filter_multi_span_uses_asplit"
        status: pass
      - kind: unit
        ref: "tests/test_render.py#test_build_ffmpeg_command_profanity_sound_adds_input_and_amix"
        status: pass
      - kind: unit
        ref: "tests/test_render.py#test_build_ffmpeg_command_profanity_sound_missing_file_raises"
        status: pass
      - kind: unit
        ref: "tests/test_render.py#test_build_jumpcut_command_profanity_sound_adds_input_and_amix"
        status: pass
      - kind: unit
        ref: "tests/test_render.py#test_build_compilation_command_profanity_sound_uses_member_count_as_sound_index"
        status: pass
    human_judgment: false
  - id: D4
    description: "render_clip fails open from sound mode to the garble mask when the censor sound file is missing/empty (never raises), across the plain/jumpcut/compilation branches, and the new --profanity-mask-mode/--profanity-mask-sound-path CLI flags are wired end-to-end"
    requirement: "PROF-SOUND-MODE"
    verification:
      - kind: unit
        ref: "tests/test_render.py#test_render_clip_sound_mode_missing_file_falls_back_to_garble"
        status: pass
      - kind: unit
        ref: "tests/test_render.py#test_render_clip_sound_mode_existing_file_uses_sound_filter_in_plain_branch"
        status: pass
      - kind: unit
        ref: "tests/test_render.py#test_render_clip_sound_mode_compilation_branch_uses_member_count_as_sound_index"
        status: pass
    human_judgment: false
  - id: D5
    description: "Local operator config.yaml wired to mask_mode=sound/onset=0.12/a real censor sound path, and make-shorts SKILL.md steps 5/5b/6 thread --onset-seconds/--profanity-mask-mode/--profanity-mask-sound-path (both files disk-only, gitignored, not committed)"
    human_judgment: true
    rationale: "Neither config.yaml nor SKILL.md is version-controlled (project convention, both gitignored) - verification is disk-state inspection (load_config assertions + grep) run during execution, not a committed automated test; a human running /make-shorts end-to-end with mask_mode=sound is the real confirmation this SKILL.md wiring behaves as intended."

duration: 22min
completed: 2026-07-11
status: complete
---

# Quick Task 260711-id0: Profanity onset delay + custom sound-censor mode Summary

**Added mask-onset delay and a custom sound-censor overlay mode to shorts-maker's profanity auto-bleep pipeline, on top of the existing duck+garble mask, with full fail-open behavior and byte-identical garble defaults.**

## Performance

- **Duration:** ~22 min
- **Completed:** 2026-07-11
- **Tasks:** 3/3
- **Files modified:** 7 (scripts/config.py, config.example.yaml, scripts/profanity.py, scripts/render.py, tests/test_config.py, tests/test_profanity.py, tests/test_render.py) + 2 disk-only gitignored files (config.yaml, .claude/skills/make-shorts/SKILL.md)

## Accomplishments
- `ProfanityConfig` gained `mask_mode` (`garble`/`sound`), `mask_sound_path`, and `mask_onset_seconds` fields with load-time validation (invalid mode, negative onset, sound-mode-without-a-path all raise `ConfigError`); `config.example.yaml` documents all three.
- `find_profane_spans` supports an `onset_seconds` parameter that delays a mask's start into the word (word's leading transient plays clean), with a degenerate whole-word fallback when onset exceeds the word's own duration; `onset_seconds=0` reproduces the pre-change spans exactly. New `--onset-seconds` CLI flag threads the value through.
- New `build_profanity_sound_filter` + extended `build_ffmpeg_command`/`build_jumpcut_command`/`build_compilation_command` implement a custom-sound censor mode: mute the main track inside each span (shared `enable` timeline with the garble mask), loop/trim/delay a censor sound clip per span, and `amix` it back in. Raises `RenderError` on a missing censor file; garble/default command output is byte-identical to before this plan when no censor sound is passed (all 106 pre-existing render tests pass unchanged).
- `render_clip` fails open: `mask_mode="sound"` with a missing/empty `mask_sound_path` warns to stderr and falls back to the garble mask rather than raising, across all three render branches (plain, jumpcut, compilation).

## Task Commits

Each task was committed atomically via a real RED/GREEN TDD cycle (tests committed first against a stashed pre-implementation tree, confirmed failing, then implementation restored and committed once green):

1. **Task 1: ProfanityConfig mask-mode/onset fields + onset-delayed span detection**
   - `6d5561b` test(07-05): add failing tests for mask-mode/onset config fields and onset span detection
   - `c0bdef0` feat(07-05): add profanity mask-mode/onset config fields and onset-delayed span detection
2. **Task 2: Sound-censor render path (build_profanity_sound_filter + builder integration + fail-open)**
   - `02b6f6c` test(07-05): add failing tests for sound-censor filter/builders/render_clip fail-open
   - `025771d` feat(07-05): add sound-censor render path with fail-open to garble mask
3. **Task 3: Wire local config.yaml + make-shorts SKILL.md** - disk-only, not committed (both files are gitignored per existing repo convention)

**Plan metadata:** (this commit, made by the orchestrator)

## Files Created/Modified
- `scripts/config.py` - `PROFANITY_MASK_MODES` constant, `ProfanityConfig.mask_mode/mask_sound_path/mask_onset_seconds`, 3 new `_validate()` rules
- `config.example.yaml` - documents the 3 new `profanity:` keys
- `scripts/profanity.py` - `find_profane_spans(onset_seconds=0.0, ...)` with degenerate whole-word guard, `--onset-seconds` CLI flag
- `scripts/render.py` - `build_profanity_sound_filter`, `profanity_sound` param on all three command builders, `render_clip` fail-open logic + `profanity_mask_mode`/`profanity_mask_sound_path` params, `--profanity-mask-mode`/`--profanity-mask-sound-path` CLI flags; also removed two now-redundant local `import sys` statements after adding a module-level `import sys`
- `tests/test_config.py` - 7 new tests for the 3 new config fields (defaults, custom round-trip, 4 validation-failure cases, 1 success case)
- `tests/test_profanity.py` - 4 new tests for `onset_seconds` (zero-matches-default, shift, degenerate, CLI threading)
- `tests/test_render.py` - 18 new tests for `build_profanity_sound_filter`, the 3 builders' sound-mode wiring, and `render_clip`'s fail-open/sound-mode behavior across all 3 render branches
- `config.yaml` (gitignored, disk-only) - `mask_mode: sound`, `mask_sound_path` pointed at a real local censor clip, `mask_onset_seconds: 0.12`, plus the stronger garble values (`1200.0/6.0/25.0/1.0`) validated in Plan 07-04 for this operator's own runtime config
- `.claude/skills/make-shorts/SKILL.md` (gitignored, disk-only) - threaded `--onset-seconds` into both `scripts/profanity.py` invocations (single-clip step 5 and compilation bullet 7) and `--profanity-mask-mode`/`--profanity-mask-sound-path` into the step 6 `scripts/render.py` invocation, with matching prose updates

## Decisions Made
- `profanity_sound` builder param is one `(sound_path, mute_clause, censor_branches)` tuple appended last on all three `build_*_command` functions (not three separate params) - matches the plan's explicit "pick a single clean parameter shape" instruction and keeps the append-only positional-param convention from 07-02 (`profanity_filter`) intact.
- `build_ffmpeg_command`'s sound-mode branch folds both video and audio into one `-filter_complex` (mirroring `build_jumpcut_command`'s `[vout]`/`[aout]` structure), since `-vf` cannot coexist with `-filter_complex`; the no-sound-mode path is completely untouched, so all 106 pre-existing render tests pass byte-identically.
- `span_count` for `amix=inputs=<N+1>` is derived by counting `censor_branches` entries containing `"adelay="` (the asplit stage, present only when N>1, doesn't have that marker) rather than threading a separate span-count argument through the tuple.
- Task 3's `config.yaml`/SKILL.md edits are disk-only per the pre-existing repo convention (both gitignored) - same pattern as 02-01/04-06/07-04.

## Deviations from Plan

None - plan executed exactly as written. All three tasks' `<action>` specs were implemented verbatim; the empirically-validated garble defaults (1800/4/18/0.7) in `scripts/config.py`/`scripts/render.py` were left completely unchanged.

## Issues Encountered
- One incidental bug surfaced and fixed during implementation (Rule 1 - not a deviation from plan scope, a direct consequence of adding a module-level `import sys` to `scripts/render.py`): a pre-existing local `import sys` inside `render_clip`'s `keep_segments_raw` branch shadowed the new module-level import within the whole function's scope (Python function-scope binding rules), causing `UnboundLocalError` on the subtitles code path that runs earlier in the same function. Fixed by removing both now-redundant local `import sys` statements in `render_clip` (subtitles block and boundary-transitions block) since the module now imports `sys` at the top. Verified via the full `tests/test_render.py` suite (120/120 passing) before committing.

## User Setup Required
None - no external service configuration required. The operator's local `config.yaml` sound-censor path was wired in Task 3 (disk-only, see Decisions above).

## Next Phase Readiness
Profanity auto-bleep (Phase 07) now supports both refinements from this quick task: onset-delayed masking and a custom sound-censor mode, both fully unit-tested and fail-open. No blockers for future work. A live end-to-end `/make-shorts` run with `mask_mode=sound` against the operator's real censor clip (config.yaml, Task 3) remains a manual verification step (D5 above) since it exercises a real ffmpeg render, not just the command-builder unit tests.

---
*Phase: quick-260711-id0*
*Completed: 2026-07-11*

## Self-Check: PASSED

All 7 modified source/test files confirmed present on disk; all 4 task commit hashes (6d5561b, c0bdef0, 02b6f6c, 025771d) confirmed in `git log`.
