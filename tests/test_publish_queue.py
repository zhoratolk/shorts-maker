from scripts.publish_queue import (
    QUEUED,
    VALID_STATUSES,
    enqueue,
    load_queue,
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
