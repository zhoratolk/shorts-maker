---
phase: 03-youtube-scheduled-auto-publish
plan: 02
subsystem: publishing
tags: [python, datetime, youtube-data-api, resumable-upload, pytest]

# Dependency graph
requires:
  - phase: 03-youtube-scheduled-auto-publish
    plan: 01
    provides: "queue.py status enum/load_queue/save_queue/enqueue and config.py's PublishConfig this plan builds the upload path on top of"
provides:
  - "next_free_slot()/collect_scheduled_slots() fixed daily-grid slot math with a strict UTC future-guard"
  - "build_insert_body() pure videos.insert request-body builder with field-limit validation and a seq-marker for later reconciliation"
  - "upload_and_schedule() orchestration: dry-run gate -> write-ahead uploading -> insert -> record scheduled"
  - "UPLOAD_SCOPE module constant (youtube.upload only)"
affects: [03-03, 03-04]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Deferred import of googleapiclient.http.MediaFileUpload inside upload_and_schedule - module stays import-safe with stdlib only in dry-run mode"
    - "Write-ahead persistence: save_queue(status=UPLOADING) happens before any network call, not after, so a mid-upload crash leaves a durable trace"
    - "Injected service_factory callable - tests pass a fake, the CLI/wiring layer (a later plan) will pass a real load_credentials-backed factory"

key-files:
  created: []
  modified:
    - scripts/publish_queue.py
    - tests/test_publish_queue.py
    - .gitignore

key-decisions:
  - "Slot marker embedded as a trailing '[queue-id: {seq}]' line in the description, not a separate API field - YouTube's videos.insert has no dedicated custom-metadata field, so the description is the only place Plan 03's reconciliation can read a stable local identifier back from"
  - "Field-limit validation (title<=100, description<=5000, tags<=500 combined) raises ValueError from build_insert_body itself, not from upload_and_schedule - keeps the pure body-builder independently testable and lets a future caller decide how to handle a per-item validation failure (fail this item, continue the run)"
  - "upload_and_schedule takes an explicit queue_path parameter (defaulting to DEFAULT_QUEUE_PATH) so tests can assert the write-ahead save actually persisted to a real file on disk, not just mutated the in-memory dict"

requirements-completed: [PUB-02, PUB-03, PUB-05]

coverage:
  - id: D1
    description: "next_free_slot always returns a strictly-future UTC RFC3339 Z-suffixed timestamp from the fixed daily grid, never a past one (Pitfall 1)"
    requirement: "PUB-02"
    verification:
      - kind: unit
        ref: "tests/test_publish_queue.py::test_next_free_slot_returns_next_future_grid_time"
        status: pass
      - kind: unit
        ref: "tests/test_publish_queue.py::test_next_free_slot_never_returns_a_past_timestamp"
        status: pass
    human_judgment: false
  - id: D2
    description: "An already-used slot is skipped and the grid rolls to the next day when today is exhausted"
    verification:
      - kind: unit
        ref: "tests/test_publish_queue.py::test_next_free_slot_skips_already_used_slot"
        status: pass
      - kind: unit
        ref: "tests/test_publish_queue.py::test_next_free_slot_rolls_to_tomorrow_when_today_exhausted"
        status: pass
    human_judgment: false
  - id: D3
    description: "collect_scheduled_slots feeds already_scheduled from SCHEDULED entries so two clips never collide on the same slot"
    verification:
      - kind: unit
        ref: "tests/test_publish_queue.py::test_collect_scheduled_slots_returns_publish_at_of_scheduled_entries"
        status: pass
    human_judgment: false
  - id: D4
    description: "build_insert_body constructs the exact videos.insert body (private + future publishAt + seq marker) and rejects oversized title/description/tags with a per-item error"
    requirement: "PUB-02"
    verification:
      - kind: unit
        ref: "tests/test_publish_queue.py::test_build_insert_body_shapes_snippet_and_status"
        status: pass
      - kind: unit
        ref: "tests/test_publish_queue.py::test_build_insert_body_rejects_oversized_title"
        status: pass
      - kind: unit
        ref: "tests/test_publish_queue.py::test_build_insert_body_rejects_oversized_description"
        status: pass
      - kind: unit
        ref: "tests/test_publish_queue.py::test_build_insert_body_rejects_oversized_combined_tags"
        status: pass
    human_judgment: false
  - id: D5
    description: "With publish.enabled=false, upload_and_schedule makes zero calls to service_factory and leaves status at QUEUED (PUB-03 dry-run gate is provably network-free)"
    requirement: "PUB-03"
    verification:
      - kind: unit
        ref: "tests/test_publish_queue.py::test_dry_run_makes_zero_calls_and_does_not_advance_status"
        status: pass
    human_judgment: false
  - id: D6
    description: "With enabled=true, status is persisted as UPLOADING before videos.insert fires (write-ahead), then flips to SCHEDULED with the returned video_id and future publish_at once the fake insert completes (PUB-05 write-ahead half)"
    requirement: "PUB-05"
    verification:
      - kind: unit
        ref: "tests/test_publish_queue.py::test_upload_and_schedule_enabled_drives_status_transitions_and_body"
        status: pass
    human_judgment: false
  - id: D7
    description: "UPLOAD_SCOPE is exactly the narrow youtube.upload scope string, never a broader scope"
    requirement: "PUB-02"
    verification:
      - kind: unit
        ref: "tests/test_publish_queue.py::test_upload_scope_is_exactly_the_upload_scope_constant"
        status: pass
      - kind: manual_procedural
        ref: "grep -n UPLOAD_SCOPE scripts/publish_queue.py - single definition, single reference at the documented load_credentials call site, no other scope string present"
        status: pass
    human_judgment: false
  - id: D8
    description: "upload_token.json is gitignored alongside client_secret.json/token.json"
    requirement: "PUB-02"
    verification:
      - kind: unit
        ref: "git check-ignore upload_token.json"
        status: pass
    human_judgment: false

duration: 1h
completed: 2026-07-08
status: complete
---

# Phase 3 Plan 2: Upload + Schedule Path (dry-run gate, slot math, write-ahead) Summary

**Fixed-grid `next_free_slot` slot math with a strict UTC future-guard, a pure `build_insert_body` videos.insert body builder with field-limit validation and a seq-marker, and `upload_and_schedule` orchestration whose dry-run gate is the very first statement and whose write-ahead `UPLOADING` status is persisted before any network call.**

## Performance

- **Duration:** ~1h
- **Started:** 2026-07-08T04:05:00Z (approx, session-derived)
- **Completed:** 2026-07-08T05:05:00Z (approx, session-derived)
- **Tasks:** 3
- **Files modified:** 3 (0 created, 3 modified)

## Accomplishments
- `scripts/publish_queue.py`: `next_free_slot()` (UTC-only fixed-grid math with a strict future-guard, rolls to the next day when today's slots are exhausted) + `collect_scheduled_slots()` (feeds already-used slots from SCHEDULED entries)
- `scripts/publish_queue.py`: `build_insert_body()` pure function constructing the exact `videos.insert` request body (`snippet{title,description,tags}` + `status{privacyStatus:"private",publishAt,selfDeclaredMadeForKids:False}`), with a `[queue-id: {seq}]` marker appended to the description and field-limit validation (title<=100, description<=5000, tags<=500 combined chars) that raises `ValueError` for a single bad item
- `scripts/publish_queue.py`: `upload_and_schedule()` orchestration - dry-run gate first (zero calls to `service_factory` when `config.enabled` is False), then write-ahead `save_queue(status=UPLOADING)` before the insert, a deferred `googleapiclient.http.MediaFileUpload` import, a `next_chunk()` loop, and a final `save_queue(status=SCHEDULED, video_id=...)` on success
- `UPLOAD_SCOPE` module constant (`https://www.googleapis.com/auth/youtube.upload`) - the only scope this module ever requests
- `.gitignore`: added `upload_token.json` immediately after the existing `token.json` line
- 12 new tests across `tests/test_publish_queue.py` (17 total in that file now) using hand-written fake-service test doubles (`FakeVideosInsertService`/`FakeNextChunkRequest`) matching the house style already established in `tests/test_youtube_analytics.py` - full project suite at 294 passed

## Task Commits

Each task was committed atomically (TDD RED->GREEN per task):

1. **Task 1: Fixed daily-grid slot math with UTC future-guard** - `5b1d80d` (test, RED) / `cf976ee` (feat, GREEN)
2. **Task 2: videos.insert body builder + dry-run gate + write-ahead upload** - `6b67e05` (test, RED) / `20c2f12` (feat, GREEN)
3. **Task 3: Gitignore upload_token.json** - `db92514` (chore)

**Plan metadata:** (this commit, see final_commit step)

## Files Created/Modified
- `scripts/publish_queue.py` - Added `UPLOAD_SCOPE`/`MAX_TITLE_LENGTH`/`MAX_DESCRIPTION_LENGTH`/`MAX_TAGS_TOTAL_LENGTH` constants, `collect_scheduled_slots()`, `next_free_slot()`, `build_insert_body()`, `upload_and_schedule()`
- `tests/test_publish_queue.py` - 12 new tests: 4 slot-math tests, 1 collect_scheduled_slots test, 1 UPLOAD_SCOPE constant test, 4 build_insert_body tests (shape + 3 field-limit rejections), 2 upload_and_schedule tests (dry-run zero-calls, enabled full transition with write-ahead assertion)
- `.gitignore` - Added `upload_token.json` line after `token.json`

## Decisions Made
- The seq marker for Plan 03's reconciliation is embedded as a trailing `[queue-id: {seq}]` line in the video description (no dedicated custom-metadata field exists on `videos.insert`) - this is the only place a stable local identifier can round-trip through the YouTube API back to a local queue entry.
- Field-limit validation lives inside `build_insert_body` itself (raises `ValueError`), not inside `upload_and_schedule` - keeps the pure body-builder independently unit-testable and leaves the "fail this item, keep the run going" handling to whichever future caller drives multiple items through the queue.
- `upload_and_schedule` takes an explicit `queue_path` parameter (defaulting to `DEFAULT_QUEUE_PATH`) specifically so the write-ahead test could assert the `UPLOADING` status was actually persisted to a real file on disk at the moment `insert()` fired, not merely mutated in the in-memory dict - this is the load-bearing assertion for PUB-05's write-ahead guarantee.
- `MediaFileUpload` genuinely opens the file at construction time (verified empirically when the first version of the enabled-path test used a bare non-existent filename and failed with `FileNotFoundError`) - the test was adjusted to write a real (empty) temp file via `tmp_path`, which is a more honest fake-service test anyway since it exercises the actual code path `MediaFileUpload` takes.

## Deviations from Plan

None - plan executed exactly as written. All three tasks matched their `<action>`/`<behavior>` specs. One test-construction detail required adjustment (see Decisions Made: `MediaFileUpload` needs a real file to open), classified as normal test-writing work, not a deviation from the plan's design.

## Auth Gates

None encountered - this plan only builds the pure/orchestration functions with injected fakes; no real OAuth flow or credential file was touched. The real `service_factory` (calling `load_credentials(client_secret_path, upload_token_path, [UPLOAD_SCOPE])`) is documented in `upload_and_schedule`'s docstring as the intended real-world usage but its concrete wiring (and the resulting first-run browser consent for `upload_token.json`) is out of this plan's file scope - reserved for the plan that adds the CLI/periodic-check entry point.

## Known Stubs

None. Every function delivered in this plan is fully wired to real logic (no hardcoded empty returns, no placeholder text) - the only thing deliberately deferred is the CLI-level `service_factory` construction, which is documented as scope for a later plan, not a stub masquerading as done.

## Threat Flags

None - all new surface (write-ahead persistence, insert body construction, UPLOAD_SCOPE) was already anticipated and dispositioned in this plan's own `<threat_model>` (T-03-04 through T-03-07, T-03-SC); no new trust boundary was introduced beyond what the plan already covers.

## Issues Encountered
- Same pre-existing pytest tmp-dir permission quirk noted in 03-01-SUMMARY.md (`C:\Users\<cyrillic-username>\AppData\Local\Temp\pytest-of-...` lock) - worked around identically via `--basetemp=<writable-scratch-dir>` for every verification run in this plan. Not introduced by this plan's changes; carried-forward informational note only.

## Next Phase Readiness
- `upload_and_schedule`'s write-ahead `UPLOADING` status transition (persisted before `.execute()`/`.next_chunk()` runs) is exactly the durable trace Plan 03's reconciliation logic needs to key on - no redesign required.
- `UPLOAD_SCOPE` and the documented `load_credentials(client_secret_path, upload_token_path, [UPLOAD_SCOPE])` call shape are ready for whichever plan adds the concrete CLI wiring / periodic-check entry point.
- No blockers for Plan 03. The only carried-forward note is the pytest tmp-dir environment quirk (informational, not blocking - workaround documented, same as Plan 01).

---
*Phase: 03-youtube-scheduled-auto-publish*
*Completed: 2026-07-08*

## Self-Check: PASSED

- FOUND: scripts/publish_queue.py
- FOUND: tests/test_publish_queue.py
- FOUND: .gitignore
- FOUND: .planning/phases/03-youtube-scheduled-auto-publish/03-02-SUMMARY.md
- FOUND: 5b1d80d (Task 1 test/RED commit)
- FOUND: cf976ee (Task 1 feat/GREEN commit)
- FOUND: 6b67e05 (Task 2 test/RED commit)
- FOUND: 20c2f12 (Task 2 feat/GREEN commit)
- FOUND: db92514 (Task 3 chore commit)
