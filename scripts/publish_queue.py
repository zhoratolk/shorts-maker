from __future__ import annotations

"""Local publish-queue + upload/schedule/kill layer.

Tracks finished shorts through the local queue manifest (sequential
numbering, idempotent enqueue keyed on clip_id) and, in later plans, drives
the YouTube Data API upload/schedule/kill calls. This module stays
import-safe with the standard library only - no top-level Google-API-client
import (that arrives as a deferred, inside-function import once the upload
path is added).
"""

import json
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

# Narrowest scope that permits videos.insert/videos.update - deliberately
# NOT the broader plain `youtube` or `youtubepartner` scopes (D-08/D-09:
# smaller blast radius if this token leaks, separate from the read-only
# token.json used by youtube_analytics.py).
UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"

# YouTube's own field-length limits (V5 input validation, 03-RESEARCH
# Security Domain) - a violation fails this one queue item, not the whole
# run.
MAX_TITLE_LENGTH = 100
MAX_DESCRIPTION_LENGTH = 5000
MAX_TAGS_TOTAL_LENGTH = 500


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
