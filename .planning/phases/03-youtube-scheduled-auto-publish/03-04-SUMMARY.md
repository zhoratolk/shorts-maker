---
phase: 03-youtube-scheduled-auto-publish
plan: 04
subsystem: publishing
tags: [python, argparse, cli, youtube-data-api, notifications, pytest, windows-task-scheduler]

# Dependency graph
requires:
  - phase: 03-youtube-scheduled-auto-publish
    plan: 02
    provides: "upload_and_schedule() orchestration - the single upload path both --check and --now route through"
  - phase: 03-youtube-scheduled-auto-publish
    plan: 03
    provides: "pause_item/resume_item/select_next_due/kill_item/reconcile_all_uploading - the CLI's --pause/--resume/--kill/--check reconcile-first behavior"
provides:
  - "append_notification()/read_unread_notifications() - append-only D-06 session-bridge log with a persisted last-read line-count marker"
  - "build_argument_parser()/run_command()/main() - argparse CLI: --check/--now/--pause/--kill/--resume/--list, main() builds the real service_factory, run_command() is the testable dispatch"
  - "docs/publish-queue.md operator guide: schtasks setup+verify, dry-run->opt-in flip, daily grid, notification surfacing, CLI reference"
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Line-count marker (not byte-offset) for the notification-log last-read position - simpler to reason about with splitlines()/readlines(), no multi-byte-UTF-8 boundary risk, persisted alongside the log rather than embedded in it"
    - "Shared _upload_one() helper called by both the --check and --now CLI branches - guarantees the two trigger paths can never diverge onto separate publish logic (D-05 key link)"
    - "run_command(args, service_factory, config) factored out from main() so tests drive the full CLI dispatch with a fake service and tmp-path queue/config, without ever touching OAuth - main() only parses args and builds the real service_factory/config"

key-files:
  created: []
  modified:
    - scripts/publish_queue.py
    - tests/test_publish_queue.py
    - docs/publish-queue.md

key-decisions:
  - "Notification marker is a persisted line-count in a sibling .read file, not a byte offset - chosen for readability/no-encoding-boundary-risk since the log is always read in full and re-diffed, never seeked into"
  - "Only uploads and errors are logged to notifications.log, never no-op 'nothing due' checks - keeps the log signal-dense per 03-RESEARCH's anti-noise recommendation"
  - "_upload_one() is the single shared call site for upload_and_schedule() from both --check and --now - not just 'both call the same function' as a convention, but literally one helper function neither branch reimplements"
  - "--check enforces 'at most one item per invocation' structurally: select_next_due() (after reconcile_all_uploading resolves any stuck entry) returns at most one entry, and _upload_one() is called at most once per --check invocation - there is no loop that could accidentally process more than one"
  - "Unknown clip_id on --now/--kill/--pause/--resume prints a stderr error and raises SystemExit(2) (argparse-style clean error) rather than letting a KeyError propagate as an unhandled traceback"
  - "docs/publish-queue.md's new operator-guide sections were inserted ABOVE the existing Plan 03 'Kill-path verification (Assumption A1)' scaffold, which is left untouched - the live human-check for Assumption A1 remains open and unrelated to this plan's CLI/docs wiring work"

requirements-completed: [PUB-01, PUB-02, PUB-03, PUB-04, PUB-05]

coverage:
  - id: D1
    description: "append_notification appends a UTC-timestamped, append-only line to notifications.log, creating parent dirs, never rewriting existing lines"
    requirement: "PUB-05"
    verification:
      - kind: unit
        ref: "tests/test_publish_queue.py::test_append_notification_creates_parent_dirs_and_writes_a_line"
        status: pass
      - kind: unit
        ref: "tests/test_publish_queue.py::test_append_notification_is_append_only_never_rewrites_existing_lines"
        status: pass
    human_judgment: false
  - id: D2
    description: "read_unread_notifications returns only lines appended since the last read and advances a persisted line-count marker so a second read in a row (or a read after no new appends) returns []"
    requirement: "PUB-05"
    verification:
      - kind: unit
        ref: "tests/test_publish_queue.py::test_read_unread_notifications_returns_new_lines_and_advances_marker"
        status: pass
      - kind: unit
        ref: "tests/test_publish_queue.py::test_read_unread_notifications_second_read_returns_empty_no_double_report"
        status: pass
      - kind: unit
        ref: "tests/test_publish_queue.py::test_read_unread_notifications_only_returns_lines_appended_since_last_read"
        status: pass
      - kind: unit
        ref: "tests/test_publish_queue.py::test_read_unread_notifications_missing_log_returns_empty"
        status: pass
    human_judgment: false
  - id: D3
    description: "The upload success notification line carries the D-05 wording with seq + HH:MM derived from publish_at"
    requirement: "PUB-05"
    verification:
      - kind: unit
        ref: "tests/test_publish_queue.py::test_append_notification_success_line_contains_seq_and_hhmm"
        status: pass
    human_judgment: false
  - id: D4
    description: "--list prints the queue's seq/status/title so sequential numbering is visible (PUB-01)"
    requirement: "PUB-01"
    verification:
      - kind: unit
        ref: "tests/test_publish_queue.py::test_list_prints_seq_numbers"
        status: pass
    human_judgment: false
  - id: D5
    description: "--check in dry-run makes zero service_factory calls and leaves the queue untouched, printing a dry-run skip message (PUB-03)"
    requirement: "PUB-03"
    verification:
      - kind: unit
        ref: "tests/test_publish_queue.py::test_check_dry_run_makes_zero_service_calls"
        status: pass
    human_judgment: false
  - id: D6
    description: "--check with publish.enabled=true uploads exactly one due item (leaving other QUEUED items untouched) and appends exactly one notification line"
    requirement: "PUB-02"
    verification:
      - kind: unit
        ref: "tests/test_publish_queue.py::test_check_enabled_uploads_exactly_one_item_and_appends_one_notification"
        status: pass
    human_judgment: false
  - id: D7
    description: "--now <clip_id> force-publishes the named clip (not necessarily the lowest-seq one) through the identical upload_and_schedule path"
    requirement: "PUB-02"
    verification:
      - kind: unit
        ref: "tests/test_publish_queue.py::test_now_targets_the_named_clip_via_same_upload_path"
        status: pass
    human_judgment: false
  - id: D8
    description: "Unknown clip_id on --now/--kill errors cleanly (SystemExit, not an unhandled crash)"
    requirement: "PUB-04"
    verification:
      - kind: unit
        ref: "tests/test_publish_queue.py::test_now_unknown_clip_id_errors_cleanly_not_crash"
        status: pass
      - kind: unit
        ref: "tests/test_publish_queue.py::test_kill_unknown_clip_id_errors_cleanly_not_crash"
        status: pass
    human_judgment: false
  - id: D9
    description: "--pause/--resume flip a queue entry's status via the CLI dispatch"
    requirement: "PUB-04"
    verification:
      - kind: unit
        ref: "tests/test_publish_queue.py::test_pause_and_resume_via_cli_dispatch"
        status: pass
    human_judgment: false
  - id: D10
    description: "docs/publish-queue.md documents a single-entry schtasks /create (3-hourly --check, wake-to-run note) and a schtasks /query verification command, the dry-run->opt-in flip with a safety note, the daily-grid config, the notification-surfacing mechanism, and the manual/pause/kill CLI reference"
    verification: []
    human_judgment: true
    rationale: "Task 3 is a documentation deliverable with a <human-check> verify type in the plan (not an automated test) - a reviewer must skim docs/publish-queue.md once to confirm an operator could set up the scheduled task and flip to live from this doc alone, per the plan's own verification spec. Content review: confirmed present via grep (schtasks /create, schtasks /query, publish.enabled opt-in, notification-surfacing section) but the actual operability judgment is inherently human."

duration: ~40min
completed: 2026-07-08
status: complete
---

# Phase 3 Plan 4: CLI + Notification Log + Task Scheduler Docs Summary

**argparse CLI (`--check`/`--now`/`--pause`/`--kill`/`--resume`/`--list`) where both trigger paths call one shared `_upload_one()` helper wrapping Plan 02's `upload_and_schedule`, an append-only notification log with a persisted line-count last-read marker bridging session-less Task Scheduler runs back into chat, and a `docs/publish-queue.md` operator guide with the exact `schtasks /create`+`/query` commands.**

## Performance

- **Duration:** ~40 min
- **Started:** 2026-07-08 (session-derived)
- **Completed:** 2026-07-08 (session-derived)
- **Tasks:** 3
- **Files modified:** 3 (0 created, 3 modified)

## Accomplishments
- `scripts/publish_queue.py`: `append_notification()` (append-only, UTC-timestamped, creates parent dirs) + `read_unread_notifications()` (persisted line-count marker in a sibling `.read` file, returns `[]` on a repeat read) - the D-06 durable bridge between a session-less Task Scheduler run and the next interactive Claude Code session
- `scripts/publish_queue.py`: `build_argument_parser()` + `run_command()` (the testable dispatch) + `main()` (real wiring: `load_config` + `load_credentials(client_secret, upload_token, [UPLOAD_SCOPE])` + `build("youtube","v3",...)`) - full CLI covering `--check`/`--now`/`--pause`/`--kill`/`--resume`/`--list`
- Shared `_upload_one()` helper: both `--check` and `--now` call it, which itself calls the identical `upload_and_schedule()` - no divergent publish logic exists anywhere in the codebase (D-05 key link)
- `--check` reconciles stuck `UPLOADING` entries first (`reconcile_all_uploading`), then either logs a dry-run skip (zero service calls, PUB-03) or uploads/schedules at most one due item and appends exactly one notification (natural quota debounce, Pitfall 4)
- `docs/publish-queue.md`: new sections 1-5 (Task Scheduler setup+verify, dry-run→opt-in flip with a bold safety note + one-time OAuth consent explanation, daily grid, notification surfacing, manual/pause/kill CLI reference) inserted above the existing Plan 03 kill-path-verification scaffold, which is untouched
- 22 new tests across `tests/test_publish_queue.py` (70 total in that file now) - 7 notification-log tests, 8 CLI-dispatch tests (list/dry-run/enabled-upload/now-targeting/unknown-clip-id x2/pause-resume) - full project suite at 325 passed

## Task Commits

Each task was committed atomically (TDD RED->GREEN per task):

1. **Task 1: Notification log - append + read-unread with a marker** - `11ba1be` (test, RED) / `3d5dd68` (feat, GREEN)
2. **Task 2: argparse CLI** - `35da582` (test, RED) / `14d4288` (feat, GREEN)
3. **Task 3: docs/publish-queue.md operator guide** - `703058e` (docs)

**Plan metadata:** (this commit, see final_commit step)

## Files Created/Modified
- `scripts/publish_queue.py` - Added `DEFAULT_NOTIFICATIONS_MARKER_PATH`, `append_notification()`, `read_unread_notifications()`, `_success_notification_text()`, `_error_notification_text()`, `_upload_one()`, `build_argument_parser()`, `run_command()`, `main()`; added `argparse`/`sys` imports
- `tests/test_publish_queue.py` - 22 new tests: 7 notification-log tests (append/parent-dirs/append-only/read-unread/second-read-empty/only-new-since-last-read/missing-log/success-line-wording), 8 CLI-dispatch tests (`--list` output, `--check` dry-run zero-calls, `--check` enabled single-upload+single-notification, `--now` targeting, `--now`/`--kill` unknown-clip-id clean errors, `--pause`/`--resume` round-trip); `FakeCliPublishConfig`, `make_cli_queue` helper
- `docs/publish-queue.md` - Added 5 new operator-guide sections above the existing Plan 03 scaffold: Task Scheduler setup (`schtasks /create`+`/query`), dry-run→live opt-in flip + OAuth consent, daily grid, notification surfacing, manual/pause/kill CLI reference; footer updated to reference both 03-03 and 03-04

## Decisions Made
- Notification-log marker is a persisted **line count** in a sibling `.read` file (`work/_publish/notifications.read`), not a byte offset - simpler to reason about with `splitlines()`, no multi-byte-UTF-8 boundary-splitting risk, and there's no performance reason to prefer a byte offset since the log is always read in full and re-diffed, never seeked into. Documented inline in the code comment per the plan's explicit ask.
- Only actual uploads and errors are logged - no-op "nothing due" `--check` runs are silent, keeping the log signal-dense (per 03-RESEARCH's explicit anti-noise recommendation).
- `_upload_one()` is a single shared helper both CLI branches call - not merely "both branches happen to call the same function" as a coding convention, but one literal call site so the two trigger paths structurally cannot diverge.
- `--check`'s "at most one item per invocation" guarantee is structural, not a counter/limit check: `select_next_due()` returns at most one entry (a `dict | None`), and `_upload_one()` is invoked at most once per `--check` call - there is no loop over multiple due items to accidentally get wrong.
- Unknown `clip_id` on `--now`/`--kill`/`--pause`/`--resume` is caught as a `KeyError` from the underlying `_find_entry`/`pause_item`/etc. and converted to a printed stderr message + `SystemExit(2)`, matching argparse's own `parser.error()`-style clean-exit convention rather than letting a raw traceback surface.
- The new `docs/publish-queue.md` sections were inserted *above* the existing Plan 03 "Kill-path verification (Assumption A1)" scaffold rather than replacing or reorganizing it - that section's live human-check (Task 3 of Plan 03) remains open and independent of this plan's CLI/docs deliverable.

## Deviations from Plan

None (Rules 1-3) - all three tasks were implemented exactly as specified in their `<behavior>`/`<action>` blocks; every test case named in the plan's task descriptions (`--list` seq output, dry-run zero-calls, enabled single-upload, `--now` targeting, clean errors on unknown clip_id, schtasks create+query+opt-in+notification-surfacing docs content) was written and passes.

## User Setup Required

**External service requires manual configuration - this is the plan's explicit `user_setup` item, not an oversight.** Registering the actual Windows Task Scheduler entry that drives the periodic `--check` cadence is a human action on the user's own machine and was deliberately NOT run by this execution (schtasks would register a live, always-firing scheduled task tied to the user's real Windows account and real OAuth-token-bearing script - not something an agent should silently create).

**What's needed:**
1. Open a terminal with access to this machine and run the `schtasks /create` command exactly as documented in `docs/publish-queue.md` section 1 (3-hourly `--check` trigger, running under the user's own account).
2. Verify with `schtasks /query /tn "shorts-maker-publish" /v /fo list` that exactly one entry exists (Pitfall 4 - a duplicate/overlapping entry is the one realistic quota-burn risk).
3. Optionally enable "Wake the computer to run this task" via the Task Scheduler GUI (`taskschd.msc`) if the machine sleeps often - `schtasks /create` has no CLI flag for this one setting.
4. When ready to go live (not required immediately - dry-run remains the safe default), follow section 2 of the doc: flip `publish.enabled: true` in `config.yaml`, and expect the first live `--check`/`--now` run to open a browser for the one-time `upload_token.json` OAuth consent (recommended to do this first run interactively, not via the detached Task Scheduler task, per the doc's note).

See `docs/publish-queue.md` sections 1-2 for the complete, copy-pasteable steps.

## Issues Encountered

Same pre-existing pytest tmp-dir permission quirk noted in 03-01/03-02/03-03-SUMMARY.md (`C:\Users\<cyrillic-username>\AppData\Local\Temp\pytest-of-...` lock, and `.pytest_cache` write-permission warnings during test runs). Worked around identically via `--basetemp=<writable-scratch-dir>` for every verification run in this plan. Not introduced by this plan's changes; carried-forward informational note only.

## Next Phase Readiness

- Phase 3 (YouTube Scheduled Auto-Publish) is now code-complete across all 5 requirements (PUB-01 through PUB-05) and all 4 plans (03-01 queue/config, 03-02 upload+schedule, 03-03 pause/kill/reconciliation, 03-04 CLI/notifications/docs).
- **Carried-forward blocker (not from this plan, from 03-03):** Plan 03's Task 3 live-kill human-verify checkpoint (empirically confirming Assumption A1 - the bare re-send-private `videos.update` body actually cancels a scheduled release) is still open/unconfirmed. This does not block this plan's CLI/notification/docs wiring (confirmed unaffected per this plan's dispatch instructions), but it does mean `kill_item`'s live-safety guarantee is code-complete-but-not-yet-empirically-verified before the phase can be considered fully trustworthy for a real scheduled kill.
- **New user-facing action needed (this plan's own `user_setup` item):** registering the actual Windows Task Scheduler entry (see "User Setup Required" above) - the code and docs are ready, but no scheduled task exists on the machine yet until a human runs the documented `schtasks /create` command.
- Full pytest suite green (325 passed) - phase gate verification command (`pytest` at repo root) passes.

---
*Phase: 03-youtube-scheduled-auto-publish*
*Completed: 2026-07-08*

## Self-Check: PASSED

- FOUND: scripts/publish_queue.py
- FOUND: tests/test_publish_queue.py
- FOUND: docs/publish-queue.md
- FOUND: .planning/phases/03-youtube-scheduled-auto-publish/03-04-SUMMARY.md
- FOUND: 11ba1be (Task 1 test/RED commit)
- FOUND: 3d5dd68 (Task 1 feat/GREEN commit)
- FOUND: 35da582 (Task 2 test/RED commit)
- FOUND: 14d4288 (Task 2 feat/GREEN commit)
- FOUND: 703058e (Task 3 docs commit)
