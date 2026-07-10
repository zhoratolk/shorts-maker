---
phase: 06-tiktok-instagram-auto-publish
reviewed: 2026-07-10T00:00:00Z
depth: standard
files_reviewed: 7
files_reviewed_list:
  - docs/publish-queue.md
  - scripts/config.py
  - scripts/instagram_publish.py
  - scripts/tiktok_publish.py
  - tests/test_config.py
  - tests/test_instagram_publish.py
  - tests/test_tiktok_publish.py
findings:
  critical: 1
  warning: 7
  info: 2
  total: 10
status: issues_found
---

# Phase 06: Code Review Report

**Reviewed:** 2026-07-10T00:00:00Z
**Depth:** standard
**Files Reviewed:** 7
**Status:** issues_found

## Summary

Reviewed the TikTok/Instagram auto-publish queue lifecycle, OAuth handling,
HTTP orchestration, kill/reconcile logic, and config schema against
`scripts/publish_queue.py`'s established YouTube pattern. The overall
architecture is sound: dry-run gating, write-ahead persistence, and
per-platform queue file isolation are all implemented and covered by tests
that specifically prove cross-platform file isolation.

The most serious finding is a genuine safety-mechanism gap in
`tiktok_publish.py`'s crash-recovery path: the D-05 "never silently report
success as if public when the account is still pre-audit SELF_ONLY"
guarantee only holds on the primary `_upload_one` path. If a `--check`
process dies after `init_direct_post` but before the poll loop finishes, the
*next* `--check`'s `reconcile_uploading` will complete the publish and mark
the entry `PUBLISHED` without ever recording or notifying whether the
achieved `privacy_level` was `SELF_ONLY` — the information needed to make
that call (`check_tiktok_publish_gate`'s result) is never persisted onto the
queue entry, so it is unrecoverable even after the fact. This directly
undermines the one safety property this module was built specifically to
guarantee.

The rest of the findings are narrower robustness/consistency gaps: a missing
permission-error translation on one Instagram HTTP call, an unvalidated
required CLI argument, an unenforced queue-path-isolation config invariant,
a decorative (unvalidated, non-cryptographic) OAuth `state` parameter shared
by both new consent flows, and a type mismatch storing a list into a
singular-named field.

## Critical Issues

### CR-01: TikTok reconcile-completed entries lose the SELF_ONLY/gated signal permanently

**File:** `scripts/tiktok_publish.py:507-584` (`upload_and_publish`) and `scripts/tiktok_publish.py:643-684` (`reconcile_uploading`)
**Issue:** `check_tiktok_publish_gate`'s result (`privacy_level`/`is_still_gated`) is
only ever used transiently inside `upload_and_publish` to decide the
`_upload_one` notification text (`_self_only_notification_text` vs
`_success_notification_text`, `tiktok_publish.py:591-637`). It is **never
persisted onto the queue entry** — `enqueue()` (`tiktok_publish.py:123-161`)
has no field for it, and neither `upload_and_publish` nor
`reconcile_uploading` ever writes it to disk.

Concretely: if the process crashes/times out after `init_direct_post`
persists `publish_id` (write-ahead #2) but before the poll loop in
`upload_and_publish` returns, the entry is left `UPLOADING`. The *next*
`--check` calls `reconcile_all_uploading` → `reconcile_uploading`
(`tiktok_publish.py:643-684`), which polls `fetch_post_status` directly and,
on `PUBLISH_COMPLETE`, sets `entry["status"] = PUBLISHED` — with **no call
to `append_notification` anywhere in `reconcile_uploading`/
`reconcile_all_uploading`**, and no `privacy_level`/`is_still_gated` field
ever written to the entry.

The operator therefore has no way — now or by inspecting the queue file
later, or via `--list` (which only prints `seq/status/caption`) — to learn
that a `PUBLISHED` entry recovered this way might still be `SELF_ONLY`
(private). This is exactly the trap D-05 and `docs/publish-queue.md`
section 6 ("Pre-audit posts are SELF_ONLY") describe TikTok's API as
setting: the call succeeds even though nothing went public, and the code's
whole reason for calling `check_tiktok_publish_gate` up front is to prevent
an operator from being misled about this. The crash-recovery path silently
reintroduces exactly that blind spot.

**Fix:** Persist the gate result onto the entry the same write-ahead pass
that persists `publish_id`, and make `reconcile_uploading` re-check/report
it on completion:
```python
# in upload_and_publish, alongside the publish_id write-ahead:
entry["publish_id"] = data["publish_id"]
entry["privacy_level_achieved"] = privacy_level  # NEW
entry["updated_at"] = datetime.now(timezone.utc).isoformat()
save_queue(queue, queue_path)

# in reconcile_uploading, on PUBLISH_COMPLETE:
if status == "PUBLISH_COMPLETE":
    entry["status"] = PUBLISHED
    entry["video_share_url"] = status_data.get("publicaly_available_post_id")
    entry["updated_at"] = datetime.now(timezone.utc).isoformat()
    if entry.get("privacy_level_achieved") == "SELF_ONLY":
        append_notification(_self_only_notification_text(entry), notifications_path)
    else:
        append_notification(_success_notification_text(entry), notifications_path)
```
(`reconcile_uploading`/`reconcile_all_uploading` will need a
`notifications_path` parameter threaded through, mirroring how
`credentials_factory` is already threaded.)

## Warnings

### WR-01: `poll_container_status` skips Instagram's permission-error translation

**File:** `scripts/instagram_publish.py:588-596`
**Issue:** `create_resumable_container` (`:550-562`), `upload_local_video`
(`:565-585`), and `publish_container` (`:599-611`) all call
`_check_meta_permission_error(response)` before `response.raise_for_status()`,
so a 403/permission-flavored response raises the actionable
`InstagramAccessError` (with the "Advanced Access / App Review" guidance).
`poll_container_status` is the one HTTP call in this module that omits this
— it goes straight to `response.raise_for_status()`. Per the module's own
docstring, `_check_meta_permission_error` is meant to be "the ONLY
mechanism this module uses to detect an access-tier problem" — this call
site breaks that invariant. A token revocation or access-tier change that
manifests during status polling (rather than at container-create/upload/
publish time) surfaces as a generic `requests.HTTPError` instead of the
actionable message pointing at `docs/publish-queue.md`'s Instagram section.
No test (`tests/test_instagram_publish.py`) exercises a 403 from
`poll_container_status`, which is how this gap went unnoticed.
**Fix:**
```python
def poll_container_status(container_id: str, access_token: str, session=requests) -> str:
    response = session.get(
        f"https://graph.facebook.com/{GRAPH_API_VERSION}/{container_id}",
        params={"fields": "status_code", "access_token": access_token},
    )
    _check_meta_permission_error(response)
    response.raise_for_status()
    return response.json()["status_code"]
```

### WR-02: TikTok token refresh overwrites the whole token file, dropping fields the API response omits

**File:** `scripts/tiktok_publish.py:285-291`
**Issue:** On refresh, `load_credentials` does:
```python
refreshed = response.json()
refreshed["expires_at"] = time.time() + refreshed["expires_in"]
token_file.write_text(json.dumps(refreshed, ...))
```
This **replaces** the entire on-disk token file with whatever the refresh
response contains, rather than merging into the existing `token_data`. If
TikTok's refresh-token grant response ever omits `refresh_token` (token
rotation not always guaranteed to repeat every field on every provider), the
cached file permanently loses it, and the *next* refresh attempt will
`KeyError` on `token_data["refresh_token"]` (`:282`) with no recovery path
short of deleting the file and redoing interactive consent. Contrast with
`instagram_publish.py`'s `load_credentials` (`:337-343`), which explicitly
merges only the fields it knows about (`access_token`, `obtained_at`,
`expires_at`) into the existing `token_data`, preserving everything else.
No test exercises a refresh response missing `refresh_token`, so this gap
is untested either way.
**Fix:** Merge into `token_data` instead of replacing it wholesale:
```python
token_data["access_token"] = refreshed["access_token"]
token_data["refresh_token"] = refreshed.get("refresh_token", token_data["refresh_token"])
token_data["expires_at"] = time.time() + refreshed["expires_in"]
token_file.write_text(json.dumps(token_data, ensure_ascii=False, indent=2), encoding="utf-8")
return token_data["access_token"]
```

### WR-03: TikTok's `video_share_url` is assigned a list, not a URL string

**File:** `scripts/tiktok_publish.py:580` (`upload_and_publish`) and `scripts/tiktok_publish.py:676` (`reconcile_uploading`)
**Issue:** `entry["video_share_url"] = status_data.get("publicaly_available_post_id")`.
TikTok's `status/fetch` response documents this field as an **array** of
URLs (confirmed by the test fixtures themselves, e.g.
`tests/test_tiktok_publish.py:688`: `"publicaly_available_post_id": ["share-1"]`).
The field is being stored verbatim under a singular-named key
(`video_share_url`), so any future consumer (CLI display, a notification
line, a dashboard) that treats it as a single URL string will instead get a
Python list serialized into JSON (`["share-1"]`). No test asserts on the
actual stored value, so this went unnoticed.
**Fix:**
```python
post_ids = status_data.get("publicaly_available_post_id") or []
entry["video_share_url"] = post_ids[0] if post_ids else None
```

### WR-04: `--ig-user-id` is not validated before a live Instagram publish attempt

**File:** `scripts/instagram_publish.py:833` (arg definition), `scripts/instagram_publish.py:905-935` (`--now`/`--check` dispatch), `scripts/instagram_publish.py:940-951` (`main`)
**Issue:** `docs/publish-queue.md` (section 7) states `--now`/`--check` "also
need `--ig-user-id <your-ig-user-id>`", but nothing in `run_command` or
`main()` enforces this. If `instagram_enabled: true` and the operator omits
`--ig-user-id` (or a Task Scheduler entry is copy-pasted without it —
plausible given three near-identical sibling tasks), `args.ig_user_id` is
`None`, which flows unchanged into `upload_and_publish(..., ig_user_id, ...)`
→ `create_resumable_container` (`:550-562`), building the URL
`https://graph.facebook.com/{GRAPH_API_VERSION}/None/media`. This produces a
confusing Graph API error instead of the clear, actionable failure the
project's error-handling convention calls for elsewhere in this same module
(e.g. `InstagramAccessError`, `FileNotFoundError` with actionable text).
**Fix:** Validate eagerly in `run_command` before dispatching to `--now`/`--check`:
```python
if (args.now or args.check) and not ig_user_id:
    print("error: --ig-user-id is required for --now/--check", file=sys.stderr)
    raise SystemExit(2)
```

### WR-05: No config-level guarantee that the three platform queue paths stay distinct

**File:** `scripts/config.py:391-407` (`_validate`), `scripts/config.py:195-218` (`PublishConfig`)
**Issue:** The project's whole isolation design (Success Criterion 3,
explicitly tested via `test_isolation_pause_and_kill_*_never_touches_*`
in both `tests/test_tiktok_publish.py` and
`tests/test_instagram_publish.py`) assumes `publish.queue_path`,
`publish.tiktok_queue_path`, and `publish.instagram_queue_path` always point
at three different files. `_validate` never checks this. A config typo
(e.g. copy-pasting the `publish:` block and forgetting to change one path)
would silently point two platforms' CLIs at the same JSON file. Since each
module's status enum/field names only partially overlap (e.g. TikTok's
`publish_id` vs Instagram's `container_id`/`media_id` vs YouTube's
`video_id`/`publish_at`), the practical failure mode ranges from `KeyError`
crashes to one platform's `kill_item`/`select_next_due` silently operating
on another platform's entries — exactly the failure mode the isolation
tests were written to rule out, but only at the code level, not the config
level.
**Fix:**
```python
paths = {config.publish.queue_path, config.publish.tiktok_queue_path, config.publish.instagram_queue_path}
if len(paths) != 3:
    raise ConfigError(
        "publish.queue_path, publish.tiktok_queue_path, and "
        "publish.instagram_queue_path must all be distinct"
    )
```

### WR-06: OAuth `state` parameter is generated insecurely and never validated

**File:** `scripts/tiktok_publish.py:358` / `scripts/tiktok_publish.py:324-340` (`_capture_oauth_redirect_code`); `scripts/instagram_publish.py:415` / `scripts/instagram_publish.py:378-394` (`_capture_oauth_redirect_code`)
**Issue:** Both `run_tiktok_oauth_consent` and `run_instagram_oauth_consent`
generate a `state` value via `"".join(random.choices(string.ascii_letters + string.digits, k=16))`
— `random` (Mersenne Twister) is not a cryptographically secure source and
is the wrong tool for a security-sensitive nonce (`secrets` module exists
for exactly this). More importantly, `_capture_oauth_redirect_code` in both
modules only ever reads `params.get("code", [""])[0]` from the redirect —
`state` is captured nowhere and never compared back against the value that
was sent. The nonce is generated and embedded in the authorize URL but
provides zero actual CSRF protection since nothing validates it on return.
Exploitability is limited by the redirect listener binding to `127.0.0.1`
only (`T-06-05`/`T-06-03`, already correctly enforced and tested), but the
`state` parameter as implemented is decorative, not defensive.
**Fix:** Use `secrets.token_urlsafe(16)` for `state`, and validate the
returned `state` in `_capture_oauth_redirect_code` (or its caller) against
the value that was sent, rejecting the redirect if they don't match.

### WR-07: Sibling Task Scheduler entries all fire at the same `/st 09:00` anchor, risking interleaved writes to the shared notifications.log

**File:** `docs/publish-queue.md:76-83`
**Issue:** Section "Sibling tasks for TikTok and Instagram" instructs
creating `shorts-maker-publish-tiktok` and `shorts-maker-publish-instagram`
with the exact same `/sc hourly /mo 3 /st 09:00` schedule as the original
`shorts-maker-publish` task. All three will genuinely fire concurrently
(not just conceptually — same start time, same 3-hour interval), each as a
separate OS process, all appending to the same
`work/_publish/notifications.log` via `append_notification`
(`scripts/publish_queue.py:494-504`, imported and used unchanged by both
new modules). `append_notification` performs a single `open(..., "a")` +
`write()` per call with no locking; three near-simultaneous single-line
appends from separate Windows processes are not guaranteed atomic across
platforms/filesystems, risking an occasional interleaved/corrupted log
line. The doc's own OAuth-consent sections note "even though they are never
run simultaneously in practice" for the *interactive* consent flows, but
that caveat does not apply to the recurring `--check` tasks this same
section sets up with identical timing.
**Fix:** Stagger the sibling tasks' `/st` times by a minute or two (e.g.
`09:01`, `09:02`) so the three periodic checks never fire in the same
instant, or document the (currently unaddressed) concurrent-append risk
explicitly.

## Info

### IN-01: Duplicate substrings in `_PERMISSION_ERROR_SUBSTRINGS`

**File:** `scripts/instagram_publish.py:134-144`
**Issue:** Both `"access level"` and `"access_level"` are listed; harmless
(just means the OR-list has one redundant entry), but worth trimming for
clarity when this heuristic gets tuned against a real captured Meta error
response per the doc's own "Status: not yet performed" note.
**Fix:** Drop one of the two variants, or leave a comment noting both
casings are intentionally covered.

### IN-02: `load_queue`/`save_queue` are copy-pasted verbatim across three modules

**File:** `scripts/tiktok_publish.py:102-120`, `scripts/instagram_publish.py:150-168` (vs `scripts/publish_queue.py:52-73`)
**Issue:** Both new modules hand-roll their own byte-identical
`load_queue`/`save_queue` instead of importing them from
`scripts.publish_queue` (which is already imported for
`append_notification`). This matches the project's stated "hand-rolled per
platform, not a shared library" convention documented in both modules'
docstrings, so it is intentional rather than an oversight — noting it only
because any future fix to the write path (e.g. WR-07's atomicity, or
switching to a temp-file+rename write) will need to be applied in three
places, not one.
**Fix:** No action required if the "no shared library" convention is
deliberate; if it is ever revisited, consider factoring `load_queue`/
`save_queue` into a tiny shared helper module.

---

_Reviewed: 2026-07-10T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
