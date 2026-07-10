---
phase: 05-sub-threshold-highlight-compilation
plan: 05
subsystem: compilation-validation
tags: [gap-closure, bugfix, docs]
dependency-graph:
  requires: [05-01, 05-02, 05-04]
  provides: [COMP-02-unblocked, WR-01-closed, WR-02-closed, WR-03-closed]
  affects: [scripts/compilation.py, scripts/candidates.py, .claude/skills/make-shorts/SKILL.md]
tech-stack:
  added: []
  patterns:
    - "Truncate-then-validate: reconcile a pre-cap caller-supplied list against a post-cap fitted list by truncating to the fitted prefix before the existing length check, rather than requiring the caller to predict the cap result"
    - ".get()-with-default for display-only dict access on untrusted/hand-assembled JSON input, matching merge_candidates's existing convention"
key-files:
  created: []
  modified:
    - scripts/compilation.py
    - tests/test_compilation.py
    - scripts/candidates.py
    - tests/test_candidates.py
    - .claude/skills/make-shorts/SKILL.md
decisions:
  - "CR-01 fix placed inside build_compilation_entry's validation block only (not the capping loop) — truncation happens after fitted is computed, before the existing length-mismatch raise, so a genuinely too-short list still raises unchanged"
  - "SKILL.md edits are disk-only, not committed to git history — .claude/ is gitignored project-wide (confirmed via git check-ignore), same pre-existing convention as Plans 02-01/04-06"
metrics:
  duration: 15min
  completed: 2026-07-10
status: complete
---

# Phase 05 Plan 05: Gap Closure — CR-01 + WR-01/WR-02/WR-03 Summary

Truncates pre-cap `boundary_transitions` to the fitted post-cap prefix inside `build_compilation_entry`, closing the Critical bug that made capping+transitions-enabled always raise `CompilationError`; also hardens SKILL.md's compilation groups/unmatched hand-off docs and adds defensive `.get()` access to `append_compilation_sections_markdown`.

## What Was Built

**Task 1 (CR-01, TDD):** `build_compilation_entry` in `scripts/compilation.py` previously validated the caller-supplied `boundary_transitions` list against the *post-cap* fitted member count, but SKILL.md step 5b computes that list *pre-cap* (before capping ever runs). Whenever capping actually dropped trailing members and `config.transitions.enabled` was true, the length check always failed and `CompilationError` was raised, silently discarding the compilation — exactly the failure mode this phase exists to prevent. Fixed by truncating `boundary_transitions` to `expected_length` (the fitted/post-cap boundary count) immediately before the existing length-mismatch check, when the supplied list is longer than expected. Truncation only ever shrinks — a list still too short after truncation continues to raise `CompilationError` exactly as before, preserving the guard's role alongside `render.py`'s own independent re-validation (Plan 05-03).

Added two regression tests to `tests/test_compilation.py`:
- `test_build_compilation_entry_caps_and_truncates_boundary_transitions` — the exact untested capping+pre-cap-boundary-list combination CR-01 identified; asserts no exception and `boundary_transitions == ["crossfade"]` (the pre-cap list's own first-boundary prefix).
- `test_build_compilation_entry_still_rejects_too_short_boundary_transitions` — same 3-member/cap-150 setup with `boundary_transitions=[]`; asserts `CompilationError` still raised.

All 10 tests in `tests/test_compilation.py` pass (8 pre-existing + 2 new — the plan's objective text said "7 existing" but the file actually had 8; none were modified).

**Task 2 (WR-01 + WR-02, docs only):** Scoped edits to `.claude/skills/make-shorts/SKILL.md` step 5b:
- Bullet 9's lead-in reworked to explicitly instruct accumulating `work/<video_stem>/compilations/groups.json` and `work/<video_stem>/compilations/unmatched.json` as bullets 1-8 are worked through for each group — appending a group dict right after that group's `_entry.json` build (bullet 8) and an unmatched-candidate dict for every sub-threshold candidate that never joined a group (bullet 1). Also notes both files must be initialized as `[]` if this run produces zero groups/unmatched candidates, since `append_compilation_sections_markdown` reads both unconditionally. The existing `python -c` call and its trailing explanation sentence were left unchanged.
- Bullet 7 extended with the same explicit-literal-path treatment step 5's single-clip words bullet already has: the literal output path `work/<video_stem>/compilations/<compilation_stem>_words.json`, plus the full three-argument `scripts/jumpcuts.py remap-words` CLI invocation (absolute-words file, flattened segments file, words output path), mirroring step 5's own three-arg call shape. Only the words-file half of bullet 7 was touched; the metadata half and every other bullet/step were left unchanged.

Automated verification passed: both `grep -c` checks returned counts ≥1, and the full non-integration suite stayed green (409 passed before Task 3's new test, 410 after — see final regression check below).

**Note:** `.claude/` is gitignored project-wide in this repo (confirmed via `git check-ignore -v .claude/skills/make-shorts/SKILL.md`), so this task's edits live on disk only, not in git history — the same pre-existing convention already documented for Plans 02-01 and 04-06. No commit was made for this task; there is nothing to stage.

**Task 3 (WR-03, TDD):** `append_compilation_sections_markdown` in `scripts/candidates.py` previously used unchecked bracket access (`member['id']`, `group['title']`, `candidate['reason']`, `candidate['tag']`) that would raise a bare `KeyError` on a malformed hand-assembled `groups.json`/`unmatched.json` entry, aborting step 9's CANDIDATES.md bookkeeping for the whole run. Replaced with `.get()` calls carrying sensible display defaults, matching `merge_candidates`'s existing defensive style in the same file: `member.get('id', '?')`, `group.get('title', '(untitled compilation)')`, `candidate.get('reason', '(no reason given)')`, `candidate.get('tag', '(untagged)')`. `candidate["start"]`/`candidate["end"]` (fed to `format_timecode`) were left as required bracket access, unchanged — a missing start/end is a more structural bug already caught upstream by `build_compilation_entry`, out of scope for this display-only fix.

Added `test_append_compilation_sections_markdown_defaults_missing_fields` to `tests/test_candidates.py`, asserting the function degrades to readable placeholder text instead of raising when `id`/`title`/`reason`/`tag` are missing from a hand-assembled entry. All 16 tests in `tests/test_candidates.py` pass (14 pre-existing + 2 new across this plan and prior plans — the two pre-existing `append_compilation_sections_markdown` tests were not modified).

## CR-01 Reproduction (05-VERIFICATION.md repro snippet)

Directly reproduced the exact scenario from `05-VERIFICATION.md`: 3 members with durations 60/60/60, cap 150, `boundary_transitions=["crossfade", "crossfade"]` (sized for the pre-cap 2-boundary list):

```python
entry = build_compilation_entry(members, 150, 'zoom', boundary_transitions=['crossfade', 'crossfade'])
# Before fix: raised CompilationError
# After fix: {'type': 'compilation', 'segments': [{'start': 0, 'end': 60}, {'start': 100, 'end': 160}],
#             'crop_style': 'zoom', 'boundary_transitions': ['crossfade']}
```

Confirmed: previously raised `CompilationError`; now returns a valid entry (2 fitted segments, `boundary_transitions` truncated to `['crossfade']`) instead of raising. COMP-02 is unblocked.

## Final Regression Check

`python -m pytest -m "not integration" -q` (with `--basetemp` override for this machine's permission-locked default pytest temp dir — a pre-existing environment quirk documented in STATE.md, unrelated to any code change in this plan):

```
410 passed, 5 skipped, 9 deselected, 1 warning
```

No failures. (409 before Task 3's new test was added; 410 after.)

## Deviations from Plan

### Auto-fixed Issues

None beyond what the plan itself specified — all three tasks were executed exactly per their `<action>`/`<behavior>` specs with no additional Rule 1-3 fixes required.

### Notes

**1. [Informational] Plan's existing-test-count text was off by one**
- **Found during:** Task 1
- **Detail:** The plan's `<behavior>`/`<done>` text referred to "7 existing tests" / "all 9 tests" in `tests/test_compilation.py`, but the file actually had 8 pre-existing tests (including `test_min_group_size_constant_is_two`), so the post-task total is 10, not 9. This is a plan-authoring miscount, not a code issue — none of the 8 existing tests were modified, and both new tests were added as specified. No action needed; documented here for traceability.

**2. [Expected, pre-existing convention] SKILL.md edits not committed**
- **Found during:** Task 2
- **Detail:** `.claude/` is gitignored project-wide in this repo. Task 2's edits to `.claude/skills/make-shorts/SKILL.md` therefore live on disk only, not in git history — this matches the identical situation already documented for Plans 02-01 and 04-06 in STATE.md's Roadmap Evolution log. Not a deviation from expected behavior; no fix applied or needed.

### WR-04 — Explicitly Deferred (not addressed in this pass)

Per this plan's own objective, `WR-04` (duplication between `_build_compilation_fold` and `_build_transition_fold` in `scripts/render.py`) was explicitly out of scope for this gap-closure plan and was not touched. `scripts/render.py` was not modified.

## Self-Check: PASSED

- `scripts/compilation.py` — FOUND, contains the truncation fix
- `tests/test_compilation.py` — FOUND, 10 tests, all passing
- `scripts/candidates.py` — FOUND, contains the `.get()` defensive access
- `tests/test_candidates.py` — FOUND, 16 tests, all passing
- `.claude/skills/make-shorts/SKILL.md` — FOUND on disk (gitignored, no commit hash to verify — see Deviations note 2)
- Commit `d048a95` (Task 1) — FOUND in git log
- Commit `3c9e2df` (Task 3) — FOUND in git log
- CR-01 repro snippet — directly executed, confirmed fixed (see above)
- Final regression: 410 passed, 0 failed
