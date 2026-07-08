---
phase: 03-youtube-scheduled-auto-publish
plan: 03
subsystem: publishing
tags: [python, youtube-data-api, pytest, idempotency, safety]

# Dependency graph
requires:
  - phase: 03-youtube-scheduled-auto-publish
    plan: 02
    provides: "upload_and_schedule's write-ahead UPLOADING status and build_insert_body's embedded [queue-id: {seq}] marker, both reused/reconciled against here"
provides:
  - "pause_item/resume_item + select_next_due - PAUSED/KILLED entries are never picked as the next-due item"
  - "kill_item - local-only KILLED flip for not-yet-uploaded entries; API revert + mandatory verify for already-scheduled entries"
  - "cancel_scheduled_release + verify_killed - the re-send-private revert body and the post-kill re-fetch that must confirm private before KILLED is trusted"
  - "reconcile_uploading + reconcile_all_uploading - resolves a crash-mid-upload UPLOADING entry against YouTube's actual uploads before any retry, adopt-or-requeue, never re-inserts"
affects: [03-04]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Verify-before-trust: kill_item never marks KILLED on the strength of the update() call alone - it always re-fetches via verify_killed and raises RuntimeError if the re-fetch doesn't confirm private (Pitfall 2)"
    - "Reconcile-before-select: reconcile_all_uploading resolves every stuck UPLOADING entry before select_next_due ever runs, closing the PUB-05 crash-mid-upload gap at the selection boundary rather than scattering the check across callers"
    - "Marker match reuses the exact string build_insert_body embeds (_seq_marker helper) so the embed and the reconciliation match can never silently drift apart"

key-files:
  created: []
  modified:
    - scripts/publish_queue.py
    - tests/test_publish_queue.py
    - docs/publish-queue.md

key-decisions:
  - "kill_item treats UPLOADING-with-no-video_id the same as QUEUED/PAUSED (local-only KILLED) - an in-flight upload that hasn't yet produced a video_id has nothing on YouTube to revert"
  - "reconcile_uploading fetches descriptions via a dedicated videos.list(part=snippet) call (chunked to 50 ids) rather than extending list_uploaded_videos's return shape, since youtube_analytics.py's existing playlistItems-based helper doesn't carry description and this plan intentionally left that module unmodified"
  - "reconcile_all_uploading skips (does not touch) an UPLOADING entry that already has a video_id recorded - that is not the 'stuck mid-upload, no record' case PUB-05 targets, and touching it would risk clobbering a legitimate in-progress multi-chunk upload"
  - "docs/publish-queue.md created as a scaffold with the Outcome section explicitly unfilled - Task 3's empirical live-API confirmation was not performed in this execution (see Deviations/Checkpoint below), so no outcome could be honestly recorded yet"

patterns-established:
  - "Post-mutation verify-before-trust for any irreversible-adjacent state transition (kill) - the transition is only committed to the manifest after independently re-observing the external system's actual state, not merely trusting the mutating call's return value"

requirements-completed: [PUB-04, PUB-05]

coverage:
  - id: D1
    description: "pause_item/resume_item flip QUEUED<->PAUSED; select_next_due skips PAUSED and KILLED entries, returning the lowest-seq QUEUED entry or None"
    requirement: "PUB-04"
    verification:
      - kind: unit
        ref: "tests/test_publish_queue.py::test_pause_item_flips_queued_to_paused"
        status: pass
      - kind: unit
        ref: "tests/test_publish_queue.py::test_resume_item_flips_paused_back_to_queued"
        status: pass
      - kind: unit
        ref: "tests/test_publish_queue.py::test_select_next_due_skips_paused_items"
        status: pass
      - kind: unit
        ref: "tests/test_publish_queue.py::test_select_next_due_skips_killed_items"
        status: pass
      - kind: unit
        ref: "tests/test_publish_queue.py::test_select_next_due_returns_none_when_nothing_eligible"
        status: pass
    human_judgment: false
  - id: D2
    description: "kill_item is local-only (no service_factory call) for not-yet-uploaded entries: QUEUED, PAUSED, and UPLOADING-with-no-video_id"
    requirement: "PUB-04"
    verification:
      - kind: unit
        ref: "tests/test_publish_queue.py::test_kill_item_not_yet_uploaded_is_local_only_no_service_call"
        status: pass
      - kind: unit
        ref: "tests/test_publish_queue.py::test_kill_item_paused_not_yet_uploaded_is_also_local_only"
        status: pass
      - kind: unit
        ref: "tests/test_publish_queue.py::test_kill_item_uploading_with_no_video_id_is_local_only"
        status: pass
    human_judgment: false
  - id: D3
    description: "cancel_scheduled_release sends the exact revert body {id, status:{privacyStatus:private}} with publishAt deliberately absent from the body entirely (Pitfall 2 guard)"
    requirement: "PUB-04"
    verification:
      - kind: unit
        ref: "tests/test_publish_queue.py::test_cancel_scheduled_release_sends_exact_revert_body_no_publish_at"
        status: pass
    human_judgment: false
  - id: D4
    description: "verify_killed re-fetches videos.list(part=status) and returns True only when privacyStatus==private, False otherwise; kill_item marks KILLED only on a True verify and raises RuntimeError (leaving status unchanged) on a failed verify"
    requirement: "PUB-04"
    verification:
      - kind: unit
        ref: "tests/test_publish_queue.py::test_verify_killed_returns_true_when_private"
        status: pass
      - kind: unit
        ref: "tests/test_publish_queue.py::test_verify_killed_returns_false_when_not_private"
        status: pass
      - kind: unit
        ref: "tests/test_publish_queue.py::test_kill_item_scheduled_calls_revert_then_verify_then_marks_killed"
        status: pass
      - kind: unit
        ref: "tests/test_publish_queue.py::test_kill_item_scheduled_failed_verify_blocks_killed_mark_and_raises"
        status: pass
    human_judgment: false
  - id: D5
    description: "reconcile_uploading adopts the existing video_id (status->SCHEDULED) when the embedded [queue-id: {seq}] marker matches a channel upload's description, and never calls videos().insert while doing so"
    requirement: "PUB-05"
    verification:
      - kind: unit
        ref: "tests/test_publish_queue.py::test_reconcile_uploading_adopts_video_id_when_marker_matches"
        status: pass
      - kind: unit
        ref: "tests/test_publish_queue.py::test_reconcile_uploading_never_calls_insert"
        status: pass
    human_judgment: false
  - id: D6
    description: "reconcile_uploading resets a stuck entry to QUEUED (clearing video_id) when no matching upload is found - safe retry since nothing was created"
    requirement: "PUB-05"
    verification:
      - kind: unit
        ref: "tests/test_publish_queue.py::test_reconcile_uploading_resets_to_queued_when_no_match"
        status: pass
    human_judgment: false
  - id: D7
    description: "reconcile_all_uploading resolves every stuck UPLOADING entry before select_next_due ever runs, so a crash-mid-upload entry can never be silently bypassed and re-uploaded as a fresh QUEUED item"
    requirement: "PUB-05"
    verification:
      - kind: unit
        ref: "tests/test_publish_queue.py::test_select_next_due_reconciles_uploading_entries_before_selecting_new_item"
        status: pass
    human_judgment: false
  - id: D8
    description: "The kill body is empirically confirmed against a real scheduled YouTube video to cancel the pending auto-publish (Assumption A1), with the confirmed outcome/body recorded in docs/publish-queue.md"
    requirement: "PUB-04"
    verification: []
    human_judgment: true
    rationale: "Requires a real OAuth consent flow for upload_token.json (does not yet exist on this machine - browser interaction needed), a genuine throwaway private test video uploaded to the real channel, and waiting for a real publishAt timestamp to pass to observe whether the video actually stays private. This is irreversible-adjacent live API surface (a wrong result means a video the user believed killed goes public) and cannot be safely simulated or auto-approved by an agent - it is Task 3's dedicated human-check checkpoint, not yet performed in this execution."

duration: ~35min (Tasks 1-2 code+tests; Task 3 checkpoint reached, not executed)
completed: 2026-07-08
status: complete
---

# Phase 3 Plan 3: Pause/Kill + Idempotency Reconciliation Summary

**Verify-before-trust kill path (local flip for not-yet-uploaded items, API revert + mandatory re-fetch confirmation for scheduled items) and marker-based reconciliation that resolves a crash-mid-upload manifest entry against YouTube's actual uploads before ever considering a retry.**

## Performance

- **Duration:** ~35 min for Tasks 1-2 (code + tests, TDD RED/GREEN per task)
- **Started:** 2026-07-08T15:41:44Z
- **Completed:** 2026-07-08T15:46:30Z (Tasks 1-2; Task 3 is an open human-check checkpoint, see below)
- **Tasks:** 2 of 3 code/verification tasks complete; Task 3 (live empirical confirmation) reached and documented as a checkpoint, not executed
- **Files modified:** 3 (2 modified: `scripts/publish_queue.py`, `tests/test_publish_queue.py`; 1 created: `docs/publish-queue.md`)

## Accomplishments
- `scripts/publish_queue.py`: `pause_item`/`resume_item` (QUEUED<->PAUSED) + `select_next_due` (lowest-seq QUEUED entry, skips PAUSED/KILLED)
- `scripts/publish_queue.py`: `kill_item` - local-only KILLED flip for QUEUED/PAUSED/UPLOADING-with-no-video_id; for SCHEDULED entries, calls `cancel_scheduled_release` then `verify_killed`, only marking KILLED on a successful verify (raises `RuntimeError` and leaves status untouched otherwise)
- `scripts/publish_queue.py`: `cancel_scheduled_release` sends the exact `{id, status:{privacyStatus:"private"}}` revert body with `publishAt` deliberately absent (Pitfall 2); `verify_killed` re-fetches `videos.list(part="status")` and confirms `privacyStatus=="private"`
- `scripts/publish_queue.py`: `reconcile_uploading` reuses `youtube_analytics.get_own_channel`/`list_uploaded_videos` plus a new `_fetch_descriptions` helper (`videos.list(part="snippet")`, chunked to 50 ids) to match the embedded `[queue-id: {seq}]` marker; adopts the video_id on match (status->SCHEDULED, zero `insert` calls) or resets to QUEUED on no match
- `scripts/publish_queue.py`: `reconcile_all_uploading` resolves every stuck UPLOADING entry (that has no `video_id` yet) before any new selection - wired as the mandatory step ahead of `select_next_due` so a crash-mid-upload entry can never be silently bypassed
- `docs/publish-queue.md`: created with a "Kill-path verification" scaffold documenting the required live test steps for Assumption A1 - outcome section deliberately left unfilled pending the human-check
- 19 new tests across `tests/test_publish_queue.py` (49 total in that file now) using hand-written fake-service test doubles matching the house style from `tests/test_youtube_analytics.py` - full project suite at 311 passed

## Task Commits

Each task was committed atomically (TDD RED->GREEN per task):

1. **Task 1: Pause/kill for both not-yet-uploaded and already-scheduled items (PUB-04)** - `b49004a` (test, RED) / `1edf7e3` (feat, GREEN)
2. **Task 2: Reconciliation of a stuck `uploading` entry (PUB-05)** - `80620fc` (test, RED) / `77b5f26` (feat, GREEN)
3. **Task 3: Empirically confirm the kill body (Assumption A1)** - `d195e78` (docs, scaffold only - checkpoint reached, live test NOT performed; see Checkpoint below)

**Plan metadata:** (this commit, see final_commit step)

## Files Created/Modified
- `scripts/publish_queue.py` - Added `pause_item`, `resume_item`, `select_next_due`, `_find_entry`, `_NOT_YET_UPLOADED_STATUSES`, `kill_item`, `cancel_scheduled_release`, `verify_killed`, `_seq_marker`, `_fetch_descriptions`, `reconcile_uploading`, `reconcile_all_uploading`
- `tests/test_publish_queue.py` - 19 new tests: 5 pause/select_next_due tests, 3 local-only-kill tests, 1 revert-body test, 2 verify_killed tests, 2 full-kill-flow tests (success + failed-verify), 2 reconcile_uploading tests (adopt + requeue), 1 never-calls-insert test, 1 select-reconciles-before-selecting test; plus new fake-service classes (`FakeVideosUpdateService`, `FakeChannelsServiceForReconcile`, `FakePlaylistItemsServiceForReconcile`, `FakeVideosSnippetService`, `FakeReconcileService`)
- `docs/publish-queue.md` - New file: "Kill-path verification (Assumption A1)" section with required live-test steps and an unfilled Outcome section

## Decisions Made
- `kill_item` treats `UPLOADING`-with-no-`video_id` identically to `QUEUED`/`PAUSED` (local-only) - an in-flight upload that has not yet produced a `video_id` has nothing on YouTube to revert, so there is no API-half case to trigger.
- `reconcile_uploading` fetches descriptions via a dedicated `videos.list(part="snippet")` call (chunked to the API's 50-ids-per-request limit) rather than modifying `youtube_analytics.py::list_uploaded_videos`'s return shape - that existing helper is playlistItems-based and doesn't carry description, and this plan deliberately left `youtube_analytics.py` unmodified (read-only reuse only, per the plan's stated scope).
- `reconcile_all_uploading` explicitly skips (does not touch) any `UPLOADING` entry that already has a `video_id` recorded - that's not the "stuck mid-upload, no record" case PUB-05 targets, and touching it risks clobbering a legitimately still-in-progress multi-chunk upload rather than a crashed one.
- `docs/publish-queue.md` was created as a scaffold with the live-test steps and an explicitly unfilled Outcome section, rather than fabricating a confirmed result - the empirical confirmation genuinely did not happen in this execution (see Checkpoint below).

## Deviations from Plan

None (Rules 1-3) - Tasks 1 and 2 were implemented exactly as specified in `<behavior>`/`<action>`, all specified test cases were written and pass, and the additional `select_next_due`/`reconcile_all_uploading` selector functions were added because the plan explicitly called for them ("Ensure the 'next due item' selector ... already excludes PAUSED and KILLED - if not present yet, add/adjust it here" and "Wire a reconciliation pass into the check-selection helper") - no such selector existed before this plan, so this is the plan's own scope, not scope creep.

## Checkpoint: Task 3 (Assumption A1 live verification) NOT performed

**Type:** human-verify (blocking-human, safety-critical live API test)

Task 3 requires an actual live test against a real YouTube channel: temporarily
flipping `publish.enabled: true`, running a real OAuth consent flow to create
`upload_token.json` (does not exist on this machine - confirmed via file
check; only the read-only `token.json` used by `youtube_analytics.py`
exists), uploading a genuine throwaway private clip, waiting for a real
`publishAt` timestamp to approach, killing it, and then continuing to wait
past the original `publishAt` to observe whether the video actually stayed
private (or went public, which would mean the kill body is insufficient and
a gap must be opened before this path is trusted live).

This cannot be auto-approved or simulated by an agent:
- It requires interactive browser-based OAuth consent (first-ever run of the
  upload-scoped token).
- It requires posting an actual (even if throwaway/private) video to the
  user's real YouTube channel.
- Its entire purpose is empirically verifying a safety-critical assumption
  (Assumption A1) that, if wrong, means a video the user believes is killed
  could go public - exactly the kind of package-legitimacy-adjacent,
  irreversible-if-wrong live action the checkpoint protocol reserves for
  explicit human execution, not agent auto-approval.

**What's built and ready for the human-check:**
- `kill_item`/`cancel_scheduled_release`/`verify_killed` (this plan, fully
  tested against fakes) - the exact code path the live test will exercise.
- `docs/publish-queue.md` - the scaffold to record the outcome in, with the
  precise steps to follow already written out.

**How to verify (steps a human should run):**
1. In `config.yaml`, set `publish.enabled: true` temporarily.
2. Run the upload path (e.g. via a short Python REPL/script calling
   `enqueue()` + `upload_and_schedule()`, or a small ad-hoc CLI invocation)
   against one real, throwaway, clearly-marked-private test clip. The first
   run will open a browser for the `youtube.upload`-scoped OAuth consent,
   writing `upload_token.json`.
3. Confirm in YouTube Studio that the video is Private/Scheduled.
4. Before its `publishAt` passes, call `kill_item()` against that entry (or
   invoke `cancel_scheduled_release()` + `verify_killed()` directly against
   the video_id).
5. Confirm `verify_killed()` returned `True` and the local manifest entry
   shows `KILLED`.
6. Wait past the original `publishAt` timestamp; re-check the video's status
   (YouTube Studio or a fresh `videos.list(part="status")` call). Confirm
   `privacyStatus` is still `"private"` and the video did **not** go public.
7. Update `docs/publish-queue.md`'s "Outcome" section with the confirmed
   result (body used, timestamp, pass/fail) and revert `publish.enabled` back
   to `false` in `config.yaml`.
8. If the video went public despite the kill, STOP - do not consider the
   kill path trustworthy for live use; capture the actual body/behavior the
   API required and treat this as a gap requiring a follow-up fix before any
   further phase work relies on `kill_item`.

**Resume signal:** Once the human has performed the steps above and recorded
the outcome in `docs/publish-queue.md`, re-invoke plan execution (or a
lightweight follow-up) to close out Task 3's `<done>` criterion formally
(update this SUMMARY's D8 coverage entry's `verification`/`status` and the
plan's overall completion state). If the kill did not take, open a gap/issue
instead of proceeding to trust the live kill path.

## Auth Gates

None encountered directly in Tasks 1-2 (fakes only, no real credentials
touched) - the auth gate is embedded in Task 3's checkpoint above: the very
first live use of `upload_token.json` will require an interactive OAuth
consent flow (browser), which is exactly why Task 3 cannot be automated.

## Known Stubs

None. Every function delivered in Tasks 1-2 is fully wired to real logic (no
hardcoded empty returns, no placeholder text). `docs/publish-queue.md`'s
Outcome section is an intentionally unfilled placeholder, not a code stub -
it is explicitly labeled "Not yet recorded" and documents exactly what must
be filled in and by whom (Task 3's human-check).

## Threat Flags

None - all new surface (pause/kill local flip, kill API revert+verify,
reconciliation match/adopt/requeue) was already anticipated and dispositioned
in this plan's own `<threat_model>` (T-03-08, T-03-09, T-03-10); no new trust
boundary was introduced beyond what the plan already covers.

## Issues Encountered

Same pre-existing pytest tmp-dir permission quirk noted in 03-01-SUMMARY.md
and 03-02-SUMMARY.md (`C:\Users\<cyrillic-username>\AppData\Local\Temp\
pytest-of-...` lock, and this session additionally saw `.pytest_cache`
directory listing permission-denied during `git status`). Worked around
identically via `--basetemp=<writable-scratch-dir>` for every verification
run in this plan; `git status --short` output is unaffected by the
`.pytest_cache` warning (git still reports tracked-file changes correctly).
Not introduced by this plan's changes; carried-forward informational note
only.

## Next Phase Readiness

- `kill_item`/`pause_item`/`resume_item`/`select_next_due` and
  `reconcile_uploading`/`reconcile_all_uploading` are fully implemented and
  unit-tested against fakes - ready for Plan 04's CLI/periodic-check wiring
  to call them with a real `service_factory`
  (`load_credentials(client_secret_path, upload_token_path, [UPLOAD_SCOPE])`
  + `build("youtube", "v3", ...)`, matching Plan 02's documented pattern).
- **Blocker for full phase sign-off (not for Plan 04's code, but for trusting
  the kill path live):** Task 3's empirical confirmation of Assumption A1 is
  outstanding. Plan 04 (and the phase's overall human-verify gate) should
  treat the kill path as code-complete-but-not-yet-empirically-verified until
  a human performs the steps in this SUMMARY's Checkpoint section and
  `docs/publish-queue.md`'s Outcome section is filled in.
- No blockers for Plan 04's code work itself - only the live human-check
  above gates full trust in `kill_item` for real scheduled videos.

---
*Phase: 03-youtube-scheduled-auto-publish*
*Completed: 2026-07-08*

## Self-Check: PASSED

- FOUND: scripts/publish_queue.py
- FOUND: tests/test_publish_queue.py
- FOUND: docs/publish-queue.md
- FOUND: .planning/phases/03-youtube-scheduled-auto-publish/03-03-SUMMARY.md
- FOUND: b49004a (Task 1 test/RED commit)
- FOUND: 1edf7e3 (Task 1 feat/GREEN commit)
- FOUND: 80620fc (Task 2 test/RED commit)
- FOUND: 77b5f26 (Task 2 feat/GREEN commit)
- FOUND: d195e78 (Task 3 docs scaffold commit)
