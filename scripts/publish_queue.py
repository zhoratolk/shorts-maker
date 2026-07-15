from __future__ import annotations

"""Local publish-queue + upload/schedule/kill layer.

Tracks finished shorts through the local queue manifest (sequential
numbering, idempotent enqueue keyed on clip_id) and, in later plans, drives
the YouTube Data API upload/schedule/kill calls. This module stays
import-safe with the standard library only - no top-level Google-API-client
import (that arrives as a deferred, inside-function import once the upload
path is added).
"""

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# Status enum - the full lifecycle a queue entry can move through.
QUEUED = "queued"
UPLOADING = "uploading"
SCHEDULED = "scheduled"
PUBLISHED = "published"
KILLED = "killed"
PAUSED = "paused"

VALID_STATUSES = frozenset({QUEUED, UPLOADING, SCHEDULED, PUBLISHED, KILLED, PAUSED})

# Queue manifest + notification-log locations (paths only - no file is
# created by importing this module).
DEFAULT_QUEUE_PATH = "work/_publish/queue.json"
DEFAULT_NOTIFICATIONS_PATH = "work/_publish/notifications.log"

# D-08/D-09 originally picked the narrower `youtube.upload` scope for smaller
# blast radius if this token leaks (separate from the read-only token.json
# used by youtube_analytics.py). A live kill-path test (2026-07-08) proved
# that scope insufficient: videos.update (used by cancel_scheduled_release/
# kill_item) returns 403 insufficientPermissions under `youtube.upload` alone.
# Without videos.update, the pause/kill safety mechanism cannot function, so
# the scope was deliberately widened to cover it.
UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube"

# YouTube's own field-length limits (V5 input validation, 03-RESEARCH
# Security Domain) - a violation fails this one queue item, not the whole
# run.
MAX_TITLE_LENGTH = 100
MAX_DESCRIPTION_LENGTH = 5000
MAX_TAGS_TOTAL_LENGTH = 500
# Explicit video category improves search/browse classification for Shorts
# (uploads without one land in the default "People & Blogs"). 20 = Gaming.
GAMING_CATEGORY_ID = "20"


def load_queue(path: str = DEFAULT_QUEUE_PATH) -> dict[str, Any]:
    """Loads the queue manifest, fail-open: a missing file yields an empty
    queue rather than crashing (project convention - see AudioEnergy/
    Diarization fail-open pattern). Malformed JSON is NOT caught here - a
    corrupt manifest should surface as a hard error rather than silently
    reset to empty (that would re-process everything, see T-03-03).
    """
    queue_file = Path(path)
    if not queue_file.exists():
        return {"entries": []}
    return json.loads(queue_file.read_text(encoding="utf-8"))


def save_queue(queue: dict[str, Any], path: str = DEFAULT_QUEUE_PATH) -> None:
    """Writes the queue manifest as human-readable UTF-8 JSON, creating
    parent directories as needed (matches youtube_analytics.py's cache-
    writing style: ensure_ascii=False, indent=2)."""
    queue_file = Path(path)
    queue_file.parent.mkdir(parents=True, exist_ok=True)
    queue_file.write_text(
        json.dumps(queue, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def enqueue(
    queue: dict[str, Any],
    clip_id: str,
    video_path: str,
    metadata_path: str,
    title: str,
    description: str,
    tags: list[str],
) -> dict[str, Any]:
    """Appends a new entry to queue["entries"] with a sequential seq number
    (max existing seq + 1, starting at 1) and status=QUEUED. Idempotent on
    clip_id: re-enqueuing an already-present clip_id is a no-op that returns
    the existing entry unchanged - sequential numbering stays stable and
    inspectable (PUB-01), and a duplicate enqueue can't renumber or
    double-queue a clip (T-03-01).

    title/description/tags are taken verbatim from the already-finished
    per-clip metadata produced at make-shorts time (D-01/D-02) - this
    function never regenerates metadata.
    """
    for entry in queue["entries"]:
        if entry["clip_id"] == clip_id:
            return entry

    next_seq = max((entry["seq"] for entry in queue["entries"]), default=0) + 1
    now = datetime.now(timezone.utc).isoformat()
    entry = {
        "seq": next_seq,
        "clip_id": clip_id,
        "video_path": video_path,
        "metadata_path": metadata_path,
        "title": title,
        "description": description,
        "tags": tags,
        "status": QUEUED,
        "video_id": None,
        "publish_at": None,
        "enqueued_at": now,
        "updated_at": now,
    }
    queue["entries"].append(entry)
    return entry


def collect_scheduled_slots(queue: dict[str, Any]) -> list[str]:
    """Returns the publish_at values of every entry currently in SCHEDULED
    status - the set of grid slots already spoken for, so next_free_slot
    never double-books two clips onto the same slot.
    """
    return [
        entry["publish_at"]
        for entry in queue["entries"]
        if entry["status"] == SCHEDULED and entry["publish_at"] is not None
    ]


def next_free_slot(
    daily_slots_utc: list[str],
    already_scheduled: list[str],
    now: datetime | None = None,
) -> str:
    """Returns the next RFC3339 UTC timestamp (Z-suffixed) from the fixed
    daily grid such that the slot is STRICTLY in the future relative to
    `now` and not already present in `already_scheduled`.

    All math is UTC-only (no local-time ambiguity) - candidates are built
    from each HH:MM in daily_slots_utc across the current day, then
    subsequent days, until a free future slot is found. A slot equal to or
    earlier than `now` is always skipped (Pitfall 1: a past/near-past
    publishAt makes YouTube publish immediately instead of scheduling).
    """
    now = now or datetime.now(timezone.utc)
    candidate_day = now.date()
    while True:
        for hhmm in daily_slots_utc:
            hour, minute = map(int, hhmm.split(":"))
            candidate = datetime(
                candidate_day.year, candidate_day.month, candidate_day.day,
                hour, minute, tzinfo=timezone.utc,
            )
            candidate_iso = candidate.isoformat().replace("+00:00", "Z")
            if candidate > now and candidate_iso not in already_scheduled:
                return candidate_iso
        candidate_day += timedelta(days=1)


def build_insert_body(
    title: str, description: str, tags: list[str], publish_at: str, seq: int
) -> dict[str, Any]:
    """Builds the exact videos.insert request body: snippet{title,
    description, tags} + status{privacyStatus:"private", publishAt,
    selfDeclaredMadeForKids:False}. privacyStatus is hardcoded, never
    derived from mutable input, so a bad manifest field can't force an
    immediate public post (T-03-06).

    Embeds a stable machine-readable marker for the local seq into the
    description (a trailing queue-id tag line) so Plan 03's reconciliation
    can match a YouTube video back to a local queue entry (Pitfall 3).

    Raises ValueError if title/description/tags exceed YouTube's field
    limits - a violation must fail only this item, not the whole run
    (V5 input validation, 03-RESEARCH Security Domain).
    """
    if len(title) > MAX_TITLE_LENGTH:
        raise ValueError(
            f"title exceeds YouTube's {MAX_TITLE_LENGTH}-char limit ({len(title)} chars)"
        )
    if len(description) > MAX_DESCRIPTION_LENGTH:
        raise ValueError(
            f"description exceeds YouTube's {MAX_DESCRIPTION_LENGTH}-char limit ({len(description)} chars)"
        )
    tags_total_length = sum(len(tag) for tag in tags)
    if tags_total_length > MAX_TAGS_TOTAL_LENGTH:
        raise ValueError(
            f"combined tags length exceeds YouTube's {MAX_TAGS_TOTAL_LENGTH}-char limit "
            f"({tags_total_length} chars)"
        )

    marker = f"[queue-id: {seq}]"
    full_description = f"{description}\n\n{marker}"

    return {
        "snippet": {
            "title": title,
            "description": full_description,
            "tags": tags,
            "categoryId": GAMING_CATEGORY_ID,
        },
        "status": {
            "privacyStatus": "private",
            "publishAt": publish_at,
            "selfDeclaredMadeForKids": False,
        },
    }


def upload_and_schedule(
    queue: dict[str, Any],
    entry: dict[str, Any],
    service_factory,
    config,
    now: datetime | None = None,
    queue_path: str = DEFAULT_QUEUE_PATH,
) -> dict[str, Any] | str:
    """Orchestrates the dry-run gate -> write-ahead uploading -> insert ->
    record scheduled flow for one queue entry.

    If config.publish.enabled is False, this is the VERY FIRST thing
    checked - before service_factory is ever called - so dry-run makes NO
    credential load and NO network call (PUB-03, T-03-05). Returns a
    sentinel {"dry_run": True} and leaves entry["status"] untouched.

    If enabled, drives: (a) computes next_free_slot from the fixed daily
    grid against already-scheduled entries in `queue`, (b) sets
    entry["status"]=UPLOADING + entry["publish_at"] and persists via
    save_queue BEFORE any insert call (write-ahead - PUB-05, T-03-07: a
    crash mid-upload leaves a durable trace instead of a silent duplicate),
    (c) builds the media upload and drives videos().insert(...).next_chunk()
    to completion, (d) on a returned video_id sets status=SCHEDULED +
    video_id and persists again, returning the video_id.

    service_factory is an injected callable returning an authenticated
    youtube service - tests pass a fake without OAuth. The real factory
    (used by the CLI) calls
    load_credentials(client_secret_path, upload_token_path, [UPLOAD_SCOPE])
    then build("youtube", "v3", ...).

    NOTE: Assumption A1 (kill-body semantics for videos.update) is
    empirically verified in Plan 03, not here - this function only ever
    inserts, never updates/cancels.
    """
    if not config.enabled:
        return {"dry_run": True}

    # Deferred import - keeps the module import-safe with stdlib only when
    # dry-run/disabled (project's optional-dependency convention); only
    # reached once we're committed to a live upload.
    from googleapiclient.http import MediaFileUpload

    already_scheduled = collect_scheduled_slots(queue)
    publish_at = next_free_slot(config.daily_slots_utc, already_scheduled, now=now)

    # Write-ahead: persist UPLOADING before any network call, so a crash
    # between this save and .execute() returning leaves a durable trace
    # (PUB-05) instead of a silent re-upload on the next check.
    entry["status"] = UPLOADING
    entry["publish_at"] = publish_at
    entry["updated_at"] = datetime.now(timezone.utc).isoformat()
    save_queue(queue, queue_path)

    body = build_insert_body(
        title=entry["title"],
        description=entry["description"],
        tags=entry["tags"],
        publish_at=publish_at,
        seq=entry["seq"],
    )

    service = service_factory()
    media = MediaFileUpload(entry["video_path"], chunksize=-1, resumable=True)
    request = service.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        _status, response = request.next_chunk()

    video_id = response["id"]
    entry["status"] = SCHEDULED
    entry["video_id"] = video_id
    entry["updated_at"] = datetime.now(timezone.utc).isoformat()
    save_queue(queue, queue_path)

    return video_id


# --- Pause/kill (PUB-04) ----------------------------------------------------

# Statuses a kill treats as "not yet uploaded" - no video exists on YouTube
# yet (or, for UPLOADING, no video_id has been recorded yet either), so a
# kill of these is purely local: no API call, just flip the manifest.
_NOT_YET_UPLOADED_STATUSES = frozenset({QUEUED, PAUSED, UPLOADING})


def _find_entry(queue: dict[str, Any], clip_id: str) -> dict[str, Any]:
    for entry in queue["entries"]:
        if entry["clip_id"] == clip_id:
            return entry
    raise KeyError(f"no queue entry with clip_id={clip_id!r}")


def pause_item(queue: dict[str, Any], clip_id: str) -> dict[str, Any]:
    """Flips a QUEUED entry to PAUSED so the next check/select_next_due
    skips it. Only touches status/updated_at - everything else about the
    entry (seq, video_path, etc.) is unchanged.
    """
    entry = _find_entry(queue, clip_id)
    entry["status"] = PAUSED
    entry["updated_at"] = datetime.now(timezone.utc).isoformat()
    return entry


def resume_item(queue: dict[str, Any], clip_id: str) -> dict[str, Any]:
    """Flips a PAUSED entry back to QUEUED so it becomes eligible again."""
    entry = _find_entry(queue, clip_id)
    entry["status"] = QUEUED
    entry["updated_at"] = datetime.now(timezone.utc).isoformat()
    return entry


def select_next_due(queue: dict[str, Any]) -> dict[str, Any] | None:
    """Returns the lowest-seq QUEUED entry, or None if nothing is eligible.
    PAUSED and KILLED entries are never returned - a paused item is never
    picked by the periodic-check "next due item" selection (PUB-04).
    """
    eligible = [entry for entry in queue["entries"] if entry["status"] == QUEUED]
    if not eligible:
        return None
    return min(eligible, key=lambda entry: entry["seq"])


def cancel_scheduled_release(service, video_id: str) -> None:
    """Reverts a scheduled-but-not-yet-public video back to plain private,
    cancelling its pending auto-publish (D-04 API half).

    Per 03-RESEARCH.md Pitfall 2: omitting publishAt from this update body
    does NOT clear an existing schedule - the field's write path is
    one-directional (unset -> set), not a general clear/reset toggle via
    omission. The correct kill mechanism is to re-send privacyStatus as
    "private" (required even though the video is already private) and
    deliberately NOT include publishAt at all - a private video with any
    stale publishAt simply never auto-publishes once it's confirmed private.
    """
    service.videos().update(
        part="status",
        body={"id": video_id, "status": {"privacyStatus": "private"}},
    ).execute()


def verify_killed(service, video_id: str) -> bool:
    """Re-fetches videos().list(part="status", id=video_id) and returns True
    only if privacyStatus == "private". This is the mandatory post-kill
    check (Pitfall 2 / Assumption A1) - a kill that didn't take must be
    caught here, not trusted from the update() call alone.
    """
    response = service.videos().list(part="status", id=video_id).execute()
    items = response.get("items", [])
    if not items:
        return False
    return items[0]["status"]["privacyStatus"] == "private"


def kill_item(queue: dict[str, Any], clip_id: str, service_factory) -> dict[str, Any]:
    """Kills a queue entry regardless of where it is in its lifecycle
    (PUB-04):

    - Not yet uploaded (status in QUEUED/PAUSED, or UPLOADING with no
      video_id yet): local-only - flips status to KILLED, no API call,
      service_factory is never invoked.
    - Already SCHEDULED (has a video_id): calls cancel_scheduled_release,
      then verify_killed, and marks KILLED ONLY when verify_killed returns
      True. A failed verify raises RuntimeError and leaves the entry's
      status untouched (still SCHEDULED) so a kill that didn't take is
      surfaced loudly rather than silently trusted (Pitfall 2 / T-03-08).
    """
    entry = _find_entry(queue, clip_id)

    if entry["status"] in _NOT_YET_UPLOADED_STATUSES and not entry.get("video_id"):
        entry["status"] = KILLED
        entry["updated_at"] = datetime.now(timezone.utc).isoformat()
        return entry

    service = service_factory()
    cancel_scheduled_release(service, entry["video_id"])

    if not verify_killed(service, entry["video_id"]):
        raise RuntimeError(
            f"kill_item: verify_killed returned False for clip_id={clip_id!r} "
            f"video_id={entry['video_id']!r} - the revert did not take, refusing "
            "to mark KILLED (Pitfall 2 / Assumption A1)"
        )

    entry["status"] = KILLED
    entry["updated_at"] = datetime.now(timezone.utc).isoformat()
    return entry


# --- Reconciliation of a stuck UPLOADING entry (PUB-05) --------------------


def _seq_marker(seq: int) -> str:
    """The exact marker substring build_insert_body embeds in a video's
    description - kept as a single source of truth so reconciliation's
    match and the original embed can never silently drift apart.
    """
    return f"[queue-id: {seq}]"


def _fetch_descriptions(data_service, video_ids: list[str]) -> dict[str, str]:
    """videos.list(part="snippet") for the given ids, chunked to respect the
    Data API's 50-ids-per-request limit (same constraint list_uploaded_videos's
    sibling calls in youtube_analytics.py already respect for statistics).
    Returns {video_id: description}. Reused instead of hand-rolled because
    list_uploaded_videos's playlistItems response doesn't carry description.
    """
    descriptions: dict[str, str] = {}
    for i in range(0, len(video_ids), 50):
        chunk = video_ids[i : i + 50]
        response = data_service.videos().list(part="snippet", id=",".join(chunk)).execute()
        for item in response.get("items", []):
            descriptions[item["id"]] = item["snippet"].get("description", "")
    return descriptions


def reconcile_uploading(
    queue: dict[str, Any], entry: dict[str, Any], service_factory
) -> dict[str, Any]:
    """Resolves a manifest entry stuck in UPLOADING (from a crash between
    the write-ahead persist and the insert().next_chunk() loop returning) by
    checking YouTube's actual channel uploads BEFORE ever considering a
    retry (PUB-05, Pitfall 3, T-03-09).

    Reuses scripts.youtube_analytics.get_own_channel + list_uploaded_videos
    to enumerate the channel's own recent uploads, then fetches each
    candidate's description (videos.list part=snippet) and looks for this
    entry's embedded seq marker (the exact substring build_insert_body
    wrote, "[queue-id: {seq}]") - specific enough that it can't false-match
    another video's unrelated description.

    - Match found: the upload actually DID reach YouTube before the crash -
      adopt the matched video_id, set status=SCHEDULED, and do NOT call
      videos().insert (this is the exact duplicate PUB-05 exists to
      prevent).
    - No match found: the upload did not complete - reset status to QUEUED
      (and clear any partial video_id) so a subsequent check re-attempts it
      cleanly, since nothing was actually created on YouTube.
    """
    from scripts.youtube_analytics import get_own_channel, list_uploaded_videos

    service = service_factory()
    channel = get_own_channel(service)
    uploaded = list_uploaded_videos(service, channel["uploads_playlist_id"])
    video_ids = [video["video_id"] for video in uploaded]

    descriptions = _fetch_descriptions(service, video_ids)
    marker = _seq_marker(entry["seq"])

    matched_video_id = None
    for video_id, description in descriptions.items():
        if marker in description:
            matched_video_id = video_id
            break

    if matched_video_id is not None:
        entry["status"] = SCHEDULED
        entry["video_id"] = matched_video_id
        entry["updated_at"] = datetime.now(timezone.utc).isoformat()
    else:
        entry["status"] = QUEUED
        entry["video_id"] = None
        entry["updated_at"] = datetime.now(timezone.utc).isoformat()

    return entry


# --- Notification log (D-06 session-bridge) --------------------------------

# The marker is a line-count, not a byte offset. A byte offset would be
# equally valid, but a line-count is simpler to reason about when reading the
# log back with .readlines() (no need to worry about encoding-dependent byte
# boundaries splitting a multi-byte UTF-8 character), and this log is always
# read in full then re-diffed rather than seeked-into, so there's no
# performance reason to prefer a byte offset here. Persisted alongside the
# log (not embedded in it) so re-reading the log file itself is never
# ambiguous about what "already read" means (D-06: this is the durable
# handoff between a session-less Task Scheduler run and the next interactive
# Claude Code session).
DEFAULT_NOTIFICATIONS_MARKER_PATH = "work/_publish/notifications.read"


def append_notification(text: str, path: str = DEFAULT_NOTIFICATIONS_PATH) -> None:
    """Appends one UTC-timestamped line to the notification log, creating
    parent directories as needed. Append-only - never truncates or rewrites
    existing lines, so a session-less Task Scheduler run's record survives
    even if nobody reads it right away (D-06).
    """
    log_file = Path(path)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).isoformat()
    with log_file.open("a", encoding="utf-8") as handle:
        handle.write(f"{timestamp} {text}\n")


def read_unread_notifications(
    path: str = DEFAULT_NOTIFICATIONS_PATH,
    marker_path: str = DEFAULT_NOTIFICATIONS_MARKER_PATH,
) -> list[str]:
    """Returns the notification lines appended since the last read, then
    advances the last-read marker (a persisted line count) so a second call
    in a row returns [] (no double-report, D-06).

    Robust to the log being appended between reads: the marker only ever
    records "how many lines had been read as of the last call", so lines
    appended after that point are always picked up on the next read,
    regardless of how much time passed in between.
    """
    log_file = Path(path)
    if not log_file.exists():
        return []

    lines = log_file.read_text(encoding="utf-8").splitlines()

    marker_file = Path(marker_path)
    already_read = 0
    if marker_file.exists():
        marker_text = marker_file.read_text(encoding="utf-8").strip()
        already_read = int(marker_text) if marker_text else 0

    unread = lines[already_read:]

    marker_file.parent.mkdir(parents=True, exist_ok=True)
    marker_file.write_text(str(len(lines)), encoding="utf-8")

    return unread


def reconcile_all_uploading(queue: dict[str, Any], service_factory) -> None:
    """Reconciles every UPLOADING entry in the queue before any new
    selection happens. Wired as the mandatory first step of the
    periodic-check path so a stuck entry can never be silently bypassed and
    re-uploaded as a fresh QUEUED item (PUB-05) - select_next_due only ever
    sees entries that have already been resolved one way or the other.
    """
    for entry in queue["entries"]:
        if entry["status"] == UPLOADING and entry.get("video_id"):
            # Already has a video_id recorded - not the "stuck mid-upload"
            # case this reconciliation targets; leave it alone.
            continue
        if entry["status"] == UPLOADING:
            reconcile_uploading(queue, entry, service_factory)


# --- CLI (D-05: --check / --now / --pause / --kill / --resume / --list) ----


def _success_notification_text(entry: dict[str, Any]) -> str:
    """The D-05 wording: 'залил {seq}, выйдет в {HH:MM} UTC', HH:MM derived
    from the entry's publish_at (an RFC3339 Z-suffixed UTC timestamp)."""
    hh_mm = entry["publish_at"][11:16]
    return f"залил {entry['seq']}, выйдет в {hh_mm} UTC"


def _error_notification_text(entry: dict[str, Any], reason: str) -> str:
    return f"[error] {entry['seq']}: {reason}"


def _upload_one(entry: dict[str, Any], queue: dict[str, Any], service_factory, config) -> None:
    """Shared upload step for both --check and --now: calls the exact same
    upload_and_schedule() (Plan 02) and appends the matching notification
    line - the two trigger paths never diverge (D-05, T-03-14 key link).
    Errors are caught here (not re-raised) so a single bad item doesn't
    crash the whole periodic check; an error line is appended instead.
    """
    try:
        result = upload_and_schedule(
            queue, entry, service_factory, config, queue_path=config.queue_path
        )
    except Exception as error:
        append_notification(
            _error_notification_text(entry, str(error)), config.notifications_path
        )
        raise

    if isinstance(result, dict) and result.get("dry_run"):
        print("dry-run: skipped (opt-in disabled)")
        return

    append_notification(_success_notification_text(entry), config.notifications_path)
    print(_success_notification_text(entry))


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Local publish-queue CLI: periodic --check, manual --now override, "
        "--pause/--kill/--resume, and --list - both --check and --now route through the "
        "same upload_and_schedule path (D-05)"
    )
    parser.add_argument("--check", action="store_true", help="Periodic check: reconcile stuck uploads, then upload+schedule the single next due item (or log a dry-run skip)")
    parser.add_argument("--now", metavar="CLIP_ID", help="Force-publish one specific queued clip_id out of band, via the same upload path")
    parser.add_argument("--pause", metavar="CLIP_ID", help="Pause a not-yet-uploaded queued clip_id")
    parser.add_argument("--kill", metavar="CLIP_ID", help="Kill a clip_id (local-only if not yet uploaded, API revert+verify if already scheduled)")
    parser.add_argument("--resume", metavar="CLIP_ID", help="Resume a paused clip_id back to queued")
    parser.add_argument("--list", action="store_true", help="Print the queue's seq/status/title so numbering is visible")
    parser.add_argument("--client-secret", default="client_secret.json", help="OAuth client secret JSON path")
    parser.add_argument("--token", default="upload_token.json", help="Cached upload-scoped OAuth token JSON path")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    return parser


def run_command(args: argparse.Namespace, service_factory, config) -> None:
    """Dispatches one CLI invocation. Factored out from main() so tests can
    drive it with a fake service_factory + a config carrying tmp-path
    queue/notifications paths, without ever touching real OAuth (main()'s
    only job is parsing args, building the real service_factory + config,
    and calling this).

    --check and --now both call _upload_one, which calls the identical
    upload_and_schedule - no second/divergent publish code path (D-05).
    --check enforces "at most one item per invocation" by construction:
    select_next_due (after reconcile_all_uploading resolves anything stuck)
    returns at most one entry, and only that one entry is ever passed to
    _upload_one per call.
    """
    queue_path = config.queue_path

    if args.list:
        queue = load_queue(queue_path)
        for entry in sorted(queue["entries"], key=lambda e: e["seq"]):
            print(f"{entry['seq']}\t{entry['status']}\t{entry['title']}")
        return

    if args.pause:
        queue = load_queue(queue_path)
        try:
            pause_item(queue, args.pause)
        except KeyError:
            print(f"error: no queue entry with clip_id={args.pause!r}", file=sys.stderr)
            raise SystemExit(2)
        save_queue(queue, queue_path)
        print(f"paused {args.pause}")
        return

    if args.resume:
        queue = load_queue(queue_path)
        try:
            resume_item(queue, args.resume)
        except KeyError:
            print(f"error: no queue entry with clip_id={args.resume!r}", file=sys.stderr)
            raise SystemExit(2)
        save_queue(queue, queue_path)
        print(f"resumed {args.resume}")
        return

    if args.kill:
        queue = load_queue(queue_path)
        try:
            kill_item(queue, args.kill, service_factory)
        except KeyError:
            print(f"error: no queue entry with clip_id={args.kill!r}", file=sys.stderr)
            raise SystemExit(2)
        save_queue(queue, queue_path)
        print(f"killed {args.kill}")
        return

    if args.now:
        queue = load_queue(queue_path)
        try:
            entry = _find_entry(queue, args.now)
        except KeyError:
            print(f"error: no queue entry with clip_id={args.now!r}", file=sys.stderr)
            raise SystemExit(2)
        _upload_one(entry, queue, service_factory, config)
        return

    if args.check:
        queue = load_queue(queue_path)
        # Reconcile-first (PUB-05): any crash-mid-upload entry must be
        # resolved before a fresh item is ever selected.
        reconcile_all_uploading(queue, service_factory)
        save_queue(queue, queue_path)

        if not config.enabled:
            print("dry-run: skipped (opt-in disabled)")
            return

        entry = select_next_due(queue)
        if entry is None:
            print("check: nothing due")
            return

        # --check uploads AT MOST ONE item per invocation (D-05 "one at a
        # time") - this is also the natural quota debounce (Pitfall 4).
        _upload_one(entry, queue, service_factory, config)
        return

    print("no action given - use --check/--now/--pause/--kill/--resume/--list")


def main() -> None:
    parser = build_argument_parser()
    args = parser.parse_args()

    from scripts.config import load_config
    from scripts.youtube_analytics import load_credentials
    from googleapiclient.discovery import build

    config = load_config(args.config).publish

    def service_factory():
        credentials = load_credentials(args.client_secret, args.token, [UPLOAD_SCOPE])
        return build("youtube", "v3", credentials=credentials)

    run_command(args, service_factory, config)


if __name__ == "__main__":
    main()
