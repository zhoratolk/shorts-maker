---
phase: 01-monetization-risk-flagging-creator-style-profile
plan: 03
subsystem: creator-style-profile
tags: [python, style-profile, few-shot, privacy, tdd]

# Dependency graph
requires: []
provides:
  - "scripts/style_profile.py: load_analytics_cache/derive_profile/write_profile/main, pure transform over youtube_analytics.py's cache"
  - "work/_profile/style_profile.json: gitignored, generated few-shot naming/moment-selection artifact"
affects: [phase-2-llm-titles-tags]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Pure transform over an already-cached artifact: style_profile.py never calls the YouTube APIs itself, it only reads youtube_analytics.py's JSON cache (ARCHITECTURE Pattern 2)"
    - "Concrete few-shot examples, never prose: naming/moment examples carry the actual real title string + a numeric performance signal, satisfying PITFALLS.md Pitfall 5"
    - "Gitignored-by-construction output: default write target is under work/_profile/, verified by an automated privacy-guard test (path-under-work/ assertion + git check-ignore when git is available) rather than a manual git status check"

key-files:
  created:
    - scripts/style_profile.py
    - tests/test_style_profile.py
  modified:
    - .gitignore

key-decisions:
  - "Performance signal prefers average_view_percentage when present, falls back to view_count - matches youtube_analytics.py's own fail-open comment that Analytics API data (retention) can be unavailable while Data API stats (views) still are"
  - "moment_examples reuses the same ranked (title, signal) shape as naming_examples in this plan - Phase 2 is expected to extend this with richer per-moment context once real usage data exists (kept minimal per YAGNI, no speculative schema fields)"
  - "Privacy-guard test asserts the path relationship (target resolves under work/) deterministically, with an additional git check-ignore assertion only when a git binary is available - avoids a hard dependency on git being on PATH in CI while still proving the real ignore rule works locally"

patterns-established:
  - "Explicit work/_profile/ comment in .gitignore documents the privacy boundary even though the existing work/ entry already covers it - belt-and-suspenders per the project's prior real leaked-channel-data incident"

requirements-completed: [STYLE-01, STYLE-02, STYLE-03]

coverage:
  - id: D1
    description: "derive_profile(records) produces concrete naming/moment-selection examples (real title + numeric signal), not prose, ranked by real performance"
    requirement: "STYLE-02"
    verification:
      - kind: unit
        ref: "tests/test_style_profile.py::test_derive_profile_naming_examples_are_concrete_not_prose"
        status: pass
      - kind: unit
        ref: "tests/test_style_profile.py::test_derive_profile_ranks_naming_examples_by_performance_signal"
        status: pass
      - kind: unit
        ref: "tests/test_style_profile.py::test_derive_profile_emits_structured_moment_selection_examples"
        status: pass
      - kind: unit
        ref: "tests/test_style_profile.py::test_derive_profile_has_machine_readable_schema"
        status: pass
    human_judgment: false
  - id: D2
    description: "load_analytics_cache reads youtube_analytics.py's existing JSON cache with no parallel OAuth/auth flow of its own"
    requirement: "STYLE-01"
    verification:
      - kind: unit
        ref: "manual: scripts/style_profile.py contains no OAuth/token/client_secret code, only json.loads over the cache path"
        status: pass
    human_judgment: false
  - id: D3
    description: "write_profile defaults to work/_profile/style_profile.json (gitignored); derive_profile([]) fails open to a valid empty profile; no real title/stat lands in a tracked file"
    requirement: "STYLE-03"
    verification:
      - kind: unit
        ref: "tests/test_style_profile.py::test_derive_profile_empty_input_fails_open"
        status: pass
      - kind: unit
        ref: "tests/test_style_profile.py::test_privacy_write_profile_default_target_is_under_gitignored_work_dir"
        status: pass
      - kind: manual
        ref: "git status --short after running python scripts/style_profile.py showed no new tracked/untracked-non-ignored file"
        status: pass
    human_judgment: false

duration: ~25min
completed: 2026-07-07
status: complete
---

# Phase 1 Plan 3: Creator Style/Naming Profile Summary

**Pure-function style-profile step (scripts/style_profile.py) that reads youtube_analytics.py's existing cache and derives concrete, performance-ranked few-shot naming/moment-selection examples, writing only to a gitignored work/_profile/ artifact.**

## Performance

- **Duration:** ~25 min
- **Tasks:** 3 (consolidated: the privacy-guard test from Task 3 was written directly into the Task 1 test file rather than appended later, since both belong to the same test module and the plan's own Task 3 action only required adding one test function to it)
- **Files modified:** 3 (2 created, 1 modified)

## Accomplishments

- `scripts/style_profile.py`: `load_analytics_cache()` (reads `youtube_analytics.py`'s JSON cache, fails open to `[]` on missing/malformed file), `derive_profile()` (ranks real records by performance signal into concrete `naming_examples`/`moment_examples`, each `{title, signal}` — never a prose summary), `write_profile()` (JSON write, `ensure_ascii=False`, `mkdir parents`, defaults to `work/_profile/style_profile.json`), CLI `main()`.
- `tests/test_style_profile.py`: 6 tests — concrete-not-prose naming examples, performance-ranked ordering, structured moment examples, machine-readable schema (`schema_version` int), empty-input fail-open, and a privacy-guard test proving the default write target resolves under the gitignored `work/` tree (plus a `git check-ignore` assertion when git is available).
- `.gitignore`: added an explicit `work/_profile/` comment documenting the privacy boundary directly under the existing `work/` entry.

## Task Commits

1. **Task 1: Failing test — derive a structured few-shot style profile from analytics records** - `a4dfcb4` (test)
2. **Task 2 + 3: Implement derive_profile + gitignored cache writer, including the privacy-guard test** - `4e23e39` (feat)

_Note: Task 3's privacy-guard test was written as part of the same test file edit as Task 1/2 (single cohesive test module), then verified and committed together with the implementation once green — the plan's three tasks map to two commits because the privacy assertion is a single test function addition, not a separate file or feature._

## Files Created/Modified

- `scripts/style_profile.py` - `load_analytics_cache`, `derive_profile`, `write_profile`, CLI `main()`
- `tests/test_style_profile.py` - 6 tests covering STYLE-01/02/03 and the privacy guard
- `.gitignore` - explicit `work/_profile/` privacy comment

## Decisions Made

- Performance signal: `average_view_percentage` preferred, `view_count` fallback — mirrors `youtube_analytics.py`'s own documented fail-open behavior when the Analytics API half of a fetch is unreachable.
- `moment_examples` currently mirrors `naming_examples`' shape (title + signal) rather than inventing a separate moment-taxonomy schema now — avoids speculative fields Phase 2 doesn't need yet; extendable without a breaking schema change since `schema_version` is already tracked.
- Privacy-guard test checks the path-under-`work/` invariant unconditionally, and additionally shells out to `git check-ignore` only if `git` is on PATH — keeps the test deterministic in any environment while still proving the real ignore rule when git is available (it is, on this machine — verified passing).

## Deviations from Plan

None of substance. Tasks 2 and 3 landed in one commit rather than two, since Task 3's entire scope was one additional test function appended to the same file Task 1/2 already touched — no separate implementation work was needed to satisfy it beyond what Task 2 already built.

## Issues Encountered

- Same environment-only pytest temp-dir `PermissionError` (Cyrillic Windows username) noted in Plan 01-01's summary — worked around with `TMPDIR`/`TEMP`/`TMP` pointed at the session scratchpad for verification; no code changes needed.

## User Setup Required

None. No new credentials, env vars, or external services — this step only reads a cache file `scripts/youtube_analytics.py` already produces.

## Next Phase Readiness

- `work/_profile/style_profile.json`'s `{schema_version, naming_examples: [{title, signal}], moment_examples: [{title, signal}]}` shape is the established contract Phase 2 (LLM title/tag generation, TAGS-03) will read as few-shot grounding.
- No blockers. Running `scripts/style_profile.py` against a real `youtube_analytics.py` cache (once the user has one) requires no further wiring beyond what this plan delivers — SKILL.md orchestration wiring for Phase 2 is out of scope here.

---
*Phase: 01-monetization-risk-flagging-creator-style-profile*
*Completed: 2026-07-07*

## Self-Check: PASSED

All created files and commit hashes verified present on disk / in git log.
