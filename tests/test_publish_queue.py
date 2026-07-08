from datetime import datetime, timezone

from scripts.publish_queue import (
    QUEUED,
    SCHEDULED,
    VALID_STATUSES,
    collect_scheduled_slots,
    enqueue,
    load_queue,
    next_free_slot,
    save_queue,
)


def test_valid_statuses_contains_exactly_six_states():
    assert VALID_STATUSES == frozenset(
        {"queued", "uploading", "scheduled", "published", "killed", "paused"}
    )


def test_load_queue_returns_empty_entries_when_file_missing(tmp_path):
    queue_path = str(tmp_path / "does_not_exist" / "queue.json")

    queue = load_queue(queue_path)

    assert queue == {"entries": []}


def test_sequential_numbering(tmp_path):
    queue_path = str(tmp_path / "queue.json")
    queue = load_queue(queue_path)

    entry1 = enqueue(
        queue,
        clip_id="clip-1",
        video_path="clip1.mp4",
        metadata_path="clip1.txt",
        title="Title 1",
        description="Desc 1",
        tags=["a"],
    )
    entry2 = enqueue(
        queue,
        clip_id="clip-2",
        video_path="clip2.mp4",
        metadata_path="clip2.txt",
        title="Title 2",
        description="Desc 2",
        tags=["b"],
    )
    entry3 = enqueue(
        queue,
        clip_id="clip-3",
        video_path="clip3.mp4",
        metadata_path="clip3.txt",
        title="Title 3",
        description="Desc 3",
        tags=["c"],
    )

    assert entry1["seq"] == 1
    assert entry2["seq"] == 2
    assert entry3["seq"] == 3
    assert len(queue["entries"]) == 3
    assert entry1["status"] == QUEUED
    assert entry1["video_id"] is None
    assert entry1["publish_at"] is None
    assert entry1["enqueued_at"]
    assert entry1["updated_at"]


def test_enqueue_is_idempotent_on_clip_id(tmp_path):
    queue_path = str(tmp_path / "queue.json")
    queue = load_queue(queue_path)

    enqueue(
        queue,
        clip_id="clip-1",
        video_path="clip1.mp4",
        metadata_path="clip1.txt",
        title="Title 1",
        description="Desc 1",
        tags=["a"],
    )
    enqueue(
        queue,
        clip_id="clip-2",
        video_path="clip2.mp4",
        metadata_path="clip2.txt",
        title="Title 2",
        description="Desc 2",
        tags=["b"],
    )
    enqueue(
        queue,
        clip_id="clip-3",
        video_path="clip3.mp4",
        metadata_path="clip3.txt",
        title="Title 3",
        description="Desc 3",
        tags=["c"],
    )

    duplicate = enqueue(
        queue,
        clip_id="clip-2",
        video_path="clip2-different-path.mp4",
        metadata_path="clip2.txt",
        title="Title 2",
        description="Desc 2",
        tags=["b"],
    )

    assert duplicate["seq"] == 2
    assert len(queue["entries"]) == 3


def test_save_and_load_queue_round_trips(tmp_path):
    queue_path = str(tmp_path / "nested" / "queue.json")
    queue = load_queue(queue_path)
    enqueue(
        queue,
        clip_id="clip-1",
        video_path="clip1.mp4",
        metadata_path="clip1.txt",
        title="Title 1",
        description="Desc 1",
        tags=["a"],
    )

    save_queue(queue, queue_path)
    reloaded = load_queue(queue_path)

    assert reloaded == queue
    assert reloaded["entries"][0]["seq"] == 1
    assert reloaded["entries"][0]["status"] == QUEUED
    assert reloaded["entries"][0]["clip_id"] == "clip-1"


DAILY_SLOTS_UTC = ["09:00", "15:00", "20:00"]


def test_next_free_slot_returns_next_future_grid_time():
    # 10:00 UTC -> 09:00 slot already past today, next is 15:00 today.
    now = datetime(2026, 7, 8, 10, 0, tzinfo=timezone.utc)

    slot = next_free_slot(DAILY_SLOTS_UTC, already_scheduled=[], now=now)

    assert slot == "2026-07-08T15:00:00Z"


def test_next_free_slot_skips_already_used_slot():
    now = datetime(2026, 7, 8, 10, 0, tzinfo=timezone.utc)

    slot = next_free_slot(
        DAILY_SLOTS_UTC, already_scheduled=["2026-07-08T15:00:00Z"], now=now
    )

    assert slot == "2026-07-08T20:00:00Z"


def test_next_free_slot_rolls_to_tomorrow_when_today_exhausted():
    now = datetime(2026, 7, 8, 21, 0, tzinfo=timezone.utc)

    slot = next_free_slot(DAILY_SLOTS_UTC, already_scheduled=[], now=now)

    assert slot == "2026-07-09T09:00:00Z"


def test_next_free_slot_never_returns_a_past_timestamp():
    # A slot exactly equal to now must be skipped - strictly future only.
    now = datetime(2026, 7, 8, 9, 0, tzinfo=timezone.utc)

    slot = next_free_slot(DAILY_SLOTS_UTC, already_scheduled=[], now=now)

    assert slot == "2026-07-08T15:00:00Z"
    assert datetime.fromisoformat(slot.replace("Z", "+00:00")) > now


def test_collect_scheduled_slots_returns_publish_at_of_scheduled_entries():
    queue = {
        "entries": [
            {"status": SCHEDULED, "publish_at": "2026-07-08T15:00:00Z"},
            {"status": QUEUED, "publish_at": None},
            {"status": SCHEDULED, "publish_at": "2026-07-08T20:00:00Z"},
        ]
    }

    assert collect_scheduled_slots(queue) == [
        "2026-07-08T15:00:00Z",
        "2026-07-08T20:00:00Z",
    ]
