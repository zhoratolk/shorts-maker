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
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.metadata import strip_mature_disclaimer

# Status enum - the full lifecycle a queue entry can move through.
QUEUED = "queued"
UPLOADING = "uploading"
SCHEDULED = "scheduled"
PUBLISHED = "published"
KILLED = "killed"
PAUSED = "paused"
# An entry that failed the same way too many times. Set aside rather than retried
# forever, because select_next_due always picks the lowest seq: an entry that fails
# deterministically - a title over 100 characters, a deleted file, a revoked token - is
# chosen again on every tick, and nothing behind it is ever published. That is the same
# outcome as the incident this queue was built after, reached by a different road.
BLOCKED = "blocked"

VALID_STATUSES = frozenset(
    {QUEUED, UPLOADING, SCHEDULED, PUBLISHED, KILLED, PAUSED, BLOCKED}
)

# How many times an entry may fail before it is set aside. Three, because a transient
# failure - a 5xx, a dropped connection - rarely repeats three times in a row, while a
# deterministic one repeats every time.
MAX_UPLOAD_ATTEMPTS = 3

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
# How far back to walk the uploads playlist when reading the channel's own
# pending schedule. Anything still scheduled sits at the very top of that
# playlist, so this only has to cover a plausible backlog, not the archive.
CHANNEL_SCAN_LIMIT = 150

# YouTube's own field-length limits (V5 input validation, 03-RESEARCH
# Security Domain) - a violation fails this one queue item, not the whole
# run.
MAX_TITLE_LENGTH = 100
MAX_DESCRIPTION_LENGTH = 5000
MAX_TAGS_TOTAL_LENGTH = 500
# Explicit video category improves search/browse classification for Shorts
# (uploads without one land in the default "People & Blogs"). 20 = Gaming.
GAMING_CATEGORY_ID = "20"
# YouTube's custom-thumbnail size ceiling. Kept next to the other API limits
# above rather than imported from thumbnail.py: this module stays import-safe
# on the standard library alone.
MAX_THUMBNAIL_BYTES = 2 * 1024 * 1024


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
    writing style: ensure_ascii=False, indent=2).

    Written beside the target and moved into place, because a plain write
    truncates first: a crash or a power cut in the middle leaves half a JSON
    document, and load_queue deliberately refuses to parse a broken manifest
    (T-03-03) rather than silently re-publishing everything. That combination
    stops the whole publish path until somebody repairs the file by hand - and
    the upload path writes this file two or three times per clip, so the window
    is not as small as it sounds. os.replace is atomic on both platforms this
    runs on.
    """
    queue_file = Path(path)
    queue_file.parent.mkdir(parents=True, exist_ok=True)
    temporary = queue_file.with_name(queue_file.name + ".tmp")
    # Flushed all the way to the platter before the rename, because os.replace only buys
    # atomicity, not durability: on a filesystem with delayed allocation the rename can
    # be on disk while the bytes it points at are not, and a power cut in that window
    # leaves an empty queue.json - which load_queue then refuses to parse, which is the
    # standstill this whole function exists to prevent.
    with open(temporary, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(queue, ensure_ascii=False, indent=2))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, queue_file)


def default_thumbnail_path(video_path: str) -> str:
    """The poster render_batch.py writes next to a clip (<clip>.thumb.jpg), or
    "" when there isn't one. Convention over configuration: the render step and
    the publish step agree on the filename, so nothing has to be threaded
    through by hand and a forgotten argument can't silently drop the poster.

    .png is still accepted for batches rendered before posters moved to JPEG
    (PNG overshot YouTube's 2 MB thumbnail limit on busy frames).
    """
    clip = Path(video_path)
    for suffix in (".thumb.jpg", ".thumb.png"):
        poster = clip.with_suffix(suffix)
        if poster.exists():
            return str(poster)
    return ""


def enqueue(
    queue: dict[str, Any],
    clip_id: str,
    video_path: str,
    metadata_path: str,
    title: str,
    description: str,
    tags: list[str],
    moment_tag: str | None = None,
    source_duration: float | None = None,
    thumbnail_path: str | None = None,
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

    moment_tag/source_duration are optional provenance: the candidate's
    moment tag and the clip's duration, carried so retention.py can later
    attribute a published video's audience-retention curve back to the KIND
    and LENGTH of moment it was (the auto-select learning loop). Both default
    to None and never affect scheduling or upload.

    thumbnail_path is the poster image to set as the video's custom thumbnail
    after upload. Left as None it is DERIVED from video_path - the sibling
    <clip>.thumb.png render_batch.py writes - so a caller that forgets to pass
    it still publishes the poster instead of silently falling back to
    YouTube's auto-generated frame. Pass "" to deliberately publish without a
    custom thumbnail. Setting it is fail-open (see upload_and_schedule) - a
    thumbnail error never fails the upload.
    """
    for entry in queue["entries"]:
        if entry["clip_id"] == clip_id:
            return entry

    if thumbnail_path is None:
        thumbnail_path = default_thumbnail_path(video_path)

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
        "moment_tag": moment_tag,
        "source_duration": source_duration,
        "thumbnail_path": thumbnail_path,
        "status": QUEUED,
        "video_id": None,
        "publish_at": None,
        "enqueued_at": now,
        "updated_at": now,
    }
    queue["entries"].append(entry)
    return entry


def attach_missing_thumbnails(queue: dict[str, Any]) -> list[dict[str, Any]]:
    """Fills in thumbnail_path for entries that don't have one yet but whose
    poster now exists on disk, and returns the entries that changed.

    Exists for the entries enqueued before posters were turned on, and for a
    poster regenerated after the clip was already queued. Only entries not yet
    uploaded are touched: once a video is live, its thumbnail is set through
    the API, not by editing the manifest.
    """
    changed = []
    for entry in queue["entries"]:
        if entry.get("thumbnail_path") or entry["status"] not in (QUEUED, PAUSED):
            continue
        poster = default_thumbnail_path(entry["video_path"])
        if not poster:
            continue
        entry["thumbnail_path"] = poster
        entry["updated_at"] = datetime.now(timezone.utc).isoformat()
        changed.append(entry)
    return changed


def interleave_loops(items: list[Any], is_loop) -> list[Any]:
    """Spreads the loop clips of one batch evenly through the regular ones.

    Loop clips are rendered in their own pass (they cannot carry the outro
    card, see SKILL.md), so a batch arrives as "all the regular ones, then all
    the loops". Enqueuing in that order puts every looping clip back to back on
    the grid, which reads as a stylistic tic rather than a variation. Placing
    them at evenly spaced positions keeps the batch's own ordering within each
    group while separating the loops.

    `is_loop` is a predicate applied to each item. Order within the loop group
    and within the regular group is preserved.
    """
    loops = [item for item in items if is_loop(item)]
    regular = [item for item in items if not is_loop(item)]
    if not loops or not regular:
        return list(items)

    total = len(loops) + len(regular)
    # evenly spaced slots: the i-th of L loops lands at (i + 0.5) / L of the way
    positions = {min(total - 1, int((index + 0.5) * total / len(loops))) for index in range(len(loops))}
    while len(positions) < len(loops):  # collisions when loops crowd the batch
        positions.add(max(set(range(total)) - positions))

    ordered: list[Any] = []
    loop_iter, regular_iter = iter(loops), iter(regular)
    for index in range(total):
        if index in positions:
            ordered.append(next(loop_iter))
        else:
            ordered.append(next(regular_iter))
    return ordered


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


def fetch_channel_scheduled_slots(service) -> list[str]:
    """Every publishAt currently pending on the channel itself, read from
    YouTube rather than from this file.

    collect_scheduled_slots only knows what this queue wrote. Anything
    scheduled another way - moved by hand in Studio, uploaded from the phone,
    left over from an older run - is invisible to it, and next_free_slot then
    hands out a slot that is already taken. Reading the channel closes that
    gap for good.

    Fails open: on any API problem the caller keeps the local-only set, which
    is what it used to have anyway.
    """
    try:
        channels = service.channels().list(part="contentDetails", mine=True).execute()
        uploads = channels["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    except Exception as error:  # noqa: BLE001 - advisory read, never fatal
        print(f"[warn] could not read the channel's own schedule: {error}", file=sys.stderr)
        return []

    from scripts.youtube_analytics import chunk_video_ids

    video_ids: list[str] = []
    page_token = None
    try:
        while len(video_ids) < CHANNEL_SCAN_LIMIT:
            response = service.playlistItems().list(
                part="contentDetails", playlistId=uploads,
                maxResults=50, pageToken=page_token,
            ).execute()
            video_ids += [item["contentDetails"]["videoId"] for item in response.get("items", [])]
            page_token = response.get("nextPageToken")
            if not page_token:
                break

        slots = []
        for chunk in chunk_video_ids(video_ids):
            listed = service.videos().list(part="status", id=",".join(chunk)).execute()
            for video in listed.get("items", []):
                status = video.get("status", {})
                if status.get("privacyStatus") == "private" and status.get("publishAt"):
                    slots.append(status["publishAt"])
        return slots
    except Exception as error:  # noqa: BLE001 - advisory read, never fatal
        print(f"[warn] could not read the channel's own schedule: {error}", file=sys.stderr)
        return []


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

    The description is published verbatim - no machine-readable marker is
    appended (the old trailing "[queue-id: N]" line leaked into the public
    description; reconciliation now matches by exact title instead).

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

    # Последний рубеж перед публикацией: дисклеймер про мат канал не публикует
    # (2026-07-18), а описание сюда может прийти из руками собранной очереди,
    # мимо рендера метадаты. Проверка длины выше сделана до среза намеренно —
    # ловить надо то описание, которое написали, а не то, что от него осталось.
    full_description = strip_mature_disclaimer(description)

    return {
        "snippet": {
            "title": strip_mature_disclaimer(title),
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
    thumbnail_upload: bool = True,
    extra_scheduled: list[str] | None = None,
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

    already_scheduled = collect_scheduled_slots(queue) + list(extra_scheduled or [])
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

    # Custom thumbnail is a best-effort afterthought: the video is already
    # uploaded+scheduled above, so a thumbnail failure (missing file, channel
    # not eligible for custom thumbnails, transient API error) must NOT undo
    # or fail that. Fail-open - record the outcome on the entry and move on.
    thumbnail_path = entry.get("thumbnail_path")
    if thumbnail_path and thumbnail_upload:
        entry["thumbnail_set"] = _try_set_thumbnail(service, video_id, thumbnail_path)
        entry["updated_at"] = datetime.now(timezone.utc).isoformat()
        save_queue(queue, queue_path)

    return video_id


def set_thumbnail(service, video_id: str, image_path: str) -> None:
    """Sets a video's custom thumbnail via thumbnails().set. Raises on API
    error - callers that need fail-open behaviour use _try_set_thumbnail."""
    from googleapiclient.http import MediaFileUpload

    media = MediaFileUpload(image_path)
    service.thumbnails().set(videoId=video_id, media_body=media).execute()


def _try_set_thumbnail(service, video_id: str, image_path: str) -> bool:
    """Fail-open wrapper around set_thumbnail: returns True on success, False
    (with a [warn]) on a missing file or any API error. Never raises."""
    poster = Path(image_path)
    if not poster.exists():
        print(f"[warn] thumbnail not set for {video_id}: file not found: {image_path}", file=sys.stderr)
        return False
    # Check the size here rather than letting the API answer with a bare
    # "Media larger than: 2097152" - that error names no file and no limit
    # anyone can act on (seen 2026-08-06).
    size = poster.stat().st_size
    if size > MAX_THUMBNAIL_BYTES:
        print(
            f"[warn] thumbnail not set for {video_id}: {poster.name} is {size / 1048576:.2f} MB, "
            f"over YouTube's {MAX_THUMBNAIL_BYTES / 1048576:.0f} MB limit",
            file=sys.stderr,
        )
        return False
    try:
        set_thumbnail(service, video_id, image_path)
        return True
    except Exception as error:  # noqa: BLE001 - fail-open on any upload/API error
        print(f"[warn] thumbnail not set for {video_id}: {error}", file=sys.stderr)
        return False


# --- Pause/kill (PUB-04) ----------------------------------------------------

# Statuses a kill treats as "not yet uploaded" - no video exists on YouTube
# yet (or, for UPLOADING, no video_id has been recorded yet either), so a
# kill of these is purely local: no API call, just flip the manifest.
#
# BLOCKED belongs here for the same reason and was missed when it was added: an entry
# that failed three times before the insert has no video_id, so killing it opened a real
# OAuth session and then asked YouTube to update the video with id None - the operator
# got a traceback instead of a killed entry, and the entry stayed BLOCKED. The video_id
# check below is what actually decides; the set only says which statuses may reach it.
_NOT_YET_UPLOADED_STATUSES = frozenset({QUEUED, PAUSED, UPLOADING, BLOCKED})


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
    """Flips a PAUSED or BLOCKED entry back to QUEUED so it becomes eligible again.

    The attempt counter is cleared with it. A blocked entry is resumed because
    somebody fixed what was wrong with it, and leaving the count at the limit
    would set it aside again on the first hiccup after that.
    """
    entry = _find_entry(queue, clip_id)
    entry["status"] = QUEUED
    entry["attempts"] = 0
    entry.pop("last_error", None)
    entry["updated_at"] = datetime.now(timezone.utc).isoformat()
    return entry


def select_next_due(
    queue: dict[str, Any], skip: frozenset[str] = frozenset()
) -> dict[str, Any] | None:
    """Returns the lowest-seq QUEUED entry, or None if nothing is eligible.
    PAUSED, KILLED and BLOCKED entries are never returned - a paused item is
    never picked by the periodic-check "next due item" selection (PUB-04).

    `skip` holds clip_ids already tried and failed in this batch. Without it the
    caller's loop would hand the same lowest-seq entry back on every iteration
    now that a failure no longer raises out of the loop.
    """
    eligible = [
        entry for entry in queue["entries"]
        if entry["status"] == QUEUED and entry["clip_id"] not in skip
    ]
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


def fetch_privacy_status(service, video_id: str) -> str | None:
    """Current privacyStatus of a video, or None when YouTube doesn't return
    it at all - the video was deleted (here or from the YouTube UI) and there
    is nothing left to revert. The two cases have to stay distinguishable:
    "still public" means the kill failed, "gone" means it already succeeded by
    other means, and collapsing both into a bare False strands the entry.
    """
    response = service.videos().list(part="status", id=video_id).execute()
    items = response.get("items", [])
    if not items:
        return None
    return items[0]["status"]["privacyStatus"]


def verify_killed(service, video_id: str) -> bool:
    """Re-fetches videos().list(part="status", id=video_id) and returns True
    only if privacyStatus == "private". This is the mandatory post-kill
    check (Pitfall 2 / Assumption A1) - a kill that didn't take must be
    caught here, not trusted from the update() call alone.
    """
    return fetch_privacy_status(service, video_id) == "private"


def _error_reason(error: Exception) -> str:
    """The machine-readable `reason` from an API error body, or "" if absent.

    Read rather than the human message so a localized or reworded body still
    classifies correctly - the reason string is part of the API contract.
    """
    for detail in getattr(error, "error_details", None) or []:
        if isinstance(detail, dict) and detail.get("reason"):
            return str(detail["reason"])
    content = getattr(error, "content", None)
    if not content:
        return ""
    try:
        if isinstance(content, bytes):
            content = content.decode("utf-8", "replace")
        errors = json.loads(content).get("error", {}).get("errors") or []
        return str(errors[0].get("reason", "")) if errors else ""
    except (ValueError, AttributeError, IndexError):
        return ""


# A 403 that means "this video is not yours / not reachable" and therefore cannot be
# unscheduled. Everything else the API answers 403 to - an exhausted daily quota, a token
# without videos.update, a rate limit - is a live video and a real failure.
GONE_403_REASONS = frozenset({"forbidden", "videoNotFound"})


# Failures that say "not now" rather than "not ever". The daily quota resets at midnight
# Pacific, a rate limit clears in seconds, and a 5xx is the API's own problem - none of
# them are a property of the clip, and none of them get better by giving up on it.
#
# They must not spend an attempt. Counting them did the opposite of what the attempt
# counter is for: an hourly check against an exhausted quota failed identically every
# tick, so three ticks blocked the first entry, three more blocked the second, and by the
# time the quota came back the whole queue was BLOCKED and waiting on somebody to type
# --resume for each clip. Before the counter existed, that same night fixed itself.
RETRYABLE_REASONS = frozenset({
    "quotaExceeded",
    "userRateLimitExceeded",
    "rateLimitExceeded",
    "backendError",
    "internalError",
    "uploadLimitExceeded",
})


def _is_retryable(error: Exception) -> bool:
    if _error_reason(error) in RETRYABLE_REASONS:
        return True
    # No machine-readable reason on a bare 5xx or a 429, and those are the two shapes a
    # transport-level hiccup arrives in.
    status = getattr(getattr(error, "resp", None), "status", None)
    return status == 429 or (isinstance(status, int) and 500 <= status < 600)


def _video_is_gone(error: Exception) -> bool:
    """True for the API error raised when the video id no longer exists.

    404 is unambiguous. 403 is not, and treating it as "gone" was dangerous in
    exactly one direction: an exhausted quota during --kill marked the entry
    KILLED with "video already absent" while the video was alive and still
    scheduled. The operator believes the release is cancelled, and it publishes
    on schedule anyway - the worst failure mode a safety switch can have. The
    file already knew 403 was ambiguous: see the UPLOAD_SCOPE note above, where
    videos.update answers 403 insufficientPermissions under a narrow scope.

    An unrecognised 403 counts as a real failure, because a kill that loudly did
    not work is recoverable and a kill that silently did not work is not.
    """
    status = getattr(getattr(error, "resp", None), "status", None)
    if status == 404:
        return True
    if status != 403:
        return False
    return _error_reason(error) in GONE_403_REASONS


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
    try:
        cancel_scheduled_release(service, entry["video_id"])
    except Exception as error:  # noqa: BLE001 - re-raised below unless the video is gone
        if not _video_is_gone(error):
            raise
        entry["status"] = KILLED
        entry["kill_note"] = "video already absent from YouTube"
        entry["updated_at"] = datetime.now(timezone.utc).isoformat()
        return entry

    status = fetch_privacy_status(service, entry["video_id"])
    if status is None:
        # Deleted between the update above and this check, or deleted earlier
        # and the update was a no-op: either way the schedule cannot fire.
        entry["status"] = KILLED
        entry["kill_note"] = "video already absent from YouTube"
        entry["updated_at"] = datetime.now(timezone.utc).isoformat()
        return entry
    if status != "private":
        raise RuntimeError(
            f"kill_item: video is still {status!r} for clip_id={clip_id!r} "
            f"video_id={entry['video_id']!r} - the revert did not take, refusing "
            "to mark KILLED (Pitfall 2 / Assumption A1)"
        )

    entry["status"] = KILLED
    entry["updated_at"] = datetime.now(timezone.utc).isoformat()
    return entry


# --- Reconciliation of a stuck UPLOADING entry (PUB-05) --------------------


def reconcile_uploading(
    queue: dict[str, Any], entry: dict[str, Any], service_factory
) -> dict[str, Any]:
    """Resolves a manifest entry stuck in UPLOADING (from a crash between
    the write-ahead persist and the insert().next_chunk() loop returning) by
    checking YouTube's actual channel uploads BEFORE ever considering a
    retry (PUB-05, Pitfall 3, T-03-09).

    Reuses scripts.youtube_analytics.get_own_channel + list_uploaded_videos
    to enumerate the channel's own recent uploads, then looks for a video
    whose title exactly equals this entry's title (build_insert_body
    publishes the title verbatim, so an exact-title hit among the channel's
    own recent uploads identifies the interrupted upload).

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

    matched_video_id = None
    for video in uploaded:
        if video.get("title") == entry["title"]:
            matched_video_id = video["video_id"]
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


def reconcile_all_scheduled(
    queue: dict[str, Any], service_factory, now: datetime | None = None
) -> None:
    """Flips SCHEDULED entries whose publish_at has already passed over to
    PUBLISHED once YouTube confirms the video actually went public.

    Nothing else ever makes the SCHEDULED->PUBLISHED transition: YouTube
    auto-publishes at publishAt with no callback into this pipeline, so
    without this check a past-due entry stays labeled SCHEDULED forever even
    though it's long since gone live - the local manifest silently drifts
    from reality (found 2026-07-28: 48 stale SCHEDULED entries going back to
    2026-07-16). Wired as a --check step alongside reconcile_all_uploading.

    Batches lookups via videos.list's id filter (same chunk_video_ids helper
    youtube_analytics.py uses for statistics) instead of one call per entry -
    the backlog this is meant to drain can be dozens of entries deep.

    records entry["published_at"] from the API's snippet.publishedAt (the
    real observed go-live moment) alongside the flip, distinct from
    publish_at (what we originally asked YouTube to schedule) - comparing the
    two is how a delayed/mis-scheduled publish gets caught after the fact.

    Checks EVERY scheduled entry, not only the past-due ones: publish_at is
    what we asked for, not what happened. A video can go public ahead of its
    local timestamp (rescheduled or released by hand in Studio), and such an
    entry used to sit SCHEDULED while already being public - the same drift
    this function exists to prevent, just in the other direction. The lookup
    is batched 50 ids to a call either way, so widening it costs nothing.

    An entry whose video_id no longer resolves is resolved as KILLED rather
    than left SCHEDULED forever: YouTube returning nothing for an id means
    the video is gone, so the pending release can never fire and there is
    nothing left to wait for (found 2026-08-23 on seq 215, deleted outside
    this tool a day after its slot passed). Genuinely transient failures do
    not reach here - an API error raises out of the call instead of coming
    back as an empty item list.
    """
    now = now or datetime.now(timezone.utc)
    due = [
        entry
        for entry in queue["entries"]
        if entry["status"] == SCHEDULED and entry.get("video_id")
    ]
    if not due:
        return

    from scripts.youtube_analytics import chunk_video_ids

    service = service_factory()
    by_video_id = {entry["video_id"]: entry for entry in due}

    for chunk in chunk_video_ids(list(by_video_id.keys())):
        response = service.videos().list(part="status,snippet", id=",".join(chunk)).execute()
        seen = set()
        for video in response.get("items", []):
            entry = by_video_id.get(video["id"])
            if entry is None:
                continue
            seen.add(video["id"])
            status = video.get("status", {})
            # The channel owner reschedules by hand in Studio, so publish_at
            # in this file is a request, not a fact - adopt what YouTube
            # actually holds, or the next batch picks its slots against a
            # schedule that moved (2026-08-23: every pending clip had been
            # shifted a slot earlier and the queue never noticed).
            actual_publish_at = status.get("publishAt")
            if actual_publish_at and actual_publish_at != entry.get("publish_at"):
                entry["publish_at"] = actual_publish_at
                entry["updated_at"] = datetime.now(timezone.utc).isoformat()
            privacy_status = status.get("privacyStatus")
            if privacy_status == "public":
                entry["status"] = PUBLISHED
                entry["published_at"] = video.get("snippet", {}).get("publishedAt")
                entry["updated_at"] = datetime.now(timezone.utc).isoformat()
        for video_id in chunk:
            if video_id in seen:
                continue
            entry = by_video_id[video_id]
            entry["status"] = KILLED
            entry["kill_note"] = "video already absent from YouTube"
            entry["updated_at"] = datetime.now(timezone.utc).isoformat()


# --- CLI (D-05: --check / --now / --pause / --kill / --resume / --list) ----


def _success_notification_text(entry: dict[str, Any]) -> str:
    """The D-05 wording: 'залил {seq}, выйдет в {HH:MM} UTC', HH:MM derived
    from the entry's publish_at (an RFC3339 Z-suffixed UTC timestamp)."""
    hh_mm = entry["publish_at"][11:16]
    return f"залил {entry['seq']}, выйдет в {hh_mm} UTC"


def _error_notification_text(entry: dict[str, Any], reason: str) -> str:
    return f"[error] {entry['seq']}: {reason}"


def upload_batch(
    service_factory,
    config,
    thumbnail_upload: bool = True,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Reconcile once, then upload every due item (or the first `limit` of
    them), and return the entries that actually went up.

    --check deliberately uploads at most one item per invocation, because it
    was written for an unattended timer where "one per tick" IS the pacing.
    Enqueuing a finished batch is the opposite situation: the operator is
    sitting right there and means "put these on YouTube", so making them run
    --check once per clip is busywork that gets forgotten halfway, which is
    exactly how ten clips sat in the local queue for two days looking
    enqueued while YouTube had never heard of them (2026-08-23).

    Each item still goes through the identical _upload_one/upload_and_schedule
    path, and each still lands in its own grid slot - this loops the same
    single-item step, it is not a second, batch-shaped upload path.
    """
    queue = load_queue(config.queue_path)
    reconcile_all_uploading(queue, service_factory)
    save_queue(queue, config.queue_path)
    reconcile_all_scheduled(queue, service_factory)
    save_queue(queue, config.queue_path)

    uploaded: list[dict[str, Any]] = []
    if not config.enabled:
        print("dry-run: skipped (opt-in disabled)")
        return uploaded

    # Read the channel's real pending schedule once for the whole batch: each
    # upload adds its own slot to the local queue as it goes, so only the
    # slots this queue never knew about need carrying across iterations.
    extra_scheduled = fetch_channel_scheduled_slots(service_factory())

    # Entries this batch already tried and failed. A failure no longer raises, so without
    # this the loop would keep selecting the same lowest-seq entry and never terminate.
    failed: set[str] = set()

    while limit is None or len(uploaded) < limit:
        queue = load_queue(config.queue_path)
        entry = select_next_due(queue, frozenset(failed))
        if entry is None:
            break
        if _upload_one(entry, queue, service_factory, config, thumbnail_upload,
                       extra_scheduled):
            uploaded.append(entry)
        else:
            # The rest of the batch is still worth uploading: the operator asked for
            # these clips to go up, and one bad title should not hold back nine good
            # clips. The failure is already in the notification log.
            failed.add(entry["clip_id"])
    return uploaded


def _upload_one(
    entry: dict[str, Any],
    queue: dict[str, Any],
    service_factory,
    config,
    thumbnail_upload: bool = True,
    extra_scheduled: list[str] | None = None,
) -> bool:
    """Shared upload step for both --check and --now: calls the exact same
    upload_and_schedule() (Plan 02) and appends the matching notification
    line - the two trigger paths never diverge (D-05, T-03-14 key link).
    Errors are caught here (not re-raised) so a single bad item doesn't
    crash the whole periodic check; an error line is appended instead.

    Returns whether the entry moved on. The caller needs to know: a batch loop
    that cannot tell success from failure would re-select the same entry.
    """
    try:
        result = upload_and_schedule(
            queue, entry, service_factory, config,
            queue_path=config.queue_path, thumbnail_upload=thumbnail_upload,
            extra_scheduled=extra_scheduled,
        )
    except Exception as error:
        append_notification(
            _error_notification_text(entry, str(error)), config.notifications_path
        )
        # Counted and set aside rather than re-raised. The docstring above always promised
        # that one bad item would not stop the periodic check, but the raise meant the
        # opposite: select_next_due picks the lowest seq every tick, so an entry that
        # fails the same way each time is chosen forever and nothing behind it is ever
        # published. Ten clips once sat in this queue for two days looking enqueued.
        # A quota or a rate limit is not the clip's fault and does not become the clip's
        # fault by repeating - see RETRYABLE_REASONS. It is recorded but not counted, so
        # the entry is still waiting when the quota comes back.
        if not _is_retryable(error):
            entry["attempts"] = entry.get("attempts", 0) + 1
        entry["last_error"] = str(error)[:500]
        entry["updated_at"] = datetime.now(timezone.utc).isoformat()
        if entry.get("attempts", 0) >= MAX_UPLOAD_ATTEMPTS:
            entry["status"] = BLOCKED
            append_notification(
                f"[{entry['clip_id']}] отложен после {entry['attempts']} неудач: "
                f"{entry['last_error']}. Очередь идёт дальше; вернуть — "
                f"--resume {entry['clip_id']}",
                config.notifications_path,
            )
        save_queue(queue, config.queue_path)
        return False

    if isinstance(result, dict) and result.get("dry_run"):
        print("dry-run: skipped (opt-in disabled)")
        return False

    append_notification(_success_notification_text(entry), config.notifications_path)
    print(_success_notification_text(entry))
    return True


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
    parser.add_argument(
        "--sync-thumbnails", action="store_true",
        help="Attach the poster (<clip>.thumb.png) to every not-yet-uploaded entry that lacks one",
    )
    parser.add_argument("--client-secret", default="client_secret.json", help="OAuth client secret JSON path")
    parser.add_argument("--token", default="upload_token.json", help="Cached upload-scoped OAuth token JSON path")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    return parser


def run_command(
    args: argparse.Namespace, service_factory, config, thumbnail_upload: bool = True
) -> None:
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
            poster = "+thumb" if entry.get("thumbnail_path") else ""
            print(f"{entry['seq']}\t{entry['status']}\t{poster}\t{entry['title']}")
        return

    if args.sync_thumbnails:
        queue = load_queue(queue_path)
        attached = attach_missing_thumbnails(queue)
        save_queue(queue, queue_path)
        for entry in attached:
            print(f"{entry['seq']}\t{Path(entry['thumbnail_path']).name}")
        print(f"{len(attached)} entries gained a poster")
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
        _upload_one(entry, queue, service_factory, config, thumbnail_upload)
        return

    if args.check:
        queue = load_queue(queue_path)
        # Reconcile-first (PUB-05): any crash-mid-upload entry must be
        # resolved before a fresh item is ever selected.
        reconcile_all_uploading(queue, service_factory)
        save_queue(queue, queue_path)

        # Flip any past-due SCHEDULED entry over to PUBLISHED once YouTube
        # confirms it actually went live - otherwise the local manifest
        # drifts from reality forever (nothing else makes this transition).
        reconcile_all_scheduled(queue, service_factory)
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
        _upload_one(
            entry, queue, service_factory, config, thumbnail_upload,
            fetch_channel_scheduled_slots(service_factory()),
        )
        return

    print("no action given - use --check/--now/--pause/--kill/--resume/--list")


def main() -> None:
    # Clip titles are Russian and the Windows console defaults to cp1251, so
    # --list died with UnicodeEncodeError on any title carrying a character
    # outside that codepage - an em dash was enough. Printing is this tool's
    # whole read path; make it independent of the console's codepage.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")

    parser = build_argument_parser()
    args = parser.parse_args()

    if __package__ in (None, ""):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from scripts.config import load_config
    from scripts.youtube_analytics import load_credentials
    from googleapiclient.discovery import build

    full_config = load_config(args.config)
    config = full_config.publish

    def service_factory():
        credentials = load_credentials(args.client_secret, args.token, [UPLOAD_SCOPE])
        return build("youtube", "v3", credentials=credentials)

    # This normally runs unattended from the scheduler, under pythonw.exe -
    # no console, so anything printed is discarded and a crash leaves nothing
    # but a non-zero exit code in Task Scheduler (seen 2026-08-06 00:00, cause
    # unrecoverable after the fact). _upload_one already logs upload errors;
    # this catches everything outside it - config, OAuth refresh, reconcile -
    # so the notification log always says what happened.
    try:
        run_command(args, service_factory, config, full_config.thumbnail.upload)
    except Exception as error:
        append_notification(f"[error] {type(error).__name__}: {error}", config.notifications_path)
        raise


if __name__ == "__main__":
    main()
