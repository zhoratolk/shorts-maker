---
phase: 06-tiktok-instagram-auto-publish
plan: 05
subsystem: infra
tags: [requests, tiktok-content-posting-api, cli, argparse, publish-queue]

# Dependency graph
requires:
  - phase: 06-03
    provides: "scripts/tiktok_publish.py: queue lifecycle, OAuth credential handling, Content Posting API HTTP layer, upload_and_publish orchestration, reconcile_uploading/reconcile_all_uploading"
provides:
  - "scripts/tiktok_publish.py::kill_item - TikTok's Pitfall-4 divergence from YouTube's revert-and-verify kill: local-only flip to KILLED for QUEUED/PAUSED/UPLOADING (with or without a recorded publish_id), RuntimeError (never silent success) on an already-PUBLISHED entry"
  - "scripts/tiktok_publish.py CLI: build_argument_parser/run_command/main implementing --check/--now/--pause/--kill/--resume/--list, matching publish_queue.py's exact dispatch shape and ordering"
  - "scripts/tiktok_publish.py is now independently runnable standalone (`python scripts/tiktok_publish.py --check` etc.), not just importable under pytest"
affects: [06-06 (Instagram CLI wrapper - sibling shape), 06-07 (Windows Task Scheduler docs wiring this CLI)]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "kill_item takes no service_factory/credentials_factory parameter at all (unlike publish_queue.py's kill_item) since every branch is either local-only or a hard raise - never a network call"
    - "sys.path.insert(0, str(Path(__file__).resolve().parent.parent)) before a module-top-level cross-script import, matching the existing scripts/transitions.py/scripts/render.py workaround, so `python scripts/tiktok_publish.py` works standalone (not just under pytest's pythonpath=['.'])"

key-files:
  created: []
  modified:
    - scripts/tiktok_publish.py
    - tests/test_tiktok_publish.py

key-decisions:
  - "kill_item's _NOT_YET_UPLOADED_STATUSES check covers UPLOADING regardless of whether a publish_id is already recorded - a recorded publish_id (write-ahead #2) only means an in-flight, not-yet-terminal upload exists, never that anything is public, so it still kills local-only with no API call"
  - "An already-KILLED entry re-kills idempotently (flips to KILLED again, no error) rather than falling through to the PUBLISHED-only raise branch - not explicitly specified by the plan's behavior block, but the only remaining VALID_STATUSES member after QUEUED/PAUSED/UPLOADING/PUBLISHED are handled, and idempotent re-kill is the safer default over an unspecified crash"
  - "CLI's --kill catches only KeyError (unknown clip_id) into SystemExit(2); a RuntimeError from kill_item (PUBLISHED entry) is deliberately left uncaught so it propagates to the default traceback, per the plan's explicit instruction not to swallow a genuine operator error into a clean exit code"

requirements-completed: [PUB-06]

coverage:
  - id: D1
    description: "Killing a not-yet-uploaded TikTok queue entry (QUEUED/PAUSED/UPLOADING with or without a recorded publish_id) is local-only - no API call, no credentials_factory parameter exists on kill_item at all"
    requirement: "PUB-06"
    verification:
      - kind: unit
        ref: "tests/test_tiktok_publish.py#test_kill_item_queued_is_local_only_no_publish_id"
        status: pass
      - kind: unit
        ref: "tests/test_tiktok_publish.py#test_kill_item_paused_is_local_only"
        status: pass
      - kind: unit
        ref: "tests/test_tiktok_publish.py#test_kill_item_uploading_no_publish_id_is_local_only"
        status: pass
      - kind: unit
        ref: "tests/test_tiktok_publish.py#test_kill_item_uploading_with_publish_id_is_still_local_only"
        status: pass
      - kind: unit
        ref: "tests/test_tiktok_publish.py#test_kill_item_takes_no_credentials_factory_parameter"
        status: pass
    human_judgment: false
  - id: D2
    description: "Killing an already-PUBLISHED TikTok entry raises RuntimeError rather than silently no-oping or pretending to revert it (Pitfall 4) - status is left untouched, never marked KILLED"
    requirement: "PUB-06"
    verification:
      - kind: unit
        ref: "tests/test_tiktok_publish.py#test_kill_item_published_raises_runtime_error_and_leaves_status_untouched"
        status: pass
      - kind: unit
        ref: "tests/test_tiktok_publish.py#test_kill_via_cli_on_published_entry_raises_not_system_exit"
        status: pass
    human_judgment: false
  - id: D3
    description: "python scripts/tiktok_publish.py --check reconciles stuck UPLOADING entries first, then uploads at most one due item per invocation, identically to publish_queue.py's --check contract; --list/--pause/--resume/--kill/--now all dispatch correctly and the module runs standalone with --help listing all 6 flags"
    requirement: "PUB-06"
    verification:
      - kind: unit
        ref: "tests/test_tiktok_publish.py#test_check_reconciles_before_selecting_and_uploads_at_most_one"
        status: pass
      - kind: unit
        ref: "tests/test_tiktok_publish.py#test_list_prints_seq_status_caption"
        status: pass
      - kind: unit
        ref: "tests/test_tiktok_publish.py#test_now_targets_named_clip_via_same_upload_path"
        status: pass
      - kind: unit
        ref: "tests/test_tiktok_publish.py#test_pause_and_resume_via_cli_dispatch"
        status: pass
      - kind: other
        ref: "python scripts/tiktok_publish.py --help (manual invocation, confirmed all 6 flags listed)"
        status: pass
    human_judgment: false

duration: 9min
completed: 2026-07-10
status: complete
---

# Phase 6 Plan 5: TikTok kill_item + CLI Wrapper Summary

**`scripts/tiktok_publish.py` finished as a standalone-runnable CLI (`--check`/`--now`/`--pause`/`--kill`/`--resume`/`--list`) with a `kill_item` that raises loudly instead of pretending to un-publish an already-live TikTok post.**

## Performance

- **Duration:** 9 min
- **Started:** 2026-07-10T11:45:00Z
- **Completed:** 2026-07-10T11:54:05Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- `kill_item(queue, clip_id)` added: local-only KILLED flip (no network call, no `credentials_factory` parameter on the function at all) for QUEUED/PAUSED/UPLOADING regardless of whether a `publish_id` has already been write-ahead recorded; raises `RuntimeError` on an already-PUBLISHED entry and leaves its status untouched - the deliberate Pitfall-4 divergence from `publish_queue.py`'s revert-then-verify kill, since TikTok's Content Posting API has no un-publish/cancel endpoint
- `build_argument_parser`/`run_command`/`main` added, matching `publish_queue.py`'s exact CLI contract and dispatch order (`--list`, `--pause`, `--resume`, `--kill`, `--now`, `--check`, fallback usage message), swapping `service_factory` for `credentials_factory` and renaming `--client-secret` to `--client-key`
- Fixed (Rule 3, blocking) a pre-existing standalone-execution gap: `scripts/tiktok_publish.py`'s module-top-level `from scripts.publish_queue import append_notification` only resolved under pytest's `pythonpath=["."]`, not via `python scripts/tiktok_publish.py` directly - added the same `sys.path.insert` workaround `scripts/transitions.py`/`scripts/render.py` already use, verified via a manual `--help` run listing all 6 flags
- Full `tests/test_tiktok_publish.py` suite (all 3 plans' tests combined) green: 54 passed; full project suite (`tests/`, non-integration) also green: 522 passed

## Task Commits

Each task was committed atomically:

1. **Task 1: kill_item with Pitfall-4 semantics** - `8f3c264` (feat)
2. **Task 2: CLI wrapper** - `21e8ef9` (feat)

**Plan metadata:** (this commit, docs: complete plan)

## Files Created/Modified
- `scripts/tiktok_publish.py` - Added `_NOT_YET_UPLOADED_STATUSES`, `kill_item`; added `build_argument_parser`, `run_command`, `main`, `if __name__ == "__main__"`; added a `sys.path.insert` before the existing `scripts.publish_queue` cross-script import so the module runs standalone
- `tests/test_tiktok_publish.py` - Added 6 `kill_item` tests (Task 1) and 12 CLI tests (Task 2: `--list`, `--check` dry-run, `--check` reconcile-then-select-one, `--now`, unknown-clip_id errors for `--now`/`--kill`, PUBLISHED-entry `--kill` raising not exiting cleanly, `--pause`/`--resume` round trip, `--help` flag listing)

## Decisions Made
- `kill_item`'s `_NOT_YET_UPLOADED_STATUSES` branch treats UPLOADING-with-a-recorded-`publish_id` identically to UPLOADING-without-one - both are local-only, since a `publish_id` only proves an in-flight, not-yet-terminal upload exists, never that anything is public yet
- An already-KILLED entry re-kills idempotently (no error) rather than being routed into the PUBLISHED-only raise branch - the plan's behavior block didn't specify this case explicitly; idempotent re-kill was chosen as the safer default over leaving it unhandled
- CLI's `--kill` dispatch catches only `KeyError` (unknown `clip_id`) into `SystemExit(2)`; a `RuntimeError` from `kill_item` (an already-PUBLISHED entry) is deliberately left uncaught, per the plan's explicit instruction that this genuine operator error must surface loudly rather than exit cleanly

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Added sys.path insert so the module runs standalone**
- **Found during:** Task 2 (CLI wrapper) - manual verification of `<verification>`'s `python scripts/tiktok_publish.py --help` requirement
- **Issue:** The module's pre-existing (Plan 06-03) module-top-level `from scripts.publish_queue import append_notification` only resolves when the repo root is already on `sys.path` (true under pytest via `pyproject.toml`'s `pythonpath=["."]`, false when running `python scripts/tiktok_publish.py` directly - `sys.path[0]` is the script's own directory, not the repo root) - `--help` crashed with `ModuleNotFoundError: No module named 'scripts'`
- **Fix:** Added `sys.path.insert(0, str(Path(__file__).resolve().parent.parent))` immediately before the `scripts.publish_queue` import, mirroring the exact same workaround already established in `scripts/transitions.py` (04-04's "first cross-script import" precedent) and `scripts/render.py`
- **Files modified:** scripts/tiktok_publish.py
- **Verification:** `python scripts/tiktok_publish.py --help` now runs cleanly and lists all 6 flags; full test suite unaffected (54/54, then 522/522 project-wide)
- **Committed in:** `21e8ef9` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** Necessary to satisfy the plan's own `<verification>` criterion ("python scripts/tiktok_publish.py --help runs without error"). No scope creep - fix is a one-line, precedented workaround.

## Issues Encountered
- First draft of `test_check_reconciles_before_selecting_and_uploads_at_most_one` put the stuck UPLOADING entry at the lowest `seq`; after `reconcile_all_uploading` resets it to QUEUED (no `publish_id` recorded), it became the next-due item itself instead of the intended already-QUEUED entry, so the assertion on "which entry got uploaded" failed. Fixed by reordering `seq` values so the pre-existing QUEUED entry has the lowest `seq` and the reconciled entry is not the one picked. No production code was affected.

## User Setup Required

None - this plan is code-only (kill_item + CLI wrapper over the existing Plan 06-03 module). The CLI's `--client-key`/`--token`/`--config` defaults assume the TikTok app credentials and OAuth consent flow set up as part of Plan 06-03's `user_setup` runbook; wiring this CLI into the actual Windows Task Scheduler task is Plan 06-07's job.

## Next Phase Readiness

- `scripts/tiktok_publish.py` is complete, independently-runnable, and has the exact same operator surface (`--check`/`--now`/`--pause`/`--kill`/`--resume`/`--list`) as `scripts/publish_queue.py`, ready for Plan 06-07 to wire into the Windows Task Scheduler task
- Sibling plan 06-06 (Instagram) can proceed independently - it touches `scripts/instagram_publish.py`, a disjoint file, no conflict with this plan's changes
- No outstanding blockers introduced by this plan

---
*Phase: 06-tiktok-instagram-auto-publish*
*Completed: 2026-07-10*

## Self-Check: PASSED

- FOUND: scripts/tiktok_publish.py
- FOUND: tests/test_tiktok_publish.py
- FOUND: .planning/phases/06-tiktok-instagram-auto-publish/06-05-SUMMARY.md
- FOUND: commit 8f3c264 (feat: Task 1 kill_item)
- FOUND: commit 21e8ef9 (feat: Task 2 CLI wrapper)
