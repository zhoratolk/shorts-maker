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

### Sibling tasks for TikTok and Instagram (PUB-06/PUB-07)

`schtasks`'s `/tr` only accepts one command per task, and keeping each
platform's periodic check as its own separate Task Scheduler entry
preserves this phase's whole isolation design (Success Criterion 3) at the
OS scheduling layer too, not just the file layer - a crash or hang in one
platform's `--check` can never block another platform's task from firing.
Create these as two additional **sibling** tasks alongside
`shorts-maker-publish` above, not folded into it:

```
schtasks /create /sc hourly /mo 3 /tn "shorts-maker-publish-tiktok" ^
  /tr "python D:\shorts-maker\scripts\tiktok_publish.py --check" ^
  /st 09:00 /ru "%USERNAME%"

schtasks /create /sc hourly /mo 3 /tn "shorts-maker-publish-instagram" ^
  /tr "python D:\shorts-maker\scripts\instagram_publish.py --check --ig-user-id <your-ig-user-id>" ^
  /st 09:00 /ru "%USERNAME%"
```

Verify all three tasks exist exactly once each, the same way section 1
verifies `shorts-maker-publish`:

```
schtasks /query /tn "shorts-maker-publish-tiktok" /v /fo list
schtasks /query /tn "shorts-maker-publish-instagram" /v /fo list
```

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

### Что автоплоад уже делает правильно (сверка с разбором Мартина Радина, 2026-07)

Разбор «Как правильно загружать YouTube Shorts в 2025»
(youtube.com/watch?v=iolgNqXF7Fc) — какие его советы пайплайн закрывает
автоматически:

- **«Не публикуй сразу — сначала ограниченный доступ»**: `build_insert_body`
  всегда грузит `privacyStatus: "private"` + `publishAt` (захардкожено,
  T-03-06) — клип уходит в открытый доступ только по расписанию.
- **«Выкладывай днём, не ночью»**: дефолтная сетка `daily_slots_utc`
  (09:00/15:00/20:00 UTC) — дневные-вечерние слоты по МСК; правится в
  конфиге без кода.
- **Категория**: `categoryId: 20` (Gaming) проставляется на каждом аплоаде —
  без неё YouTube кидает ролик в «Люди и блоги».
- **Описание/теги**: правила заполнения (описание никогда не пустое,
  ключевики из поисковых подсказок, тег с названием канала) — в
  [metadata-writing-ru.md](metadata-writing-ru.md), применяются на этапе
  генерации метадаты.

### Ручной чеклист в Studio (API этого не умеет)

YouTube Data API не даёт выставить два полезных флага — после аплоада (не
дожидаясь publishAt) раз в день пройтись по новым шортсам в мобильной
творческой студии:

- **Скрыть количество лайков** (настройки видео → скрыть лайки) — на старте
  канала маленькие цифры отпугивают; когда лайков станет прилично, включить
  обратно.
- **Разрешить ремиксы «видео и аудио»** — ремиксы ссылаются на оригинал и
  приносят просмотры (обычно включено по умолчанию — просто проверить).

Превью-обложку теперь можно ставить автоматически: `scripts/thumbnail.py`
генерит постер из готового клипа (сильный кадр + короткая подпись), а
`publish_queue` вызывает `thumbnails.set` после аплоада, если у записи задан
`thumbnail_path` и `config.thumbnail.upload: true`. Fail-open — ошибка
обложки (нет файла, канал не имеет права на кастомные превью, сбой API) в
`_try_set_thumbnail` только пишет `[warn]` и НЕ роняет уже загруженное видео;
результат фиксируется в `entry["thumbnail_set"]`. Важная оговорка: на кадр
**внутри самой ленты Shorts** это по-прежнему не влияет — кастомное превью
YouTube показывает на гриде канала, при шеринге и на странице просмотра, но
листалка Shorts берёт кадр из видео. Так что для чисто-Shorts-канала польза
частичная; для обычных 16:9 видео (`width/height: 1280/720`) — полная.

Провенанс для аналитики досмотров: `enqueue` также носит опциональные
`moment_tag` (тег момента кандидата) и `source_duration` (длина клипа) — они
ни на что в паблише не влияют, но позволяют `scripts/retention.py` привязать
кривую досмотра опубликованного видео обратно к ТИПУ и ДЛИНЕ момента (петля
обучения авто-отбора). Передавай их из make-shorts вместе с `thumbnail_path`.

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

## 6. TikTok setup and going live (PUB-06, D-02/D-04)

### App registration

1. Register an app in the [TikTok Developer Portal](https://developers.tiktok.com/).
   Add the **Login Kit** product first (Content Posting API's own "Add"
   button stays disabled until Login Kit is added - it's the underlying
   OAuth product) and set its Redirect URI, then add **Content Posting
   API** itself.
2. Request exactly these two Content Posting API scopes - never a broader
   one (V4): `video.publish` and `video.upload`. Login Kit adds
   `user.info.basic` on its own; that's expected and unrelated to the
   Content Posting flow this project uses.
3. Set the redirect URI to `https://127.0.0.1:8765/callback` - **https,
   not http**: TikTok's Login Kit rejects a plain-http redirect_uri even
   for 127.0.0.1, unlike Google's loopback-exception handling. The fixed
   port (8765) matches what `run_tiktok_oauth_consent` binds to.
4. The App details page also requires a Terms of Service URL, Privacy
   Policy URL, and a Web/Desktop URL before it will save - any reachable
   public URLs work (e.g. a small static page on GitHub Pages); TikTok's
   own "Verify URL properties" step (URL-prefix method, signature file)
   confirms you actually control them.
5. Save the issued `client_key`/`client_secret` into `tiktok_client_key.json`
   at the repo root:
   ```json
   {"client_key": "...", "client_secret": "..."}
   ```
   Gitignored, same discipline as `client_secret.json`/`upload_token.json` -
   never commit it.

### One-time interactive consent

The very first time `--check` or `--now` runs with `publish.tiktok_enabled:
true`, `tiktok_token.json` does not exist yet. Run the one-time interactive
consent flow yourself, once, from an open terminal (same "run it
interactively before relying on the scheduled task" recommendation as
section 2's YouTube consent):

```
python -c "from scripts.tiktok_publish import run_tiktok_oauth_consent; run_tiktok_oauth_consent('tiktok_client_key.json', 'tiktok_token.json')"
```

This opens a browser for consent, captures the redirect code on
`https://127.0.0.1:8765`, and writes `tiktok_token.json` (gitignored).
`ensure_local_tls_cert` generates a self-signed certificate on first run
(`tiktok_oauth_cert.pem`/`tiktok_oauth_key.pem`, both gitignored) purely so
the local listener can speak TLS for that one redirect - the browser will
show a "your connection is not private" warning for that single
`127.0.0.1` hit; clicking through (Advanced → Proceed) is expected and
safe, nothing on this cert is ever validated by TikTok or sent anywhere.
After consent, the cached, refreshable token means subsequent scheduled
runs don't need a browser at all.

### Opt-in to going live

**⚠️ Going live is a one-way, public action**, same as YouTube's opt-in in
section 2. With `publish.tiktok_enabled: false` (the default), `--check`
still reconciles stuck uploads but makes **zero** network calls for the
actual upload step. Once `publish.tiktok_enabled: true`, every future
`--check`/`--now` will actually attempt a real TikTok Direct Post.

```yaml
publish:
  tiktok_enabled: true
  tiktok_queue_path: "work/_publish/tiktok_queue.json"
  tiktok_client_key_path: "tiktok_client_key.json"
  tiktok_token_path: "tiktok_token.json"
```

### Pre-audit posts are SELF_ONLY (private) - D-05

Before TikTok's Content Posting API audit clears, every post this module
makes is restricted to `SELF_ONLY` (private) - **the API call still
returns success even though nothing actually goes public** (the documented
pre-audit trap). `upload_and_publish` checks this via
`check_tiktok_publish_gate` before every post and, if still gated, appends
a distinct notification line instead of the normal success line:

> TikTok {seq}: залито, но аккаунт всё ещё SELF_ONLY (аудит Content Posting API не пройден) - видео приватное

Once you're ready to go fully public, file the **Content Posting API
audit** specifically in the TikTok Developer Portal - this is a separate
application from base app approval (a common trap: base app approval alone
does not unlock public posting). There is no official published SLA for
this review; only unverified secondary-source estimates exist
(06-RESEARCH.md Assumption A1) - do not promise yourself or anyone else a
specific timeline.

## 7. Instagram setup and going live (PUB-07, D-02/D-04, user's build-both-scenarios decision)

### App registration

1. Create a Meta App of type **Business** in the
   [Meta App Dashboard](https://developers.facebook.com/apps/).
2. Add your own Instagram Business account as a tester/admin of the app
   (App Dashboard → Roles) - this is the one-time step that makes the
   account "yours" for Standard Access purposes.
3. Request exactly these two scopes - never a broader one (V4):
   `instagram_business_basic` and `instagram_business_content_publish`
   (never `instagram_business_manage_messages`/
   `instagram_business_manage_comments`, which this project has no use
   for).
4. Set the redirect URI to `http://127.0.0.1:8766/callback` (the fixed
   port `run_instagram_oauth_consent` binds to - a different port than
   TikTok's 8765 so both one-time flows can be registered as distinct
   redirect URIs without collision, even though they're never run
   simultaneously in practice).
5. Save the app id/secret into `instagram_client_secret.json` at the repo
   root:
   ```json
   {"client_id": "...", "client_secret": "..."}
   ```
   Gitignored, same discipline as every other credential file in this
   project - never commit it.

### One-time interactive consent

The very first time `--check` or `--now` runs with `publish.instagram_enabled:
true`, `instagram_token.json` does not exist yet. Run the one-time
interactive consent flow yourself, once, from an open terminal:

```
python -c "from scripts.instagram_publish import run_instagram_oauth_consent; run_instagram_oauth_consent('instagram_client_secret.json', 'instagram_token.json')"
```

This opens a browser for consent, captures the redirect code on
`127.0.0.1:8766`, exchanges it for a short-lived token and then a 60-day
long-lived token, and writes `instagram_token.json` (gitignored).
`load_credentials()` silently refreshes it (no browser) any time it's
older than 24h, well inside the 60-day validity window.

### Opt-in to going live

**⚠️ Going live is a one-way, public action**, same as YouTube's opt-in in
section 2. With `publish.instagram_enabled: false` (the default), `--check`
still reconciles stuck uploads but makes **zero** network calls for the
actual upload step. Once `publish.instagram_enabled: true`, every future
`--check`/`--now` will actually attempt a real Instagram Reels publish.

```yaml
publish:
  instagram_enabled: true
  instagram_queue_path: "work/_publish/instagram_queue.json"
  instagram_client_secret_path: "instagram_client_secret.json"
  instagram_token_path: "instagram_token.json"
```

`--now`/`--check` also need `--ig-user-id <your-ig-user-id>` (the
Instagram Business account's numeric user ID, already registered as a
tester in the App Dashboard per step 2 above) - `--list`/`--pause`/
`--resume`/`--kill` never touch the API and work without it.

### Attempt Standard Access first - do NOT file App Review preemptively

**Unlike TikTok, this module does NOT pre-check whether your account needs
Meta App Review before every publish attempt.** Per the user's explicit
decision (06-CONTEXT.md, resolving 06-RESEARCH.md Open Question 1), it
attempts a real publish directly via Standard Access - there is no
`creator_info/query`-equivalent gating call anywhere in
`instagram_publish.py`. Follow this instruction exactly:

1. **Attempt first.** Just run `--now`/`--check` with
   `instagram_enabled: true` and your registered account. If it succeeds,
   Standard Access was sufficient - no App Review needed for this
   self-owned-account use case.
2. **Only file App Review if `InstagramAccessError` says so.** If Meta's
   API itself reports a permission/access-tier problem on a live call, the
   module raises `InstagramAccessError` with a message stating that
   Advanced Access/App Review is likely needed. Only at that point should
   you go file App Review in the Meta App Dashboard.
3. **Do NOT file App Review preemptively.** Meta's documented
   Standard-vs-Advanced-Access split states Advanced Access (and its
   review requirement) is only needed "if your app publishes on behalf of
   accounts you do not own" - this project publishes exclusively to the
   creator's own account, added as a tester in step 2 above.

Do not "fix" `instagram_publish.py` by adding a TikTok-style pre-publish
gate (a `creator_info/query`-equivalent check called before every post) -
that would reintroduce a design the user explicitly rejected for
Instagram's different access model.

## Instagram permission-error heuristic (unverified assumption)

**Status: not yet performed** - `_check_meta_permission_error`'s detection
of a permission/access-tier rejection (matching substrings like
`"permission"`, `"advanced access"`, `"requires app review"` in a non-2xx
Meta response) is a best-effort heuristic built without a captured real
Meta error response - 06-RESEARCH.md never made a live API call this
session to confirm the exact shape of a real 403/permission error from the
Graph API. It should be empirically confirmed the same way "Kill-path
verification" above was confirmed: once real Instagram credentials exist
and a real publish attempt either succeeds (Standard Access sufficient) or
produces a real permission/access-tier error, compare the actual response
body against `_PERMISSION_ERROR_SUBSTRINGS` and update this section with
the observed error shape and a dated PASS/FAIL outcome, the same way
"Kill-path verification" was updated from "Status: not yet performed" to a
dated result after Phase 3's live test.

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

*Phase: 06-tiktok-instagram-auto-publish*
*Plans: 06-01 through 06-06 (TikTok/Instagram queue lifecycle, OAuth, upload/publish orchestration, kill_item, CLI wrappers), 06-07 (isolation + scope tests, this doc's TikTok/Instagram operator sections and Task Scheduler sibling-task wiring)*
