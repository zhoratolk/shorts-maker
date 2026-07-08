# Publish Queue (Phase 3: YouTube Scheduled Auto-Publish)

This document is the operator guide for `scripts/publish_queue.py`: how to set
up the periodic Windows Task Scheduler check, how to flip from dry-run to a
live upload, how the daily publish grid works, how notifications surface back
into a Claude Code chat session, and the manual override / pause / kill
commands. It also tracks empirical confirmations of API behavior that the code
depends on but that documentation alone doesn't fully settle (see "Kill-path
verification" below).

## 1. Setting up the periodic check (Windows Task Scheduler, D-06)

The periodic "check the queue every ~3 hours" behavior (D-05) is driven by a
single Windows Task Scheduler entry, **not** by keeping a Claude Code session
open. This is deliberate: Task Scheduler survives terminal closure, sleep, and
reboots, so the queue keeps advancing even on a personal machine that isn't
always running Claude Code (see `03-RESEARCH.md`'s D-06 section for the full
rationale).

### Create the task (run once)

```
schtasks /create /sc hourly /mo 3 /tn "shorts-maker-publish" ^
  /tr "python D:\shorts-maker\scripts\publish_queue.py --check" ^
  /st 09:00 /ru "%USERNAME%"
```

- `/sc hourly /mo 3` — fires every 3 hours (matches D-05's cadence).
- `/tr "..."` — the exact command that runs each time; always `--check`, never
  `--now` (the periodic path only ever does the reconcile-then-upload-one-item
  flow, never a targeted force-publish).
- `/ru "%USERNAME%"` — runs under your own Windows account, so it can read
  `client_secret.json`/`upload_token.json` and the `work/` directory exactly
  as an interactive session would (no separate service account, no elevated
  privileges).
- Add `/sc onlogon` variants or a `/z` "wake the computer to run this task" via
  the Task Scheduler GUI (`taskschd.msc` → find "shorts-maker-publish" →
  Properties → Conditions → check "Wake the computer to run this task") if
  the machine sleeps often — `schtasks /create` itself has no CLI flag for
  wake-to-run, so this one setting is a GUI-only step. This mitigates
  Assumption A3 (Task Scheduler triggers reliably firing through sleep
  cycles) — the manual `--now` override remains an always-available backstop
  even if a cycle is missed.

### Verify exactly one entry exists (Pitfall 4)

A duplicate or overlapping Task Scheduler entry is the one realistic way this
project could burn through YouTube's upload quota or double-check the queue
too often. Verify after creating it, and periodically thereafter:

```
schtasks /query /tn "shorts-maker-publish" /v /fo list
```

This should print exactly one task. If you ever see the task listed more than
once (e.g. after re-running the create command with a typo'd name), delete
the duplicates:

```
schtasks /delete /tn "shorts-maker-publish" /f
```

then re-create the single entry with the command above.

## 2. Flipping from dry-run to live (PUB-03 opt-in)

**Dry-run is the default.** With `publish.enabled: false` (or no `publish:`
section at all) in `config.yaml`, `--check` reconciles any stuck uploads but
makes **zero** network calls for the actual upload step — it prints/logs
`dry-run: skipped (opt-in disabled)` and leaves the queue untouched. This is
true for both the scheduled Task Scheduler run and any manual `--check`
invocation.

**⚠️ Going live is a one-way, public action.** Once `publish.enabled: true`,
every future `--check` (and every `--now`) will actually upload and schedule a
real video on your real YouTube channel with YouTube's own `publishAt`
auto-release — this is hard to undo (see "Pause/kill" below for how to cancel
an already-scheduled release, but a video that already went public before you
noticed cannot be un-published in the same sense).

To opt in, edit `config.yaml`:

```yaml
publish:
  enabled: true
  daily_slots_utc: ["09:00", "15:00", "20:00"]
  queue_path: "work/_publish/queue.json"
  notifications_path: "work/_publish/notifications.log"
  client_secret_path: "client_secret.json"
  upload_token_path: "upload_token.json"
```

### First live run: one-time OAuth consent (D-08)

The very first time `--check` or `--now` runs with `publish.enabled: true`,
`upload_token.json` does not exist yet — `load_credentials()` will open a
browser for an interactive consent flow, scoped to
`https://www.googleapis.com/auth/youtube` (D-08/D-09, amended 2026-07-08 —
see "Kill-path verification" below for why the originally-planned narrower
`youtube.upload`-only scope was widened after a live test). This is a
separate token from `youtube_analytics.py`'s read-only `token.json`.
`upload_token.json` is gitignored, same as `client_secret.json`/`token.json`
— never commit it. **If you already have an `upload_token.json` minted under
the old narrow scope, delete it before the next run** — `load_credentials()`
reuses a cached token as-is and will not silently re-request the broader
scope on its own.

Because the Task Scheduler task runs detached (no visible browser window in
some configurations), it's recommended to perform this first-consent run
**interactively** once (e.g. `python scripts/publish_queue.py --check` from an
open terminal) before relying on the scheduled task for the first live cycle.
After that, the cached, refreshable token means subsequent scheduled runs
don't need a browser at all.

## 3. The daily publish grid (D-07)

`publish.daily_slots_utc` is a fixed list of UTC `HH:MM` times (default
`["09:00", "15:00", "20:00"]` — three slots/day, roughly aligned with the
3-hour check cadence). Each time a clip is due for upload, `next_free_slot()`
picks the next strictly-future slot from this grid that isn't already taken by
another `SCHEDULED` entry, rolling over to the next day once today's slots are
exhausted. All math is UTC-only by design (Pitfall 1: a `publishAt` in the
past makes YouTube publish immediately instead of scheduling).

To change the cadence or number of slots, just edit the list — no code change
needed:

```yaml
publish:
  daily_slots_utc: ["08:00", "12:00", "16:00", "20:00"]
```

## 4. How notifications surface into chat (D-06 hybrid)

Because the periodic check runs via Task Scheduler (no open Claude Code
session required), it has no chat to post into directly. Instead, every
actual upload or error appends one line to the append-only
`work/_publish/notifications.log` (no-op "nothing due" checks are
deliberately **not** logged, to keep the log signal-dense). The next time a
Claude Code session is active, it can read unread lines
(`read_unread_notifications()`, which tracks a small last-read marker file,
`work/_publish/notifications.read`, so the same line is never reported
twice) and relay them in chat, e.g.:

> залил 4, выйдет в 09:00 UTC

An upload error appends a distinct line instead: `[error] {seq}: {reason}`.

The manual `--now <clip_id>` path is invoked directly from within an active
session, so its notification is immediate and synchronous by construction —
only the periodic path needs this log-buffer bridge.

## 5. Manual override, pause, and kill (D-05/D-04)

```
# Force-publish one specific queued clip right now, via the same
# upload_and_schedule path --check uses (no divergent logic, D-05):
python scripts/publish_queue.py --now <clip_id>

# Pause a not-yet-uploaded item (skipped by the next --check):
python scripts/publish_queue.py --pause <clip_id>

# Resume a paused item:
python scripts/publish_queue.py --resume <clip_id>

# Kill an item at any point in its lifecycle - local-only flip if not
# yet uploaded, or a revert-to-private + mandatory verify against
# YouTube if it's already scheduled (PUB-04):
python scripts/publish_queue.py --kill <clip_id>

# Show the queue's sequential numbering/status/title (PUB-01):
python scripts/publish_queue.py --list
```

An unknown `clip_id` on `--now`/`--kill`/`--pause`/`--resume` prints a clear
error and exits non-zero rather than silently acting on the wrong item.

## Kill-path verification (Assumption A1)

**Status: PERFORMED 2026-07-08 — first attempt FAILED live (root cause found, fixed), re-test with the fix PASSED.**

`03-RESEARCH.md` Assumption A1 flagged that the exact API acceptance of a bare
re-send-private update body —

```python
service.videos().update(
    part="status",
    body={"id": video_id, "status": {"privacyStatus": "private"}},
).execute()
```

— to cancel an already-scheduled release (cancel a pending `publishAt`) was
documented-but-not-empirically-confirmed. `PUB-04`'s kill guarantee is
safety-critical: a video believed killed must not go public.

### What actually happened (live test, 2026-07-08)

A throwaway test clip was uploaded and scheduled for `publishAt` ~2 minutes
out, using an `upload_token.json` freshly minted with the (then-narrower)
`https://www.googleapis.com/auth/youtube.upload` scope. `kill_item()` was
called before `publishAt`, but `cancel_scheduled_release()`'s
`videos().update()` call raised:

```
googleapiclient.errors.HttpError: <HttpError 403 ... "Request had
insufficient authentication scopes.". Details: "[{'message':
'Insufficient Permission', 'domain': 'global', 'reason':
'insufficientPermissions'}]">
```

`videos.update` requires the full `https://www.googleapis.com/auth/youtube`
scope — `youtube.upload` covers `videos.insert`/`videos.delete` but **not**
`videos.update`. The 403 happened before `verify_killed()` was ever reached,
so the code-level safety net (Pitfall 2's mandatory re-fetch) never got a
chance to run — the call it was meant to double-check didn't succeed in the
first place.

A parallel attempt to kill the video manually through the YouTube Studio UI
(a separate auth path — the operator's own logged-in browser session, unrelated
to the script's OAuth token scope) did not complete before `publishAt` passed.
The video went **public** for several minutes. The operator then manually
deleted it via YouTube Studio.

### Fix applied

`scripts/publish_queue.py`'s `UPLOAD_SCOPE` was widened from
`https://www.googleapis.com/auth/youtube.upload` to the full
`https://www.googleapis.com/auth/youtube` (see D-09 amendment in
`03-CONTEXT.md`). This is a real, accepted increase in the token's blast
radius — the tradeoff is that the kill/pause safety mechanism (required by
this project's "Необратимость авто-паблиша" constraint) can actually execute.
Any existing `upload_token.json` minted under the old narrow scope must be
deleted so the next run re-triggers OAuth consent under the new scope
(`load_credentials()` reuses a cached token as-is, it does not detect or
request a scope upgrade on its own).

The `kill_item()`/`cancel_scheduled_release()`/`verify_killed()` code path
itself was not changed by the scope fix — but it has now been exercised
end-to-end against a real scheduled video under the widened scope (see
Outcome below), which is the first time the bare
`{"privacyStatus": "private"}` re-send body was actually confirmed sufficient
to cancel a pending `publishAt`.

### Re-test performed (2026-07-08, widened scope)

1. Deleted the old narrow-scope `upload_token.json`.
2. Ran a fresh OAuth consent (foreground, browser-based) — new
   `upload_token.json` minted with `https://www.googleapis.com/auth/youtube`.
3. Enqueued and uploaded one throwaway test clip via `upload_and_schedule()`,
   `publishAt` ~2 minutes out.
4. Called `kill_item()` before `publishAt`.
5. `kill_item()` returned `status="killed"`; independent post-kill
   `verify_killed()` call also returned `True`.
6. Independently re-fetched `videos.list(part="status")` after `publishAt`
   had passed — confirmed `privacyStatus: "private"`, video never went
   public.
7. Deleted the disposable test video via `videos.delete()` and confirmed via
   a follow-up `videos.list()` that it no longer exists on the channel.

### Outcome

- 2026-07-08 (narrow `youtube.upload` scope): **FAILED** — 403
  `insufficientPermissions` on `videos.update`; video went public briefly;
  manually deleted by operator. Root cause: insufficient OAuth scope, fixed
  by widening `UPLOAD_SCOPE` to `https://www.googleapis.com/auth/youtube`.
- 2026-07-08 (widened `youtube` scope, re-test): **PASSED** —
  `cancel_scheduled_release()`'s bare `{"privacyStatus": "private"}` body
  successfully cancelled the pending `publishAt`; `verify_killed()` confirmed
  `private` both internally and via an independent API re-fetch after the
  original `publishAt` timestamp passed. Assumption A1 is now empirically
  confirmed under the current (widened) scope.

---

*Phase: 03-youtube-scheduled-auto-publish*
*Plans: 03-03 (kill-path verification scaffold), 03-04 (operator guide: Task Scheduler setup, dry-run/opt-in, daily grid, notifications, manual/pause/kill CLI reference)*
