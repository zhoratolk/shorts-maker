---
phase: 06-tiktok-instagram-auto-publish
plan: 02
subsystem: config
tags: [publish, tiktok, instagram, config, dataclass, gitignore]

# Dependency graph
requires:
  - phase: 03-youtube-scheduled-auto-publish
    provides: PublishConfig dataclass and load_config's publish.* section precedent (queue_path/client_secret_path/upload_token_path shape, PUB-03 dry-run-default discipline)
provides:
  - "PublishConfig extended with 8 new TikTok/Instagram fields (tiktok_enabled, tiktok_queue_path, tiktok_client_key_path, tiktok_token_path, instagram_enabled, instagram_queue_path, instagram_client_secret_path, instagram_token_path), all safe defaults"
  - "4 new credential filenames gitignored (tiktok_client_key.json, tiktok_token.json, instagram_client_secret.json, instagram_token.json) before any later plan's code can write them"
  - "Test coverage for defaults, missing-section defaults, and custom-values round-trip for both new field groups"
affects: [06-03-tiktok-publish-module, 06-04-instagram-publish-module, 06-05, 06-06, 06-07]

# Tech tracking
tech-stack:
  added: []
  patterns: ["Per-platform independent enabled flag on a single flat PublishConfig (no sibling TikTokPublishConfig/InstagramPublishConfig dataclasses), matching MonetizationConfig/DiarizationConfig opt-in-bool-per-feature convention"]

key-files:
  created: []
  modified:
    - scripts/config.py
    - .gitignore
    - tests/test_config.py

key-decisions:
  - "Extended the existing flat PublishConfig in place rather than creating sibling TikTokPublishConfig/InstagramPublishConfig dataclasses, per D-01's literal per-platform enable-flag wording"
  - "No new _validate() rule added for the 8 new fields (bool/path fields need no extra validation), matching MonetizationConfig precedent"
  - "No publish: section added to config.example.yaml, matching this repo's existing convention of never documenting the publish section since every field is a safe opt-in-False default"

patterns-established: []

requirements-completed: [PUB-06, PUB-07]

coverage:
  - id: D1
    description: "PublishConfig exposes 8 new tiktok_*/instagram_* fields, all defaulting to safe/off values"
    requirement: "PUB-06"
    verification:
      - kind: unit
        ref: "tests/test_config.py#test_default_config_tiktok_and_instagram_enabled_is_false"
        status: pass
      - kind: unit
        ref: "tests/test_config.py#test_load_config_tiktok_instagram_defaults_when_section_missing"
        status: pass
    human_judgment: false
  - id: D2
    description: "load_config round-trips custom publish.tiktok_enabled/instagram_enabled/path overrides, leaving unspecified fields at defaults"
    requirement: "PUB-07"
    verification:
      - kind: unit
        ref: "tests/test_config.py#test_load_config_tiktok_instagram_custom_values_round_trip"
        status: pass
    human_judgment: false
  - id: D3
    description: "4 new credential filenames gitignored before any code that could write them exists"
    verification:
      - kind: other
        ref: "git check-ignore tiktok_client_key.json tiktok_token.json instagram_client_secret.json instagram_token.json"
        status: pass
    human_judgment: false

duration: 5min
completed: 2026-07-10
status: complete
---

# Phase 6 Plan 2: PublishConfig TikTok/Instagram Extension Summary

**Extended `PublishConfig` with 8 new per-platform TikTok/Instagram fields (all safe defaults) and gitignored their 4 credential filenames before Plans 06-03/06-04 can write them**

## Performance

- **Duration:** ~5 min
- **Completed:** 2026-07-10T11:13:51Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- `PublishConfig` dataclass gained 8 new fields (`tiktok_enabled`, `tiktok_queue_path`, `tiktok_client_key_path`, `tiktok_token_path`, `instagram_enabled`, `instagram_queue_path`, `instagram_client_secret_path`, `instagram_token_path`), each with the exact default documented in the plan
- `.gitignore` now lists `tiktok_client_key.json`, `tiktok_token.json`, `instagram_client_secret.json`, `instagram_token.json` alongside the existing `client_secret.json`/`token.json`/`upload_token.json` entries
- `tests/test_config.py` gained 3 new tests mirroring the existing publish-field test shapes: bare-dataclass defaults, `load_config` defaults when `publish:` section is absent, and a custom-values round-trip that also verifies unspecified fields keep their defaults

## Task Commits

Each task was committed atomically:

1. **Task 1: Extend PublishConfig and gitignore the new credential files** - `93db771` (feat)
2. **Task 2: Test coverage for the new PublishConfig fields** - `575f3d5` (test)

**Plan metadata:** pending (docs: complete plan commit)

## Files Created/Modified
- `scripts/config.py` - `PublishConfig` gained 8 new tiktok_*/instagram_* fields with safe defaults
- `.gitignore` - added 4 new credential filenames
- `tests/test_config.py` - added 3 tests covering defaults, missing-section defaults, and custom-values round-trip for the new field groups

## Decisions Made
- Extended the existing flat `PublishConfig` in place rather than creating sibling `TikTokPublishConfig`/`InstagramPublishConfig` dataclasses, per D-01's literal "per-platform enable flag" wording and the `MonetizationConfig`/`DiarizationConfig` opt-in-bool-per-feature convention
- No new `_validate()` rule added for the 8 new fields — bool/path fields need no extra validation, matching `MonetizationConfig` precedent
- No `publish:` section added to `config.example.yaml` — matches this repo's existing convention of never documenting the publish section since every field is a safe opt-in-False default requiring no user action to be safe

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required. (TikTok/Instagram OAuth credential setup will be required by later plans 06-03/06-04 once the publish modules that consume `tiktok_client_key_path`/`instagram_client_secret_path` exist.)

## Next Phase Readiness
- `config.publish.tiktok_enabled`, `config.publish.instagram_enabled`, and all 6 accompanying path fields are locked, tested, and ready for Plans 06-03 (TikTok publish module) and 06-04 (Instagram publish module) to read
- Credential filenames are gitignored ahead of any code that could create them, closing the T-06-01 threat register entry for this plan's scope
- Full `tests/test_config.py` suite (68 tests) passes green

---
*Phase: 06-tiktok-instagram-auto-publish*
*Completed: 2026-07-10*

## Self-Check: PASSED

- FOUND: scripts/config.py
- FOUND: .gitignore
- FOUND: tests/test_config.py
- FOUND: .planning/phases/06-tiktok-instagram-auto-publish/06-02-SUMMARY.md
- FOUND commit: 93db771
- FOUND commit: 575f3d5
