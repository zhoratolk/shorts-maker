---
phase: 06-tiktok-instagram-auto-publish
plan: 04
subsystem: infra
tags: [requests, instagram-graph-api, oauth, resumable-upload, publish-queue]

# Dependency graph
requires:
  - phase: 06-01
    provides: "requests>=2.32 as a verified direct dependency"
  - phase: 06-02
    provides: "scripts/config.py::PublishConfig instagram_* fields (instagram_enabled, instagram_queue_path, instagram_client_secret_path, instagram_token_path)"
provides:
  - "scripts/instagram_publish.py: full queue lifecycle (load_queue/save_queue/enqueue/select_next_due/pause_item/resume_item) over its own manifest (work/_publish/instagram_queue.json)"
  - "Instagram OAuth: load_credentials (cache/refresh via ig_refresh_token) + run_instagram_oauth_consent (one-time interactive consent, port 8766, 127.0.0.1-only redirect listener)"
  - "Graph API resumable-upload HTTP layer: create_resumable_container/upload_local_video (rupload.facebook.com)/poll_container_status/publish_container"
  - "InstagramAccessError + _check_meta_permission_error: fail-closed permission/access-tier detection with NO pre-publish gating call (deliberate contrast with TikTok's creator_info/query design)"
  - "upload_and_publish orchestration (dry-run gate first, write-ahead persistence) + reconcile_uploading/reconcile_all_uploading crash recovery"
affects: [06-06 (Instagram CLI wrapper + pause/kill), 06-07 (STATE.md/docs notes for unverified live-API assumptions)]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Attempt-then-fail-closed design: real publish attempted directly via Standard Access, only a Meta-reported permission/access-tier error (403 or permission-flavored body) raises InstagramAccessError - no pre-publish gating call, unlike TikTok's creator_info/query"
    - "Own local copy of _build_redirect_server/_capture_oauth_redirect_code (not imported from scripts.tiktok_publish) - hand-rolled per platform per this project's established convention"

key-files:
  created:
    - scripts/instagram_publish.py
    - tests/test_instagram_publish.py
  modified: []

key-decisions:
  - "load_credentials treats a token as fresh (no refresh call) while under 24h old (REFRESH_AFTER_SECONDS), refreshing via GET graph.instagram.com/refresh_access_token once older - simplified from RESEARCH.md's fuller 'age>24h AND 60-day window has days left' wording since Instagram's actual hard requirement is only the 24h minimum age"
  - "_check_meta_permission_error checks status_code==403 OR permission-flavored substrings in the error body's message/type/code (case-insensitive); any other non-2xx (e.g. 500) falls through to a plain response.raise_for_status(), propagating as requests.HTTPError - documented in-code as a best-effort heuristic since 06-RESEARCH.md never captured a real Meta error response this session"
  - "Test module's grep-equivalent 'no pre-publish gating call' checks assert against instagram_publish's module namespace (function/attribute names, string URL constants) rather than raw source-text substring matching - a raw substring check false-positived on the module's own explanatory docstring prose contrasting this design with TikTok's creator_info/query"

requirements-completed: [PUB-07]

coverage:
  - id: D1
    description: "Dry-run default: instagram_enabled=False makes upload_and_publish a zero-HTTP-call, zero-credential-load no-op (PUB-03 parity)"
    requirement: "PUB-07"
    verification:
      - kind: unit
        ref: "tests/test_instagram_publish.py#test_dry_run_default_no_upload"
        status: pass
    human_judgment: false
  - id: D2
    description: "Queued clip uploaded via resumable-upload flow (local file POSTed to rupload.facebook.com, never a public video_url) and published as a REELS media item"
    requirement: "PUB-07"
    verification:
      - kind: unit
        ref: "tests/test_instagram_publish.py#test_upload_local_video_posts_bytes_to_rupload_not_graph"
        status: pass
      - kind: unit
        ref: "tests/test_instagram_publish.py#test_upload_and_publish_full_success_flow_persists_write_ahead"
        status: pass
    human_judgment: false
  - id: D3
    description: "No TikTok-style pre-publish gating check - attempts real publish directly, only a Meta-reported permission/access-tier error raises InstagramAccessError; non-permission errors propagate unchanged"
    requirement: "PUB-07"
    verification:
      - kind: unit
        ref: "tests/test_instagram_publish.py#test_upload_and_publish_no_pre_publish_gating_call"
        status: pass
      - kind: unit
        ref: "tests/test_instagram_publish.py#test_create_resumable_container_403_permission_error_raises_instagram_access_error"
        status: pass
      - kind: unit
        ref: "tests/test_instagram_publish.py#test_create_resumable_container_non_permission_500_propagates_as_http_error"
        status: pass
      - kind: unit
        ref: "tests/test_instagram_publish.py#test_no_pre_publish_gating_call_or_endpoint_exists_in_module"
        status: pass
    human_judgment: false
  - id: D4
    description: "A crash between write-ahead persist and a terminal container status is reconcilable on the next check without a duplicate container/publish call"
    requirement: "PUB-07"
    verification:
      - kind: unit
        ref: "tests/test_instagram_publish.py#test_reconcile_uploading_finished_completes_publish_no_duplicate_container_create"
        status: pass
      - kind: unit
        ref: "tests/test_instagram_publish.py#test_reconcile_uploading_no_container_id_resets_to_queued_without_api_call"
        status: pass
    human_judgment: false

duration: 6min
completed: 2026-07-10
status: complete
---

# Phase 6 Plan 4: Instagram Publish Core Summary

**Instagram Graph API Reels publishing core (queue, OAuth, resumable-upload HTTP layer, orchestration) that attempts Standard Access directly and only fails closed with an actionable InstagramAccessError on a real Meta permission rejection - deliberately no TikTok-style pre-publish gate.**

## Performance

- **Duration:** 6 min
- **Started:** 2026-07-10T11:36:03Z
- **Completed:** 2026-07-10T11:41:56Z
- **Tasks:** 3
- **Files modified:** 2 (both new)

## Accomplishments
- `scripts/instagram_publish.py` created: full queue lifecycle over its own manifest (`work/_publish/instagram_queue.json`), OAuth credential caching/refresh + one-time interactive consent flow (port 8766), Graph API resumable-upload HTTP layer, and dry-run-first orchestration with write-ahead crash recovery
- Implemented the user's explicit "attempt Standard Access first, fail closed only on a real Meta rejection" design: verified via both behavioral tests (first HTTP call is the real container-create POST, not a gating check) and a module-namespace grep-equivalent test confirming no `creator_info`/gating function exists anywhere
- 50 hand-written unit tests (`FakeSession`/`FakeResponse` doubles, no `unittest.mock`), all passing; full project suite (515 tests) green after the change

## Task Commits

Each task followed RED (failing test) -> GREEN (implementation) TDD commits:

1. **Task 1: Queue lifecycle + OAuth credential handling**
   - `29f46b3` test(06-04): add failing tests for instagram queue lifecycle + oauth
   - `d94af34` feat(06-04): instagram queue lifecycle + oauth credential handling
2. **Task 2: Instagram Graph API resumable-upload layer + fail-closed permission handling**
   - `f607990` test(06-04): add failing tests for instagram resumable-upload + fail-closed permission handling
   - `fdfa6e2` feat(06-04): instagram resumable-upload HTTP layer + fail-closed permission handling
3. **Task 3: Orchestration (dry-run gate, attempt-then-fail-closed, write-ahead) and reconciliation**
   - `2b8dfd7` test(06-04): add failing tests for instagram orchestration + reconciliation
   - `1603f3b` feat(06-04): instagram orchestration (dry-run, attempt-then-fail-closed, write-ahead) + reconciliation

**Plan metadata:** (this commit, docs: complete plan)

## Files Created/Modified
- `scripts/instagram_publish.py` - New module: queue lifecycle, OAuth (load_credentials/run_instagram_oauth_consent), Graph API resumable-upload HTTP layer (create_resumable_container/upload_local_video/poll_container_status/publish_container), InstagramAccessError/_check_meta_permission_error, upload_and_publish orchestration, reconcile_uploading/reconcile_all_uploading
- `tests/test_instagram_publish.py` - New test file: 50 hand-written unit tests covering every behavior above via FakeSession/FakeResponse doubles

## Decisions Made
- `load_credentials`'s refresh trigger is simplified to a single 24h-age threshold (`REFRESH_AFTER_SECONDS`) rather than RESEARCH.md's fuller "older than 24h AND 60-day window has more than a few days left" phrasing - Instagram's actual hard API requirement is only the 24h minimum age before a refresh is accepted; the extra "days left" clause was framed there as periodic-refresh-cadence guidance, not a gate, so encoding it as a second condition would have added untestable complexity with no behavioral difference for this project's ~3h periodic-check cadence
- `_check_meta_permission_error`'s heuristic checks `status_code == 403` OR case-insensitive permission-flavored substrings (`"permission"`, `"advanced access"`, `"not authorized"`, `"app review"`, etc.) in the combined message/type/code fields; any other non-2xx response (e.g. a plain 500) falls through to `response.raise_for_status()`, propagating as `requests.HTTPError` unchanged - documented in-code as best-effort since no live Meta error response was captured during 06-RESEARCH.md's session
- The plan's grep-based "no pre-publish gating call" verification was additionally encoded as two permanent pytest tests, but implemented against the module's namespace (function names, string URL constants) rather than a raw source-text substring search - a naive substring check on `inspect.getsource()` false-positived against the module's own explanatory docstring prose (which legitimately names `creator_info`/`daily_slots_utc` to explain their deliberate absence)

## Deviations from Plan

None - plan executed exactly as written. The "Decisions Made" items above are implementation-detail refinements within the plan's explicit behavior spec, not scope deviations.

## Issues Encountered

Two of my own supplementary source-grep tests (checking for absence of pre-publish gating patterns and `daily_slots_utc` references) initially failed against my own explanatory docstring text, which legitimately mentions `creator_info`/`daily_slots_utc` to document why they are absent. Fixed by switching those two tests from raw `inspect.getsource()` substring checks to module-namespace inspection (`vars(instagram_publish)`, `hasattr`), which verifies the actual absence of gating functions/URL constants without tripping on prose. No production code was affected.

## User Setup Required

None for this plan specifically (this plan is code-only - queue/OAuth/HTTP-layer/orchestration logic). The plan's frontmatter documents the eventual `user_setup` runbook (Meta App creation, redirect URI registration, "attempt one real publish before filing App Review" guidance) for when Plan 06-06 wires this module's CLI and the user is ready to go live - not required to complete this plan's own success criteria.

## Next Phase Readiness

- `scripts/instagram_publish.py` is fully importable and fully tested, ready for Plan 06-06 to build the CLI wrapper (`--check`/`--now`/`--pause`/`--kill`/`--resume`/`--list`) and `kill_item` on top of it, mirroring `scripts/tiktok_publish.py`'s sibling CLI shape
- The `_check_meta_permission_error` heuristic remains unverified against a real Meta error response (06-RESEARCH.md's own caveat) - Plan 06-07 should add the STATE.md/docs note tracking this the same way Phase 3 tracked its kill-path live verification
- No `kill_item` exists yet for Instagram (deliberately out of scope per this plan's frontmatter `must_haves` - Plan 06-06's job)

---
*Phase: 06-tiktok-instagram-auto-publish*
*Completed: 2026-07-10*
