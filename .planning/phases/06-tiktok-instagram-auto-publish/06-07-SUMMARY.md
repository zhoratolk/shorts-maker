---
phase: 06-tiktok-instagram-auto-publish
plan: 07
subsystem: testing
tags: [publish, tiktok, instagram, isolation, oauth-scopes, docs]

# Dependency graph
requires:
  - phase: 06-05
    provides: "scripts/tiktok_publish.py: complete kill_item + CLI wrapper"
  - phase: 06-06
    provides: "scripts/instagram_publish.py: complete kill_item + CLI wrapper"
provides:
  - "Automated proof (not just file-naming convention) that pause_item/kill_item on any one platform's in-memory queue object never touches the other two platforms' manifest files on disk - Success Criterion 3"
  - "Automated proof that TIKTOK_SCOPES/INSTAGRAM_SCOPES and their OAuth authorize-URL scope query params are exactly the documented minimal scopes, never broader (V4)"
  - "docs/publish-queue.md sections 6/7: complete TikTok/Instagram operator runbook (app registration, one-time consent, opt-in, going-live caution, SELF_ONLY notification text, Content Posting API audit pointer)"
  - "docs/publish-queue.md: Instagram's attempt-Standard-Access-first instruction stated imperatively and attributed to the user's explicit decision, so instagram_publish.py is never retrofitted with a TikTok-style pre-publish gate"
  - "docs/publish-queue.md: 'Instagram permission-error heuristic (unverified assumption)' section flagging _check_meta_permission_error as unconfirmed against a real Meta response"
  - "docs/publish-queue.md section 1 extended with two sibling Task Scheduler entries (shorts-maker-publish-tiktok, shorts-maker-publish-instagram)"
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Isolation tests construct real tmp-dir queue files for all three platforms, call pause_item AND kill_item against only the platform-under-test's in-memory queue object, save only that queue back, then assert the other two files' bytes are unchanged on disk - proves non-interference structurally rather than by file-naming convention alone"
    - "Scope-minimization tests parse the OAuth authorize URL's scope query param via urllib.parse and assert exact string equality against the comma-joined SCOPES constant, rather than a substring check, so an accidentally-appended third scope would fail the test"

key-files:
  created: []
  modified:
    - tests/test_tiktok_publish.py
    - tests/test_instagram_publish.py
    - docs/publish-queue.md

key-decisions:
  - "Isolation tests are additive to the existing pause-only/YouTube-only isolation tests from Plan 06-03/06-04 (not a replacement) - the new tests cover all three files plus both pause_item and kill_item, matching this plan's stricter must_haves wording, while the earlier tests remain valid narrower coverage"
  - "Scope tests assert exact equality on the parsed scope query param (urllib.parse.parse_qs) rather than a substring check, giving a stronger guarantee than the plan's literal 'contains ... and no other scope substring' wording while still satisfying it"
  - "TikTok Task Scheduler entry documented as a sibling to shorts-maker-publish (not folded in) per the plan's explicit schtasks /tr one-command-per-task constraint and the isolation design extending to the OS scheduling layer"

requirements-completed: [PUB-06, PUB-07]

coverage:
  - id: D1
    description: "Isolation test proving killing/pausing a TikTok queue entry never modifies instagram_queue.json or queue.json (YouTube), and vice versa for Instagram, via real tmp-dir files and byte-for-byte comparison"
    requirement: "PUB-06"
    verification:
      - kind: unit
        ref: "tests/test_tiktok_publish.py#test_isolation_pause_and_kill_tiktok_never_touches_instagram_or_youtube_queue"
        status: pass
      - kind: unit
        ref: "tests/test_instagram_publish.py#test_isolation_pause_and_kill_instagram_never_touches_tiktok_or_youtube_queue"
        status: pass
    human_judgment: false
  - id: D2
    description: "Scope-minimization test proving TIKTOK_SCOPES/INSTAGRAM_SCOPES and their authorize-URL scope query params are exactly the documented minimal scopes, never broader (V4)"
    requirement: "PUB-07"
    verification:
      - kind: unit
        ref: "tests/test_tiktok_publish.py#test_tiktok_authorize_url_scope_param_is_exact_no_broader_scope"
        status: pass
      - kind: unit
        ref: "tests/test_instagram_publish.py#test_instagram_authorize_url_scope_param_is_exact_no_broader_scope"
        status: pass
    human_judgment: false
  - id: D3
    description: "docs/publish-queue.md gains complete TikTok and Instagram operator sections (app registration, one-time consent, opt-in, going-live caution, SELF_ONLY handling, Task Scheduler sibling tasks), plus the Instagram Standard-vs-Advanced-Access attempt-first instruction stated imperatively and the unverified-permission-heuristic flag"
    requirement: "PUB-06"
    verification:
      - kind: other
        ref: "grep -c 'InstagramAccessError|Advanced Access' docs/publish-queue.md (returns 4, plan's automated verify step)"
        status: pass
    human_judgment: false

duration: 20min
completed: 2026-07-10
status: complete
---

# Phase 6 Plan 7: Isolation/Scope Tests + Operator Runbook Summary

**Byte-for-byte isolation tests prove TikTok/Instagram/YouTube queue manifests structurally can never cross-contaminate on kill/pause, exact-match scope tests lock the OAuth authorize URLs to their documented minimal scopes, and docs/publish-queue.md gains a complete TikTok/Instagram operator runbook including the user's imperative "attempt Standard Access first, never file App Review preemptively" instruction for Instagram.**

## Performance

- **Duration:** ~20 min
- **Started:** 2026-07-10T16:05:00Z
- **Completed:** 2026-07-10T16:25:00Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- Added `test_isolation_pause_and_kill_tiktok_never_touches_instagram_or_youtube_queue` and its Instagram mirror: each constructs real tmp-dir manifests for all three platforms, calls `pause_item` AND `kill_item` against only the platform-under-test's in-memory queue object, saves only that queue back, then re-reads the other two files from disk and asserts byte-for-byte equality against a pre-captured snapshot - a structural proof of Success Criterion 3, not a file-naming-convention assumption
- Added `test_tiktok_authorize_url_scope_param_is_exact_no_broader_scope` and its Instagram mirror: parses the OAuth authorize URL's `scope` query param via `urllib.parse.parse_qs` and asserts it equals exactly `"video.publish,video.upload"` / `"instagram_business_basic,instagram_business_content_publish"` - stronger than a substring check, catching any accidental future scope addition
- Extended `docs/publish-queue.md` with numbered sections 6 (TikTok) and 7 (Instagram): app registration, exact scopes/redirect URIs, one-time interactive consent one-liners (`python -c "from scripts.tiktok_publish import run_tiktok_oauth_consent; ..."` and the Instagram equivalent), `tiktok_enabled`/`instagram_enabled` opt-in with the same "⚠️ going live is a one-way, public action" caution as YouTube's section 2
- TikTok section documents the SELF_ONLY pre-audit trap with the exact notification text emitted by `_self_only_notification_text` and a pointer to filing the separate Content Posting API audit (distinct from base app approval), explicitly declining to promise a timeline (06-RESEARCH.md Assumption A1 has no official SLA)
- Instagram section's "Attempt Standard Access first - do NOT file App Review preemptively" subsection is written as a 3-step imperative instruction, explicitly attributed to the user's decision (06-CONTEXT.md, resolving 06-RESEARCH.md Open Question 1), with an explicit closing sentence warning against retrofitting a TikTok-style pre-publish gate onto `instagram_publish.py`
- Added the unnumbered "Instagram permission-error heuristic (unverified assumption)" section mirroring "Kill-path verification"'s tone/structure exactly ("Status: not yet performed" pending a real Meta error response)
- Extended section 1 with two sibling Task Scheduler entries (`shorts-maker-publish-tiktok`, `shorts-maker-publish-instagram`) rather than folding into the existing `shorts-maker-publish` task, per `schtasks /tr`'s one-command-per-task limit and to preserve the isolation design at the OS scheduling layer
- Updated the closing footer with a new Phase 6 line, Phase 3's existing line untouched
- Full combined `tests/test_tiktok_publish.py`/`tests/test_instagram_publish.py` suite: 125 passed; full project suite: 552 passed

## Task Commits

Each task was committed atomically:

1. **Task 1: Isolation and scope-minimization tests** - `0bbbf91` (test)
2. **Task 2: Operator documentation for TikTok and Instagram** - `b8b72fa` (docs)

**Plan metadata:** (this commit)

## Files Created/Modified
- `tests/test_tiktok_publish.py` - Added `test_isolation_pause_and_kill_tiktok_never_touches_instagram_or_youtube_queue` and `test_tiktok_authorize_url_scope_param_is_exact_no_broader_scope`; added `import urllib.parse`
- `tests/test_instagram_publish.py` - Added `test_isolation_pause_and_kill_instagram_never_touches_tiktok_or_youtube_queue` and `test_instagram_authorize_url_scope_param_is_exact_no_broader_scope`; added `import urllib.parse`
- `docs/publish-queue.md` - Added sections 6 (TikTok setup/going-live), 7 (Instagram setup/going-live), "Instagram permission-error heuristic (unverified assumption)"; extended section 1 with two sibling Task Scheduler entries; extended the closing footer with a Phase 6 line

## Decisions Made
- The new isolation tests are additive to the narrower pause-only/YouTube-only isolation tests already present from Plans 06-03/06-04 (not a replacement) - both remain in the suite, giving overlapping-but-not-redundant coverage
- Scope tests assert exact equality on the parsed `scope` query param rather than only a substring check, exceeding the plan's literal wording ("no other scope substring") with a stronger guarantee
- TikTok's new Task Scheduler entry is documented as a sibling task (own `/tn`), not folded into the existing `shorts-maker-publish` task, since `schtasks /tr` accepts exactly one command per task and folding would also break the isolation design at the OS scheduling layer

## Deviations from Plan

None - plan executed exactly as written. Both isolation tests cover all three platforms' files with both `pause_item` and `kill_item` as specified; both scope tests assert exact scope strings; docs sections 6/7 and the unverified-heuristic section match the plan's required content, tone, and imperative wording for the Instagram attempt-first instruction; section 1's two new sibling Task Scheduler entries and the footer update were added exactly as specified.

## Issues Encountered
None.

## User Setup Required

None from this plan directly - this plan is documentation + tests only, no new code paths requiring configuration. The runbook this plan wrote (docs/publish-queue.md sections 6/7) documents the human-only external steps (TikTok Developer Portal app registration, Meta App creation, one-time OAuth consent, `tiktok_enabled`/`instagram_enabled` opt-in, Task Scheduler entries) that an operator must still perform manually before either platform goes live - these were already known-required from Plans 06-01 through 06-06's `user_setup` sections and are now consolidated into the single operator-facing doc.

## Next Phase Readiness

- Phase 6 (TikTok/Instagram Auto-Publish) is complete: both platforms have full queue lifecycle, OAuth, upload/publish orchestration, kill_item with each platform's own Pitfall-4 divergence, CLI wrappers, isolation guarantees proven by test, and a complete operator runbook
- No outstanding blockers introduced by this plan
- Carried-forward blocker (unchanged by this plan, tracked in STATE.md): the Instagram permission-error heuristic (`_check_meta_permission_error`) remains unverified against a real Meta API response - flagged in docs/publish-queue.md for empirical confirmation once real Instagram credentials exist, same pattern as Phase 3's kill-path verification before its live test

---
*Phase: 06-tiktok-instagram-auto-publish*
*Completed: 2026-07-10*

## Self-Check: PASSED

- FOUND: tests/test_tiktok_publish.py
- FOUND: tests/test_instagram_publish.py
- FOUND: docs/publish-queue.md
- FOUND: .planning/phases/06-tiktok-instagram-auto-publish/06-07-SUMMARY.md
- FOUND: commit 0bbbf91 (test: Task 1 isolation + scope tests)
- FOUND: commit b8b72fa (docs: Task 2 operator documentation)
