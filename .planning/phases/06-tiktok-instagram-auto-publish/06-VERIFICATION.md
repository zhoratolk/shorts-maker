---
phase: 06-tiktok-instagram-auto-publish
verified: 2026-07-10T20:15:00Z
status: passed
score: 11/11 must-haves verified
behavior_unverified: 0
overrides_applied: 0
re_verification:
  previous_status: gaps_found
  previous_score: 10/11
  gaps_closed:
    - "TikTok's SELF_ONLY/gated safety signal (D-05) is preserved and surfaced on the crash-recovery (reconcile_uploading) path too, not just the primary path (CR-01)"
  gaps_remaining: []
  regressions: []
---

# Phase 6: TikTok & Instagram Auto-Publish Verification Report

**Phase Goal:** The same scheduled auto-publish flow extends to TikTok and Instagram Reels once each platform's app-review/audit gate is cleared
**Verified:** 2026-07-10T20:15:00Z
**Status:** passed
**Re-verification:** Yes — after gap closure (previous pass: gaps_found, 2026-07-10T16:36:35Z, committed at `4c7d9e3`)

## Summary of Re-Verification

The prior VERIFICATION.md (superseded by this report; prior content preserved in git history at `4c7d9e3`) found one BLOCKER-level gap, CR-01: TikTok's crash-recovery path (`reconcile_uploading`) could mark a queue entry `PUBLISHED` without ever persisting or notifying whether the account was still `SELF_ONLY` (pre-audit/private) at gate-check time.

Fix commit `71a6131` ("fix(06): persist TikTok SELF_ONLY gate signal through crash-recovery, fix video_share_url list bug") was independently re-verified by reading the actual diff and current source (not the commit message), running the full test suite, and confirming the 3 new regression tests actually fail against the pre-fix code. All checks pass — CR-01 is genuinely closed, no new gap was introduced, and Success Criteria 1/2/3 are now all satisfied.

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | TikTok: `publish.tiktok_enabled=False` (default) makes `upload_and_publish` do zero HTTP calls and zero credential loads (PUB-03 parity) | ✓ VERIFIED (regression, unchanged) | `tiktok_publish.py:539-540` — literal first statement, before `credentials_factory()`. Unchanged by fix commit. `test_dry_run_default_no_upload`, `test_check_dry_run_makes_zero_credential_calls` pass. |
| 2 | TikTok: a queued clip's caption is sent via chunked `FILE_UPLOAD` Content Posting API, with `privacy_level` sourced from `creator_info/query` (never hardcoded `PUBLIC_TO_EVERYONE`) | ✓ VERIFIED (regression, unchanged) | `check_tiktok_publish_gate` (`:485-501`) still called before `build_direct_post_body`/`init_direct_post` in `upload_and_publish` (`:548-561`). Chunked-upload tests pass. |
| 3 | TikTok: the SELF_ONLY pre-audit trap (D-05) is detected and chat-notified on the **primary** upload path | ✓ VERIFIED (regression, unchanged) | `_upload_one` (`:615-652`) unchanged by the fix; still branches on `result.get("is_still_gated")`. |
| 4 | TikTok: the SELF_ONLY/gated safety signal (D-05) is preserved and surfaced on the **crash-recovery** (`reconcile_uploading`) path too, not just the primary path | ✓ VERIFIED (gap closed — full re-verification below) | `upload_and_publish` now persists `entry["privacy_level_achieved"] = privacy_level` (`tiktok_publish.py:564`) in the exact same statement block/`save_queue` call as `entry["publish_id"]` (`:563,566`), before the chunk-upload/poll loop (`:568-573`). `reconcile_uploading` (`:654-710`) now takes a `notifications_path` parameter and, on `PUBLISH_COMPLETE` (`:696-703`), calls `append_notification` with `_self_only_notification_text` when `entry.get("privacy_level_achieved") == "SELF_ONLY"`, else `_success_notification_text`. See detailed trace below. |
| 5 | TikTok: killing a not-yet-uploaded entry is local-only (no API call); killing an already-PUBLISHED entry raises `RuntimeError` rather than silently no-oping (Pitfall 4) | ✓ VERIFIED (regression, unchanged) | `kill_item` (`:211-248`) untouched by fix commit. Tests pass. |
| 6 | Instagram: `publish.instagram_enabled=False` (default) makes `upload_and_publish` do zero HTTP calls and zero credential loads (PUB-03 parity) | ✓ VERIFIED (regression, unchanged — file not touched by fix commit) | `instagram_publish.py` untouched by `71a6131` (diff only touches `scripts/tiktok_publish.py` and `tests/test_tiktok_publish.py`). Tests still pass. |
| 7 | Instagram: a queued clip is uploaded via the resumable-upload flow, published as a REELS item; fails closed with actionable `InstagramAccessError` only on a Meta permission/access-tier error | ✓ VERIFIED (regression, unchanged) | Unaffected by this fix commit; all Instagram tests still pass. |
| 8 | Instagram: killing a not-yet-uploaded entry is local-only; killing an already-PUBLISHED entry raises `RuntimeError` (Pitfall 4) | ✓ VERIFIED (regression, unchanged) | Unaffected; tests pass. |
| 9 | Both platforms: a crash between write-ahead persist and a terminal status is reconcilable on the next check **without a duplicate init/container-create call** | ✓ VERIFIED (regression + strengthened) | `test_idempotent_retry_no_duplicate_init_on_reconcile` still asserts no duplicate `TIKTOK_INIT_URL` call and now additionally asserts `entry["video_share_url"] == "share-1"` (string, not list — WR-03 fix). Passes. |
| 10 | Cross-platform isolation (Success Criterion 3): pausing/killing one platform's queue entry never touches another platform's queue file on disk | ✓ VERIFIED (regression, unchanged) | Isolation tests unaffected by this diff (neither `kill_item`/`pause_item` nor the queue-file-selection logic was touched). Both isolation tests re-run explicitly: **PASSED**. |
| 11 | Scope minimization (V4): `TIKTOK_SCOPES`/`INSTAGRAM_SCOPES` and OAuth authorize URLs request only documented minimal scopes | ✓ VERIFIED (regression, unchanged) | Unaffected by this diff; scope tests re-run: **PASSED**. |

**Score:** 11/11 truths verified (0 present-but-behavior-unverified)

### Truth 4 (CR-01) — detailed re-verification

Read `scripts/tiktok_publish.py`'s current `upload_and_publish` (lines 508-586), `reconcile_uploading` (lines 654-710), `reconcile_all_uploading` (lines 713-725), and `run_command`'s call site (lines 825-829) directly — independent of the fix commit's message and of 06-REVIEW.md's narrative.

**1. Write-ahead persistence order (upload_and_publish, lines 561-566):**
```python
data = init_direct_post(access_token, body, session)

entry["publish_id"] = data["publish_id"]
entry["privacy_level_achieved"] = privacy_level
entry["updated_at"] = datetime.now(timezone.utc).isoformat()
save_queue(queue, queue_path)

upload_video_chunks(data["upload_url"], entry["video_path"], chunk_size, session)  # poll loop follows
```
Confirmed: `privacy_level_achieved` is set in the identical statement block and persisted by the identical `save_queue` call as `publish_id`, strictly before `upload_video_chunks`/the poll loop (lines 568-573) that can crash or time out. A crash after this point leaves the entry `UPLOADING` on disk with `privacy_level_achieved` durably recorded — closing the exact blind spot CR-01 identified.

**2. reconcile_uploading notification wiring (lines 654-710):**
`reconcile_uploading` now accepts `notifications_path: str = DEFAULT_NOTIFICATIONS_PATH` as a parameter. On `status == "PUBLISH_COMPLETE"` (lines 696-703):
```python
entry["status"] = PUBLISHED
entry["video_share_url"] = _extract_share_url(status_data)
entry["updated_at"] = datetime.now(timezone.utc).isoformat()
if entry.get("privacy_level_achieved") == "SELF_ONLY":
    append_notification(_self_only_notification_text(entry), notifications_path)
else:
    append_notification(_success_notification_text(entry), notifications_path)
```
This is keyed directly off the field persisted in step 1, using `_self_only_notification_text`/`_success_notification_text` — the exact same two notification-text functions `_upload_one`'s primary path already used, so the crash-recovery path now surfaces an identical distinction rather than a parallel/divergent one.

**3. Threading through reconcile_all_uploading and run_command (no silent drop):**
- `reconcile_all_uploading` (lines 713-725) now takes `notifications_path: str = DEFAULT_NOTIFICATIONS_PATH` and passes it positionally into every `reconcile_uploading(queue, entry, credentials_factory, session, notifications_path)` call — not defaulted/dropped.
- `run_command`'s only call site (lines 825-829, inside the `--check` branch) explicitly passes `notifications_path=config.notifications_path`:
  ```python
  reconcile_all_uploading(
      queue, credentials_factory, session=session, notifications_path=config.notifications_path
  )
  ```
  Confirmed `config.notifications_path` is a real, populated field on `PublishConfig` (`scripts/config.py:204`, default `"work/_publish/notifications.log"`) — not a stray/unused kwarg. This is the only call site of `reconcile_all_uploading` in the module (grep-confirmed), so there is no second, unwired code path that would silently no-op this in the real CLI.

**4. Regression tests are real guards, not tautologies (independently confirmed by running them against pre-fix code):**
Checked out `scripts/tiktok_publish.py` at the pre-fix commit (`d411e92`, one commit before `71a6131`) while keeping the new tests, and ran:
```
pytest tests/test_tiktok_publish.py -k "crash_recovery or threads_notifications_path" -v
```
Result: all 3 new tests fail against the pre-fix code —
- `test_reconcile_uploading_crash_recovery_self_only_appends_gated_notification_not_silent` — `TypeError: reconcile_uploading() got an unexpected keyword argument 'notifications_path'`
- `test_reconcile_uploading_crash_recovery_public_appends_normal_notification` — same `TypeError`
- `test_reconcile_all_uploading_threads_notifications_path_to_reconcile_uploading` — same `TypeError`

Restored `scripts/tiktok_publish.py` to the fix commit's version (`git checkout 71a6131 -- scripts/tiktok_publish.py`); `git diff --stat` against the fix commit is empty (working tree matches exactly). Re-ran the full suite: all pass. This confirms the tests are a genuine regression guard for the exact crash-then-reconcile scenario described in CR-01, not a tautological assertion that would pass either way.

The scenario the tests simulate: `make_tiktok_entry(status=UPLOADING, publish_id="pub-1", privacy_level_achieved="SELF_ONLY")` — i.e. an entry left mid-flight exactly as `upload_and_publish`'s write-ahead #2 would leave it after a crash — is fed directly into `reconcile_uploading` with a `FakeSession` returning `PUBLISH_COMPLETE`, and the test asserts the resulting `notifications.log` contains the `SELF_ONLY`-specific text and NOT the plain success text (and vice versa for the `PUBLIC_TO_EVERYONE` case). This is precisely the crash-then-reconcile scenario CR-01 described.

**5. No new gap introduced:**
- **WR-03 fix (`_extract_share_url`)** applied to both `upload_and_publish` (line 582) and `reconcile_uploading` (line 698) via one shared helper (lines 589-595) that returns `post_ids[0] if post_ids else None` — correctly handles the empty-list case (`None`, not an `IndexError`) as well as the documented list-of-one case. `test_upload_and_publish_full_success_flow_persists_write_ahead` now asserts `entry["video_share_url"] == "share-1"` (string) and `test_idempotent_retry_no_duplicate_init_on_reconcile` asserts the same on the reconcile path — both pass.
- **Backward compatibility for pre-fix queue entries:** `entry.get("privacy_level_achieved") == "SELF_ONLY"` uses `.get()`, not `entry[...]` — a legacy entry enqueued before this fix (which lacks the key entirely, since `enqueue()` only started setting it to `None` in this same commit) degrades to `None == "SELF_ONLY"` → `False` → the normal-success-text branch, not a `KeyError`. Confirmed no `KeyError` risk. Noted for completeness (not a blocking gap): a legacy entry that crashed mid-poll *before* this fix landed and is reconciled *after* the fix would get the plain-success notification rather than an explicit "unknown, please verify manually" one — but per `docs/publish-queue.md` and 06-CONTEXT.md D-04, `tiktok_enabled` has never been turned on in production (the TikTok audit has not yet been performed), so no such legacy in-flight entry can exist in practice at this point in the project's lifecycle. This does not affect Success Criterion 1 for any entry created going forward.

**Conclusion:** CR-01 is genuinely closed. The write-ahead persistence, the notification threading, and the CLI wiring were all independently confirmed by direct code reading (not by trusting the commit message), and the regression tests were proven to actually catch the original bug by running them against the pre-fix source.

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `scripts/tiktok_publish.py` | Queue lifecycle, OAuth, HTTP layer, orchestration, kill_item, CLI, CR-01 fix | ✓ VERIFIED (substantive, wired) | 850 lines. `privacy_level_achieved` field added to `enqueue()` (line 156) and threaded through write-ahead persistence, `reconcile_uploading`, `reconcile_all_uploading`, and `run_command`. All named functions present and exercised by 244 passing tests (241 pre-existing + 3 new). |
| `tests/test_tiktok_publish.py` | Full coverage incl. isolation/scope tests + CR-01 regression tests | ✓ VERIFIED | 3 new tests added (`test_reconcile_uploading_crash_recovery_self_only_appends_gated_notification_not_silent`, `test_reconcile_uploading_crash_recovery_public_appends_normal_notification`, `test_reconcile_all_uploading_threads_notifications_path_to_reconcile_uploading`), plus 2 existing tests strengthened with new assertions (`test_upload_and_publish_full_success_flow_persists_write_ahead`, `test_idempotent_retry_no_duplicate_init_on_reconcile`). All pass; independently confirmed to fail against pre-fix code. |
| `scripts/instagram_publish.py` | Unaffected by this fix | ✓ VERIFIED (untouched, regression-confirmed) | Not part of the `71a6131` diff; all Instagram tests still pass. |
| `docs/publish-queue.md` | TikTok + Instagram operator sections | ✓ VERIFIED (regression, unchanged) | Not part of the `71a6131` diff; sections 6/7 still present and accurate. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `check_tiktok_publish_gate`'s result | `entry["privacy_level_achieved"]` | Assigned in the same statement block as `entry["publish_id"]`, before the chunk-upload/poll loop | ✓ WIRED (NEW) | `tiktok_publish.py:563-566`. Confirmed by direct read; write-ahead ordering proven correct. |
| `entry["privacy_level_achieved"]` | `append_notification` (crash-recovery path) | `reconcile_uploading`'s `PUBLISH_COMPLETE` branch reads it via `.get()` and branches to `_self_only_notification_text`/`_success_notification_text` | ✓ WIRED (NEW) | `tiktok_publish.py:700-703`. Confirmed by direct read and by running the 3 new regression tests (pass on fixed code, fail on pre-fix code). |
| `run_command --check` | `reconcile_all_uploading(..., notifications_path=config.notifications_path)` | Explicit keyword-argument pass-through, not a default/drop | ✓ WIRED (NEW) | `tiktok_publish.py:825-829`. Only call site of `reconcile_all_uploading` in the module (grep-confirmed); `config.notifications_path` is a real populated `PublishConfig` field. |
| `status_data["publicaly_available_post_id"]` (list) | `entry["video_share_url"]` (string) | Shared `_extract_share_url` helper used by both `upload_and_publish` and `reconcile_uploading` | ✓ WIRED (NEW, WR-03) | `tiktok_publish.py:589-595,582,698`. Both call sites route through the same helper; tests assert the stored value is a string, not a list. |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|--------------|--------|----------|
| PUB-06 | 06-01, 06-02, 06-03, 06-05, 06-07 | TikTok Content Posting API integration, gated sub-phase | ✓ SATISFIED | CR-01 (the D-05 safety guarantee's crash-recovery gap) is now closed per the detailed trace above. Core integration remains real and tested. Note: `.planning/REQUIREMENTS.md` and `.planning/ROADMAP.md` still show PUB-06/Phase 6 as blocked/pending as of this verification's timestamp — this reflects the intentionally-cautious pre-fix state (`d411e92`'s correction commit) and should be updated to reflect this pass, but that update is outside this verifier's scope (VERIFICATION.md is the artifact this agent produces; ROADMAP/REQUIREMENTS updates happen in the downstream workflow step). |
| PUB-07 | 06-01, 06-02, 06-04, 06-06, 06-07 | Instagram Graph API Reels integration, gated sub-phase | ✓ SATISFIED (unchanged) | Unaffected by this fix; stands as satisfied per the prior verification pass. |

No orphaned requirements.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `scripts/instagram_publish.py` | 588-596 (`poll_container_status`) | Skips `_check_meta_permission_error` unlike the module's other 3 HTTP calls | ⚠️ Warning (WR-01, still open — confirmed unaddressed by this fix, unaffected file) | Not a required must-have, doesn't block SC1/SC2/SC3. |
| `scripts/tiktok_publish.py` | 285-291 (`load_credentials` refresh) | Overwrites the whole token file with the refresh response instead of merging | ⚠️ Warning (WR-02, still open — confirmed unaddressed) | Untested either way; not a required must-have. |
| `scripts/instagram_publish.py` | (no `--ig-user-id` validation found) | `--ig-user-id` not validated before a live `--now`/`--check` publish attempt | ⚠️ Warning (WR-04, still open — confirmed unaddressed, `grep` for a validation check found none) | Not a required must-have. |
| `scripts/config.py` | 203-216 (`PublishConfig`), `_validate` | No check that the three queue paths are distinct | ⚠️ Warning (WR-05, still open — confirmed unaddressed) | Orthogonal to SC3 as coded (SC3 is a claim about code-level isolation, which is proven by the isolation tests); doesn't block SC3. |
| Both modules | OAuth `state` param generation | Non-cryptographic `random.choices` source; `state` never validated on redirect return | ⚠️ Warning (WR-06, still open — confirmed unaddressed, `grep` still shows `random.choices` in both files) | Decorative CSRF nonce; exploitability limited by 127.0.0.1-only binding. Not a required must-have. |
| `docs/publish-queue.md` | 25, 78, 82 | TikTok/Instagram sibling Task Scheduler entries share the exact same `/st 09:00` anchor as YouTube's | ⚠️ Warning (WR-07, still open — confirmed unaddressed) | Not a required must-have. |

WR-03 is now fixed (see above) and removed from this list. No `TBD`/`FIXME`/`XXX` debt markers found in any phase-6-modified file (grep of the fix commit's diff and the current files).

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full phase-6 test suite passes | `pytest tests/test_tiktok_publish.py tests/test_instagram_publish.py tests/test_config.py tests/test_publish_queue.py -q --basetemp=D:\shorts-maker\.pytest-scratch-reverify` | `244 passed, 1 warning in 3.35s` | ✓ PASS |
| New CR-01 regression tests (isolated) | `pytest tests/test_tiktok_publish.py -k "crash_recovery or threads_notifications_path or write_ahead or idempotent_retry" -v` | `5 passed` | ✓ PASS |
| Full project test suite (non-integration) | `pytest -q -m "not integration" --basetemp=D:\shorts-maker\.pytest-scratch-reverify` | `541 passed, 5 skipped, 9 deselected in 4.39s` | ✓ PASS |
| CR-01 regression tests against **pre-fix** source (`d411e92`) | `pytest tests/test_tiktok_publish.py -k "crash_recovery or threads_notifications_path" -v` (with `scripts/tiktok_publish.py` checked out at `d411e92`) | `3 failed` — all with `TypeError: ... unexpected keyword argument 'notifications_path'` | ✓ CONFIRMS REAL REGRESSION GUARD |

Scratch pytest directories cleaned up after use (`D:\shorts-maker\.pytest-scratch-reverify`, and a stray `shorts-maker.pytest-scratch-reverify` created by an intermediate cwd resolution issue). Working tree restored to `71a6131`'s exact `scripts/tiktok_publish.py` content (`git diff --stat` empty) before finishing.

### Human Verification Required

None. All checks completed via direct code reading and executed tests.

### Gaps Summary

No gaps remain. The prior BLOCKER (CR-01) is closed: `upload_and_publish` now persists `privacy_level_achieved` in the same write-ahead `save_queue` call as `publish_id` (before the poll loop that can crash/time out), `reconcile_uploading`/`reconcile_all_uploading` thread a `notifications_path` parameter that `run_command`'s only call site correctly supplies from `config.notifications_path`, and the crash-recovery `PUBLISH_COMPLETE` branch now notifies with the same SELF_ONLY-vs-success distinction the primary path already used. Three new regression tests were independently confirmed to fail against the pre-fix source and pass against the fix — they are genuine guards against this exact scenario regressing, not tautologies.

The 6 remaining Warning-level findings from 06-REVIEW.md (WR-01, WR-02, WR-04, WR-05, WR-06, WR-07) were independently re-confirmed as still open (grep/code-read against current source) — none of them were addressed by this fix commit, none of them block Success Criteria 1/2/3, and this matches expectation since this fix commit was scoped specifically to CR-01 (+ WR-03, now also closed).

Success Criterion 1 (TikTok, incl. idempotency safety mechanism), Success Criterion 2 (Instagram), and Success Criterion 3 (platform isolation) are all now satisfied. PUB-06 and PUB-07 are both satisfied. Phase 6 goal is achieved.

**Recommended follow-up (non-blocking):** `.planning/REQUIREMENTS.md` and `.planning/ROADMAP.md` still reflect the pre-fix `gaps_found` state for PUB-06/Phase 6 as of this verification's timestamp; they should be updated to reflect this passed re-verification in the downstream workflow step (outside this verifier's scope).

---

_Verified: 2026-07-10T20:15:00Z_
_Verifier: Claude (gsd-verifier)_
