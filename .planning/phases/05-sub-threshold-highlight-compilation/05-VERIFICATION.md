---
phase: 05-sub-threshold-highlight-compilation
verified: 2026-07-10T09:00:00Z
status: gaps_found
score: 2/3 must-haves verified
behavior_unverified: 0
overrides_applied: 0
gaps:
  - truth: "Similar-tagged sub-threshold candidates (same gameplay situation or same joke/theme) from the same source video/session get grouped together and rendered as one full-length short, joined via Phase 4's transition engine"
    status: failed
    reason: "CR-01 (05-REVIEW.md, Critical, empirically reproduced): scripts/compilation.py:build_compilation_entry validates boundary_transitions length against the POST-cap (fitted) member list (lines 68-94), but SKILL.md step 5b computes boundary_transitions PRE-cap (bullet 4 flattens ALL group members before capping ever runs; bullet 5 runs select-transitions against that full uncapped list; only bullet 8's compilation.py CLI call ever applies the length-ceiling cap). Whenever compilation_max_seconds capping actually drops trailing (weakest) members AND config.transitions.enabled is true — both real, tested, non-edge-case pipeline states — build_compilation_entry always raises CompilationError, and SKILL.md step 8 has no documented fail-open handling for this specific call (unlike step 5b bullet 5's explicit 'fail open, do not abort' framing for the transitions-selection sub-step itself). The compilation for that group is not built, so those sub-threshold candidates are not rendered as a full-length short in that run — directly failing this success criterion under the exact 'similar-tagged + grouped + stitched via transition engine' condition it describes, whenever the group also happens to overflow compilation_max_seconds."
    artifacts:
      - path: "scripts/compilation.py"
        issue: "Lines 68-81 (capping loop) run before lines 83-94 (boundary_transitions length validation), but the validation compares against len(fitted) (post-cap), while SKILL.md's step 5b (lines 202-230 of .claude/skills/make-shorts/SKILL.md) computes and passes a boundary_transitions list sized for the full pre-cap member list — the two are never reconciled."
      - path: ".claude/skills/make-shorts/SKILL.md"
        issue: "Step 5b bullet 5 (transitions) runs before bullet 8 (compilation.py build, which is the only place capping happens) with no instruction to recompute or truncate boundary_transitions after capping, and step 8 documents no fail-open/catch behavior for a CompilationError from this specific CLI call."
    missing:
      - "Either: truncate the caller-supplied boundary_transitions to the fitted prefix inside build_compilation_entry (capping only ever drops a contiguous trailing run, so this is safe per the reviewer's own analysis), or update SKILL.md step 5b to recompute select-transitions after determining which members survive capping."
      - "A regression test in tests/test_compilation.py that exercises capping (dropping >=1 member) together with a non-None boundary_transitions list sized for the pre-cap member set — this exact combination has zero test coverage today (confirmed: none of the 7 existing build_compilation_entry tests combine capping with boundary_transitions)."
---

# Phase 5: Sub-Threshold Highlight Compilation Verification Report

**Phase Goal:** Moments too short to stand alone are grouped by similarity and stitched into one coherent full-length short instead of being discarded
**Verified:** 2026-07-10T09:00:00Z
**Status:** gaps_found
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Candidates shorter than `config.clip.min_seconds` show up tagged with gameplay/theme tags in review output instead of silently disappearing | ✓ VERIFIED | `Candidate` dataclass (scripts/candidates.py:9-27) carries `tag`/`sub_threshold`/`group_id`/`unmatched`; `merge_candidates` threads them through via `.get()` (lines 39-59); `append_compilation_sections_markdown` (lines 83-110) appends `## Sub-Threshold Compilations`/`## Unmatched Sub-Threshold` sections to CANDIDATES.md, confirmed substantive (not stub) by reading the function body; SKILL.md step 5 bullet "Sub-threshold detection + tagging" (line 130) documents the trigger; step 5b bullet 9 (lines 232-236) wires the append call. All 8 candidates.py tests pass (`pytest tests/test_candidates.py`, verified directly). |
| 2 | Similar-tagged sub-threshold candidates (same gameplay situation or same joke/theme) from the same source video/session get grouped together and rendered as one full-length short, joined via Phase 4's transition engine | ✗ FAILED | Grouping/ordering/PLAN.json-entry mechanics all exist and are individually well-tested (`scripts/compilation.py::build_compilation_entry`, `scripts/render.py::build_compilation_command`/`_build_compilation_fold`, `render_clip`'s `type=="compilation"` dispatch, SKILL.md step 5b). **However CR-01 (05-REVIEW.md) is a confirmed, reproducible Critical defect**: `build_compilation_entry` validates `boundary_transitions` length against the post-cap `fitted` list, but SKILL.md step 5b computes `boundary_transitions` pre-cap. Verified independently by direct reproduction (see below) — whenever `config.transitions.enabled` is true AND `compilation_max_seconds` capping actually drops trailing members (both realistic, non-edge-case run states), `build_compilation_entry` always raises `CompilationError` and that compilation is never built. This is not a hypothetical: `test_build_compilation_entry_caps_at_compilation_max_seconds_dropping_weakest` (which proves capping drops members) and `test_build_compilation_entry_rejects_boundary_transitions_length_mismatch` (which proves the length guard fires) both pass individually, but no test exercises them together — the exact gap the reviewer found. |
| 3 | Compilation groups never mix candidates from different source videos/sessions in this version | ✓ VERIFIED | `build_compilation_entry` Guard 2 (scripts/compilation.py:56-60) computes `{member["video_stem"] for member in members}` and raises `CompilationError` if more than one distinct value exists. `test_build_compilation_entry_requires_same_video_stem` passes. SKILL.md step 5b bullet 1 (line 202) explicitly instructs "never group candidates from two different video_stems together (COMP-03)". |

**Score:** 2/3 truths verified (1 present-but-defective, tracked as a gap, not behavior-unverified — the defect was directly reproduced, not merely un-exercised)

### CR-01 Direct Reproduction (independent of 05-REVIEW.md's own repro)

```python
from scripts.compilation import build_compilation_entry
members = [
    {"video_stem": "mystream", "start": 0, "end": 60},
    {"video_stem": "mystream", "start": 100, "end": 160},
    {"video_stem": "mystream", "start": 200, "end": 260},
]
build_compilation_entry(members, 150, "zoom", boundary_transitions=["crossfade", "crossfade"])
# -> CompilationError: boundary_transitions must have length 1 (flattened segment count 2 - 1), got 2
```
Ran this verbatim against the current on-disk `scripts/compilation.py` — confirmed the exception fires exactly as 05-REVIEW.md describes. This is the strongest form of evidence available (executed code, not narration).

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `scripts/candidates.py` | Candidate tag/sub_threshold/group_id/unmatched fields + append_compilation_sections_markdown | ✓ VERIFIED | Present, substantive, wired (8 tests pass) |
| `scripts/config.py` | `ClipConfig.compilation_max_seconds` (default 150) + `_validate` guard > max_seconds | ✓ VERIFIED | Lines 50, 286-289; tests pass |
| `scripts/compilation.py` | `CompilationError`, `MIN_GROUP_SIZE`, `build_compilation_entry` | ⚠️ VERIFIED-WITH-DEFECT | Exists, substantive, wired, all 7 unit tests pass individually — but CR-01's capping/boundary_transitions interaction is unhandled (see gap above) |
| `scripts/render.py` | `build_compilation_command`, `_build_compilation_fold`, `render_clip` dispatch on `type=="compilation"` | ✓ VERIFIED | Lines 626 (`_build_compilation_fold`), 707 (`build_compilation_command`), 935 (dispatch); 13 compilation-named unit tests + 1 real-ffmpeg integration test all pass (verified directly) |
| `.claude/skills/make-shorts/SKILL.md` | Step 5 sub-threshold bullet, step 5b grouping subsection, PLAN.json schema update, step 6 note | ✓ VERIFIED (content present) | Read directly (gitignored, confirmed on-disk); step 5 line 130, step 5b lines 198-236; but step 5b's bullet ordering (transitions computed at bullet 5, capping only happens at bullet 8) is the root cause of CR-01 |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|----|--------|---------|
| `merge_candidates`'s `.get()` reads | Candidate dataclass fields | direct assignment | ✓ WIRED | Confirmed in code |
| `append_compilation_sections_markdown` | CANDIDATES.md | read-append-rewrite | ✓ WIRED | No-op-when-empty and content-append both tested |
| `build_compilation_entry`'s returned dict | `render_clip`'s `type=="compilation"` dispatch | PLAN.json entry shape (`type`, `segments`, `crop_style`, ...) | ✓ WIRED | `render_clip` reads `plan_entry["segments"]`/`plan_entry.get("boundary_transitions")` etc. exactly matching `build_compilation_entry`'s output shape |
| SKILL.md step 5b bullet 5 (transitions, pre-cap flattened list) | SKILL.md step 5b bullet 8 (`compilation.py` CLI, applies cap) | file hand-off (`<compilation_stem>_boundary.json` -> `--boundary-transitions-json`) | ✗ NOT RECONCILED | This is the exact link CR-01 identifies as broken — the two bullets operate on lists of different (pre-cap vs. post-cap) lengths with nothing in between reconciling them |
| `scripts/transitions.py::select_boundary_transitions` | Step 5b's flattened segment list | unchanged CLI reuse | ✓ WIRED | Confirmed via SKILL.md text; not independently re-tested here (Plan 04's own scope) |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| candidates/compilation/config unit tests | `pytest tests/test_candidates.py tests/test_compilation.py tests/test_config.py -q` | 88 passed | ✓ PASS |
| render.py compilation-named unit tests | `pytest tests/test_render.py -k compilation -q` | 13 passed | ✓ PASS |
| Full non-integration suite (regression check) | `pytest -m "not integration" -q` | 407 passed, 5 skipped | ✓ PASS (matches 05-03/05-04 SUMMARY claims exactly) |
| Real-ffmpeg compilation integration test | `pytest tests/test_integration_ffmpeg.py -k compilation -m integration -q` | 1 passed | ✓ PASS |
| CR-01 direct reproduction | `python -c "...build_compilation_entry(... boundary_transitions=[...])"` | `CompilationError` raised as predicted | ✓ CONFIRMS GAP (not a pass/fail spot-check — this is adversarial evidence the defect is real) |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| COMP-01 | 05-01, 05-04 | Candidates shorter than min_seconds are tagged instead of discarded | ✓ SATISFIED | Truth #1 verified above |
| COMP-02 | 05-02, 05-03, 05-04 | Similar-tagged sub-threshold candidates grouped and stitched via TRANS engine into one full-length short | ✗ BLOCKED | Truth #2 failed — CR-01 breaks exactly this requirement's "joined via the transition engine" clause under a real, non-edge-case condition combination |
| COMP-03 | 05-02, 05-04 | Compilation only groups candidates from the same source video/session | ✓ SATISFIED | Truth #3 verified above |

No orphaned requirements — REQUIREMENTS.md maps only COMP-01/02/03 to Phase 5, and all three appear in at least one plan's `requirements` frontmatter field.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| — | — | No TBD/FIXME/XXX/TODO/HACK/PLACEHOLDER markers found in scripts/candidates.py, scripts/compilation.py, scripts/config.py, scripts/render.py | — | Clean |
| scripts/compilation.py:62-94 | 62-94 | CR-01 logic defect (not a marker-based anti-pattern, but a genuine correctness gap between two validation passes) | 🛑 Blocker | See gap above |

Additionally, per 05-REVIEW.md (not independently re-verified line-by-line here, but consistent with direct code reading): WR-01 (SKILL.md step 9/5b references `groups.json`/`unmatched.json` as pre-existing inputs with no earlier bullet instructing the orchestrator to write them as it works through the grouping pass — confirmed by reading SKILL.md lines 232-236 directly, no accumulation instruction precedes it), WR-02 (compilation karaoke-words file path relies on an unstated naming convention), WR-03 (unchecked dict indexing in `append_compilation_sections_markdown`), WR-04 (fold-loop duplication between `_build_transition_fold`/`_build_compilation_fold`). These are Warnings, not independently re-scored as blockers here — they don't break a stated Success Criterion the way CR-01 does, but WR-01 in particular weakens confidence in truth #1's end-to-end reliability (the append call's own inputs are undocumented bookkeeping) and is worth the same attention during gap closure.

### Human Verification Required

None. All three success criteria were resolvable via direct code reading, test execution, and one adversarial reproduction — no visual/UX/external-service judgment calls remain open.

### Gaps Summary

Phase 5's mechanical scaffolding (tagging, config knob, group validation, multi-input render fold, SKILL.md orchestration wiring) is real, substantive, and individually well-tested — this is not a stub-detection failure. The single blocking gap is a genuine **integration defect between two pieces that were each tested in isolation but never tested together**: `build_compilation_entry`'s length-ceiling capping (tested) and its `boundary_transitions` length validation (tested) interact incorrectly the moment both a non-trivial cap-drop and a non-None `boundary_transitions` list are present in the same call — a combination SKILL.md's own step 5b will produce on any real run where a sub-threshold group's full uncapped duration exceeds `compilation_max_seconds` and `config.transitions.enabled` is true. This directly undermines Success Criterion 2's explicit "joined via Phase 4's transition engine" clause — not in a rare edge case, but in the ordinary "long group + transitions on" path the feature is meant to handle. The pipeline itself is fail-open (per its own threat model) and won't crash, but the affected compilation silently fails to render, which is exactly the kind of silent-discard-under-real-conditions outcome this phase exists to prevent for sub-threshold candidates in the first place.

Recommended closure path (per 05-REVIEW.md's own fix suggestion, endorsed here as the simpler option): truncate the caller-supplied `boundary_transitions` to the fitted prefix inside `build_compilation_entry` (mechanically safe, since capping only ever drops a contiguous trailing run — the pre-cap boundary list's prefix is exactly the boundaries that survive), plus a new regression test combining capping with a boundary_transitions list sized for the pre-cap member set.

---

_Verified: 2026-07-10T09:00:00Z_
_Verifier: Claude (gsd-verifier)_
