---
phase: 03-youtube-scheduled-auto-publish
plan: 01
subsystem: publishing
tags: [python, dataclasses, json, pytest, config, queue]

# Dependency graph
requires:
  - phase: 02-llm-title-tag-generation
    provides: finished per-clip metadata (title/description/tags) that enqueue() reads verbatim
provides:
  - Local publish-queue module (scripts/publish_queue.py) with status enum, load/save, idempotent sequential enqueue
  - PublishConfig dataclass in scripts/config.py wired through load_config/_validate with a dry-run-by-default (enabled=False) guarantee
affects: [03-02, 03-03, 03-04]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Queue manifest as filesystem-as-message-bus JSON under work/_publish/, same convention as work/<stem>/*.json elsewhere in the pipeline"
    - "Idempotent enqueue keyed on clip_id, sequential numbering derived solely from max(existing seq)+1 against the persisted manifest"
    - "Config dataclass-per-section pattern (PublishConfig mirrors MonetizationConfig) wired via _build/_validate"

key-files:
  created:
    - scripts/publish_queue.py
    - tests/test_publish_queue.py
  modified:
    - scripts/config.py
    - tests/test_config.py

key-decisions:
  - "enqueue() takes already-finished title/description/tags verbatim (per D-01/D-02) - never regenerates metadata"
  - "daily_slots_utc default set to [\"09:00\", \"15:00\", \"20:00\"] per D-07 (Claude's discretion), aligning with the ~3h periodic-check cadence"
  - "Slot validation implemented via split(\":\")+int parsing rather than importing re, since re wasn't already used in config.py"

patterns-established:
  - "Status enum as module-level string constants + VALID_STATUSES frozenset (queued/uploading/scheduled/published/killed/paused) - the full PUB-04/PUB-05 lifecycle other plans in this phase will drive transitions through"

requirements-completed: [PUB-01, PUB-03]

coverage:
  - id: D1
    description: "A finished short can be enqueued and gets a stable, contiguous, sequential local number visible before any publish (PUB-01)"
    requirement: "PUB-01"
    verification:
      - kind: unit
        ref: "tests/test_publish_queue.py::test_sequential_numbering"
        status: pass
    human_judgment: false
  - id: D2
    description: "Re-enqueuing an already-queued clip_id is idempotent - no duplicate entry, no second seq consumed"
    requirement: "PUB-01"
    verification:
      - kind: unit
        ref: "tests/test_publish_queue.py::test_enqueue_is_idempotent_on_clip_id"
        status: pass
    human_judgment: false
  - id: D3
    description: "Queue persists as human-readable UTF-8 JSON under work/_publish/queue.json, save->load round-trips faithfully"
    verification:
      - kind: unit
        ref: "tests/test_publish_queue.py::test_save_and_load_queue_round_trips"
        status: pass
      - kind: manual_procedural
        ref: "Manual run: enqueued 2 demo clips, inspected work/_publish/queue.json - readable JSON, contiguous seq 1/2, status queued"
        status: pass
    human_judgment: false
  - id: D4
    description: "PublishConfig.enabled defaults to False (dry-run), including when the publish: section is entirely absent from config.yaml (PUB-03 config side)"
    requirement: "PUB-03"
    verification:
      - kind: unit
        ref: "tests/test_config.py::test_default_config_publish_enabled_is_false"
        status: pass
      - kind: unit
        ref: "tests/test_config.py::test_load_config_publish_defaults_when_section_missing"
        status: pass
    human_judgment: false
  - id: D5
    description: "Invalid daily_slots_utc entries (bad HH:MM format or out-of-range hour) raise ConfigError; empty slots when enabled=true also raises"
    requirement: "PUB-03"
    verification:
      - kind: unit
        ref: "tests/test_config.py::test_load_config_publish_invalid_slot_format_raises"
        status: pass
      - kind: unit
        ref: "tests/test_config.py::test_load_config_publish_invalid_slot_hour_out_of_range_raises"
        status: pass
      - kind: unit
        ref: "tests/test_config.py::test_load_config_publish_empty_slots_when_enabled_raises"
        status: pass
    human_judgment: false
  - id: D6
    description: "Module stays import-safe with stdlib only (no top-level Google-API-client import)"
    verification:
      - kind: manual_procedural
        ref: "python -c AST-walk of scripts/publish_queue.py top-level imports: __future__, json, datetime, pathlib, typing only"
        status: pass
    human_judgment: false

duration: 2h
completed: 2026-07-08
status: complete
---

# Phase 3 Plan 1: Publish Queue Core + Dry-Run Config Summary

**Local publish-queue module (sequential idempotent enqueue keyed on clip_id, six-state status enum) plus a `PublishConfig` dataclass wired into `scripts/config.py` with `enabled=False` as the hard-coded dry-run default.**

## Performance

- **Duration:** ~2h
- **Started:** 2026-07-08T01:16:10Z
- **Completed:** 2026-07-08T03:15:43Z
- **Tasks:** 3
- **Files modified:** 4 (2 created, 2 modified)

## Accomplishments
- `scripts/publish_queue.py`: status enum (`QUEUED`/`UPLOADING`/`SCHEDULED`/`PUBLISHED`/`KILLED`/`PAUSED`) + `VALID_STATUSES`, queue/notification path constants, `load_queue`/`save_queue` (fail-open on missing file, UTF-8 JSON persistence), and `enqueue()` with contiguous sequential numbering and idempotent no-op on a duplicate `clip_id`
- `scripts/config.py`: new `PublishConfig` dataclass (`enabled=False`, `daily_slots_utc=["09:00","15:00","20:00"]`, `queue_path`, `notifications_path`, `client_secret_path`, `upload_token_path`) wired into `Config`/`load_config`/`_validate` exactly like every other section
- 12 new tests across `tests/test_publish_queue.py` (5) and `tests/test_config.py` (6 new, mixed into the existing 47) — full project suite at 282 passed

## Task Commits

Each task was committed atomically (TDD RED->GREEN per task):

1. **Task 1: Wave-0 test scaffold + publish-queue module skeleton** - `985ed8c` (test)
2. **Task 2: Queue load/save + sequential numbering + idempotent enqueue (PUB-01)** - `ffdd710` (feat)
3. **Task 3: PublishConfig dataclass with dry-run default (PUB-03 config side)** - `394f39f` (feat)

**Plan metadata:** (this commit, see final_commit step)

## Files Created/Modified
- `scripts/publish_queue.py` - Queue core: status enum, path constants, `load_queue`/`save_queue`/`enqueue`
- `tests/test_publish_queue.py` - Unit coverage: status scaffold, missing-file fail-open, sequential numbering, idempotent re-enqueue, save/load round-trip
- `scripts/config.py` - `PublishConfig` dataclass, `Config.publish` field, `load_config` wiring, `_validate` slot-format/empty-slots checks
- `tests/test_config.py` - Default/missing-section/custom-values/invalid-slot/empty-slots-when-enabled test cases for `publish`

## Decisions Made
- `enqueue()` reads title/description/tags verbatim from already-finished per-clip metadata (D-01/D-02) — no metadata regeneration logic added, keeping this plan's scope strictly local/filesystem as intended.
- `daily_slots_utc` default chosen as `["09:00", "15:00", "20:00"]` (3-slot grid), Claude's discretion per D-07, aligned with the phase's ~3-hour periodic-check cadence described in CONTEXT.md/RESEARCH.md for later plans to consume.
- Slot-time validation implemented with `str.split(":")` + `int()` parsing (no `re` import) since `config.py` doesn't already import `re` — keeps the diff minimal per the plan's action guidance.

## Deviations from Plan

None - plan executed exactly as written. All three tasks matched their `<action>`/`<behavior>` specs; no architectural changes, no missing-critical-functionality gaps found, no blocking issues beyond one out-of-scope environment quirk (below).

## Issues Encountered
- **Pre-existing environment quirk (out of scope, not fixed):** the default pytest temp directory (`C:\Users\<cyrillic-username>\AppData\Local\Temp\pytest-of-<cyrillic-username>`) has a permission-denied lock from a prior session, which breaks `tmp_path`-based tests when running plain `pytest tests/test_publish_queue.py -x -q` without a `--basetemp` override. This is unrelated to any code touched by this plan (confirmed `tests/test_config.py`'s pre-existing `tmp_path` tests hit the same issue) and was not introduced by this plan's changes. Workaround used for all verification in this plan: `pytest ... --basetemp=<writable-scratch-dir>`. Logged here rather than fixed, per the deviation-rules scope boundary (pre-existing issue unrelated to current task's changes). Future plans/sessions in this environment should be aware that a plain `pytest -x` run may fail on `tmp_path` collection for reasons unrelated to the code under test.

## Next Phase Readiness
- Queue manifest schema (six-status lifecycle, `video_id`/`publish_at` fields already present as `None` placeholders) is ready for Plan 02/03 to fill in upload/schedule/idempotency transitions without redesigning state.
- `PublishConfig` gives Plan 02/03 direct access to `daily_slots_utc` (for slot-picker math), `client_secret_path`/`upload_token_path` (for the separate upload-scoped OAuth token per D-08), and `queue_path`/`notifications_path` (for wiring the periodic-check/manual-override CLI).
- No blockers for Plan 02. The only carried-forward note is the pytest tmp-dir environment quirk above (informational, not blocking — workaround documented).

---
*Phase: 03-youtube-scheduled-auto-publish*
*Completed: 2026-07-08*

## Self-Check: PASSED

- FOUND: scripts/publish_queue.py
- FOUND: tests/test_publish_queue.py
- FOUND: .planning/phases/03-youtube-scheduled-auto-publish/03-01-SUMMARY.md
- FOUND: 985ed8c (Task 1 commit)
- FOUND: ffdd710 (Task 2 commit)
- FOUND: 394f39f (Task 3 commit)
