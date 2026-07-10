---
phase: 07-profanity-auto-bleep
plan: 01
subsystem: audio-processing
tags: [python, regex, yaml, whisper, profanity-detection, fail-open]

# Dependency graph
requires:
  - phase: 01-monetization-and-style
    provides: fail-open YAML wordlist-load pattern (monetization_risk.py::load_rules)
provides:
  - "scripts/profanity.py: load_wordlist, normalize_word, compile_patterns, find_profane_spans, argparse main() CLI"
  - "data/profanity_wordlist.yaml: committed RU+EN swear stem wordlist with obfuscation-normalization block"
  - "tests/test_profanity.py: 19 tests mirroring tests/test_monetization_risk.py structure"
affects: [07-02-render-masking, 07-03-config-toggle-or-plan-json-wiring]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Fail-open YAML wordlist load (missing/malformed -> empty dict + [warn] stderr, never raise) - exact mirror of monetization_risk.load_rules"
    - "re.escape() every data-file-supplied regex root before compiling word-boundary stems - ASVS V5 ReDoS guard"
    - "Detection consumes an already clip-relative word list; never reimplements jumpcuts.remap_words itself"

key-files:
  created:
    - scripts/profanity.py
    - data/profanity_wordlist.yaml
    - tests/test_profanity.py
  modified: []

key-decisions:
  - "TDD RED-phase obfuscation test fixture uses a strip_chars censor case (fu_ck) instead of Latin-leetspeak (f0ck), since the wordlist's substitutions map (0->о, 3->е, ...) targets Cyrillic obfuscation only, not Latin digit-for-letter substitution - matches the exact drafted normalize block in 07-RESEARCH.md verbatim"

patterns-established:
  - "Pattern 2 (clip-relative remap reuse): find_profane_spans accepts an already-remapped words list; a jump-cut-dropped word is simply absent from the input, proven by a dedicated remap interaction test calling jumpcuts.remap_words directly"

requirements-completed: [AUDIO-01]

coverage:
  - id: D1
    description: "load_wordlist fails open on missing/malformed wordlist files (D-04) - never raises, warns to stderr, returns empty-but-valid wordlist"
    requirement: "AUDIO-01"
    verification:
      - kind: unit
        ref: "tests/test_profanity.py::test_load_wordlist_missing_file_returns_empty_and_warns"
        status: pass
      - kind: unit
        ref: "tests/test_profanity.py::test_load_wordlist_malformed_yaml_returns_empty_and_warns"
        status: pass
    human_judgment: false
  - id: D2
    description: "normalize_word collapses leetspeak substitutions, censor-char stripping, and repeated-character runs to a bare stem (D-02 obfuscated spelling support)"
    requirement: "AUDIO-01"
    verification:
      - kind: unit
        ref: "tests/test_profanity.py::test_normalize_word_applies_substitutions_strip_and_collapse"
        status: pass
      - kind: unit
        ref: "tests/test_profanity.py::test_normalize_word_collapses_repeated_chars_leetspeak"
        status: pass
    human_judgment: false
  - id: D3
    description: "compile_patterns re.escape()s every wordlist root and rejects a stem match inside an unrelated word (Pitfall 1 false positive, ASVS V5 ReDoS guard)"
    requirement: "AUDIO-01"
    verification:
      - kind: unit
        ref: "tests/test_profanity.py::test_compile_patterns_escapes_root_and_rejects_non_boundary_match"
        status: pass
      - kind: unit
        ref: "tests/test_profanity.py::test_compile_patterns_treats_raw_regex_root_as_literal_not_backtracking"
        status: pass
    human_judgment: false
  - id: D4
    description: "find_profane_spans detects RU/EN/obfuscated stems, pads/clamps/merges spans, and fails open past max_masked_spans_per_clip (Pitfall 5)"
    requirement: "AUDIO-01"
    verification:
      - kind: unit
        ref: "tests/test_profanity.py::test_find_profane_spans_detects_ru_en_and_obfuscated_stems"
        status: pass
      - kind: unit
        ref: "tests/test_profanity.py::test_find_profane_spans_merges_overlapping_padded_spans"
        status: pass
      - kind: unit
        ref: "tests/test_profanity.py::test_find_profane_spans_span_cap_fail_open_returns_empty_and_warns"
        status: pass
    human_judgment: false
  - id: D5
    description: "Detection runs on an already clip-relative, post-jumpcut-remap word list; a word dropped by a jump cut is simply absent, with zero remap logic inside profanity.py (Pattern 2)"
    requirement: "AUDIO-01"
    verification:
      - kind: unit
        ref: "tests/test_profanity.py::test_find_profane_spans_remap_dropped_word_is_absent"
        status: pass
    human_judgment: false
  - id: D6
    description: "data/profanity_wordlist.yaml committed data file loads end-to-end and detects a known stem while leaving a clean control word unmasked"
    requirement: "AUDIO-01"
    verification:
      - kind: unit
        ref: "tests/test_profanity.py::test_shipped_wordlist_file_loads_with_normalize_ru_en"
        status: pass
      - kind: unit
        ref: "tests/test_profanity.py::test_shipped_wordlist_file_detects_known_stem_and_ignores_clean_word"
        status: pass
    human_judgment: false
  - id: D7
    description: "argparse main() CLI reads a words JSON file + wordlist and prints spans JSON followed by a capturable final line"
    requirement: "AUDIO-01"
    verification:
      - kind: unit
        ref: "tests/test_profanity.py::test_cli_prints_spans_json_and_capturable_last_line"
        status: pass
    human_judgment: false

duration: 25min
completed: 2026-07-11
status: complete
---

# Phase 7 Plan 1: Profanity Detection Module Summary

**New `scripts/profanity.py` (`load_wordlist`, `normalize_word`, `compile_patterns`, `find_profane_spans`, CLI) plus committed `data/profanity_wordlist.yaml` RU+EN stem wordlist, mirroring `monetization_risk.py`'s fail-open shape exactly.**

## Performance

- **Duration:** 25 min
- **Started:** 2026-07-10T21:48:00Z
- **Completed:** 2026-07-10T22:13:00Z
- **Tasks:** 3
- **Files modified:** 3 (all new)

## Accomplishments
- Deterministic RU+EN profanity detection over a clip-relative Whisper word list, with obfuscated-spelling normalization (leetspeak substitutions, censor-char stripping, repeated-char collapse) per D-02
- Word-boundary-safe stem matching (`\b<root>\w*`, `re.IGNORECASE`) that rejects a stem match inside an unrelated word (Pitfall 1) and never compiles a raw regex fragment from the data file (ASVS V5 ReDoS guard)
- Fail-open on every failure mode: missing/malformed wordlist file (D-04), and span-count cap exceeded (Pitfall 5) — both degrade to "no masking" + `[warn]` stderr line, never raise, never block a downstream render
- Committed `data/profanity_wordlist.yaml` (generic, non-channel-specific RU+EN stems), on the same footing as `data/monetization_rules.yaml`
- `find_profane_spans` consumes an already clip-relative, post-jumpcut-remap word list — proven via a dedicated test that calls `jumpcuts.remap_words` directly and shows a jump-cut-dropped word is simply absent, with zero remap logic duplicated inside `scripts/profanity.py` (Pattern 2)

## Task Commits

Each task was executed via the TDD RED/GREEN cycle, committed atomically:

1. **Task 1: load_wordlist + normalize_word + compile_patterns**
   - `6f9e058` (test) — failing tests for fail-open load, obfuscation normalization, ReDoS guard
   - `abf3a64` (feat) — implementation, all 10 tests green
2. **Task 2: find_profane_spans + CLI wrapper**
   - `4034e02` (test) — failing tests for detect/pad/merge/remap/span-cap/CLI
   - `3692ed3` (feat) — implementation + test-fixture fix (leetspeak substitution targets Cyrillic, not Latin), all 17 tests green
3. **Task 3: data/profanity_wordlist.yaml committed data file**
   - `f26ac07` (feat) — committed wordlist + shipped-file end-to-end tests, all 19 tests green

**Plan metadata:** (this commit)

## Files Created/Modified
- `scripts/profanity.py` - `load_wordlist`, `normalize_word`, `compile_patterns`, `find_profane_spans`, `main()` CLI
- `data/profanity_wordlist.yaml` - committed RU+EN swear stem wordlist + `normalize:` block
- `tests/test_profanity.py` - 19 tests mirroring `tests/test_monetization_risk.py` structure

## Decisions Made
- TDD RED-phase obfuscation test originally used Latin leetspeak (`f0ck`) but the wordlist's `substitutions` map (`"0": "о"`, `"3": "е"`, ...) targets Cyrillic obfuscation only, per the exact drafted normalize block in 07-RESEARCH.md — switched the test fixture to a `strip_chars` censor case (`fu_ck`) instead of altering the substitution map, since the map is copied verbatim from research and the wordlist file itself later confirms this design end-to-end (Task 3 tests).

## Deviations from Plan

None - plan executed exactly as written. The one test-fixture adjustment above was a test-authoring correction during the RED->GREEN cycle (the substitution map itself was implemented verbatim per the plan's `<action>` instructions), not a change to `scripts/profanity.py`'s behavior or the plan's `<behavior>` contract.

## Issues Encountered
- Local pytest temp dir (`AppData/Local/Temp/pytest-of-<user>`) is permission-locked on this machine (pre-existing, documented environment quirk per STATE.md Blockers/Concerns) - worked around with `--basetemp` override for all test runs in this session, same as prior phases. Not a code issue.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- `find_profane_spans` returns clip-relative `(start, end)` spans ready to be consumed by Plan 07-02's `render.py` extensions (`build_profanity_mask_filter`, extended `build_audio_filter_chain`)
- No `ProfanityConfig`/`config.yaml` section yet — that wiring (D-04 fail-open config toggle) is scoped to a later plan in this phase per 07-RESEARCH.md's Architectural Responsibility Map
- No blockers for Plan 07-02 (independent wave-1 output is complete and tested)

---
*Phase: 07-profanity-auto-bleep*
*Completed: 2026-07-11*

## Self-Check: PASSED

All created files exist on disk; all 5 task commit hashes (`6f9e058`, `abf3a64`, `4034e02`, `3692ed3`, `f26ac07`) found in git history.
