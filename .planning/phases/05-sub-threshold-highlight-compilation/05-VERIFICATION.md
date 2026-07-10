---
phase: 05-sub-threshold-highlight-compilation
verified: 2026-07-10T10:59:01Z
status: passed
score: 3/3 must-haves verified
behavior_unverified: 0
overrides_applied: 0
re_verification:
  previous_status: gaps_found
  previous_score: 2/3
  gaps_closed:
    - "Similar-tagged sub-threshold candidates get grouped together and rendered as one full-length short, joined via Phase 4's transition engine (CR-01 fixed — build_compilation_entry now truncates a pre-cap boundary_transitions list to the fitted post-cap prefix before length-validating, instead of always raising CompilationError when capping drops members and transitions are enabled)"
  gaps_remaining: []
  regressions: []
---

# Phase 5: Sub-Threshold Highlight Compilation Verification Report

**Phase Goal:** Moments too short to stand alone are grouped by similarity and stitched into one coherent full-length short instead of being discarded
**Verified:** 2026-07-10T10:59:01Z
**Status:** passed
**Re-verification:** Yes — after gap closure (05-05-PLAN.md, gap_closure: true)

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Candidates shorter than `config.clip.min_seconds` show up tagged with gameplay/theme tags in review output instead of silently disappearing | ✓ VERIFIED | Unchanged since prior pass. `Candidate` dataclass (scripts/candidates.py:9-27) carries `tag`/`sub_threshold`/`group_id`/`unmatched`; `merge_candidates` threads them through via `.get()`; `append_compilation_sections_markdown` (scripts/candidates.py:83-115) appends `## Sub-Threshold Compilations`/`## Unmatched Sub-Threshold` sections to CANDIDATES.md. Now additionally hardened by 05-05's WR-03 fix: unchecked `member['id']`/`group['title']`/`candidate['reason']`/`candidate['tag']` bracket access replaced with `.get()`-with-default (verified by direct code read, lines 97, 100, 110-111). Independently re-ran `pytest tests/test_candidates.py -q`: 16 passed (was 8 pre-Phase-5-baseline; 14 pre-05-05, +2 new in 05-05 including `test_append_compilation_sections_markdown_defaults_missing_fields`, confirmed present via `--collect-only`). |
| 2 | Similar-tagged sub-threshold candidates (same gameplay situation or same joke/theme) from the same source video/session get grouped together and rendered as one full-length short, joined via Phase 4's transition engine | ✓ VERIFIED | **CR-01 closed.** Independently re-read `scripts/compilation.py:87-103` (not just SUMMARY narration): the caller-supplied `boundary_transitions` is now truncated to `expected_length` (the post-cap fitted boundary count) via `boundary_transitions = boundary_transitions[:expected_length]` *before* the existing `if len(boundary_transitions) != expected_length: raise CompilationError(...)` check. Independently re-ran the exact CR-01 repro snippet from the prior 05-VERIFICATION.md against the current on-disk module (see reproduction below) — it now returns a valid entry instead of raising. Also independently verified a genuinely-too-short list (unrelated to capping) still raises `CompilationError` — the fix truncates, it does not silently accept any length. |
| 3 | Compilation groups never mix candidates from different source videos/sessions in this version | ✓ VERIFIED | Unchanged since prior pass. `build_compilation_entry` Guard 2 (scripts/compilation.py:56-60) computes `{member["video_stem"] for member in members}` and raises `CompilationError` if more than one distinct value exists — confirmed present and untouched by the gap-closure diff. `test_build_compilation_entry_requires_same_video_stem` confirmed present via `--collect-only` and passing. |

**Score:** 3/3 truths verified (0 present-but-behavior-unverified)

### Truth #2 Independent Re-Verification (fresh, not carried over)

**1. Exact prior repro snippet, re-run against current code:**

```python
from scripts.compilation import build_compilation_entry, CompilationError
members = [
    {"video_stem": "mystream", "start": 0, "end": 60},
    {"video_stem": "mystream", "start": 100, "end": 160},
    {"video_stem": "mystream", "start": 200, "end": 260},
]
entry = build_compilation_entry(members, 150, "zoom", boundary_transitions=["crossfade", "crossfade"])
print(entry)
```

Actual output (executed directly by this verifier, not narrated):

```
{'type': 'compilation', 'segments': [{'start': 0, 'end': 60}, {'start': 100, 'end': 160}], 'crop_style': 'zoom', 'boundary_transitions': ['crossfade']}
```

No exception raised. Capping drops the third member (running_total 60+60=120, +60=180 > 150 → stop), leaving 2 fitted members / 1 boundary. The pre-cap 2-length `boundary_transitions` is truncated to its own first-element prefix `['crossfade']`, matching the truncate-not-pad contract.

**2. Genuinely-too-short list (unrelated to capping) still raises:**

```python
build_compilation_entry(members, 150, "zoom", boundary_transitions=[])
```

Actual output: `CompilationError: boundary_transitions must have length 1 (flattened segment count 2 - 1), got 0` — raised as expected. Confirms the fix is a truncate-only reconciliation, not a relaxed/removed guard: a list that is still short after truncation (here, trivially short since it was empty) continues to fail closed.

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `scripts/compilation.py` | `CompilationError`, `MIN_GROUP_SIZE`, `build_compilation_entry` with truncate-then-validate `boundary_transitions` handling | ✓ VERIFIED | Lines 87-103 read directly; truncation logic confirmed correct by independent execution (above), not just static reading |
| `tests/test_compilation.py` | Regression tests combining capping-drops-members with a pre-cap-sized `boundary_transitions`, plus a still-too-short-after-truncation case | ✓ VERIFIED | `test_build_compilation_entry_caps_and_truncates_boundary_transitions` and `test_build_compilation_entry_still_rejects_too_short_boundary_transitions` confirmed present via `pytest --collect-only`; both pass as part of the file's 10/10 passing tests |
| `scripts/candidates.py` | Defensive `.get()` access in `append_compilation_sections_markdown` (WR-03) | ✓ VERIFIED | Lines 97, 100, 110-111 read directly; `member['id']`/`group['title']`/`candidate['reason']`/`candidate['tag']` all now `.get(...)`-with-default; `start`/`end` intentionally left as required bracket access (structural, not display-only) |
| `tests/test_candidates.py` | New regression test for missing-field defaulting (WR-03) | ✓ VERIFIED | `test_append_compilation_sections_markdown_defaults_missing_fields` confirmed present and passing |
| `.claude/skills/make-shorts/SKILL.md` | Step 5b bullet 9 explicit groups.json/unmatched.json write instruction (WR-01); bullet 7 explicit compilation words-file literal path (WR-02) | ✓ VERIFIED | Read directly (gitignored, confirmed on-disk): bullet 9 (SKILL.md:236) now reads "as bullets 1-8 above are worked through, accumulate two running JSON files... write them yourself (they do not exist beforehand); start each as `[]` before the first append..."; bullet 7 (SKILL.md:224-227) now spells out the literal path `work/<video_stem>/compilations/<compilation_stem>_words.json` and the full three-arg `remap-words` CLI invocation |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|----|--------|---------|
| SKILL.md step 5b bullet 5 (transitions computed pre-cap, full uncapped flattened segment list) | scripts/compilation.py CLI (step 8, where capping actually happens) -> build_compilation_entry's own truncation | file hand-off (`<compilation_stem>_boundary.json` -> `--boundary-transitions-json`) reconciled inside the function | ✓ WIRED (was ✗ NOT RECONCILED) | This is the exact link CR-01 identified as broken. Now reconciled: `build_compilation_entry` truncates the pre-cap list to the fitted post-cap prefix itself, so SKILL.md no longer needs to predict the cap result in advance. Independently confirmed by direct execution above, not just code reading. |
| `build_compilation_entry`'s returned dict | `render_clip`'s `type=="compilation"` dispatch | PLAN.json entry shape | ✓ WIRED | Unchanged since prior pass; `render.py` compilation-named tests still pass (see spot-checks) |
| `merge_candidates`'s `.get()` reads | Candidate dataclass fields | direct assignment | ✓ WIRED | Unchanged since prior pass |
| `append_compilation_sections_markdown` | CANDIDATES.md | read-append-rewrite, now defensive against missing fields | ✓ WIRED | Unchanged wiring, hardened field access (WR-03) |
| SKILL.md step 5b bullets 1-8 (groups/unmatched decided) | groups.json/unmatched.json | explicit accumulate-as-you-go instruction (WR-01, was undocumented) | ✓ WIRED | Now explicit; previously an unexplained pre-existing-input assumption |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| CR-01 exact repro (3 members, 60/60/60, cap 150, boundary_transitions sized for pre-cap 2-boundary list) | `python -c "...build_compilation_entry(...)"` | Returns valid entry, `boundary_transitions == ['crossfade']`, no exception | ✓ PASS (was ✗ FAIL / CompilationError in prior verification) |
| Genuinely-too-short boundary_transitions (empty list, unrelated to capping) | `python -c "...build_compilation_entry(..., boundary_transitions=[])"` | `CompilationError: ...got 0` raised | ✓ PASS (truncate-only, not a relaxed guard) |
| tests/test_compilation.py | `pytest tests/test_compilation.py -q` | 10 passed | ✓ PASS |
| tests/test_candidates.py | `pytest tests/test_candidates.py -q` | 16 passed | ✓ PASS |
| New test names present (not just claimed) | `pytest tests/test_compilation.py tests/test_candidates.py --collect-only -q \| grep -E "truncat\|still_rejects\|defaults_missing"` | All 3 new test IDs listed | ✓ PASS |
| Full non-integration regression suite (run once, not per-truth) | `pytest -m "not integration" -q --basetemp=/tmp/pytest-scratch` | 410 passed, 5 skipped, 9 deselected | ✓ PASS (matches 05-05-SUMMARY.md's claimed count exactly) |

Note: this machine's default pytest tmp dir breaks under the Cyrillic Windows username (`PermissionError` mentioning `pytest-of-`); `--basetemp=/tmp/pytest-scratch` was used to work around it, per the task instructions — this is an environment quirk unrelated to any code under test, and does not affect the pass/fail outcome (identical to the workaround 05-05-SUMMARY.md itself documents).

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|--------------|--------|----------|
| COMP-01 | 05-01, 05-04, 05-05 (WR-03 hardening) | Candidates shorter than min_seconds are tagged instead of discarded | ✓ SATISFIED | Truth #1 verified above; REQUIREMENTS.md marks `[x]` and "Complete" |
| COMP-02 | 05-02, 05-03, 05-04, 05-05 (CR-01 fix) | Similar-tagged sub-threshold candidates grouped and stitched via TRANS engine into one full-length short | ✓ SATISFIED (was ✗ BLOCKED) | Truth #2 verified above via fresh, independent reproduction — CR-01 confirmed closed by direct execution, not narration; REQUIREMENTS.md marks `[x]` and "Complete" |
| COMP-03 | 05-02, 05-04 | Compilation only groups candidates from the same source video/session | ✓ SATISFIED | Truth #3 verified above; REQUIREMENTS.md marks `[x]` and "Complete" |

No orphaned requirements — REQUIREMENTS.md maps only COMP-01/02/03 to Phase 5, and all three appear in 05-05-PLAN.md's own `requirements` frontmatter field (`[COMP-01, COMP-02]`) plus prior plans' frontmatter.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| — | — | No TBD/FIXME/XXX/TODO/HACK/PLACEHOLDER markers found in scripts/candidates.py, scripts/compilation.py (re-scanned on current code) | — | Clean |
| — | — | CR-01 logic defect (prior 🛑 Blocker) | — | **Resolved.** Truncate-then-validate logic confirmed correct by independent execution, not just reading. |

05-REVIEW.md (re-review dated 2026-07-10T00:00:00Z, after 05-05's gap closure) independently confirms: CR-01 fixed, WR-01 fixed, WR-02 fixed, WR-03 fixed (all four re-verified against current code by the reviewer, matching this verifier's own independent findings). WR-04 (fold-loop duplication in render.py) remains explicitly deferred — a maintainability-only observation with zero functional impact on any Success Criterion, not part of this plan's scope, and does not block phase completion. The review surfaced two new lower-severity Warning findings during its adversarial re-review of the whole phase (not just the gap-closure diff):

- **WR-05** (SKILL.md's illustrative compilation `PLAN.json` example combines `crop_style: "pad"` with `punch_zoom_at`, and its `boundary_transitions` length doesn't match its own `segments` shape — an internally-inconsistent reference example, not a runtime code defect).
- **WR-06** (SKILL.md step 5b bullet 8 reads `<compilation_stem>_members.json` with no earlier bullet instructing it be written — the same class of documentation gap as WR-01, but for a different file).

Both are SKILL.md documentation-only issues discovered in this re-review pass, outside 05-05-PLAN.md's declared scope (which targeted only CR-01/WR-01/WR-02/WR-03). Neither breaks a stated Success Criterion or blocks a requirement — `scripts/compilation.py`'s CLI itself still functions correctly when `_members.json` is actually written (confirmed by this verifier's direct code/test execution above), and WR-05's broken example is illustrative text, not code invoked at runtime. These are tracked here as informational follow-up, not phase-blocking gaps; they do not affect the phase goal ("moments too short to stand alone are grouped by similarity and stitched into one coherent full-length short") which is achieved by the underlying Python mechanics, independently verified above.

### Human Verification Required

None. All three success criteria and the CR-01 gap closure were resolvable via direct code reading, independent test execution, and adversarial reproduction of both the fixed case and the still-must-fail case — no visual/UX/external-service judgment calls remain open.

### Gaps Summary

No gaps remain. The single blocking gap from the prior verification (CR-01: `build_compilation_entry` validated `boundary_transitions` length against the post-cap fitted list while SKILL.md computed it pre-cap, always raising `CompilationError` under the realistic "capping drops members + transitions enabled" combination) is confirmed closed by this verifier's own independent execution of both the original failing repro (now succeeds) and a genuinely-too-short case (still correctly raises). The three Warning-level findings addressed by 05-05 (WR-01/WR-02/WR-03) are also confirmed fixed by direct code reading. WR-04 remains explicitly and appropriately deferred. Two new lower-priority SKILL.md documentation findings (WR-05, WR-06) surfaced during the post-fix code review are informational follow-ups, not phase-blocking — they concern illustrative/doc text, not the tested Python mechanics that deliver the phase goal. Phase 5's goal — "moments too short to stand alone are grouped by similarity and stitched into one coherent full-length short instead of being discarded" — is achieved: tagging (COMP-01), grouping+stitching via the transition engine (COMP-02), and same-session-only grouping (COMP-03) are all implemented, tested, and independently confirmed working end-to-end at the mechanical level this phase's Python layer is responsible for.

---

_Verified: 2026-07-10T10:59:01Z_
_Verifier: Claude (gsd-verifier)_
