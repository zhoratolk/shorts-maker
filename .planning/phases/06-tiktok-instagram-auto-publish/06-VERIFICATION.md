---
phase: 06-tiktok-instagram-auto-publish
verified: 2026-07-10T16:36:35Z
status: gaps_found
score: 10/11 must-haves verified
behavior_unverified: 0
overrides_applied: 0
gaps:
  - truth: "TikTok's SELF_ONLY/gated safety signal (D-05) is preserved and surfaced on the crash-recovery (reconcile_uploading) path, not just the primary upload_and_publish path"
    status: failed
    reason: "check_tiktok_publish_gate's result (privacy_level/is_still_gated) is only ever used transiently inside upload_and_publish (tiktok_publish.py:507-584) to pick the notification text (_self_only_notification_text vs _success_notification_text). It is never persisted onto the queue entry - enqueue() has no field for it, and neither upload_and_publish nor reconcile_uploading writes it to disk. If a --check process crashes/times out after init_direct_post persists publish_id (write-ahead #2) but before the poll loop in upload_and_publish returns, the entry is left UPLOADING. The next --check's reconcile_all_uploading -> reconcile_uploading (tiktok_publish.py:643-684) polls fetch_post_status directly and, on PUBLISH_COMPLETE, sets entry['status']=PUBLISHED - with no call to append_notification anywhere in reconcile_uploading/reconcile_all_uploading, and no privacy_level/is_still_gated field ever written to the entry. The operator has no way - now, later via --list, or by inspecting the queue file - to learn that a PUBLISHED entry recovered this way might still be SELF_ONLY (private). This is exactly the trap D-05 and docs/publish-queue.md section 6 describe TikTok's API as setting (a call that succeeds even though nothing went public); the whole reason for calling check_tiktok_publish_gate up front is to prevent an operator from being misled about this, and the crash-recovery path silently reintroduces that blind spot. Independently confirmed by reading upload_and_publish (tiktok_publish.py:507-584) and reconcile_uploading (tiktok_publish.py:643-684) directly - this VERIFICATION agrees with 06-REVIEW.md's CR-01 finding. Also confirmed the gap is untested: tests/test_tiktok_publish.py:705-720 (test_idempotent_retry_no_duplicate_init_on_reconcile) only asserts entry['status']==PUBLISHED and that TIKTOK_INIT_URL was not re-called on reconcile - it asserts nothing about notification or privacy-signal persistence, so this gap was never caught by the existing test suite (241/241 tests pass, none of them exercise this)."
    artifacts:
      - path: "scripts/tiktok_publish.py"
        issue: "upload_and_publish (lines 507-584) computes privacy_level/is_still_gated via check_tiktok_publish_gate but never persists it onto entry before the poll loop starts; reconcile_uploading (lines 643-684) has no notifications_path parameter and never calls append_notification on PUBLISH_COMPLETE, and has no access to the original gate result to re-derive it"
    missing:
      - "Persist entry['privacy_level_achieved'] (or equivalent field) onto the queue entry in the same write-ahead pass that persists entry['publish_id'] inside upload_and_publish, so the signal survives a crash"
      - "Thread a notifications_path parameter through reconcile_uploading/reconcile_all_uploading (mirroring how credentials_factory is already threaded) and call append_notification with the SELF_ONLY-specific text (_self_only_notification_text) when a reconcile-adopted PUBLISH_COMPLETE entry's persisted privacy signal indicates it is still gated, or the normal success text otherwise"
      - "A regression test proving reconcile_uploading notifies (or otherwise durably records) the SELF_ONLY state when adopting a PUBLISH_COMPLETE entry whose original creator_info/query gate result was SELF_ONLY, so this exact path can never silently regress again"
---

# Phase 6: TikTok & Instagram Auto-Publish Verification Report

**Phase Goal:** The same scheduled auto-publish flow extends to TikTok and Instagram Reels once each platform's app-review/audit gate is cleared
**Verified:** 2026-07-10T16:36:35Z
**Status:** gaps_found
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | TikTok: `publish.tiktok_enabled=False` (default) makes `upload_and_publish` do zero HTTP calls and zero credential loads (PUB-03 parity) | ✓ VERIFIED | `tiktok_publish.py:538-539` — literal first statement, before `credentials_factory()`. `tests/test_tiktok_publish.py:650` (`test_dry_run_default_no_upload`), `:937` (`test_check_dry_run_makes_zero_credential_calls`) pass. |
| 2 | TikTok: a queued clip's caption is sent via chunked `FILE_UPLOAD` Content Posting API, with `privacy_level` sourced from `creator_info/query` (never hardcoded `PUBLIC_TO_EVERYONE`) | ✓ VERIFIED | `check_tiktok_publish_gate` (`tiktok_publish.py:485-501`) called before `build_direct_post_body`/`init_direct_post` in `upload_and_publish` (`:547-560`); `upload_video_chunks` (`:442-467`) uses `Content-Range` PUT covering the whole file. Read directly, plus `tests/test_tiktok_publish.py:523-542` (gate tests) and chunked-upload tests pass. |
| 3 | TikTok: the SELF_ONLY pre-audit trap (D-05) is detected and chat-notified on the **primary** upload path | ✓ VERIFIED | `_upload_one` (`tiktok_publish.py:604-637`) branches on `result.get("is_still_gated")` and appends `_self_only_notification_text` distinct from the normal success text. Code read directly; consistent with 06-CONTEXT.md D-05. |
| 4 | TikTok: the SELF_ONLY/gated safety signal (D-05) is preserved and surfaced on the **crash-recovery** (`reconcile_uploading`) path too, not just the primary path | ✗ FAILED | See `gaps` in frontmatter (matches 06-REVIEW.md CR-01, independently confirmed by direct code read — see "CR-01 independent confirmation" section below). |
| 5 | TikTok: killing a not-yet-uploaded entry is local-only (no API call); killing an already-PUBLISHED entry raises `RuntimeError` rather than silently no-oping (Pitfall 4) | ✓ VERIFIED | `kill_item` (`tiktok_publish.py:211-248`). `tests/test_tiktok_publish.py` kill-item tests pass. |
| 6 | Instagram: `publish.instagram_enabled=False` (default) makes `upload_and_publish` do zero HTTP calls and zero credential loads (PUB-03 parity) | ✓ VERIFIED | `instagram_publish.py:659-660` — literal first statement. `tests/test_instagram_publish.py:743` (`test_dry_run_default_no_upload`), `:1126` (`test_check_dry_run_makes_zero_credential_calls`) pass. |
| 7 | Instagram: a queued clip is uploaded via the resumable-upload flow (local file POSTed to `rupload.facebook.com`, never a public `video_url`) and published as a REELS item; no TikTok-style pre-publish gate — attempts real publish directly, fails closed with actionable `InstagramAccessError` only on a Meta-reported permission/access-tier error | ✓ VERIFIED | `create_resumable_container`/`upload_local_video`/`publish_container` (`instagram_publish.py:550-611`) route through `_check_meta_permission_error` (`:503-544`); `upload_and_publish` (`:617-694`) calls `create_resumable_container` with no prior gating call, matching the user's explicit build-both-scenarios decision (06-CONTEXT.md, RESEARCH.md Open Question 1). |
| 8 | Instagram: killing a not-yet-uploaded entry is local-only; killing an already-PUBLISHED entry raises `RuntimeError` (Pitfall 4) | ✓ VERIFIED | `kill_item` (`instagram_publish.py:259-...`, mirrors TikTok's shape). Kill-item tests pass. |
| 9 | Both platforms: a crash between write-ahead persist and a terminal status is reconcilable on the next check **without a duplicate init/container-create call** | ✓ VERIFIED | TikTok `reconcile_uploading` (`:643-684`) and Instagram `reconcile_uploading` (`:748-801`) both poll status using the persisted `publish_id`/`container_id` rather than blindly re-calling init/create. `test_idempotent_retry_no_duplicate_init_on_reconcile` (TikTok) and Instagram's equivalent pass — but note this narrower "no duplicate call" property is distinct from, and does not cover, Truth 4's "signal preserved" property, which is what actually fails. |
| 10 | Cross-platform isolation (Success Criterion 3): pausing/killing one platform's queue entry never touches another platform's queue file on disk | ✓ VERIFIED | `test_isolation_pause_and_kill_tiktok_never_touches_instagram_or_youtube_queue` and `test_isolation_pause_and_kill_instagram_never_touches_tiktok_or_youtube_queue` — read in full; both construct real tmp-dir manifests for all three platforms, exercise `pause_item`/`kill_item` against only the platform-under-test's in-memory queue object, save only that queue, then assert the other two files are byte-for-byte unchanged on disk. Ran both explicitly: **PASSED**. This is genuine structural proof, not a name-only check. |
| 11 | Scope minimization (V4): `TIKTOK_SCOPES`/`INSTAGRAM_SCOPES` and the OAuth authorize URLs built from them request only the documented minimal scopes | ✓ VERIFIED | `test_tiktok_scopes_are_minimal`, `test_tiktok_authorize_url_scope_param_is_exact_no_broader_scope`, and Instagram equivalents — parse the URL's `scope` query param via `urllib.parse` and assert exact equality, not substring match. Ran, passed. |

**Score:** 10/11 truths verified (0 present-but-behavior-unverified)

### CR-01 independent confirmation (requested specifically)

Read `scripts/tiktok_publish.py`'s `upload_and_publish` (lines 507-584) and `reconcile_uploading` (lines 643-684) directly, independent of 06-REVIEW.md's narrative. Confirmed accurate:

- `upload_and_publish` calls `check_tiktok_publish_gate` (line 547) and uses its `(privacy_level, is_still_gated)` result only to (a) build the `video/init` body's `privacy_level` field, and (b) as the return value's `is_still_gated` key, which `_upload_one` (the caller) uses to pick between `_self_only_notification_text` and `_success_notification_text`. Nothing in `upload_and_publish` writes this result onto `entry` — the two `save_queue` write-ahead calls at lines 545 and 564 persist `status`/`updated_at` and `publish_id` respectively, never a privacy/gated field.
- `reconcile_uploading` (called only from `reconcile_all_uploading`, which runs unconditionally at the top of every `--check` before `select_next_due`) has no `check_tiktok_publish_gate` call and no `notifications_path` parameter. On `status == "PUBLISH_COMPLETE"` (line 674-677) it sets `entry["status"] = PUBLISHED` and persists `video_share_url`/`updated_at` — no notification, no privacy signal, no way to recover after the fact whether this publish was still SELF_ONLY.

**Assessment of effect on Success Criterion 1:** This is a genuine gap in the safety mechanism, not a narrower edge case that can be waved off. Reasoning:
1. SC1's literal wording is "following the same dry-run-default/pause/**idempotency** safety mechanism as YouTube" — `reconcile_uploading` **is** the idempotency mechanism (it is what makes a crash-mid-poll recoverable without a duplicate `video/init` call). The gap is inside that exact mechanism, not adjacent to it.
2. D-05 (06-CONTEXT.md) is an explicit, named requirement of this phase specifically because TikTok's API returns success even when nothing went public — the whole point of `check_tiktok_publish_gate` existing is to prevent the operator from being misled about this. A code path that reaches `PUBLISHED` status without ever recording whether it was actually public reintroduces precisely the trap D-05 was written to close.
3. It is not a hypothetical: `reconcile_all_uploading` runs on every single `--check` invocation unconditionally (line 797, before the `tiktok_enabled` gate is even checked for new items), so any operator running the periodic Task Scheduler check while pre-audit (SELF_ONLY) and hitting a crash/timeout mid-poll (network hiccup, process killed, laptop sleep) will hit this path in practice, not in a contrived scenario.
4. No test in the 241-test suite exercises the notification/signal-persistence behavior of `reconcile_uploading`'s `PUBLISH_COMPLETE` branch — `test_idempotent_retry_no_duplicate_init_on_reconcile` only proves "no duplicate `video/init` call," a different and narrower property.

Conclusion: this constitutes a **BLOCKER**-level gap in Success Criterion 1 as literally worded, not merely a narrower robustness nice-to-have. It is captured as a structured gap above.

### Success Criterion 3 isolation — specific confirmation (requested)

Read the full bodies of both isolation tests (not just their names):

- `tests/test_tiktok_publish.py:172-218` (`test_isolation_pause_and_kill_tiktok_never_touches_instagram_or_youtube_queue`) — creates three separate `tmp_path` files (`queue.json` via `scripts.publish_queue`, `instagram_queue.json` via `scripts.instagram_publish`, `tiktok_queue.json` via `scripts.tiktok_publish`), enqueues into all three, snapshots the YouTube and Instagram files' raw bytes, then calls `pause_item`/`kill_item` **only** against the in-memory TikTok queue object and saves **only** that queue back to disk. It then re-reads the YouTube and Instagram files from disk and asserts byte-for-byte equality against the pre-operation snapshot.
- `tests/test_instagram_publish.py:177-223` is the exact mirror for Instagram (asserting YouTube's and TikTok's files are unchanged after an Instagram-only pause/kill).

Both were executed directly (not just enumerated): **both PASSED**. This is genuine structural evidence — it proves the actual `load_queue`/`save_queue`/`pause_item`/`kill_item` functions in each module never open, read, or write either sibling file, because the test would fail on a real byte mismatch if they did. This is not a name-only or convention-only check.

**On WR-05 (config.py has no runtime check that the three queue paths are distinct):** Confirmed accurate by reading `scripts/config.py`'s `_validate` (lines 285-455+) — there is no check anywhere comparing `config.publish.queue_path`, `tiktok_queue_path`, and `instagram_queue_path` for distinctness. Assessed as an **orthogonal robustness concern, not a gap in Success Criterion 3 itself**: SC3 as literally worded ("each platform integration is isolated enough that...") is a claim about the *code's* structural isolation — which is real and proven (three independent modules, each with its own `load_queue`/`save_queue`, no shared mutable state, no cross-imports of queue-manipulating functions). WR-05's risk is a *configuration-authoring* mistake (an operator copy-pasting the `publish:` block in `config.yaml` and forgetting to change one path) that would undermine that isolation at the deployment layer, not evidence that the code itself fails to isolate the platforms. It is a real, worth-fixing gap (recommended fix already in 06-REVIEW.md WR-05), but it does not falsify SC3 as written and is not included as a failed truth. Recorded here as a WARNING for visibility.

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `requirements.txt` | `requests>=2.32` direct dependency, human-signed-off | ✓ VERIFIED | Line 16: `requests>=2.32`. 06-01-SUMMARY.md documents the human checkpoint. |
| `.gitignore` | 4 new credential filenames | ✓ VERIFIED | `tiktok_client_key.json`, `tiktok_token.json`, `instagram_client_secret.json`, `instagram_token.json` all present. |
| `scripts/config.py::PublishConfig` | 8 new tiktok_*/instagram_* fields, all default-False/safe | ✓ VERIFIED | Lines 207-218: `tiktok_enabled=False`, `tiktok_queue_path`, `tiktok_client_key_path`, `tiktok_token_path`, `instagram_enabled=False`, `instagram_queue_path`, `instagram_client_secret_path`, `instagram_token_path`. |
| `scripts/tiktok_publish.py` | Queue lifecycle, OAuth, HTTP layer, orchestration, kill_item, CLI | ✓ VERIFIED (substantive, wired) | 833 lines, all named functions from PLAN must_haves present and exercised by 241 passing tests. One behavioral gap (CR-01) inside the reconcile path — see gaps. |
| `scripts/instagram_publish.py` | Queue lifecycle, OAuth, HTTP layer, orchestration, kill_item, CLI | ✓ VERIFIED (substantive, wired) | Same shape as TikTok's module; all functions present and tested; no equivalent CR-01-style gap found (Instagram has no analogous D-05 safety property to lose). |
| `tests/test_tiktok_publish.py` | Full coverage incl. isolation/scope tests | ✓ VERIFIED | Present, 241/241 combined suite passes. |
| `tests/test_instagram_publish.py` | Full coverage incl. isolation/scope tests | ✓ VERIFIED | Present, passes. |
| `docs/publish-queue.md` | TikTok + Instagram operator sections | ✓ VERIFIED | Sections 6/7 present; Instagram section explicitly states "Attempt Standard Access first - do NOT file App Review preemptively," matching the user's decision verbatim rather than the pre-resolution "always needs review" assumption. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `upload_and_publish` (TikTok/Instagram) | `config.tiktok_enabled`/`config.instagram_enabled` | Literal first statement, before any credential load or HTTP call | ✓ WIRED | Confirmed by direct read at `tiktok_publish.py:538` and `instagram_publish.py:659`; zero-call dry-run tests pass. |
| `check_tiktok_publish_gate` | `init_direct_post`'s `privacy_level` + D-05 notification branch | Result flows into `build_direct_post_body` and `_upload_one`'s branch | ✓ WIRED (primary path only) | Confirmed on the happy path; **not** wired into `reconcile_uploading` — see Truth 4 / gap. |
| `entry['publish_id']` | `save_queue` | Persisted immediately after `init_direct_post`, before chunk PUT loop | ✓ WIRED | `tiktok_publish.py:562-564`; write-ahead order confirmed by `test_publish_id_persisted_before_chunk_upload`-style assertion at line 700-702. |
| `run_command --check` | `reconcile_all_uploading` → `select_next_due` | Reconcile-first ordering, mirrors `publish_queue.py` | ✓ WIRED | Confirmed at `tiktok_publish.py:792-812` and Instagram equivalent; `test_check_reconciles_before_selecting_and_uploads_at_most_one` passes. |
| Isolation | 3 separate queue files, 3 separate modules | No shared mutable state or cross-module queue writes | ✓ WIRED | Proven by executed isolation tests (see above), not just by file-naming convention. |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|--------------|--------|----------|
| PUB-06 | 06-01, 06-02, 06-03, 06-05, 06-07 | TikTok Content Posting API integration, gated sub-phase | ✗ BLOCKED | Core integration (queue, OAuth, chunked upload, dry-run, kill, isolation) is real and tested, but the D-05 SELF_ONLY safety guarantee — a requirement explicitly named for this platform — does not hold on the crash-recovery path (CR-01, Truth 4). REQUIREMENTS.md currently marks this `[x]`/"Complete"; this verification finds that premature pending the gap closure. |
| PUB-07 | 06-01, 06-02, 06-04, 06-06, 06-07 | Instagram Graph API Reels integration, gated sub-phase | ✓ SATISFIED | Full integration built and tested; attempt-then-fail-closed design correctly implements the user's Standard-Access-first decision; no analogous safety-signal-loss gap found (Instagram has no D-05-equivalent property). |

No orphaned requirements: both PUB-06 and PUB-07 are declared in plan frontmatter and covered by REQUIREMENTS.md's Phase 6 row.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `scripts/tiktok_publish.py` | 643-684 | `reconcile_uploading` reaches a terminal `PUBLISHED` state with no `append_notification` call and no persisted privacy signal | 🛑 Blocker | CR-01 — see gaps. Undermines D-05's core safety guarantee on the crash-recovery path. |
| `scripts/config.py` | 285-455 (`_validate`) | No check that `publish.queue_path`/`tiktok_queue_path`/`instagram_queue_path` are distinct | ⚠️ Warning | WR-05 (06-REVIEW.md) — orthogonal to SC3 as coded, but a config typo could silently defeat the isolation the code otherwise guarantees. Recommend fixing but not blocking. |
| `scripts/instagram_publish.py` | 588-596 (`poll_container_status`) | Skips `_check_meta_permission_error` unlike the module's other 3 HTTP calls | ⚠️ Warning | WR-01 (06-REVIEW.md) — a token/access-tier problem surfacing during polling shows a generic `HTTPError` instead of the actionable `InstagramAccessError`. Not a required must-have, doesn't block SC2. |
| `scripts/tiktok_publish.py` | 285-291 (`load_credentials` refresh) | Overwrites the whole token file with the refresh response instead of merging | ⚠️ Warning | WR-02 — could lose `refresh_token` if TikTok ever omits it from a refresh response. Untested either way; not a required must-have. |
| `scripts/tiktok_publish.py` | 580, 676 | `video_share_url` assigned TikTok's array-typed `publicaly_available_post_id` verbatim (list, not string) | ⚠️ Warning | WR-03 — future consumers of this field would get `["url"]` instead of `"url"`. Not a required must-have. |
| `scripts/instagram_publish.py` | 833, 905-951 | `--ig-user-id` not validated before a live `--now`/`--check` publish attempt | ⚠️ Warning | WR-04 — omission produces a confusing Graph API 404/error (`.../None/media`) instead of a clear message. Not a required must-have. |
| Both modules | OAuth `state` param generation | Non-cryptographic `random.choices` source; `state` never validated on redirect return | ⚠️ Warning | WR-06 — decorative CSRF nonce. Exploitability limited by 127.0.0.1-only binding (tested/enforced). Not a required must-have. |
| `docs/publish-queue.md` | 65-83 | TikTok/Instagram sibling Task Scheduler entries share the exact same `/st 09:00` anchor as YouTube's | ⚠️ Warning | WR-07 — concurrent unlocked appends to the shared `notifications.log`. Not a required must-have. |

No `TBD`/`FIXME`/`XXX` debt markers found in any phase-6-modified file.

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full phase-6 test suite passes | `pytest tests/test_tiktok_publish.py tests/test_instagram_publish.py tests/test_config.py tests/test_publish_queue.py -q` | `241 passed, 1 warning in 3.59s` | ✓ PASS |
| TikTok isolation test (named, single) | `pytest tests/test_tiktok_publish.py::test_isolation_pause_and_kill_tiktok_never_touches_instagram_or_youtube_queue -v` | `1 passed` | ✓ PASS |
| Instagram isolation test (named, single) | `pytest tests/test_instagram_publish.py::test_isolation_pause_and_kill_instagram_never_touches_tiktok_or_youtube_queue -v` | `1 passed` | ✓ PASS |

No live TikTok/Instagram API calls were made (by design — both platforms' real credentials/audits are external, human-only, not-yet-performed steps per D-01/D-04; `docs/publish-queue.md`'s "Instagram permission-error heuristic" section is honestly marked "Status: not yet performed," which is expected at this stage, not a gap).

### Human Verification Required

None — the CR-01 finding is a concrete, code-confirmed defect (not an ambiguous/subjective item), so it is routed as a structured gap rather than a human-verification item. Live-API behavior against real TikTok/Instagram credentials remains genuinely unverifiable until the user files both audits (external, out of this phase's control per D-04) — this is expected and already documented honestly in `docs/publish-queue.md`, not a blocking item for this verification.

### Gaps Summary

One Blocker-level gap: TikTok's `reconcile_uploading` (the module's idempotency/crash-recovery mechanism) can mark a queue entry `PUBLISHED` after a crash/timeout mid-poll without ever persisting or notifying whether the account was still `SELF_ONLY` at gate-check time. This was independently confirmed by direct code inspection (not merely trusting 06-REVIEW.md's CR-01) and assessed as a genuine failure of Success Criterion 1's "idempotency safety mechanism" clause — not a narrow edge case — because `reconcile_all_uploading` runs unconditionally on every `--check`, and the SELF_ONLY-misleading-success case (an unaudited TikTok account, the expected state for this entire phase until the audit clears) is exactly the scenario this crash-recovery path exists to cover. No existing test exercises the notification/signal-persistence behavior on this path.

Seven Warning-level findings (WR-01 through WR-07, from 06-REVIEW.md, independently spot-checked) are real but narrower robustness/consistency issues that do not block any Success Criterion as literally worded; they are listed for visibility and should be swept into a closure plan alongside CR-01.

Success Criterion 3 (platform isolation) is genuinely proven at the code level by two substantive, executed isolation tests (not just test-name conventions) — WR-05 (no config-level distinct-path enforcement) is a real but orthogonal robustness gap, not a falsification of SC3 as coded.

REQUIREMENTS.md and ROADMAP.md currently mark PUB-06/Phase 6 as complete — this verification finds that premature: PUB-06 should move back to a gaps-closure cycle before the phase is considered done. PUB-07 has no equivalent finding and stands as satisfied.

---

_Verified: 2026-07-10T16:36:35Z_
_Verifier: Claude (gsd-verifier)_
