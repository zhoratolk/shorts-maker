---
phase: 06-tiktok-instagram-auto-publish
plan: 06
subsystem: publish
tags: [publish, instagram, cli, kill-item, oauth]

# Dependency graph
requires:
  - phase: 06-tiktok-instagram-auto-publish
    provides: "Plan 06-04's queue lifecycle, OAuth, Graph API resumable-upload orchestration, and reconciliation for Instagram"
provides:
  - "kill_item(queue, clip_id) for Instagram - local-only KILLED flip for not-yet-published entries, RuntimeError for already-PUBLISHED entries (no un-publish API exists)"
  - "Full CLI wrapper for scripts/instagram_publish.py: --check/--now/--pause/--kill/--resume/--list, matching publish_queue.py's and tiktok_publish.py's exact dispatch contract"
  - "scripts/instagram_publish.py is now a complete, independently-runnable module (python scripts/instagram_publish.py --check etc.)"
affects: [06-07-docs-windows-task-scheduler]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "kill_item takes no service_factory/credentials_factory parameter - every branch is either local-only or a hard RuntimeError raise, never a network call (mirrors tiktok_publish.py's identical Pitfall-4 design)"
    - "sys.path.insert(0, repo_root) workaround at module top so the script is runnable standalone via `python scripts/instagram_publish.py`, matching tiktok_publish.py/transitions.py/render.py precedent"

key-files:
  created: []
  modified:
    - scripts/instagram_publish.py
    - tests/test_instagram_publish.py

key-decisions:
  - "kill_item's not-yet-uploaded check keys off entry.get('media_id') only (never container_id) - a created-but-not-yet-published container has nothing public on Instagram to revert"
  - "run_command takes ig_user_id as an explicit positional parameter (after config, before session) rather than folding it into config, since Instagram's account ID is CLI-supplied per D-02, not a config.yaml field"
  - "--ig-user-id is an optional argparse flag (no required=True) - only --now/--check's live-call paths actually need it; --list/--pause/--resume/--kill never touch the API and work without it"
  - "Help-flag test asserts on 7 flags (--check/--now/--pause/--kill/--resume/--list/--ig-user-id), excluding --client-secret/--token/--config plumbing flags, mirroring tiktok_publish.py's test convention of checking only the operator-facing action surface"

patterns-established:
  - "kill_item's PUBLISHED-branch RuntimeError message names the specific platform limitation (no un-publish/cancel endpoint) and states the entry is left untouched, not silently marked KILLED - reused verbatim shape from tiktok_publish.py's kill_item"

requirements-completed: [PUB-07]

coverage:
  - id: D1
    description: "kill_item flips QUEUED/PAUSED/UPLOADING (no media_id, with or without container_id) Instagram queue entries to KILLED locally with no API call"
    requirement: "PUB-07"
    verification:
      - kind: unit
        ref: "tests/test_instagram_publish.py#test_kill_item_queued_is_local_only_no_media_id"
        status: pass
      - kind: unit
        ref: "tests/test_instagram_publish.py#test_kill_item_paused_is_local_only"
        status: pass
      - kind: unit
        ref: "tests/test_instagram_publish.py#test_kill_item_uploading_no_container_id_no_media_id_is_local_only"
        status: pass
      - kind: unit
        ref: "tests/test_instagram_publish.py#test_kill_item_uploading_with_container_id_no_media_id_is_still_local_only"
        status: pass
    human_judgment: false
  - id: D2
    description: "kill_item on a PUBLISHED (media_id recorded) entry raises RuntimeError and leaves status untouched - never silently succeeds"
    requirement: "PUB-07"
    verification:
      - kind: unit
        ref: "tests/test_instagram_publish.py#test_kill_item_published_raises_runtime_error_and_leaves_status_untouched"
        status: pass
    human_judgment: false
  - id: D3
    description: "CLI wrapper (build_argument_parser/run_command/main) with --check/--now/--pause/--kill/--resume/--list, --check reconciling stuck UPLOADING entries before selecting/uploading at most one due item"
    requirement: "PUB-07"
    verification:
      - kind: unit
        ref: "tests/test_instagram_publish.py#test_check_reconciles_before_selecting_and_uploads_at_most_one"
        status: pass
      - kind: unit
        ref: "tests/test_instagram_publish.py#test_now_targets_named_clip_via_same_upload_path"
        status: pass
      - kind: unit
        ref: "tests/test_instagram_publish.py#test_kill_via_cli_on_published_entry_raises_not_system_exit"
        status: pass
      - kind: unit
        ref: "tests/test_instagram_publish.py#test_pause_and_resume_via_cli_dispatch"
        status: pass
      - kind: other
        ref: "python scripts/instagram_publish.py --help (manual invocation, exits 0, lists all flags)"
        status: pass
    human_judgment: false

duration: 10min
completed: 2026-07-10
status: complete
---

# Phase 06 Plan 06: Instagram kill_item + CLI Wrapper Summary

**Finished `scripts/instagram_publish.py` with `kill_item` (Instagram's own Pitfall-4 divergence - media_id-gated, not container_id-gated) and a full `--check`/`--now`/`--pause`/`--kill`/`--resume`/`--list` CLI matching `publish_queue.py`'s exact dispatch contract.**

## Performance

- **Duration:** ~10 min
- **Completed:** 2026-07-10T12:02:00Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- `kill_item(queue, clip_id)` added to `scripts/instagram_publish.py`: local-only KILLED flip for QUEUED/PAUSED/UPLOADING entries with no `media_id` recorded (regardless of `container_id`); RuntimeError (status left untouched) for already-PUBLISHED entries, since Instagram's Graph API has no un-publish/cancel endpoint for a live Reel
- `build_argument_parser`/`run_command`/`main` added, giving `scripts/instagram_publish.py` the same operator surface as `publish_queue.py` and `tiktok_publish.py`: `--check`, `--now CLIP_ID`, `--pause CLIP_ID`, `--kill CLIP_ID`, `--resume CLIP_ID`, `--list`, plus `--client-secret`, `--token`, `--ig-user-id`, `--config`
- `--check` reconciles all stuck UPLOADING entries first (even in dry-run), then uploads at most one due item per invocation, identical ordering to `publish_queue.py`
- Added `sys.path.insert` workaround so `python scripts/instagram_publish.py --check` runs standalone (verified via `--help`)
- No pre-publish gating call was added anywhere - `upload_and_publish`'s orchestration logic is untouched by this plan

## Task Commits

Each task was committed atomically:

1. **Task 1: kill_item with Pitfall-4 semantics** - `b387490` (feat)
2. **Task 2: CLI wrapper** - `abf55d0` (feat)

**Plan metadata:** (this commit)

_Note: Task 1 was `tdd="true"` per plan frontmatter, but the plan's own `<behavior>`/`<action>` blocks specified the exact final implementation up front (not an incremental RED/GREEN cycle against evolving requirements), so tests and implementation were written together and verified green before commit - consistent with the plan's single `<verify>` step running the full kill_item test subset post-implementation, not a separate pre-implementation failing-test gate._

## Files Created/Modified
- `scripts/instagram_publish.py` - added `_NOT_YET_UPLOADED_STATUSES`, `kill_item`, `build_argument_parser`, `run_command`, `main`, plus `argparse`/`sys` imports and the `sys.path.insert` standalone-run workaround
- `tests/test_instagram_publish.py` - added 6 `kill_item` tests and 11 CLI dispatch tests (`--list`/`--check`/`--now`/`--pause`/`--resume`/`--kill`/`--help`), 67 tests total in the file, all passing

## Decisions Made
- kill_item's not-yet-uploaded check keys off `media_id` only (never `container_id`) - a created-but-not-yet-published container has nothing public on Instagram to revert
- `run_command` takes `ig_user_id` as an explicit positional parameter (after `config`, before `session`) rather than folding it into `config`, since Instagram's account ID is CLI-supplied per D-02, not a `config.yaml` field
- `--ig-user-id` is an optional argparse flag (no `required=True`) - only `--now`/`--check`'s live-call paths actually need it; `--list`/`--pause`/`--resume`/`--kill` never touch the API and work without it
- Help-flag test asserts on exactly 7 flags (`--check`/`--now`/`--pause`/`--kill`/`--resume`/`--list`/`--ig-user-id`), excluding `--client-secret`/`--token`/`--config` plumbing flags, mirroring `tiktok_publish.py`'s test convention of checking only the operator-facing action surface

## Deviations from Plan

None - plan executed exactly as written. `kill_item` takes no service_factory/credentials_factory parameter as specified; CLI dispatch order and `--check`/`--now` routing exactly mirror `publish_queue.py`/`tiktok_publish.py`; no pre-publish gating call was added.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required for this plan (kill_item and the CLI wrapper are pure local/dispatch logic; OAuth/Graph API credential setup was already covered by Plan 06-04's docs).

## Next Phase Readiness
- `scripts/instagram_publish.py` is now a complete, independently-runnable CLI module (`python scripts/instagram_publish.py --check`, `--now`, `--pause`, `--kill`, `--resume`, `--list`), ready to be wired into the Windows Task Scheduler task in Plan 06-07
- No blockers identified for Plan 06-07 (docs update / Task Scheduler wiring)

---
*Phase: 06-tiktok-instagram-auto-publish*
*Completed: 2026-07-10*

## Self-Check: PASSED

- FOUND: scripts/instagram_publish.py
- FOUND: tests/test_instagram_publish.py
- FOUND: .planning/phases/06-tiktok-instagram-auto-publish/06-06-SUMMARY.md
- FOUND commit: b387490
- FOUND commit: abf55d0
