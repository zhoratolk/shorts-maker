# Phase 3: YouTube Scheduled Auto-Publish - Research

**Researched:** 2026-07-08
**Domain:** YouTube Data API v3 resumable upload + scheduled release, Windows-local periodic trigger mechanisms
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Titles/tags are generated **at make-shorts time** (during the interactive Claude Code session), same as today — NOT regenerated headlessly at publish time. Phase 3 only reads an already-finished `metadata.json`/equivalent per clip and uploads it as-is.
- **D-02 (rationale):** This means Phase 3 does **not** need the deferred headless-generation architecture (Ollama fallback / standalone Anthropic-SDK script, TAGS-02) — that remains deferred.
- **D-03:** Actual "going live" uses YouTube's native scheduled-publish: video is uploaded now with `status.privacyStatus: "private"` and `status.publishAt` set to the target slot — YouTube itself flips it public at that timestamp. This is NOT our own pause-then-cron-push-public logic.
- **D-04:** Pause/kill (PUB-04) means: for videos NOT YET uploaded, skip/hold them in the local queue. For videos already uploaded-and-scheduled on YouTube, "kill" = call the Data API to set `privacyStatus` back to `private` with no `publishAt` (cancels the scheduled release) before the `publishAt` timestamp passes.
- **D-05:** Two trigger paths, both required: (1) periodic auto-check roughly every 3 hours — check queue, upload+schedule next due item, notify in chat, no per-item confirmation once live mode opted in; (2) manual on-demand override — "выложи X сейчас" force-publishes a specific queued item immediately, same upload+schedule path.
- **D-06 (open technical question — THIS RESEARCH RESOLVES IT BELOW):** Exact trigger mechanism not locked. Two candidates to evaluate: (a) Claude Code harness self-waking (ScheduleWakeup/CronCreate-style, tied to a session) vs (b) standalone Windows Task Scheduler one-shot script (works without open session, can't post chat notification directly).
- **D-07:** `publishAt` slots come from a fixed daily grid (N slots/day at fixed times), not per-video manual dates. Next queued (lowest-numbered/oldest) finished short takes next free slot. Exact N/times are Claude's discretion.
- **D-08:** Upload uses a separate `upload_token.json` (own OAuth consent, scope `https://www.googleapis.com/auth/youtube.upload`), distinct from `youtube_analytics.py`'s existing read-only `token.json` (scopes `youtube.readonly` + `yt-analytics.readonly`). Reuses `load_credentials()`-style pattern (parameterized by scopes/token path) rather than inventing a new OAuth flow.
- **D-09 (rationale):** Smaller blast radius if one token leaks — directly relevant given this project's prior real leaked-data incident. `client_secret.json`/`token.json`/`upload_token.json` all stay gitignored.

### Claude's Discretion

- Exact trigger implementation (ScheduleWakeup vs Task Scheduler vs other) — see D-06.
- Exact number/timing of daily publish slots (D-07).
- Local queue file format/location (likely a manifest alongside existing `work/` conventions — planner to decide, consistent with idempotency manifest requirement PUB-05).
- Exact wording/format of the chat notification after an auto-publish.

### Deferred Ideas (OUT OF SCOPE)

- **Headless/API-based metadata (re)generation at publish time** — still deferred (TAGS-02 lineage); not needed since D-01 confirms metadata is baked in before the queue.
- **TikTok/Instagram publish** (PUB-06/07) — explicitly Phase 6, gated behind external app-review/audit; not discussed here.

</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| PUB-01 | Finished shorts queued with sequential local numbering | Queue/manifest design below (`## Architecture Patterns` → Local Queue Manifest); reuses filesystem-as-message-bus convention already used by `work/<stem>/` |
| PUB-02 | Scheduled auto-publish to YouTube via YouTube Data API, reusing existing OAuth client pattern | `videos.insert` resumable upload + `status.publishAt` documented below; `load_credentials()` reuse pattern confirmed against `scripts/youtube_analytics.py` |
| PUB-03 | Dry-run mode default; explicit opt-in before any platform goes live | Config-flag pattern (`publish.enabled: false` default) matches existing fail-open/opt-in conventions (`diarization.enabled`, `audio_fingerprint_enabled`) |
| PUB-04 | Pause/kill mechanism to halt scheduled publishing at any time | `videos.update` revert-to-private pattern documented below; queue-level pause flag for not-yet-uploaded items |
| PUB-05 | Idempotency/already-published manifest prevents duplicate posts on retry | Manifest schema below (`status` field + YouTube `video_id` recorded before any state transition) |

</phase_requirements>

## Summary

Phase 3 has almost no open design questions left after CONTEXT.md's D-01 through D-09 — this research focused on the one open technical question (D-06, trigger mechanism) plus nailing down the exact YouTube Data API v3 contract for resumable upload + scheduled release, since that is new API surface beyond the existing read-only `youtube_analytics.py` calls.

**YouTube Data API mechanics are straightforward and well-documented.** `videos.insert` with `part=snippet,status`, `status.privacyStatus="private"`, `status.publishAt=<RFC3339 timestamp>` schedules a video for automatic public release — YouTube's own infrastructure flips visibility at that timestamp, no polling or second API call needed to "go live." `MediaFileUpload(path, chunksize=-1, resumable=True)` from `googleapiclient.http` (already a transitive dependency of the installed `google-api-python-client==2.198.0`) handles the resumable protocol with built-in retry-on-interruption. Reverting a scheduled video to private (kill/pause per D-04) is a single `videos.update` call that re-sets `privacyStatus="private"` — critically, `publishAt` **cannot** be cleared by omission; it must be actively unset or the video stays on its original publish schedule (see Common Pitfalls). Required scope is confirmed as `https://www.googleapis.com/auth/youtube.upload` (narrowest scope that permits `videos.insert`/`videos.update`), matching D-08 exactly.

**Quota is not a practical constraint at this project's cadence.** `videos.insert` draws from its own separate daily quota bucket (100 calls/day, cost 1 unit/call as of a Dec 2025 Google-side reduction from the historical ~1600-unit cost) — independent of the shared 10,000-unit pool that `videos.update` and everything else draws from. At "roughly every 3 hours" (≈8 uploads/day max) plus occasional manual force-publishes, this project will never come close to either quota ceiling.

**D-06 (trigger mechanism) recommendation: Windows Task Scheduler running a one-shot Python script, writing a status/notification file that the next active Claude Code session surfaces in chat — NOT the harness's own session-tied self-wake mechanism as the primary driver.** Rationale in the dedicated section below. This is a hybrid of the two candidates, not a pure pick of (b): Task Scheduler does the mechanical "check queue, upload if due" work reliably regardless of whether any Claude Code session is open (a real requirement — this is a personal machine, sessions end when the laptop closes or the terminal is closed), while a lightweight chat-surfacing mechanism (append-only notification log + a prompt to read it) satisfies D-05's "notify in chat" requirement without depending on a session staying alive for 3+ hours.

**Primary recommendation:** Task Scheduler (`schtasks /create`, triggers every 3h, `python scripts/publish_queue.py`) does the actual upload/schedule work and writes to a small append-only `work/_publish/notifications.log`; the manual override path (`scripts/publish_queue.py --now <clip_id>`) is invoked directly by Claude Code inline when the user asks to force-publish something, going through the identical upload function. The next time a Claude Code session starts (or is already open), it reads any unread notification lines and reports them in chat — this matches the project's existing "filesystem as message bus" pattern used everywhere else in the codebase (`work/<stem>/*.json`).

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Queue management (numbering, status, idempotency manifest) | Local script / filesystem | — | Same filesystem-as-message-bus pattern as every other pipeline stage (`work/<stem>/*.json`); no server tier exists in this project |
| Periodic trigger (every ~3h check) | OS (Windows Task Scheduler) | Claude Code session (manual override only) | Must survive session death on a personal machine; Task Scheduler is the only mechanism in this stack that runs independent of an open Claude Code session |
| Upload + schedule (`videos.insert`) | YouTube Data API (external) | Local Python script | API call itself is YouTube's responsibility; script only constructs and sends the request |
| Pause/kill (`videos.update`) | YouTube Data API (external) + local queue flag | — | Two-part per D-04: local queue flag for not-yet-uploaded items, API call for already-scheduled items |
| Chat notification surfacing | Claude Code session (interactive) | Local log file (durable buffer) | Chat itself only exists inside a live session; the log file is the durable handoff so notifications aren't lost between sessions |
| OAuth credential storage | Local filesystem (gitignored) | — | No secrets manager in this project; matches existing `token.json` discipline |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `google-api-python-client` | 2.198.0 (installed; confirmed via `pip show`) [VERIFIED: local pip environment] | `videos().insert()`, `videos().update()` calls, `MediaFileUpload` | Already a project dependency (`requirements.txt`, used by `youtube_analytics.py`); no new package needed |
| `google-auth-oauthlib` | 1.4.0 (installed) [VERIFIED: local pip environment] | `InstalledAppFlow` OAuth consent flow | Already used by `load_credentials()` in `youtube_analytics.py` — reused as-is per D-08 |
| `google-auth-httplib2` | 0.4.0 (installed) [VERIFIED: local pip environment] | Transport binding for `google-auth` credentials with `googleapiclient` | Already a project dependency |

No new packages are required for this phase — `googleapiclient.http.MediaFileUpload` ships inside the already-installed `google-api-python-client` package; nothing new to add to `requirements.txt`.

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| stdlib `json` | builtin | Queue/manifest read-write | Matches project convention (no ORM/DB anywhere in this codebase) |
| stdlib `datetime` (RFC3339/ISO 8601 formatting) | builtin | `publishAt` timestamp construction | `datetime.isoformat()` + explicit `Z`/offset suffix; no `dateutil` needed for this narrow use |
| stdlib `argparse` | builtin | CLI wrapper for `publish_queue.py` | Matches every other `scripts/*.py` module's CLI-plus-importable-function pattern |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Windows Task Scheduler (`schtasks`) | `pywin32`-based Windows Service | A full service adds install/uninstall complexity and runs as SYSTEM by default (harder to reach the user's own OAuth token file and `work/` dir); Task Scheduler under the user's own account is simpler and sufficient for a personal machine |
| Windows Task Scheduler | Claude Code harness's own `schedule`/`loop` skill (cloud-agent cron or session-interval prompt runner) | These are real, available mechanisms in this environment, but `schedule` runs as a *cloud* agent (separate from this local, credential-bound machine — would need to ship `upload_token.json`/`client_secret.json` off-device, violating D-09's blast-radius rationale) and `loop` requires an open, continuously-running local session for its interval to fire, which contradicts "closed laptop" resilience. See dedicated D-06 section below. |
| Google's resumable upload raw HTTP protocol (manual chunked PUT) | `googleapiclient.http.MediaFileUpload(..., resumable=True)` | The high-level library already implements the chunked-upload session/resume logic; hand-rolling it duplicates library code for no benefit (see Don't Hand-Roll) |

**Installation:** No installation needed — all three core libraries are already installed and already in `requirements.txt` for `youtube_analytics.py`.

**Version verification:** Confirmed via `pip show google-api-python-client google-auth-oauthlib google-auth-httplib2` in the actual project `.venv`-equivalent environment on 2026-07-08. `pip index versions` also confirms `2.198.0`/`1.4.0` are current published releases (not stale training-data versions), and both packages have `requirements.txt` floors already satisfied (`>=2.100`, `>=1.2`).

## Package Legitimacy Audit

No new external packages are introduced by this phase — `videos.insert`/`videos.update`/`MediaFileUpload` are all part of the already-installed, already-`requirements.txt`-declared `google-api-python-client` (and its already-declared `google-auth-oauthlib`/`google-auth-httplib2` peers). These are the same packages `scripts/youtube_analytics.py` already imports and were presumably audited when Phase 1's analytics grounding was built. No `package-legitimacy check` run was needed since the package set is unchanged.

**Packages removed due to [SLOP] verdict:** none (no new packages)
**Packages flagged as suspicious [SUS]:** none (no new packages)

## Architecture Patterns

### System Architecture Diagram

```
[Task Scheduler, every ~3h]                [User, ad hoc]
        |                                        |
        v                                        v
  publish_queue.py --check              publish_queue.py --now <clip_id>
        |                                        |
        +------------------+---------------------+
                           |
                 [Local queue manifest]
                 work/_publish/queue.json
                 (sequential numbering,
                  status: queued/uploaded/
                  published/killed/paused)
                           |
              is publish.enabled=true (opt-in)?
                    /              \
                  no                yes
                   |                 |
         [log "dry-run, skipped"]   pick next due item
                                     (lowest queue number,
                                      status=queued,
                                      not paused)
                                          |
                                 load_credentials(
                                   client_secret.json,
                                   upload_token.json,
                                   [youtube.upload])
                                          |
                                 compute next free
                                 publishAt slot from
                                 fixed daily grid (D-07)
                                          |
                          MediaFileUpload(video_path,
                            resumable=True)
                                          |
                          youtube.videos().insert(
                            part="snippet,status",
                            body={
                              snippet: {title, description, tags},
                              status: {privacyStatus:"private",
                                       publishAt: <slot>}
                            },
                            media_body=media
                          ).execute()
                                          |
                          record {video_id, publishAt,
                                  status:"scheduled"}
                          into queue manifest (idempotency)
                                          |
                          append line to
                          work/_publish/notifications.log
                                          |
                                          v
                          [Claude Code session, next
                           time it's open, reads log,
                           reports "залил X, выйдет в HH:MM"]

[Pause/Kill path, any time]
        |
        v
  publish_queue.py --pause | --kill <clip_id>
        |
   status=queued (not yet uploaded)?
     yes -> flip queue status to "paused"/"killed", skip on next check
     no (already status=scheduled on YouTube)?
       -> youtube.videos().update(part="status",
            body={id, status:{privacyStatus:"private"}})
          (D-04: must NOT include publishAt — see Pitfall 2)
       -> record status="killed" in manifest
```

### Recommended Project Structure
```
scripts/
├── publish_queue.py     # new: queue management + upload/schedule/kill logic, CLI + importable functions
work/
├── _publish/
│   ├── queue.json        # manifest: sequential-numbered queue entries + status + video_id (PUB-01, PUB-05)
│   └── notifications.log # append-only chat-notification buffer (D-06 hybrid trigger)
upload_token.json          # gitignored, scope youtube.upload only (D-08)
```

### Pattern 1: Resumable Upload with Scheduled Release
**What:** Upload a finished clip as `private` with a future `publishAt`, letting YouTube auto-publish it.
**When to use:** Every queued item's actual publish step (both the periodic-check path and the manual-override path — same function, D-05 requires no divergent logic between the two triggers).
**Example:**
```python
# Source: https://developers.google.com/youtube/v3/guides/uploading_a_video
# Source: https://developers.google.com/youtube/v3/docs/videos/insert
from googleapiclient.http import MediaFileUpload

def upload_and_schedule(youtube_service, video_path: str, title: str, description: str,
                         tags: list[str], publish_at_rfc3339: str) -> str:
    """Uploads video_path as private, scheduled to go public at publish_at_rfc3339.
    Returns the new video's id. publish_at_rfc3339 must be an ISO 8601 / RFC3339
    timestamp (e.g. "2026-07-09T09:00:00Z") in the future - a past timestamp
    publishes immediately instead of scheduling (see Common Pitfalls).
    """
    body = {
        "snippet": {"title": title, "description": description, "tags": tags},
        "status": {
            "privacyStatus": "private",   # required: publishAt only settable while private
            "publishAt": publish_at_rfc3339,
            "selfDeclaredMadeForKids": False,
        },
    }
    media = MediaFileUpload(video_path, chunksize=-1, resumable=True)
    request = youtube_service.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        status, response = request.next_chunk()  # resumable protocol handles retry internally
    return response["id"]
```

### Pattern 2: Reverting a Scheduled Video (Pause/Kill)
**What:** Cancel a pending scheduled release for a video already uploaded to YouTube.
**When to use:** D-04's "kill already-uploaded-and-scheduled" case — user pauses/kills after the upload already happened but before `publishAt` passes.
**Example:**
```python
# Source: https://developers.google.com/youtube/v3/docs/videos (status.publishAt field notes)
def cancel_scheduled_release(youtube_service, video_id: str) -> None:
    """Reverts a scheduled-but-not-yet-public video back to plain private,
    with no publishAt - cancels the pending auto-publish. Per the API docs,
    status.privacyStatus MUST be re-sent as "private" alongside this update
    even though it's already private, or the update is rejected.
    """
    youtube_service.videos().update(
        part="status",
        body={
            "id": video_id,
            "status": {"privacyStatus": "private"},  # omitting publishAt here does NOT clear it - see Pitfall 2
        },
    ).execute()
```

### Pattern 3: Reusing `load_credentials` for a Second, Narrower Token
**What:** Call the existing generic OAuth helper with upload-only scope and a separate token file.
**When to use:** Any place `publish_queue.py` needs an authenticated `youtube` Data API service object.
**Example:**
```python
# Source: scripts/youtube_analytics.py (existing code, reused verbatim per D-08)
from scripts.youtube_analytics import load_credentials
from googleapiclient.discovery import build

UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"

credentials = load_credentials(
    client_secret_path="client_secret.json",
    token_path="upload_token.json",   # separate file from token.json (D-08/D-09)
    scopes=[UPLOAD_SCOPE],
)
youtube_service = build("youtube", "v3", credentials=credentials)
```

### Anti-Patterns to Avoid
- **Building a custom pause-then-push-public scheduler:** D-03 explicitly rejects this — YouTube's own `publishAt` mechanism already does it server-side; a custom cron that flips `privacyStatus` to public at the right time duplicates YouTube's own infrastructure and adds a new failure mode (script must run at the exact moment, no grace for downtime).
- **Treating chat notification as the only durable record of what happened:** if a periodic check runs while no Claude Code session is open, "notify in chat" has nowhere to go. The log-file buffer is not optional — it's the difference between "notification delayed until next session" and "notification silently lost."
- **Clearing `publishAt` by omitting the field on `videos.update`:** per official docs, `status.publishAt` is only mutable while going from a state where it's unset to set (or on the initial insert) — trying to "unset" it by leaving it out of an update body does not clear an already-scheduled `publishAt`. The correct kill mechanism is `privacyStatus: "private"` sent alone in the update body (see Pitfall 2).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Resumable/chunked upload protocol | Custom chunked-PUT-with-resume logic against the raw upload endpoint | `googleapiclient.http.MediaFileUpload(path, resumable=True)` | Already implements session-URI tracking, chunk-size negotiation (256 KB multiples), and resume-from-last-byte on interruption; hand-rolling duplicates well-tested library code |
| OAuth token caching/refresh | New OAuth flow logic | `scripts/youtube_analytics.py::load_credentials` (parameterized, reused per D-08) | Already handles the InstalledAppFlow browser consent + token refresh + token-file round-trip; the only change needed is a different `token_path`/`scopes` argument |
| "Go live at time X" scheduling | A cron/Task-Scheduler job that flips `privacyStatus` to `public` at the target minute | `status.publishAt` on the video resource itself | YouTube's own infrastructure performs the flip server-side with no local script needing to be running at the exact moment — matches D-03 exactly |
| Retry/backoff on transient upload failures | Custom retry loop | The resumable-upload sample's documented pattern: catch `HttpError`/`socket.error` on `next_chunk()`, retry with exponential backoff on 500/502/503/504, up to a bounded attempt count [CITED: developers.google.com/youtube/v3/guides/using_resumable_upload_protocol] | This is the officially documented approach for exactly this API; no need to invent a different retry policy |

**Key insight:** Almost everything hard about "scheduled publish" (the actual timed release) is already solved server-side by YouTube's `publishAt` field — the local code's job shrinks to "upload once, set two status fields correctly, track state so it isn't repeated." Most hand-rolling risk in this phase is in the *queue/idempotency* layer, which is genuinely new local code (no library solves "don't double-upload the same clip" for you) — see Common Pitfalls below for that layer specifically.

## D-06: Trigger Mechanism Recommendation (Windows Task Scheduler + notification-log hybrid)

### Option (a): Claude Code harness self-wake (session-tied)

This environment does have real periodic/scheduled-execution primitives — the `loop` skill (recurring interval prompt runner within a session) and the `schedule` skill (cloud-hosted cron agents). Both were checked against this specific requirement:

- **`loop`**: requires an actively running local Claude Code session for the interval timer to keep firing. If the user closes the terminal, puts the laptop to sleep, or simply isn't running Claude Code, the loop stops — "roughly every 3 hours" becomes "roughly every 3 hours, but only while I happen to have a session open," which does not match the user's stated expectation of hands-off background behavior on a machine they might not be actively using.
- **`schedule`**: runs as a **cloud** agent, not on this local Windows machine. That means the video files (already-rendered `.mp4`s under local `output_dir`) and both OAuth token files (`upload_token.json`, `client_secret.json`) would need to be reachable from a remote environment — either uploaded to cloud storage or the credentials copied off-device. This directly conflicts with D-09's rationale (smaller blast radius after a prior real leaked-data incident); shipping the upload-scoped token to a cloud runner increases blast radius, it doesn't shrink it. `PROJECT.md`'s "Локальность" constraint (pipeline stays on-device, no persistent cloud backend beyond the platforms' own APIs) also argues against this.

**Verdict on (a):** Rejected as the primary driver. Session-tied timers cannot guarantee the cadence on a personal machine that isn't always running Claude Code, and the cloud-cron alternative violates this project's explicit locality and credential-blast-radius constraints.

### Option (b): Windows Task Scheduler, one-shot script

- `schtasks /create /sc hourly /mo 3 /tn "shorts-maker-publish" /tr "python D:\shorts-maker\scripts\publish_queue.py --check"` (or an equivalent trigger set up once, interactively, during phase execution) runs independent of any Claude Code session — survives terminal closure, reboots (with `/ru` and appropriate "run whether user is logged on or not" settings if desired), and doesn't need the laptop to be "in a Claude Code conversation" at all.
- Confirmed available on this machine: `schtasks` is a built-in Windows command (verified via `schtasks /?` in this session).
- The one real gap: Task Scheduler cannot post directly into an interactive Claude Code chat — there is no chat surface to write to from a detached background process.

**Verdict on (b) alone:** Solves the reliability half of D-05 completely, but leaves "notify in chat" unaddressed as stated.

### Recommended hybrid

Task Scheduler (option b) drives the actual periodic check-and-publish mechanics, exactly as D-06's option (b) describes — this is the reliable, session-independent half. To close the notification gap, `publish_queue.py` appends a short structured line to `work/_publish/notifications.log` every time it uploads something (or every time it finds nothing due, if verbose logging is wanted — recommend: only log on actual uploads/errors, not on no-op checks, to avoid a noisy log). The **next time a Claude Code session is active** — which, given this project is a `/make-shorts`-driven interactive workflow, will typically be within the same day the creator next processes a new recording — the assistant checks for unread lines in that log (e.g. tracking a `last_read_line` marker file, or simply diffing against what was already reported) and relays them: *"залил {N}, выйдет в {HH:MM}"*, one line per unread upload event, satisfying D-05's notification requirement without requiring a session to be continuously open for 3+ hours.

This is not a compromise that weakens either locked decision — D-05 only requires that the *behavior* (periodic check + act + eventually notify) happens; it does not require the notification to be synchronous with the upload event. The manual on-demand path (`--now <clip_id>`) is invoked directly from within an active Claude Code session when the user asks for it, so that path's notification is immediate and synchronous by construction (the session is already open, by definition, when the user is typing the request) — only the *periodic* path needs the log-buffer bridge.

**Confidence:** MEDIUM. The API mechanics (upload/schedule/kill) are HIGH confidence (official docs, directly fetched). The trigger recommendation itself is a reasoned architecture decision under real constraints (session liveness, credential locality) rather than a documented "best practice" from an external source — flagged as an assumption for discuss-phase/planner sign-off if the user wants to weigh in on log-polling cadence (e.g. "check unread notifications at the start of every session" vs. some other cadence).

## Common Pitfalls

### Pitfall 1: `publishAt` in the past silently publishes immediately instead of scheduling
**What goes wrong:** If the computed "next free slot" from the fixed daily grid (D-07) accidentally resolves to a timestamp already in the past (e.g. a timezone bug, or the grid-slot computation running right as a slot boundary passes), YouTube publishes the video immediately instead of holding it private-until-`publishAt` [CITED: developers.google.com/youtube/v3/docs/videos — "If your request schedules a video to be published at some time in the past, the video will be published right away."].
**Why it happens:** Ambiguous local-time-vs-UTC handling, or grid-slot math that doesn't defensively check "is this slot still in the future" before submitting.
**How to avoid:** Always construct `publishAt` in UTC (`datetime.now(timezone.utc)` based math, explicit `Z` suffix), and add an explicit guard in the slot-picker: if the computed next slot is not strictly in the future, roll forward to the next grid slot instead of submitting a past/near-past timestamp.
**Warning signs:** A "dry-run" test that computes a slot time close to "now" without a forward-looking margin.

### Pitfall 2: Omitting `publishAt` on `videos.update` does not cancel a scheduled release
**What goes wrong:** The natural instinct for "cancel the schedule" is to just not include `publishAt` in the update body, assuming that means "leave/clear it." Per Data API docs, `status.publishAt` "can only be set if the video's privacy status is private and the video has never been published" — the field's write-path is one-directional (private+unset → private+set, at insert or a subsequent update), not designed as a general clear/reset toggle via omission.
**Why it happens:** Most REST APIs treat "field absent in PATCH-like update body" as "no change" — which is actually correct here too (that's exactly why omitting it doesn't clear it). The mistake is assuming omission clears it, when instead omission just leaves the existing schedule untouched.
**How to avoid:** D-04's kill path must explicitly reason about this: re-sending `privacyStatus: "private"` (required to be resent even though already private) is what keeps the video from ever auto-publishing — the point isn't to "clear publishAt," it's that a `private` video with any `publishAt` (past or future) simply never flips public on its own once you've confirmed it's staying private; verify empirically during implementation (via a real test video, not just docs) exactly which combination the API accepts, since the docs are not fully explicit on whether a bare `{"privacyStatus": "private"}` update leaves a *stale* `publishAt` in place (harmless, since the video is private) or errors.
**Warning signs:** A "killed" video that still transitions to public at its original scheduled time — this must be caught by a post-kill verification step (re-fetch `videos.list(part="status")` and confirm `privacyStatus == "private"`) before the manifest is marked `killed`.

### Pitfall 3: Idempotency manifest race between "upload started" and "upload confirmed"
**What goes wrong:** If the manifest only records "published" *after* `videos.insert` fully succeeds, a crash mid-upload (network drop, script killed, machine sleeps) leaves no record that an upload was attempted — the next periodic check sees the item still `queued` and re-uploads it, creating a duplicate video on YouTube. This is exactly the failure PUB-05 exists to prevent.
**Why it happens:** Naive "write manifest entry after the API call returns" ordering has a gap between "upload in flight" and "state recorded."
**How to avoid:** Write a manifest entry with status `uploading` (or `attempting`) *before* calling `videos.insert`, and only flip to `scheduled`/`published` after `.execute()` returns a `video_id`. On the next run, an item stuck in `uploading` needs explicit human/manifest-level reconciliation (check YouTube directly for a video with a matching identifying marker — e.g. embed the local clip's sequential number or a UUID in the description — before blindly retrying) rather than silently re-uploading. This reconciliation step is the actual hard part of PUB-05 and deserves its own planned task, not just a status enum.
**Warning signs:** Any test that only covers the "happy path" retry (upload succeeds, manifest updates) without a crash-mid-upload simulation.

### Pitfall 4: `googleapiclient` quota/`HttpError` on quota exceeded (`quotaExceeded` / 403)
**What goes wrong:** Although quota is not expected to be hit at this project's cadence (see Summary), a bug that fires the periodic check far more often than every 3 hours (e.g. a Task Scheduler misconfiguration creating overlapping triggers) could burn through the 100/day upload quota bucket and start failing with HTTP 403 `quotaExceeded`.
**Why it happens:** Duplicate/overlapping scheduled tasks, or a bug that doesn't debounce "check" invocations.
**How to avoid:** The queue manifest's own "already uploaded, only one due item per check" logic is itself a natural debounce (each check should upload at most one item per D-05's "one at a time" cadence) — as long as the manifest correctly prevents re-processing an already-`scheduled` item, quota exhaustion would require either a manifest bug or a genuinely duplicated Task Scheduler entry. Verify only one Task Scheduler entry exists for this job (`schtasks /query /tn "shorts-maker-publish"`) as part of setup verification.
**Warning signs:** Errors logged with `quotaExceeded` reason in the notification log — treat this itself as a signal the manifest's dedupe logic may have failed, not just as "wait until quota resets."

## Code Examples

Verified patterns from official sources (also see `## Architecture Patterns` above for the primary upload/kill code):

### Constructing an RFC3339 `publishAt` from a fixed daily grid
```python
# Source: stdlib datetime, RFC3339 format per
# https://developers.google.com/youtube/v3/docs/videos (status.publishAt: "ISO 8601 datetime format")
from datetime import datetime, timedelta, timezone

DAILY_SLOTS_UTC = ["09:00", "15:00", "20:00"]  # example 3-slot grid, exact N/times at Claude's discretion (D-07)

def next_free_slot(already_scheduled: list[str], now: datetime | None = None) -> str:
    """Returns the next free RFC3339 UTC timestamp from the fixed daily grid,
    skipping any slot already present in already_scheduled (ISO strings) and
    any slot not strictly in the future (Pitfall 1)."""
    now = now or datetime.now(timezone.utc)
    candidate_day = now.date()
    while True:
        for hhmm in DAILY_SLOTS_UTC:
            hour, minute = map(int, hhmm.split(":"))
            candidate = datetime(candidate_day.year, candidate_day.month, candidate_day.day,
                                  hour, minute, tzinfo=timezone.utc)
            candidate_iso = candidate.isoformat().replace("+00:00", "Z")
            if candidate > now and candidate_iso not in already_scheduled:
                return candidate_iso
        candidate_day += timedelta(days=1)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| `videos.insert` cost ~1600 quota units/call | `videos.insert` costs ~100 quota units/call, drawn from its own separate 100-calls/day bucket rather than the shared 10,000-unit pool | Google-side change, effective around Dec 4, 2025 per Google's API revision history [CITED: multiple secondary sources corroborating the same date/numbers; not independently re-confirmed against Google's raw revision-history page text in this session] | Practically irrelevant at this project's ≈8 uploads/day cadence either way, but worth knowing the old "6 uploads/day max" folklore floating around older blog posts/tutorials is stale |

**Deprecated/outdated:** None specific to this API surface beyond the quota-cost change above — `videos.insert`/`videos.update`/`MediaFileUpload` are all current, non-deprecated API surface as of this research date.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | A bare `{"status": {"privacyStatus": "private"}}` update body, with no `publishAt` key at all, is sufficient to prevent an already-scheduled video from auto-publishing (rather than needing some other explicit "clear schedule" call) | Pitfall 2 / Pattern 2 | If wrong, the kill path silently fails to cancel a scheduled release — a video the user believed was killed goes public anyway. **Must be empirically verified with a real test video during implementation**, not just trusted from docs interpretation, before this path ships live (opt-in gate per PUB-03 makes this lower-stakes, but the pause/kill guarantee itself (PUB-04) is safety-critical and deserves a manual verification step in the plan). |
| A2 | The Dec-2025 quota-cost reduction (1600→100 units) for `videos.insert` is accurate as stated by secondary sources | State of the Art | Low risk either way — even at the old 1600-unit cost, 10000/1600 ≈ 6 uploads/day would still cover this project's "one per ~3h check" cadence most days, just with less headroom for the manual-override path stacking on the same day. Not a blocking risk, just worth the planner knowing the number might be off. |
| A3 | Task Scheduler triggers configured via `schtasks /create` will reliably fire even through sleep/hibernate cycles typical of a personal laptop, without additional "wake to run" configuration | D-06 recommendation | If wrong, the periodic cadence becomes unreliable on a machine that sleeps a lot — mitigated by the manual on-demand override (D-05 path 2) always being available as a backstop, and by Task Scheduler's own "wake the computer to run this task" checkbox being a known, documented option the planner should include in setup instructions. |

## Open Questions

1. **Exact daily grid size/times (D-07 discretion)**
   - What we know: "roughly every 3 hours" was the *check* cadence for path 1 (D-05), not necessarily the *publish slot* cadence (D-07) — these are two separate grids that happen to plausibly align (e.g. checking every 3h and publishing on a 3-slot or so daily grid), but CONTEXT.md doesn't force them to be the same number.
   - What's unclear: whether the planner should make the check-interval and the publish-grid-interval the same cadence (simpler mental model) or decouple them (e.g. check every 3h but only 2-3 fixed publish slots/day, matching typical audience-online-time patterns for a gaming channel).
   - Recommendation: default to aligning them for simplicity (e.g. 3 fixed daily slots roughly matching the 3-hour check granularity during expected active hours) unless the planner has a reason to decouple; this is explicitly Claude's discretion per CONTEXT.md, not a user requirement to satisfy exactly.

2. **Reconciliation logic for a manifest entry stuck in `uploading` (Pitfall 3)**
   - What we know: the failure mode (crash mid-upload) and the general shape of the fix (embed an identifying marker, check YouTube before retrying) are clear.
   - What's unclear: whether `videos.list` filtered by the uploads playlist (reusing `list_uploaded_videos` from `youtube_analytics.py`) is a sufficient reconciliation check, or whether search-by-title is needed as a fallback given YouTube's list-by-id-only search constraints for very recent uploads.
   - Recommendation: planner should scope this as its own explicit task (not folded silently into the main upload task) given its safety-criticality for PUB-05.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `google-api-python-client` | PUB-02 upload/schedule/kill calls | Yes | 2.198.0 | — |
| `google-auth-oauthlib` | OAuth consent flow (`load_credentials` reuse) | Yes | 1.4.0 | — |
| `google-auth-httplib2` | OAuth transport binding | Yes | 0.4.0 | — |
| Windows Task Scheduler (`schtasks`) | D-06 periodic trigger | Yes | Built into Windows 11 | — |
| `client_secret.json` (OAuth desktop client) | Any OAuth flow at all | Not verified this session — gitignored, presumed present from Phase 1's `youtube_analytics.py` setup | — | If absent, the very first `upload_token.json` consent flow will fail at `flow.run_local_server()`; not a Phase 3-specific gap since `youtube_analytics.py` already depends on the same file |
| Internet connectivity to `www.googleapis.com` / `upload.youtube.com` | Every upload/schedule/kill call | Not tested this session (no live API call made — dry-run/research only, per instructions not to touch real credentials) | — | Fail-open per project convention: `publish_queue.py`'s periodic check should catch network errors and log-and-skip, not crash, matching the existing pattern in `fetch_channel_performance`'s try/except around the Analytics half |

**Missing dependencies with no fallback:** None identified — all required libraries are already installed.

**Missing dependencies with fallback:** Network/credential availability at actual publish time — already covered by the project's existing fail-open convention; the planner should carry this same try/except-and-log pattern into `publish_queue.py`.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 7.4.0+ (already in `requirements-dev.txt`) |
| Config file | `pyproject.toml` (`[tool.pytest.ini_options]`: `pythonpath=["."]`, `testpaths=["tests"]`, `integration` marker registered) |
| Quick run command | `pytest tests/test_publish_queue.py -x` (new test file, mirrors 1:1 module-naming convention already used by every other `scripts/*.py`↔`tests/test_*.py` pair) |
| Full suite command | `pytest` (repo root) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PUB-01 | Queue assigns sequential local numbering to new finished shorts | unit | `pytest tests/test_publish_queue.py::test_sequential_numbering -x` | ❌ Wave 0 |
| PUB-02 | Upload+schedule call constructs correct `videos.insert` body (`privacyStatus`, `publishAt`, `snippet`) given a fake/mock YouTube service (matching the `FakeVideosService`-style test doubles already used in `tests/test_youtube_analytics.py`) | unit | `pytest tests/test_publish_queue.py::test_upload_and_schedule_body -x` | ❌ Wave 0 |
| PUB-03 | Dry-run default: with `publish.enabled=false` (or equivalent flag), no upload call is attempted at all | unit | `pytest tests/test_publish_queue.py::test_dry_run_default_no_upload -x` | ❌ Wave 0 |
| PUB-04 | Pause flips not-yet-uploaded queue item to skipped; kill on an already-scheduled item calls `videos.update` with the correct revert body | unit | `pytest tests/test_publish_queue.py::test_pause_kill -x` | ❌ Wave 0 |
| PUB-05 | Re-running the check after a simulated crash (manifest entry left in `uploading` state) does not blindly re-upload | unit | `pytest tests/test_publish_queue.py::test_idempotent_retry_no_duplicate -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/test_publish_queue.py -x`
- **Per wave merge:** `pytest` (full suite)
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/test_publish_queue.py` — covers PUB-01 through PUB-05, following the existing `FakeVideosService`/`FakeChannelsService`-style fake-service test-double pattern already established in `tests/test_youtube_analytics.py` (no new mocking library needed — this project has never used `unittest.mock`/`pytest-mock` for the YouTube API surface, preferring hand-written fakes; stay consistent)
- [ ] No new shared fixtures needed beyond what `tests/test_youtube_analytics.py` already demonstrates (fake service classes are copy-adaptable, not shared via `conftest.py` currently — check whether this phase's plan wants to extract a shared fake-service fixture, given two files will now need similar fakes)
- [ ] Framework install: none — pytest already installed and configured

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | Yes | OAuth 2.0 installed-app flow via `google-auth-oauthlib`'s `InstalledAppFlow` — do not hand-roll token exchange; reuse `load_credentials` as locked (D-08) |
| V3 Session Management | No | No web session/cookie surface in this CLI-only project |
| V4 Access Control | Partial | Scope-minimization is the access-control mechanism here: `upload_token.json` must be requested with **only** `youtube.upload`, never a broader scope like plain `youtube` or `youtubepartner`, even though those would also work — D-08 already locks this, this is a build-time verification item (grep the actual `scopes=[...]` argument passed at the `publish_queue.py` call site) |
| V5 Input Validation | Yes | Queue manifest entries (title/description/tags sourced from `metadata.py` output) should be validated for YouTube's own field constraints before submission (title ≤100 chars, description ≤5000 chars, tags total ≤500 chars) — a validation failure here should fail the specific queue item, not crash the whole periodic check (fail-open at the item level, not silent data corruption) |
| V6 Cryptography | No custom crypto | Token storage is plaintext JSON on local disk, matching the existing `token.json` precedent exactly — no *new* crypto decision needed here since this phase explicitly follows the established pattern rather than introducing anything new; note this is the same trust model as the rest of the project (local machine, not a shared/multi-tenant environment) |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Leaked `upload_token.json`/`client_secret.json` (this project's prior real incident) | Information Disclosure | Gitignore discipline (already required per D-09) + scope minimization (upload-only token, not a broad token) shrinks blast radius if leaked; a leaked upload-only token can post videos as private-scheduled but cannot read analytics/channel data the read-only token can |
| Duplicate/repeated upload on retry (PUB-05's exact concern) | — (not classic STRIDE, but a real reliability/trust threat: unwanted public duplicate content) | Idempotency manifest with `uploading` intermediate state (Pitfall 3) + a reconciliation check against YouTube's actual video list before any retry |
| A malformed/adversarial `metadata.json` (e.g. from a corrupted or manually-edited queue file) causing an unintended `publishAt`/`privacyStatus` combination that publishes something prematurely | Tampering | Validate the constructed API request body against expected shape/types before calling `.execute()`; treat the local queue manifest as trusted-but-verify (it's local-only, not attacker-controlled in the traditional sense, but a bug that writes a bad manifest entry should fail loud rather than silently upload with wrong settings) |

## Sources

### Primary (HIGH confidence)
- [YouTube Data API — Videos: insert](https://developers.google.com/youtube/v3/docs/videos/insert) - request format, required scopes, quota cost (fetched directly)
- [YouTube Data API — Upload a Video guide](https://developers.google.com/youtube/v3/guides/uploading_a_video) - `MediaFileUpload` usage, scope example, retry-strategy notes (fetched directly)
- [YouTube Data API — Videos resource reference](https://developers.google.com/youtube/v3/docs/videos) - `status.publishAt`/`status.privacyStatus` field semantics, past-date behavior (fetched directly)
- [YouTube Data API — Quota Calculator](https://developers.google.com/youtube/v3/determine_quota_cost) - `videos.insert`/`videos.update` quota costs, separate 100/day upload bucket (fetched directly)
- `scripts/youtube_analytics.py` (this repo) - existing `load_credentials` pattern, reused per D-08 [VERIFIED: read directly from repo]
- `scripts/metadata.py`, `scripts/config.py`, `tests/test_youtube_analytics.py` (this repo) - existing metadata schema, config-dataclass convention, fake-service test-double pattern [VERIFIED: read directly from repo]
- `pip show` / `pip index versions` output for `google-api-python-client`, `google-auth-oauthlib`, `google-auth-httplib2` [VERIFIED: local environment command output]
- `schtasks /?` output confirming Windows Task Scheduler CLI availability on this machine [VERIFIED: local environment command output]

### Secondary (MEDIUM confidence)
- WebSearch results corroborating the Dec-2025 `videos.insert` quota-cost reduction (1600→100 units) across multiple independent blog/aggregator sources — not independently re-verified against Google's raw API revision-history changelog text itself in this session [CITED: multiple secondary sources, cross-referenced against each other]

### Tertiary (LOW confidence)
- None used as load-bearing claims — where WebFetch could not answer a question directly from official docs (e.g. the full OAuth scopes enumeration page), the equivalent information was cross-confirmed instead from the `videos/insert` docs page itself, which is authoritative and was fetched directly.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - all libraries already installed and in use in this exact repo; versions confirmed via direct `pip` inspection, not assumed
- Architecture (upload/schedule/kill API mechanics): HIGH - every claim fetched directly from `developers.google.com` official docs pages in this session
- Architecture (D-06 trigger recommendation): MEDIUM - reasoned from this project's concrete constraints (personal machine, locality, credential blast-radius) rather than an external documented "best practice"; flagged with its own confidence note in the D-06 section
- Pitfalls: HIGH for Pitfall 1/2/4 (directly sourced from official docs field-semantics text), MEDIUM for Pitfall 3 (general software-engineering idempotency pattern, not YouTube-specific, but directly applicable and necessary for PUB-05)

**Research date:** 2026-07-08
**Valid until:** 2026-08-08 (30 days) — YouTube Data API quota/field semantics are stable, but the Dec-2025 quota-cost change shows Google does adjust quota costs without much fanfare; re-verify quota costs specifically if this phase's execution slips past that window.
