---
phase: 06-tiktok-instagram-auto-publish
plan: 03
subsystem: publish
tags: [tiktok, content-posting-api, oauth, requests, chunked-upload, queue]

requires:
  - phase: 06-tiktok-instagram-auto-publish
    provides: "06-01 (requests as direct dependency), 06-02 (PublishConfig tiktok_* fields)"
  - phase: 03-youtube-scheduled-auto-publish
    provides: "publish_queue.py's queue lifecycle/write-ahead/notification-log shape this module mirrors"
provides:
  - "scripts/tiktok_publish.py: own tiktok_queue.json manifest lifecycle (load/save/enqueue/select_next_due/pause/resume)"
  - "TikTok OAuth: load_credentials (cache/refresh) + run_tiktok_oauth_consent (one-time interactive browser-redirect flow)"
  - "Content Posting API HTTP layer: build_direct_post_body/init_direct_post/upload_video_chunks/fetch_post_status/check_tiktok_publish_gate"
  - "upload_and_publish orchestration: dry-run-gate-first, D-05 SELF_ONLY detection, two-stage write-ahead persistence"
  - "reconcile_uploading/reconcile_all_uploading: crash-safe resolution of a stuck UPLOADING entry via status/fetch, no blind re-init"
affects: [06-05-cli-wrapper-and-kill, 06-04-instagram-publish]

tech-stack:
  added: []
  patterns:
    - "session=requests injectable HTTP-layer parameter (mirrors runner=subprocess.run convention) - every network-calling function accepts it, tests pass FakeSession"
    - "Own separate queue manifest per platform (tiktok_queue.json) - structural isolation from YouTube's queue.json, not just a status-field convention"
    - "Pre-post gating check (creator_info/query) instead of post-hoc status inspection for detecting a platform-side restriction (D-05)"

key-files:
  created:
    - scripts/tiktok_publish.py
    - tests/test_tiktok_publish.py
  modified: []

key-decisions:
  - "kill_item and the CLI wrapper are explicitly out of scope for this plan (deferred to 06-05) - only pause_item/resume_item are implemented, matching the plan's must_haves artifact list"
  - "video_share_url is populated from status/fetch's publicaly_available_post_id field on both the success path (upload_and_publish) and the reconcile-adopts-PUBLISH_COMPLETE path (reconcile_uploading), for consistency"
  - "upload_and_publish's terminal-status poll loop takes a poll_interval_seconds parameter (default 2.0) so tests can supply an already-terminal first status/fetch response and incur zero real sleep"
  - "run_tiktok_oauth_consent and _capture_oauth_redirect_code are tested directly (via monkeypatched webbrowser.open + a background thread hitting the real loopback listener) rather than treated as fully manual-only, since the redirect-listener bind address is a threat-model-mandated (T-06-03) automated check"

requirements-completed: [PUB-06]

coverage:
  - id: D1
    description: "TikTok queue lifecycle (load/save/enqueue idempotent-on-clip_id/select_next_due/pause/resume) on its own tiktok_queue.json manifest, structurally isolated from YouTube's queue.json"
    requirement: "PUB-06"
    verification:
      - kind: unit
        ref: "tests/test_tiktok_publish.py::test_enqueue_sequential_numbering_and_shape"
        status: pass
      - kind: unit
        ref: "tests/test_tiktok_publish.py::test_select_next_due_skips_non_queued_statuses"
        status: pass
      - kind: unit
        ref: "tests/test_tiktok_publish.py::test_isolation_pause_tiktok_queue_never_touches_youtube_queue"
        status: pass
    human_judgment: false
  - id: D2
    description: "OAuth credential handling: cached-token reuse, silent refresh via grant_type=refresh_token, FileNotFoundError before first-time consent, and a one-time interactive consent flow (127.0.0.1-only local redirect listener, never 0.0.0.0)"
    requirement: "PUB-06"
    verification:
      - kind: unit
        ref: "tests/test_tiktok_publish.py::test_load_credentials_refreshes_expired_token"
        status: pass
      - kind: unit
        ref: "tests/test_tiktok_publish.py::test_capture_oauth_redirect_server_binds_to_localhost_only"
        status: pass
      - kind: unit
        ref: "tests/test_tiktok_publish.py::test_run_tiktok_oauth_consent_full_flow"
        status: pass
    human_judgment: true
    rationale: "The redirect-listener bind address and token-exchange plumbing are automated-tested, but a real OAuth consent against TikTok's live authorize endpoint (actual developer app, actual browser approval) can only be exercised manually once real credentials exist - 06-VALIDATION.md's own Manual-Only Verifications table lists this."
  - id: D3
    description: "Content Posting API HTTP layer: FILE_UPLOAD video/init body shape, chunked PUT upload with correct Content-Range headers (single- and multi-chunk), status/fetch polling, and D-05's creator_info/query pre-post gating check"
    requirement: "PUB-06"
    verification:
      - kind: unit
        ref: "tests/test_tiktok_publish.py::test_build_direct_post_body_shapes_file_upload_source"
        status: pass
      - kind: unit
        ref: "tests/test_tiktok_publish.py::test_upload_video_chunks_multi_chunk_covers_whole_file"
        status: pass
      - kind: unit
        ref: "tests/test_tiktok_publish.py::test_check_tiktok_publish_gate_self_only"
        status: pass
    human_judgment: false
  - id: D4
    description: "Orchestration: dry-run-gate-first (zero credential load, zero HTTP call when tiktok_enabled=False), two-stage write-ahead persistence (UPLOADING before the gate check, publish_id before the chunk PUT loop), and D-05's distinct SELF_ONLY notification branch that never masquerades as a normal success"
    requirement: "PUB-06"
    verification:
      - kind: unit
        ref: "tests/test_tiktok_publish.py::test_dry_run_default_no_upload"
        status: pass
      - kind: unit
        ref: "tests/test_tiktok_publish.py::test_upload_and_publish_full_success_flow_persists_write_ahead"
        status: pass
      - kind: unit
        ref: "tests/test_tiktok_publish.py::test_upload_one_self_only_appends_distinct_notification_not_normal_success"
        status: pass
    human_judgment: false
  - id: D5
    description: "Crash-safe reconciliation of a stuck UPLOADING entry via status/fetch using the recorded publish_id - never a blind re-init - across all four cases (no publish_id / PUBLISH_COMPLETE / FAILED / still in-flight)"
    requirement: "PUB-06"
    verification:
      - kind: unit
        ref: "tests/test_tiktok_publish.py::test_idempotent_retry_no_duplicate_init_on_reconcile"
        status: pass
      - kind: unit
        ref: "tests/test_tiktok_publish.py::test_reconcile_uploading_still_in_flight_is_left_untouched"
        status: pass
    human_judgment: false

duration: 25min
completed: 2026-07-10
status: complete
---

# Phase 06 Plan 03: TikTok Publish Core (Queue, OAuth, HTTP, Orchestration) Summary

**Built `scripts/tiktok_publish.py`'s complete core — its own `tiktok_queue.json` lifecycle, hand-rolled TikTok OAuth (cache/refresh + one-time interactive browser-redirect consent), the Content Posting API's chunked `FILE_UPLOAD` HTTP layer, and dry-run-first orchestration with D-05's pre-post SELF_ONLY gating detection — fully covered by 38 hand-written-fake-based tests, no CLI/kill_item yet (Plan 06-05).**

## Performance

- **Duration:** ~25 min
- **Tasks:** 3 completed (each as a test/RED then feat/GREEN commit pair)
- **Files modified:** 2 (both new)

## Accomplishments

- `scripts/tiktok_publish.py`'s queue lifecycle (`load_queue`/`save_queue`/`enqueue`/`select_next_due`/`pause_item`/`resume_item`) mirrors `scripts/publish_queue.py` exactly, applied to its own `work/_publish/tiktok_queue.json` manifest — a TikTok bug or audit delay can never touch the already-live YouTube queue.
- `load_credentials`/`run_tiktok_oauth_consent` implement TikTok's OAuth 2.0 flow from scratch on top of `requests` (no TikTok Python SDK exists): cached-token reuse, silent refresh, and a one-time interactive consent flow whose local redirect listener is bound explicitly to `127.0.0.1` (never `0.0.0.0`, T-06-03/V4) via a single bounded `handle_request()` call — no lingering listener.
- The Content Posting API HTTP layer (`build_direct_post_body`, `init_direct_post`, `upload_video_chunks`, `fetch_post_status`, `check_tiktok_publish_gate`) copies 06-RESEARCH.md's request/response shapes verbatim, each accepting an injectable `session=requests` parameter for testability.
- `upload_and_publish` orchestrates the full flow with PUB-03 parity (`tiktok_enabled` check is the literal first statement) and two write-ahead persistence points (Pitfall 5): `UPLOADING` before the gate check, and `publish_id` before the chunk-PUT loop starts.
- D-05's SELF_ONLY detection happens exclusively via `creator_info/query`'s `privacy_level_options`, called *before* `init_direct_post` — never inferred from `status/fetch` after the fact (Pitfall 1). `_upload_one` surfaces this as a distinct notification line, never conflated with a normal success report.
- `reconcile_uploading`/`reconcile_all_uploading` resolve a crash-stuck `UPLOADING` entry via `status/fetch` using the recorded `publish_id` — no blind re-`init_direct_post` retry (T-06-04).

## Task Commits

Each task followed the RED (test) → GREEN (feat) TDD cycle:

1. **Task 1: Queue lifecycle + OAuth credential handling**
   - `77dae7a` test(06-03): add failing tests for TikTok queue lifecycle + OAuth credential handling
   - `0a78ecd` feat(06-03): implement TikTok queue lifecycle + OAuth credential handling
2. **Task 2: TikTok HTTP upload layer**
   - `4cf53a3` test(06-03): add failing tests for TikTok HTTP upload layer
   - `dd28962` feat(06-03): implement TikTok Content Posting API HTTP upload layer
3. **Task 3: Orchestration (dry-run gate, D-05 detection, write-ahead) and reconciliation**
   - `ddb766d` test(06-03): add failing tests for TikTok orchestration + reconciliation
   - `9e20548` feat(06-03): implement TikTok orchestration (dry-run, D-05, write-ahead) and reconciliation

**Plan metadata:** (this commit) docs(06-03): complete plan

## Files Created/Modified

- `scripts/tiktok_publish.py` - Queue lifecycle, OAuth credential handling, Content Posting API HTTP layer, orchestration (`upload_and_publish`/`_upload_one`), and reconciliation (`reconcile_uploading`/`reconcile_all_uploading`) — 633 lines, no CLI wrapper or `kill_item` (Plan 06-05)
- `tests/test_tiktok_publish.py` - 38 tests covering all three tasks via a hand-written `FakeResponse`/`FakeSession` HTTP double (no `unittest.mock`) plus a `SpyingSession` subclass for write-ahead-persistence assertions — 764 lines

## Decisions Made

- `kill_item` and the CLI wrapper (`argparse`/`main()`) are deliberately not built in this plan — the PLAN.md `must_haves.artifacts` list only names `pause_item`/`resume_item`, and the objective explicitly scopes `kill_item`/CLI to Plan 06-05 (an already-`PUBLISHED` TikTok post cannot be un-published via any API call, unlike YouTube's `publishAt`-based kill — 06-PATTERNS.md).
- `video_share_url` is populated from `status/fetch`'s `publicaly_available_post_id` field consistently on both the direct-success path (`upload_and_publish`) and the reconcile-adopts-`PUBLISH_COMPLETE` path (`reconcile_uploading`).
- `upload_and_publish` exposes a `poll_interval_seconds` parameter (default 2.0) so the terminal-status poll loop is real-time in production but tests can supply an already-terminal first `status/fetch` response and incur zero actual sleep.
- Beyond the plan's literal task scope, added two low-cost bonus tests directly relevant to this plan's own threat-model entries and VALIDATION.md's requirement→test map: `test_isolation_pause_tiktok_queue_never_touches_youtube_queue` (partial coverage of 06-03-01's isolation row, using only `publish_queue.py`+`tiktok_publish.py` since `instagram_publish.py` doesn't exist until Plan 06-04) and `test_tiktok_scopes_are_minimal` (06-03-02's scope-minimization row for this platform).

## Deviations from Plan

None — plan executed exactly as written. All `<behavior>`/`<action>` blocks in Tasks 1-3 were implemented as specified; function signatures, constants, and endpoint URLs match 06-RESEARCH.md's patterns verbatim.

## Issues Encountered

None.

## User Setup Required

None for this plan specifically — PUB-06's `user_setup` block (TikTok Developer Portal app registration, redirect URI registration, Content Posting API audit filing) is a runbook item for whenever the user is ready to actually exercise `run_tiktok_oauth_consent` against a real TikTok app; it does not block this plan's code, which is fully testable against fakes (06-RESEARCH.md Environment Availability: "code can still be written and unit-tested against fakes in the meantime").

## Next Phase Readiness

`scripts/tiktok_publish.py` is a fully importable, fully-tested module capable of publishing one queued clip to TikTok end-to-end (given real credentials), safely dry-run by default, with D-05's SELF_ONLY detection and crash-safe reconciliation. Plan 06-04 (Instagram, disjoint file `scripts/instagram_publish.py`) and Plan 06-05 (TikTok `kill_item` + CLI wrapper, extending this module) can both build on top of this without touching each other's or YouTube's files.

---
*Phase: 06-tiktok-instagram-auto-publish*
*Completed: 2026-07-10*

## Self-Check: PASSED

- FOUND: scripts/tiktok_publish.py
- FOUND: tests/test_tiktok_publish.py
- FOUND: .planning/phases/06-tiktok-instagram-auto-publish/06-03-SUMMARY.md
- FOUND commit: 77dae7a, 0a78ecd, 4cf53a3, dd28962, ddb766d, 9e20548
