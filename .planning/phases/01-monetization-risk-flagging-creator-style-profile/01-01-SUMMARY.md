---
phase: 01-monetization-risk-flagging-creator-style-profile
plan: 01
subsystem: risk-flagging
tags: [python, pyyaml, monetization-risk, metadata, dataclasses, tdd]

# Dependency graph
requires: []
provides:
  - "scripts/monetization_risk.py: load_rules/score_transcript/score_all_platforms/main, rule-table-driven, fail-open"
  - "data/monetization_rules.yaml: per-platform (youtube/tiktok/instagram) rule table, date-stamped, committed"
  - "MonetizationConfig dataclass on Config aggregate (config.py)"
  - "Advisory 'Monetization risk (advisory)' sub-block in metadata.py's render_metadata_text"
affects: [01-02-audio-fingerprint, 01-03-creator-style-profile, phase-3-llm-titles-tags, phase-6-scheduled-publish]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Rule-table-driven scoring: platform policy tables live in data/*.yaml, never hardcoded in Python (scripts/monetization_risk.py mirrors scripts/audio_energy.py's pure-function + injectable-CLI shape)"
    - "Structured advisory-flag dict, never a pass/fail gate (Pattern 1 from ARCHITECTURE.md) - risk dict is an additive optional field consumed by metadata.py, never blocks export"
    - "Fail-open ruleset loading: malformed/missing YAML warns to stderr and returns an empty valid risk dict, matching CONVENTIONS.md's fail-open tier used by diarization/audio-energy/YouTube Analytics"

key-files:
  created:
    - scripts/monetization_risk.py
    - data/monetization_rules.yaml
    - tests/test_monetization_risk.py
  modified:
    - scripts/metadata.py
    - scripts/config.py
    - config.example.yaml
    - tests/test_metadata.py
    - tests/test_config.py

key-decisions:
  - "Ruleset committed (not gitignored) - data/monetization_rules.yaml is generic platform-policy data with zero channel-specific content, unlike the analytics cache"
  - "risk_level is the max severity of any matched category per platform; confidence is the matched rule's own declared confidence, never a computed aggregate score presented as certainty"
  - "last_checked is copied verbatim from the ruleset's own `updated:` date stamp, not today's date, so staleness is visible per flag (Pitfall 2 from PITFALLS.md)"

patterns-established:
  - "Advisory-only framing in rendered text: 'Monetization risk (advisory)' label, never 'will be demonetized' - enforced by an explicit test assertion"
  - "Optional dict field wired into render_metadata_text: when 'risk' key is absent, output is byte-identical to prior behavior"

requirements-completed: [MONET-02, MONET-03, MONET-04]

coverage:
  - id: D1
    description: "score_transcript()/score_all_platforms() produce a per-platform advisory risk dict (platform, risk_level, flags, flagged_spans, confidence, last_checked) from a rule-table YAML, never raising and never gating"
    requirement: "MONET-02"
    verification:
      - kind: unit
        ref: "tests/test_monetization_risk.py::test_score_transcript_flags_gambling_keyword_on_youtube"
        status: pass
      - kind: unit
        ref: "tests/test_monetization_risk.py::test_score_transcript_clean_text_returns_none_or_low_never_raises"
        status: pass
      - kind: unit
        ref: "tests/test_monetization_risk.py::test_score_all_platforms_returns_one_entry_per_ruleset_platform_key"
        status: pass
    human_judgment: false
  - id: D2
    description: "Every flag carries confidence + last_checked (copied from ruleset's own updated date, not today's date) so staleness is visible; export path never blocked by risk level"
    requirement: "MONET-03"
    verification:
      - kind: unit
        ref: "tests/test_monetization_risk.py::test_score_transcript_last_checked_matches_ruleset_updated_field_not_today"
        status: pass
      - kind: unit
        ref: "tests/test_metadata.py::test_render_metadata_text_renders_advisory_risk_subblock_when_present"
        status: pass
      - kind: unit
        ref: "tests/test_metadata.py::test_render_metadata_text_unchanged_when_risk_absent"
        status: pass
    human_judgment: false
  - id: D3
    description: "youtube/tiktok/instagram rulesets are separate and demonstrably differ - the same transcript scores differently per platform"
    requirement: "MONET-04"
    verification:
      - kind: unit
        ref: "tests/test_monetization_risk.py::test_score_transcript_same_text_scores_lower_on_platform_without_category"
        status: pass
    human_judgment: false
  - id: D4
    description: "MonetizationConfig dataclass (enabled, rules_path) wired into Config aggregate/load_config with documented defaults; config.example.yaml documents the monetization: block as advisory-only"
    verification:
      - kind: unit
        ref: "tests/test_config.py::test_load_config_monetization_defaults"
        status: pass
      - kind: unit
        ref: "tests/test_config.py::test_load_config_monetization_custom_values_round_trip"
        status: pass
    human_judgment: false

duration: 35min
completed: 2026-07-07
status: complete
---

# Phase 1 Plan 1: Monetization-Risk Flagging (Deterministic Keyword/Topic Tier) Summary

**Rule-table-driven per-platform monetization risk scorer (scripts/monetization_risk.py + data/monetization_rules.yaml) wired as an advisory-only sub-block into metadata.py's per-platform .txt output, never gating export.**

## Performance

- **Duration:** 35 min
- **Started:** 2026-07-07T17:23:00Z
- **Completed:** 2026-07-07T17:58:13Z
- **Tasks:** 3
- **Files modified:** 8 (3 created, 5 modified)

## Accomplishments

- `scripts/monetization_risk.py`: `load_rules()`, `score_transcript()`, `score_all_platforms()`, and a CLI `main()` — pure-function + injectable-CLI shape mirroring `scripts/audio_energy.py`. Never raises on normal input; a missing/malformed `data/monetization_rules.yaml` fails open with a `[warn] ...` and an empty valid risk dict.
- `data/monetization_rules.yaml`: a real, committed (non-gitignored) ruleset with `youtube`/`tiktok`/`instagram` category tables (gambling, regulated_goods, hate_speech, dangerous_acts) and an `updated:` date stamp. Coverage deliberately differs per platform — e.g. only youtube/tiktok list a `gambling` category, instagram does not — so the same transcript demonstrably scores differently per platform (MONET-04).
- `scripts/metadata.py`'s `render_metadata_text` renders a `Monetization risk (advisory)` sub-block (level, flags, last-checked date) whenever a platform's fields dict carries an optional `"risk"` key; output is byte-identical to prior behavior when the key is absent.
- `scripts/config.py` gained a `MonetizationConfig` dataclass (`enabled: bool = True`, `rules_path: str = "data/monetization_rules.yaml"`) wired into `Config`/`load_config` the same way `MetadataConfig` is.
- `config.example.yaml` documents the new `monetization:` block with inline comments explicitly stating flags are advisory-only and never block export.

## Task Commits

Each task was committed atomically (TDD RED/GREEN):

1. **Task 1: Failing end-to-end test — score a transcript to a per-platform advisory risk dict** - `3cbe7fa` (test)
2. **Task 2: Implement the rule-table scorer that makes the test pass (MONET-02, MONET-03, MONET-04)** - `4e56437` (feat)
3. **Task 3: Wire risk block into per-platform metadata output + add MonetizationConfig (MONET-03, MONET-04)** - `68f391f` (feat)

_Note: Task 3 combined its own RED (new failing assertions added to existing test_metadata.py/test_config.py) and GREEN (implementation) into a single commit since the plan scoped it as one task rather than a plan-level TDD gate; RED was verified interactively (pytest failure observed) before implementing, per the task's `tdd="true"` flag._

## Files Created/Modified

- `scripts/monetization_risk.py` - rule-table scorer: `load_rules`, `score_transcript`, `score_all_platforms`, CLI `main()`
- `data/monetization_rules.yaml` - per-platform rule table, date-stamped, committed (no channel data)
- `tests/test_monetization_risk.py` - 5 tests covering flagging, per-platform divergence, clean-transcript no-raise, staleness-visible date, all-platforms scoring
- `scripts/metadata.py` - added `render_risk_subblock()` + wired optional `risk` key into `render_metadata_text`
- `scripts/config.py` - added `MonetizationConfig` dataclass + `Config.monetization` field + `load_config` wiring
- `config.example.yaml` - documented `monetization:` block
- `tests/test_metadata.py` - 3 new tests for the advisory risk sub-block (present/absent/none-level)
- `tests/test_config.py` - 2 new tests for `MonetizationConfig` defaults + round-trip

## Decisions Made

- `data/monetization_rules.yaml` is committed, not gitignored — it is generic platform-policy data with zero channel-specific content, unlike `youtube_analytics.py`'s cache or a future style-profile artifact.
- `risk_level` is computed as the max severity across all matched categories per platform (not a numeric aggregate score) to keep the value in the same enum space the metadata renderer and future phases (MONET-01 audio fingerprint merge, Phase 6 publish) can reason about.
- `last_checked` is copied verbatim from the ruleset's own `updated:` field rather than `datetime.now()`, so a stale ruleset is visible in every single flag it produces — directly addresses PITFALLS.md Pitfall 2 ("crying wolf" / stale-ruleset risk).
- No validation added to `MonetizationConfig` in `config.py`'s `_validate()` — both fields (`bool`, `str` path) have no constrained range/enum, consistent with how simpler existing config sections (e.g. `ContentConfig`) skip validation when there's nothing to constrain.

## Deviations from Plan

None - plan executed exactly as written. All three tasks matched their `<action>`/`<verify>`/`<done>` blocks; no Rule 1-4 auto-fixes were needed.

## Issues Encountered

- Local pytest run initially failed with `PermissionError` on the default Windows temp directory (`C:\Users\{cyrillic-user}\AppData\Local\Temp\pytest-of-...`) due to a non-ASCII username — unrelated to the plan's code. Worked around by pointing `TMPDIR`/`TEMP`/`TMP` at the session scratchpad directory for verification runs; no code or test changes were needed since this is a local environment quirk, not a bug in the implementation.

## User Setup Required

None - no external service configuration required. `data/monetization_rules.yaml` is a local, editable data file; no credentials or env vars involved.

## Next Phase Readiness

- The `{platform, risk_level, flags, flagged_spans, confidence, last_checked}` risk dict shape is now the established contract that Plan 02 (MONET-01, audio fingerprint via `fpcalc`) must merge into for the same per-platform risk dict, and that Phase 6's publish step will read (advisory display, never a gate) once built.
- `render_metadata_text`'s optional `"risk"` key pattern is ready for Plan 02 to populate the same way once audio-fingerprint flags exist.
- No blockers. `MonetizationConfig.rules_path` is ready to be read by the orchestrator (`SKILL.md`) once Stage 5c is wired into the live pipeline — that orchestration wiring is out of scope for this plan (Plan 01 delivers the scorer + config + metadata rendering only, per the plan's stated objective).

---
*Phase: 01-monetization-risk-flagging-creator-style-profile*
*Completed: 2026-07-07*

## Self-Check: PASSED

All created files and commit hashes verified present on disk / in git log.
