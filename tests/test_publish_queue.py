from datetime import datetime, timezone

import pytest

from scripts.publish_queue import (
    KILLED,
    PAUSED,
    QUEUED,
    SCHEDULED,
    UPLOADING,
    UPLOAD_SCOPE,
    VALID_STATUSES,
    build_insert_body,
    cancel_scheduled_release,
    collect_scheduled_slots,
    enqueue,
    kill_item,
    load_queue,
    next_free_slot,
    pause_item,
    resume_item,
    save_queue,
    select_next_due,
    upload_and_schedule,
    verify_killed,
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


# --- Task 2: build_insert_body + upload_and_schedule -----------------------


class FakePublishConfig:
    """Minimal stand-in for scripts.config.PublishConfig - only the fields
    upload_and_schedule actually reads."""

    def __init__(self, enabled, daily_slots_utc=None, client_secret_path="client_secret.json",
                 upload_token_path="upload_token.json"):
        self.enabled = enabled
        self.daily_slots_utc = daily_slots_utc or DAILY_SLOTS_UTC
        self.client_secret_path = client_secret_path
        self.upload_token_path = upload_token_path


class FakeNextChunkRequest:
    """Records the insert() call's kwargs and yields a single next_chunk()
    call returning (None, {"id": ...}) - mirrors the resumable-upload
    protocol shape without a real network call."""

    def __init__(self, video_id, **kwargs):
        self.kwargs = kwargs
        self._video_id = video_id
        self._done = False

    def next_chunk(self):
        if self._done:
            raise AssertionError("next_chunk called again after completion")
        self._done = True
        return None, {"id": self._video_id}


class FakeVideosInsertService:
    """Fake youtube service exposing only videos().insert(...) - records the
    body passed so tests can assert on it, house style per
    tests/test_youtube_analytics.py's FakeVideosService."""

    def __init__(self, video_id="vid_fake"):
        self.video_id = video_id
        self.insert_calls = []

    def videos(self):
        return self

    def insert(self, **kwargs):
        self.insert_calls.append(kwargs)
        return FakeNextChunkRequest(self.video_id, **kwargs)


def make_entry(**overrides):
    entry = {
        "seq": 1,
        "clip_id": "clip-1",
        "video_path": "clip1.mp4",
        "metadata_path": "clip1.txt",
        "title": "Title 1",
        "description": "Desc 1",
        "tags": ["a", "b"],
        "status": QUEUED,
        "video_id": None,
        "publish_at": None,
        "enqueued_at": "2026-07-08T00:00:00Z",
        "updated_at": "2026-07-08T00:00:00Z",
    }
    entry.update(overrides)
    return entry


def test_upload_scope_is_exactly_the_upload_scope_constant():
    assert UPLOAD_SCOPE == "https://www.googleapis.com/auth/youtube.upload"


def test_build_insert_body_shapes_snippet_and_status():
    now = datetime(2026, 7, 8, 10, 0, tzinfo=timezone.utc)
    publish_at = next_free_slot(DAILY_SLOTS_UTC, [], now=now)

    body = build_insert_body(
        title="My Clip", description="A description", tags=["a", "b"],
        publish_at=publish_at, seq=7,
    )

    assert body["snippet"]["title"] == "My Clip"
    assert body["snippet"]["tags"] == ["a", "b"]
    assert body["status"]["privacyStatus"] == "private"
    assert body["status"]["publishAt"] == publish_at
    assert body["status"]["selfDeclaredMadeForKids"] is False
    # Stable machine-readable marker for local seq, for Plan 03 reconciliation.
    assert "7" in body["snippet"]["description"]
    assert "A description" in body["snippet"]["description"]


def test_build_insert_body_rejects_oversized_title():
    with pytest.raises(ValueError):
        build_insert_body(
            title="x" * 101, description="d", tags=[], publish_at="2026-07-08T15:00:00Z", seq=1,
        )


def test_build_insert_body_rejects_oversized_description():
    with pytest.raises(ValueError):
        build_insert_body(
            title="t", description="x" * 5001, tags=[], publish_at="2026-07-08T15:00:00Z", seq=1,
        )


def test_build_insert_body_rejects_oversized_combined_tags():
    with pytest.raises(ValueError):
        build_insert_body(
            title="t", description="d", tags=["x" * 500 for _ in range(2)],
            publish_at="2026-07-08T15:00:00Z", seq=1,
        )


def test_dry_run_makes_zero_calls_and_does_not_advance_status(tmp_path):
    queue_path = str(tmp_path / "queue.json")
    queue = load_queue(queue_path)
    entry = enqueue(
        queue, clip_id="clip-1", video_path="clip1.mp4", metadata_path="clip1.txt",
        title="Title 1", description="Desc 1", tags=["a"],
    )
    config = FakePublishConfig(enabled=False)

    def service_factory_should_not_be_called():
        raise AssertionError("service_factory must not be called in dry-run mode")

    now = datetime(2026, 7, 8, 10, 0, tzinfo=timezone.utc)
    result = upload_and_schedule(
        queue, entry, service_factory_should_not_be_called, config, now=now,
    )

    assert result == {"dry_run": True}
    assert entry["status"] == QUEUED


def test_upload_and_schedule_enabled_drives_status_transitions_and_body(tmp_path):
    queue_path = str(tmp_path / "queue.json")
    # MediaFileUpload opens the file at construction time, so this must be a
    # real (if empty) file on disk rather than a bare string path.
    video_path = tmp_path / "clip1.mp4"
    video_path.write_bytes(b"")
    queue = load_queue(queue_path)
    entry = enqueue(
        queue, clip_id="clip-1", video_path=str(video_path), metadata_path="clip1.txt",
        title="Title 1", description="Desc 1", tags=["a"],
    )
    config = FakePublishConfig(enabled=True)
    fake_service = FakeVideosInsertService(video_id="vid_fake")
    save_calls = []

    def service_factory():
        return fake_service

    now = datetime(2026, 7, 8, 10, 0, tzinfo=timezone.utc)

    # Monkeypatch-free save-order check: wrap save_queue via a local closure
    # by passing queue_path so upload_and_schedule's own internal save_queue
    # calls are inspectable through the persisted file after the fact, and
    # by asserting status was UPLOADING at the moment insert() was called.
    original_insert = fake_service.insert

    def spying_insert(**kwargs):
        # At the moment insert() fires, the write-ahead status must already
        # be UPLOADING and already persisted to disk (PUB-05 write-ahead).
        assert entry["status"] == UPLOADING
        persisted = load_queue(queue_path)
        assert persisted["entries"][0]["status"] == UPLOADING
        return original_insert(**kwargs)

    fake_service.insert = spying_insert

    video_id = upload_and_schedule(
        queue, entry, service_factory, config, now=now, queue_path=queue_path,
    )

    assert video_id == "vid_fake"
    assert entry["status"] == SCHEDULED
    assert entry["video_id"] == "vid_fake"
    assert entry["publish_at"] == "2026-07-08T15:00:00Z"

    call_kwargs = fake_service.insert_calls[0]
    body = call_kwargs["body"]
    assert body["status"]["privacyStatus"] == "private"
    assert body["status"]["publishAt"] == "2026-07-08T15:00:00Z"
    assert "1" in body["snippet"]["description"]

    persisted = load_queue(queue_path)
    assert persisted["entries"][0]["status"] == SCHEDULED
    assert persisted["entries"][0]["video_id"] == "vid_fake"


# --- Task 1: pause/resume/kill/revert/verify (PUB-04) -----------------------


class FakeVideosUpdateService:
    """Fake youtube service exposing videos().update(...) and
    videos().list(...) - records the update body, and returns a
    pre-configured status for the post-kill verify re-fetch. House style per
    tests/test_youtube_analytics.py's FakeVideosService."""

    def __init__(self, list_privacy_status="private"):
        self.update_calls = []
        self.list_calls = []
        self._list_privacy_status = list_privacy_status
        self._mode = None

    def videos(self):
        return self

    def update(self, **kwargs):
        self.update_calls.append(kwargs)
        self._mode = "update"
        return self

    def list(self, **kwargs):
        self.list_calls.append(kwargs)
        self._mode = "list"
        return self

    def execute(self):
        if self._mode == "update":
            return {"id": "vid_fake", "status": {"privacyStatus": self._list_privacy_status}}
        return {
            "items": [
                {"id": "vid_fake", "status": {"privacyStatus": self._list_privacy_status}}
            ]
        }


def test_pause_item_flips_queued_to_paused():
    queue = {"entries": [make_entry(clip_id="clip-1", status=QUEUED)]}

    pause_item(queue, "clip-1")

    assert queue["entries"][0]["status"] == PAUSED


def test_resume_item_flips_paused_back_to_queued():
    queue = {"entries": [make_entry(clip_id="clip-1", status=PAUSED)]}

    resume_item(queue, "clip-1")

    assert queue["entries"][0]["status"] == QUEUED


def test_select_next_due_skips_paused_items():
    queue = {
        "entries": [
            make_entry(clip_id="clip-1", seq=1, status=PAUSED),
            make_entry(clip_id="clip-2", seq=2, status=QUEUED),
        ]
    }

    next_entry = select_next_due(queue)

    assert next_entry["clip_id"] == "clip-2"


def test_select_next_due_skips_killed_items():
    queue = {
        "entries": [
            make_entry(clip_id="clip-1", seq=1, status=KILLED),
            make_entry(clip_id="clip-2", seq=2, status=QUEUED),
        ]
    }

    next_entry = select_next_due(queue)

    assert next_entry["clip_id"] == "clip-2"


def test_select_next_due_returns_none_when_nothing_eligible():
    queue = {
        "entries": [
            make_entry(clip_id="clip-1", seq=1, status=PAUSED),
            make_entry(clip_id="clip-2", seq=2, status=KILLED),
        ]
    }

    assert select_next_due(queue) is None


def test_kill_item_not_yet_uploaded_is_local_only_no_service_call():
    queue = {"entries": [make_entry(clip_id="clip-1", status=QUEUED, video_id=None)]}

    def service_factory_should_not_be_called():
        raise AssertionError("service_factory must not be called for a not-yet-uploaded kill")

    kill_item(queue, "clip-1", service_factory_should_not_be_called)

    assert queue["entries"][0]["status"] == KILLED


def test_kill_item_paused_not_yet_uploaded_is_also_local_only():
    queue = {"entries": [make_entry(clip_id="clip-1", status=PAUSED, video_id=None)]}

    def service_factory_should_not_be_called():
        raise AssertionError("service_factory must not be called for a not-yet-uploaded kill")

    kill_item(queue, "clip-1", service_factory_should_not_be_called)

    assert queue["entries"][0]["status"] == KILLED


def test_kill_item_uploading_with_no_video_id_is_local_only():
    # Simulates a kill request racing an in-flight upload that hasn't yet
    # produced a video_id - still safe to treat as local-only.
    queue = {"entries": [make_entry(clip_id="clip-1", status=UPLOADING, video_id=None)]}

    def service_factory_should_not_be_called():
        raise AssertionError("service_factory must not be called when there is no video_id yet")

    kill_item(queue, "clip-1", service_factory_should_not_be_called)

    assert queue["entries"][0]["status"] == KILLED


def test_cancel_scheduled_release_sends_exact_revert_body_no_publish_at():
    service = FakeVideosUpdateService()

    cancel_scheduled_release(service, "vid_fake")

    assert len(service.update_calls) == 1
    call = service.update_calls[0]
    assert call["part"] == "status"
    assert call["body"]["id"] == "vid_fake"
    assert call["body"]["status"]["privacyStatus"] == "private"
    assert "publishAt" not in call["body"]["status"]


def test_verify_killed_returns_true_when_private():
    service = FakeVideosUpdateService(list_privacy_status="private")

    assert verify_killed(service, "vid_fake") is True
    assert service.list_calls[0]["part"] == "status"
    assert service.list_calls[0]["id"] == "vid_fake"


def test_verify_killed_returns_false_when_not_private():
    service = FakeVideosUpdateService(list_privacy_status="public")

    assert verify_killed(service, "vid_fake") is False


def test_kill_item_scheduled_calls_revert_then_verify_then_marks_killed():
    queue = {
        "entries": [
            make_entry(clip_id="clip-1", status=SCHEDULED, video_id="vid_fake")
        ]
    }
    service = FakeVideosUpdateService(list_privacy_status="private")

    def service_factory():
        return service

    kill_item(queue, "clip-1", service_factory)

    assert len(service.update_calls) == 1
    assert len(service.list_calls) == 1
    assert queue["entries"][0]["status"] == KILLED


def test_kill_item_scheduled_failed_verify_blocks_killed_mark_and_raises():
    queue = {
        "entries": [
            make_entry(clip_id="clip-1", status=SCHEDULED, video_id="vid_fake")
        ]
    }
    # Verify re-fetch reports the video did NOT actually go private - the
    # kill did not take (Pitfall 2 warning sign).
    service = FakeVideosUpdateService(list_privacy_status="public")

    def service_factory():
        return service

    with pytest.raises(RuntimeError):
        kill_item(queue, "clip-1", service_factory)

    # A failed verify must NOT let the manifest trust the kill.
    assert queue["entries"][0]["status"] != KILLED
    assert queue["entries"][0]["status"] == SCHEDULED
