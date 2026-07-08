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
from datetime import datetime, timezone
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
