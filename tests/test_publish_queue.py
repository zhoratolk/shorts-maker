import io
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts import publish_queue

from scripts.publish_queue import (
    BLOCKED,
    KILLED,
    MAX_UPLOAD_ATTEMPTS,
    PAUSED,
    PUBLISHED,
    QUEUED,
    SCHEDULED,
    UPLOADING,
    UPLOAD_SCOPE,
    VALID_STATUSES,
    append_notification,
    attach_missing_thumbnails,
    build_argument_parser,
    build_insert_body,
    cancel_scheduled_release,
    collect_scheduled_slots,
    default_thumbnail_path,
    enqueue,
    interleave_loops,
    kill_item,
    load_queue,
    next_free_slot,
    pause_item,
    read_unread_notifications,
    reconcile_all_scheduled,
    reconcile_all_uploading,
    reconcile_uploading,
    resume_item,
    run_command,
    save_queue,
    select_next_due,
    set_thumbnail,
    upload_and_schedule,
    fetch_privacy_status,
    verify_killed,
    _try_set_thumbnail,
)


def test_valid_statuses_contains_exactly_seven_states():
    """`blocked` joined the set: an entry that keeps failing the same way is set aside
    so the queue behind it keeps moving, instead of being retried on every tick."""
    assert VALID_STATUSES == frozenset(
        {"queued", "uploading", "scheduled", "published", "killed", "paused", "blocked"}
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


def test_interleave_loops_spreads_two_loops_through_nine_regular():
    items = [f"r{index}" for index in range(9)] + ["L0", "L1"]

    ordered = interleave_loops(items, lambda item: item.startswith("L"))

    loop_positions = [index for index, item in enumerate(ordered) if item.startswith("L")]
    assert len(ordered) == 11
    assert sorted(ordered) == sorted(items)
    # not adjacent, and not both crammed at one end
    assert loop_positions[1] - loop_positions[0] > 1
    assert loop_positions == [2, 8]


def test_interleave_loops_preserves_order_within_each_group():
    items = ["r0", "r1", "r2", "r3", "L0", "L1"]

    ordered = interleave_loops(items, lambda item: item.startswith("L"))

    assert [item for item in ordered if item.startswith("r")] == ["r0", "r1", "r2", "r3"]
    assert [item for item in ordered if item.startswith("L")] == ["L0", "L1"]


def test_interleave_loops_is_a_noop_when_one_group_is_empty():
    only_regular = ["r0", "r1"]
    only_loops = ["L0", "L1"]
    predicate = lambda item: item.startswith("L")  # noqa: E731

    assert interleave_loops(only_regular, predicate) == only_regular
    assert interleave_loops(only_loops, predicate) == only_loops


def test_interleave_loops_handles_loops_outnumbering_regular():
    items = ["r0", "L0", "L1", "L2"]

    ordered = interleave_loops(items, lambda item: item.startswith("L"))

    assert len(ordered) == 4
    assert sorted(ordered) == sorted(items)


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
    assert UPLOAD_SCOPE == "https://www.googleapis.com/auth/youtube"


def test_build_insert_body_shapes_snippet_and_status():
    now = datetime(2026, 7, 8, 10, 0, tzinfo=timezone.utc)
    publish_at = next_free_slot(DAILY_SLOTS_UTC, [], now=now)

    body = build_insert_body(
        title="My Clip", description="A description", tags=["a", "b"],
        publish_at=publish_at, seq=7,
    )

    assert body["snippet"]["title"] == "My Clip"
    assert body["snippet"]["tags"] == ["a", "b"]
    # Gaming category is always set explicitly - uploads without one land in
    # the default "People & Blogs", hurting search/browse classification.
    assert body["snippet"]["categoryId"] == "20"
    assert body["status"]["privacyStatus"] == "private"
    assert body["status"]["publishAt"] == publish_at
    assert body["status"]["selfDeclaredMadeForKids"] is False
    # The description is published verbatim - the old "[queue-id: N]" marker
    # leaked into the public description and was removed.
    assert body["snippet"]["description"] == "A description"


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


# --- Custom thumbnail (thumbnails.set) --------------------------------------

class FakeThumbnailsRequest:
    def __init__(self, recorder, raise_error=None, **kwargs):
        self._recorder = recorder
        self._raise_error = raise_error
        self.kwargs = kwargs

    def execute(self):
        if self._raise_error is not None:
            raise self._raise_error
        self._recorder.append(self.kwargs)
        return {"items": []}


class FakeVideosAndThumbnailsService(FakeVideosInsertService):
    """Extends the insert-only fake with a recording thumbnails().set()."""

    def __init__(self, video_id="vid_fake", thumbnail_error=None):
        super().__init__(video_id)
        self.thumbnail_set_calls = []
        self._thumbnail_error = thumbnail_error

    def thumbnails(self):
        return self

    def set(self, **kwargs):
        return FakeThumbnailsRequest(self.thumbnail_set_calls, self._thumbnail_error, **kwargs)


def test_upload_and_schedule_sets_thumbnail_when_path_present(tmp_path):
    queue_path = str(tmp_path / "queue.json")
    video_path = tmp_path / "clip1.mp4"
    video_path.write_bytes(b"")
    thumb_path = tmp_path / "thumb.png"
    thumb_path.write_bytes(b"\x89PNG\r\n")
    queue = load_queue(queue_path)
    entry = enqueue(
        queue, clip_id="clip-1", video_path=str(video_path), metadata_path="clip1.txt",
        title="T", description="D", tags=["a"], thumbnail_path=str(thumb_path),
    )
    fake_service = FakeVideosAndThumbnailsService(video_id="vid_fake")

    upload_and_schedule(
        queue, entry, lambda: fake_service, FakePublishConfig(enabled=True),
        now=datetime(2026, 7, 8, 10, 0, tzinfo=timezone.utc), queue_path=queue_path,
    )

    assert entry["thumbnail_set"] is True
    assert fake_service.thumbnail_set_calls[0]["videoId"] == "vid_fake"
    assert load_queue(queue_path)["entries"][0]["thumbnail_set"] is True


def test_upload_and_schedule_no_thumbnail_path_leaves_it_untouched(tmp_path):
    queue_path = str(tmp_path / "queue.json")
    video_path = tmp_path / "clip1.mp4"
    video_path.write_bytes(b"")
    queue = load_queue(queue_path)
    entry = enqueue(
        queue, clip_id="clip-1", video_path=str(video_path), metadata_path="clip1.txt",
        title="T", description="D", tags=["a"],
    )
    fake_service = FakeVideosAndThumbnailsService(video_id="vid_fake")

    upload_and_schedule(
        queue, entry, lambda: fake_service, FakePublishConfig(enabled=True),
        now=datetime(2026, 7, 8, 10, 0, tzinfo=timezone.utc), queue_path=queue_path,
    )

    assert "thumbnail_set" not in entry
    assert fake_service.thumbnail_set_calls == []


def test_try_set_thumbnail_missing_file_returns_false(tmp_path):
    calls = []

    class Recorder:
        def thumbnails(self):
            return self

        def set(self, **kwargs):
            calls.append(kwargs)
            return FakeThumbnailsRequest(calls, **kwargs)

    assert _try_set_thumbnail(Recorder(), "vid", str(tmp_path / "nope.png")) is False
    assert calls == []  # short-circuits before any API call


def test_try_set_thumbnail_fail_open_on_api_error(tmp_path):
    thumb_path = tmp_path / "thumb.png"
    thumb_path.write_bytes(b"\x89PNG\r\n")
    service = FakeVideosAndThumbnailsService(thumbnail_error=RuntimeError("403 not eligible"))
    assert _try_set_thumbnail(service, "vid", str(thumb_path)) is False


def test_set_thumbnail_calls_api(tmp_path):
    thumb_path = tmp_path / "thumb.png"
    thumb_path.write_bytes(b"\x89PNG\r\n")
    service = FakeVideosAndThumbnailsService()
    set_thumbnail(service, "vid_x", str(thumb_path))
    assert service.thumbnail_set_calls[0]["videoId"] == "vid_x"


# --- Task 1: pause/resume/kill/revert/verify (PUB-04) -----------------------


class FakeVideosUpdateService:
    """Fake youtube service exposing videos().update(...) and
    videos().list(...) - records the update body, and returns a
    pre-configured status for the post-kill verify re-fetch. House style per
    tests/test_youtube_analytics.py's FakeVideosService."""

    def __init__(self, list_privacy_status="private", missing=False, update_error=None):
        self.update_calls = []
        self.list_calls = []
        self._list_privacy_status = list_privacy_status
        self._missing = missing
        self._update_error = update_error
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
            if self._update_error is not None:
                raise self._update_error
            return {"id": "vid_fake", "status": {"privacyStatus": self._list_privacy_status}}
        if self._missing:
            return {"items": []}
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


class _FakeApiError(Exception):
    """Stands in for googleapiclient.errors.HttpError: only the resp.status
    is read, so the fake needs nothing more than that."""

    def __init__(self, status):
        super().__init__(f"api error {status}")
        self.resp = type("Resp", (), {"status": status})()


def test_fetch_privacy_status_returns_none_when_the_video_is_gone():
    service = FakeVideosUpdateService(missing=True)

    assert fetch_privacy_status(service, "vid_fake") is None
    assert verify_killed(service, "vid_fake") is False


def test_kill_item_marks_killed_when_the_video_no_longer_exists():
    # A video deleted outside this tool leaves a SCHEDULED entry that the
    # strict verify could never clear - the schedule cannot fire either way.
    queue = {
        "entries": [
            make_entry(clip_id="clip-1", status=SCHEDULED, video_id="vid_fake")
        ]
    }
    service = FakeVideosUpdateService(missing=True)

    kill_item(queue, "clip-1", lambda: service)

    assert queue["entries"][0]["status"] == KILLED
    assert queue["entries"][0]["kill_note"] == "video already absent from YouTube"


def test_kill_item_marks_killed_when_the_revert_itself_404s():
    queue = {
        "entries": [
            make_entry(clip_id="clip-1", status=SCHEDULED, video_id="vid_fake")
        ]
    }
    service = FakeVideosUpdateService(update_error=_FakeApiError(404))

    kill_item(queue, "clip-1", lambda: service)

    assert queue["entries"][0]["status"] == KILLED
    assert service.list_calls == []


def test_kill_item_reraises_an_api_error_that_is_not_a_missing_video():
    queue = {
        "entries": [
            make_entry(clip_id="clip-1", status=SCHEDULED, video_id="vid_fake")
        ]
    }
    service = FakeVideosUpdateService(update_error=_FakeApiError(500))

    with pytest.raises(_FakeApiError):
        kill_item(queue, "clip-1", lambda: service)

    assert queue["entries"][0]["status"] != KILLED


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


# --- Task 2: reconcile_uploading - crash-mid-upload safety (PUB-05) --------


class FakeChannelsServiceForReconcile:
    def __init__(self):
        self.calls = []

    def channels(self):
        return self

    def list(self, **kwargs):
        self.calls.append(kwargs)
        return self

    def execute(self):
        return {
            "items": [
                {"id": "UC1", "contentDetails": {"relatedPlaylists": {"uploads": "UU1"}}}
            ]
        }


class FakePlaylistItemsServiceForReconcile:
    def __init__(self, videos):
        # videos: list of {"video_id", "title", "published_at"}
        self._videos = videos
        self.calls = []

    def playlistItems(self):
        return self

    def list(self, **kwargs):
        self.calls.append(kwargs)
        return self

    def execute(self):
        return {
            "items": [
                {
                    "snippet": {
                        "resourceId": {"videoId": v["video_id"]},
                        "title": v["title"],
                        "publishedAt": v["published_at"],
                    }
                }
                for v in self._videos
            ]
        }


class FakeReconcileService:
    """Combines channels/playlistItems/videos resources on one object -
    reconcile_uploading calls get_own_channel + list_uploaded_videos (both
    reused from youtube_analytics.py) and matches the stuck entry by exact
    title, all against the same service object."""

    def __init__(self, uploaded_videos):
        self._channels = FakeChannelsServiceForReconcile()
        self._playlist = FakePlaylistItemsServiceForReconcile(uploaded_videos)
        self.insert_calls = []

    def channels(self):
        return self._channels

    def playlistItems(self):
        return self._playlist

    def videos(self):
        return self


    def insert(self, **kwargs):
        self.insert_calls.append(kwargs)
        raise AssertionError("videos().insert must never be called during reconciliation")


def test_reconcile_uploading_adopts_video_id_when_title_matches():
    queue = {
        "entries": [
            make_entry(clip_id="clip-1", seq=7, status=UPLOADING, video_id=None)
        ]
    }
    entry = queue["entries"][0]
    service = FakeReconcileService(
        uploaded_videos=[
            {"video_id": "vid_match", "title": "Title 1", "published_at": "2026-07-08T09:00:00Z"},
            {"video_id": "vid_other", "title": "Unrelated", "published_at": "2026-07-07T09:00:00Z"},
        ],
    )

    def service_factory():
        return service

    reconcile_uploading(queue, entry, service_factory)

    assert entry["status"] == SCHEDULED
    assert entry["video_id"] == "vid_match"
    assert service.insert_calls == []


def test_reconcile_uploading_resets_to_queued_when_no_match():
    queue = {
        "entries": [
            make_entry(clip_id="clip-1", seq=7, status=UPLOADING, video_id=None)
        ]
    }
    entry = queue["entries"][0]
    service = FakeReconcileService(
        uploaded_videos=[
            {"video_id": "vid_other", "title": "Unrelated", "published_at": "2026-07-07T09:00:00Z"},
        ],
    )

    def service_factory():
        return service

    reconcile_uploading(queue, entry, service_factory)

    assert entry["status"] == QUEUED
    assert entry["video_id"] is None
    assert service.insert_calls == []


def test_reconcile_uploading_never_calls_insert():
    queue = {
        "entries": [
            make_entry(clip_id="clip-1", seq=3, status=UPLOADING, video_id=None)
        ]
    }
    entry = queue["entries"][0]
    service = FakeReconcileService(
        uploaded_videos=[
            {"video_id": "vid_match", "title": "Title 1", "published_at": "2026-07-08T09:00:00Z"},
        ],
    )

    def service_factory():
        return service

    reconcile_uploading(queue, entry, service_factory)

    assert service.insert_calls == []


def test_select_next_due_reconciles_uploading_entries_before_selecting_new_item():
    # A stuck UPLOADING entry must be resolved BEFORE the selector would ever
    # consider a fresh QUEUED item - it can't be silently passed over and
    # re-uploaded as a new item (PUB-05).
    queue = {
        "entries": [
            make_entry(clip_id="clip-stuck", seq=1, status=UPLOADING, video_id=None),
            make_entry(clip_id="clip-2", seq=2, status=QUEUED),
        ]
    }
    service = FakeReconcileService(
        uploaded_videos=[
            {"video_id": "vid_match", "title": "Title 1", "published_at": "2026-07-08T09:00:00Z"},
        ],
    )

    def service_factory():
        return service

    reconcile_all_uploading(queue, service_factory)
    next_entry = select_next_due(queue)

    # The stuck entry adopted vid_match and moved to SCHEDULED, so it is no
    # longer QUEUED/UPLOADING - the selector now correctly picks clip-2, the
    # genuinely next-due item, having safely resolved the stuck one first.
    assert queue["entries"][0]["status"] == SCHEDULED
    assert queue["entries"][0]["video_id"] == "vid_match"
    assert next_entry["clip_id"] == "clip-2"
    assert service.insert_calls == []


# --- reconcile_all_scheduled - SCHEDULED->PUBLISHED drift fix --------------


class FakeVideosListService:
    """videos().list(part="status,snippet", id="a,b,...") - videos keyed by
    id, each carrying the fields reconcile_all_scheduled reads."""

    def __init__(self, videos_by_id):
        self._videos_by_id = videos_by_id
        self.list_calls = []

    def videos(self):
        return self

    def list(self, **kwargs):
        self.list_calls.append(kwargs)
        ids = kwargs["id"].split(",")
        items = []
        for video_id in ids:
            video = self._videos_by_id.get(video_id)
            if video is not None:
                items.append(video)
        return self

    def execute(self):
        return {"items": self._last_items()}

    def _last_items(self):
        ids = self.list_calls[-1]["id"].split(",")
        return [self._videos_by_id[v] for v in ids if v in self._videos_by_id]


def test_reconcile_all_scheduled_flips_past_due_public_video_to_published():
    queue = {
        "entries": [
            make_entry(
                clip_id="clip-1", seq=1, status=SCHEDULED, video_id="vid1",
                publish_at="2026-07-16T11:00:00Z",
            )
        ]
    }
    service = FakeVideosListService({
        "vid1": {
            "id": "vid1",
            "status": {"privacyStatus": "public"},
            "snippet": {"publishedAt": "2026-07-16T11:02:13Z"},
        }
    })

    def service_factory():
        return service

    reconcile_all_scheduled(queue, service_factory, now=datetime(2026, 7, 28, 18, 0, tzinfo=timezone.utc))

    entry = queue["entries"][0]
    assert entry["status"] == PUBLISHED
    assert entry["published_at"] == "2026-07-16T11:02:13Z"


def test_reconcile_all_scheduled_leaves_still_private_entry_scheduled():
    queue = {
        "entries": [
            make_entry(
                clip_id="clip-1", seq=1, status=SCHEDULED, video_id="vid1",
                publish_at="2026-07-16T11:00:00Z",
            )
        ]
    }
    service = FakeVideosListService({
        "vid1": {
            "id": "vid1",
            "status": {"privacyStatus": "private"},
            "snippet": {},
        }
    })

    def service_factory():
        return service

    reconcile_all_scheduled(queue, service_factory, now=datetime(2026, 7, 28, 18, 0, tzinfo=timezone.utc))

    entry = queue["entries"][0]
    assert entry["status"] == SCHEDULED
    assert "published_at" not in entry


def test_reconcile_all_scheduled_leaves_a_not_yet_due_entry_youtube_still_calls_private():
    queue = {
        "entries": [
            make_entry(
                clip_id="clip-future", seq=1, status=SCHEDULED, video_id="vid1",
                publish_at="2026-07-30T11:00:00Z",
            )
        ]
    }
    service = FakeVideosListService({
        "vid1": {"id": "vid1", "status": {"privacyStatus": "private"}, "snippet": {}}
    })

    reconcile_all_scheduled(queue, lambda: service, now=datetime(2026, 7, 28, 18, 0, tzinfo=timezone.utc))

    assert queue["entries"][0]["status"] == SCHEDULED


def test_reconcile_all_scheduled_flips_an_entry_that_went_public_ahead_of_its_slot():
    # publish_at is what we asked for, not what happened: a video released by
    # hand in Studio is public well before its local timestamp comes round.
    queue = {
        "entries": [
            make_entry(
                clip_id="clip-early", seq=1, status=SCHEDULED, video_id="vid1",
                publish_at="2026-07-30T11:00:00Z",
            )
        ]
    }
    service = FakeVideosListService({
        "vid1": {
            "id": "vid1",
            "status": {"privacyStatus": "public"},
            "snippet": {"publishedAt": "2026-07-28T09:12:00Z"},
        }
    })

    reconcile_all_scheduled(queue, lambda: service, now=datetime(2026, 7, 28, 18, 0, tzinfo=timezone.utc))

    assert queue["entries"][0]["status"] == PUBLISHED
    assert queue["entries"][0]["published_at"] == "2026-07-28T09:12:00Z"


def test_reconcile_all_scheduled_kills_an_entry_whose_video_is_gone():
    # A video_id YouTube no longer resolves is a video that no longer exists,
    # so its pending release can never fire - leaving it SCHEDULED means
    # waiting forever for something that cannot happen.
    queue = {
        "entries": [
            make_entry(
                clip_id="clip-1", seq=1, status=SCHEDULED, video_id="vid-gone",
                publish_at="2026-07-16T11:00:00Z",
            )
        ]
    }
    service = FakeVideosListService({})

    reconcile_all_scheduled(queue, lambda: service, now=datetime(2026, 7, 28, 18, 0, tzinfo=timezone.utc))

    assert queue["entries"][0]["status"] == KILLED
    assert queue["entries"][0]["kill_note"] == "video already absent from YouTube"


# --- Task 1: notification log - append + read-unread with a marker (D-06) --


def test_append_notification_creates_parent_dirs_and_writes_a_line(tmp_path):
    log_path = str(tmp_path / "_publish" / "notifications.log")

    append_notification("залил 1, выйдет в 09:00 UTC", log_path)

    assert Path(log_path).exists()
    content = Path(log_path).read_text(encoding="utf-8")
    assert "залил 1, выйдет в 09:00 UTC" in content


def test_append_notification_is_append_only_never_rewrites_existing_lines(tmp_path):
    log_path = str(tmp_path / "notifications.log")

    append_notification("first line", log_path)
    append_notification("second line", log_path)

    content = Path(log_path).read_text(encoding="utf-8")
    lines = [line for line in content.splitlines() if line.strip()]
    assert len(lines) == 2
    assert "first line" in lines[0]
    assert "second line" in lines[1]


def test_read_unread_notifications_returns_new_lines_and_advances_marker(tmp_path):
    log_path = str(tmp_path / "notifications.log")
    marker_path = str(tmp_path / "notifications.read")

    append_notification("залил 1, выйдет в 09:00 UTC", log_path)
    append_notification("залил 2, выйдет в 15:00 UTC", log_path)

    unread = read_unread_notifications(log_path, marker_path)

    assert len(unread) == 2
    assert "залил 1, выйдет в 09:00 UTC" in unread[0]
    assert "залил 2, выйдет в 15:00 UTC" in unread[1]


def test_read_unread_notifications_second_read_returns_empty_no_double_report(tmp_path):
    log_path = str(tmp_path / "notifications.log")
    marker_path = str(tmp_path / "notifications.read")

    append_notification("залил 1, выйдет в 09:00 UTC", log_path)

    first_read = read_unread_notifications(log_path, marker_path)
    second_read = read_unread_notifications(log_path, marker_path)

    assert len(first_read) == 1
    assert second_read == []


def test_read_unread_notifications_only_returns_lines_appended_since_last_read(tmp_path):
    log_path = str(tmp_path / "notifications.log")
    marker_path = str(tmp_path / "notifications.read")

    append_notification("залил 1, выйдет в 09:00 UTC", log_path)
    read_unread_notifications(log_path, marker_path)

    append_notification("залил 2, выйдет в 15:00 UTC", log_path)
    second_unread = read_unread_notifications(log_path, marker_path)

    assert len(second_unread) == 1
    assert "залил 2, выйдет в 15:00 UTC" in second_unread[0]


def test_read_unread_notifications_missing_log_returns_empty(tmp_path):
    log_path = str(tmp_path / "does_not_exist.log")
    marker_path = str(tmp_path / "notifications.read")

    assert read_unread_notifications(log_path, marker_path) == []


def test_append_notification_success_line_contains_seq_and_hhmm(tmp_path):
    log_path = str(tmp_path / "notifications.log")

    append_notification("залил 3, выйдет в 20:00 UTC", log_path)

    unread = read_unread_notifications(log_path, str(tmp_path / "notifications.read"))
    assert len(unread) == 1
    line = unread[0]
    assert "3" in line
    assert "20:00" in line


# --- Task 2: argparse CLI - --check/--now/--pause/--kill/--resume/--list ----


class FakeCliPublishConfig:
    """Minimal stand-in for scripts.config.PublishConfig used by run_command
    tests - mirrors FakePublishConfig's fields plus paths run_command needs.
    """

    def __init__(
        self,
        enabled,
        daily_slots_utc=None,
        queue_path="work/_publish/queue.json",
        notifications_path="work/_publish/notifications.log",
        client_secret_path="client_secret.json",
        upload_token_path="upload_token.json",
    ):
        self.enabled = enabled
        self.daily_slots_utc = daily_slots_utc or DAILY_SLOTS_UTC
        self.queue_path = queue_path
        self.notifications_path = notifications_path
        self.client_secret_path = client_secret_path
        self.upload_token_path = upload_token_path


def make_cli_queue(tmp_path, entries):
    queue_path = str(tmp_path / "queue.json")
    save_queue({"entries": entries}, queue_path)
    return queue_path


def test_list_prints_seq_numbers(tmp_path, capsys):
    queue_path = make_cli_queue(
        tmp_path,
        [
            make_entry(clip_id="clip-1", seq=1, status=QUEUED, title="First"),
            make_entry(clip_id="clip-2", seq=2, status=SCHEDULED, title="Second"),
        ],
    )
    config = FakeCliPublishConfig(enabled=False, queue_path=queue_path)

    args = build_argument_parser().parse_args(["--list"])
    run_command(args, service_factory=lambda: None, config=config)

    out = capsys.readouterr().out
    assert "1" in out
    assert "2" in out
    assert "First" in out
    assert "Second" in out


def test_check_dry_run_makes_zero_service_calls(tmp_path, capsys):
    queue_path = make_cli_queue(
        tmp_path, [make_entry(clip_id="clip-1", seq=1, status=QUEUED)]
    )
    config = FakeCliPublishConfig(enabled=False, queue_path=queue_path)

    calls = []

    def service_factory():
        calls.append("called")
        raise AssertionError("service_factory must never be called in dry-run")

    args = build_argument_parser().parse_args(["--check"])
    run_command(args, service_factory=service_factory, config=config)

    assert calls == []
    queue = load_queue(queue_path)
    assert queue["entries"][0]["status"] == QUEUED
    out = capsys.readouterr().out
    assert "dry-run" in out.lower()


def test_check_enabled_uploads_exactly_one_item_and_appends_one_notification(tmp_path):
    video_path = tmp_path / "clip1.mp4"
    video_path.write_bytes(b"fake video bytes")
    queue_path = make_cli_queue(
        tmp_path,
        [
            make_entry(clip_id="clip-1", seq=1, status=QUEUED, video_path=str(video_path)),
            make_entry(clip_id="clip-2", seq=2, status=QUEUED, video_path=str(video_path)),
        ],
    )
    notifications_path = str(tmp_path / "notifications.log")
    marker_path = str(tmp_path / "notifications.read")
    config = FakeCliPublishConfig(
        enabled=True, queue_path=queue_path, notifications_path=notifications_path
    )

    service = FakeVideosInsertService(video_id="vid_checked")

    def service_factory():
        return service

    args = build_argument_parser().parse_args(["--check"])
    run_command(args, service_factory=service_factory, config=config)

    queue = load_queue(queue_path)
    scheduled = [e for e in queue["entries"] if e["status"] == SCHEDULED]
    still_queued = [e for e in queue["entries"] if e["status"] == QUEUED]
    assert len(scheduled) == 1
    assert len(still_queued) == 1
    assert len(service.insert_calls) == 1

    unread = read_unread_notifications(notifications_path, marker_path)
    assert len(unread) == 1
    assert "1" in unread[0]


def test_now_targets_the_named_clip_via_same_upload_path(tmp_path):
    video_path = tmp_path / "clip2.mp4"
    video_path.write_bytes(b"fake video bytes")
    queue_path = make_cli_queue(
        tmp_path,
        [
            make_entry(clip_id="clip-1", seq=1, status=QUEUED, video_path=str(video_path)),
            make_entry(clip_id="clip-2", seq=2, status=QUEUED, video_path=str(video_path)),
        ],
    )
    notifications_path = str(tmp_path / "notifications.log")
    config = FakeCliPublishConfig(
        enabled=True, queue_path=queue_path, notifications_path=notifications_path
    )

    service = FakeVideosInsertService(video_id="vid_now")

    def service_factory():
        return service

    args = build_argument_parser().parse_args(["--now", "clip-2"])
    run_command(args, service_factory=service_factory, config=config)

    queue = load_queue(queue_path)
    entry_1 = next(e for e in queue["entries"] if e["clip_id"] == "clip-1")
    entry_2 = next(e for e in queue["entries"] if e["clip_id"] == "clip-2")
    assert entry_1["status"] == QUEUED
    assert entry_2["status"] == SCHEDULED
    assert len(service.insert_calls) == 1


def test_now_unknown_clip_id_errors_cleanly_not_crash(tmp_path, capsys):
    queue_path = make_cli_queue(
        tmp_path, [make_entry(clip_id="clip-1", seq=1, status=QUEUED)]
    )
    config = FakeCliPublishConfig(enabled=True, queue_path=queue_path)

    args = build_argument_parser().parse_args(["--now", "does-not-exist"])
    with pytest.raises(SystemExit):
        run_command(args, service_factory=lambda: None, config=config)


def test_kill_unknown_clip_id_errors_cleanly_not_crash(tmp_path):
    queue_path = make_cli_queue(
        tmp_path, [make_entry(clip_id="clip-1", seq=1, status=QUEUED)]
    )
    config = FakeCliPublishConfig(enabled=True, queue_path=queue_path)

    args = build_argument_parser().parse_args(["--kill", "does-not-exist"])
    with pytest.raises(SystemExit):
        run_command(args, service_factory=lambda: None, config=config)


def test_pause_and_resume_via_cli_dispatch(tmp_path):
    queue_path = make_cli_queue(
        tmp_path, [make_entry(clip_id="clip-1", seq=1, status=QUEUED)]
    )
    config = FakeCliPublishConfig(enabled=True, queue_path=queue_path)

    pause_args = build_argument_parser().parse_args(["--pause", "clip-1"])
    run_command(pause_args, service_factory=lambda: None, config=config)
    assert load_queue(queue_path)["entries"][0]["status"] == PAUSED

    resume_args = build_argument_parser().parse_args(["--resume", "clip-1"])
    run_command(resume_args, service_factory=lambda: None, config=config)
    assert load_queue(queue_path)["entries"][0]["status"] == QUEUED


def test_default_thumbnail_path_finds_the_sibling_poster(tmp_path):
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"")
    assert default_thumbnail_path(str(clip)) == ""

    poster = tmp_path / "clip.thumb.png"
    poster.write_bytes(b"")
    assert default_thumbnail_path(str(clip)) == str(poster)


def test_enqueue_derives_the_poster_when_the_caller_forgets(tmp_path):
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"")
    poster = tmp_path / "clip.thumb.png"
    poster.write_bytes(b"")
    queue = {"entries": []}

    entry = enqueue(
        queue, clip_id="clip-1", video_path=str(clip), metadata_path="clip.txt",
        title="T", description="D", tags=[],
    )

    assert entry["thumbnail_path"] == str(poster)


def test_enqueue_honours_an_explicit_no_thumbnail(tmp_path):
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"")
    (tmp_path / "clip.thumb.png").write_bytes(b"")
    queue = {"entries": []}

    entry = enqueue(
        queue, clip_id="clip-1", video_path=str(clip), metadata_path="clip.txt",
        title="T", description="D", tags=[], thumbnail_path="",
    )

    assert entry["thumbnail_path"] == ""


def test_attach_missing_thumbnails_skips_already_uploaded_entries(tmp_path):
    def clip_with_poster(name):
        (tmp_path / f"{name}.mp4").write_bytes(b"")
        (tmp_path / f"{name}.thumb.png").write_bytes(b"")
        return str(tmp_path / f"{name}.mp4")

    queue = {
        "entries": [
            make_entry(clip_id="a", seq=1, status=QUEUED, video_path=clip_with_poster("a")),
            make_entry(clip_id="b", seq=2, status=SCHEDULED, video_path=clip_with_poster("b")),
            make_entry(clip_id="c", seq=3, status=QUEUED, video_path=str(tmp_path / "missing.mp4")),
        ]
    }

    changed = attach_missing_thumbnails(queue)

    assert [entry["clip_id"] for entry in changed] == ["a"]
    assert queue["entries"][1].get("thumbnail_path") is None  # already uploaded
    assert queue["entries"][2].get("thumbnail_path") is None  # no poster on disk


def test_attach_missing_thumbnails_never_overwrites_an_existing_path(tmp_path):
    (tmp_path / "a.mp4").write_bytes(b"")
    (tmp_path / "a.thumb.png").write_bytes(b"")
    queue = {
        "entries": [
            make_entry(
                clip_id="a", seq=1, status=QUEUED,
                video_path=str(tmp_path / "a.mp4"), thumbnail_path="chosen/by/hand.png",
            )
        ]
    }

    assert attach_missing_thumbnails(queue) == []
    assert queue["entries"][0]["thumbnail_path"] == "chosen/by/hand.png"


def test_sync_thumbnails_cli_writes_the_paths_back(tmp_path, capsys):
    (tmp_path / "a.mp4").write_bytes(b"")
    (tmp_path / "a.thumb.png").write_bytes(b"")
    queue_path = make_cli_queue(
        tmp_path,
        [make_entry(clip_id="a", seq=1, status=QUEUED, video_path=str(tmp_path / "a.mp4"))],
    )
    config = FakeCliPublishConfig(enabled=False, queue_path=queue_path)

    args = build_argument_parser().parse_args(["--sync-thumbnails"])
    run_command(args, service_factory=lambda: None, config=config)

    assert load_queue(queue_path)["entries"][0]["thumbnail_path"].endswith("a.thumb.png")
    assert "1 entries gained a poster" in capsys.readouterr().out


def test_thumbnail_upload_disabled_skips_the_api_call(tmp_path):
    """config.thumbnail.upload=false must reach the upload path - it used to be
    a dead config key that nothing ever read."""
    (tmp_path / "a.mp4").write_bytes(b"")
    poster = tmp_path / "a.thumb.png"
    poster.write_bytes(b"")
    entry = make_entry(
        clip_id="a", seq=1, status=QUEUED,
        video_path=str(tmp_path / "a.mp4"), thumbnail_path=str(poster),
    )
    queue = {"entries": [entry]}
    service = FakeVideosAndThumbnailsService(video_id="vid-1")

    upload_and_schedule(
        queue, entry, lambda: service, FakePublishConfig(enabled=True),
        now=datetime(2026, 8, 6, 8, 0, tzinfo=timezone.utc),
        queue_path=str(tmp_path / "queue.json"),
        thumbnail_upload=False,
    )

    assert service.thumbnail_set_calls == []
    assert "thumbnail_set" not in entry


def test_main_logs_a_crash_that_happens_outside_the_upload_path(tmp_path, monkeypatch):
    """The scheduler runs this under pythonw.exe with no console, so an
    unlogged crash leaves only a non-zero exit code behind."""
    import scripts.publish_queue as module

    notifications = tmp_path / "notifications.log"
    config = FakeCliPublishConfig(
        enabled=True,
        queue_path=str(tmp_path / "queue.json"),
        notifications_path=str(notifications),
    )

    class FakeFullConfig:
        publish = config
        thumbnail = type("T", (), {"upload": True})()

    monkeypatch.setattr(module, "run_command", _raise_boom)
    monkeypatch.setattr(sys, "argv", ["publish_queue.py", "--check"])
    monkeypatch.setitem(
        sys.modules, "scripts.config",
        type("M", (), {"load_config": staticmethod(lambda path: FakeFullConfig())}),
    )
    monkeypatch.setitem(
        sys.modules, "scripts.youtube_analytics",
        type("M", (), {"load_credentials": staticmethod(lambda *a, **k: None)}),
    )
    monkeypatch.setitem(
        sys.modules, "googleapiclient.discovery",
        type("M", (), {"build": staticmethod(lambda *a, **k: None)}),
    )

    with pytest.raises(RuntimeError, match="boom"):
        module.main()

    assert "[error] RuntimeError: boom" in notifications.read_text(encoding="utf-8")


def _raise_boom(*args, **kwargs):
    raise RuntimeError("boom")


def test_cli_list_prints_titles_a_cp1251_console_cannot_encode(tmp_path):
    """--list is the queue's read path and it died with UnicodeEncodeError on any
    title carrying a character outside the Windows console codepage - an em dash
    was enough. PYTHONIOENCODING=cp1251 reproduces that console here.
    """
    queue_path = tmp_path / "queue.json"
    queue_path.write_text(json.dumps({"entries": [
        {"clip_id": "c1", "seq": 1, "status": "queued", "title": "Слабоумие и отвага — и сразу минус",
         "video_path": str(tmp_path / "c1.mp4"), "description": "", "tags": []},
    ]}, ensure_ascii=False), encoding="utf-8")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"input_dir: {json.dumps(str(tmp_path))}\n"
        f"output_dir: {json.dumps(str(tmp_path))}\n"
        "publish:\n  enabled: true\n"
        f"  queue_path: {json.dumps(str(queue_path))}\n"
        f"  notifications_path: {json.dumps(str(tmp_path / 'notify.log'))}\n",
        encoding="utf-8",
    )
    repo_root = Path(__file__).resolve().parent.parent

    result = subprocess.run(
        [sys.executable, "scripts/publish_queue.py", "--list", "--config", str(config_path)],
        cwd=repo_root, capture_output=True, text=True, encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "cp1251"},
    )

    assert result.returncode == 0, result.stderr
    assert "Слабоумие и отвага" in result.stdout


# --- upload_batch: "on the grid" means on YouTube (2026-08-23) -------------


def _batch_config(tmp_path, enabled=True):
    return FakeCliPublishConfig(
        enabled=enabled,
        queue_path=str(tmp_path / "queue.json"),
        notifications_path=str(tmp_path / "notifications.log"),
    )


def _batch_queue(tmp_path, count):
    """`count` queued entries, each with a real (empty) file to upload."""
    from scripts.publish_queue import upload_batch  # noqa: F401 - import guard

    entries = []
    for index in range(count):
        video_path = tmp_path / f"clip{index}.mp4"
        video_path.write_bytes(b"")
        entries.append(
            make_entry(
                clip_id=f"clip-{index}", seq=index + 1, status=QUEUED,
                title=f"Title {index}", video_path=str(video_path),
            )
        )
    save_queue({"entries": entries}, str(tmp_path / "queue.json"))


def test_upload_batch_uploads_every_queued_clip_not_just_the_first(tmp_path):
    from scripts.publish_queue import upload_batch

    _batch_queue(tmp_path, 3)
    config = _batch_config(tmp_path)
    service = FakeVideosInsertService(video_id="vid")

    uploaded = upload_batch(lambda: service, config)

    assert len(uploaded) == 3
    persisted = load_queue(config.queue_path)["entries"]
    assert [entry["status"] for entry in persisted] == [SCHEDULED] * 3
    # each still lands in its own slot - this loops the single-item path
    assert len({entry["publish_at"] for entry in persisted}) == 3


def test_upload_batch_honours_a_limit(tmp_path):
    from scripts.publish_queue import upload_batch

    _batch_queue(tmp_path, 3)
    config = _batch_config(tmp_path)

    uploaded = upload_batch(lambda: FakeVideosInsertService(video_id="vid"), config, limit=2)

    assert len(uploaded) == 2
    statuses = [entry["status"] for entry in load_queue(config.queue_path)["entries"]]
    assert statuses == [SCHEDULED, SCHEDULED, QUEUED]


def test_upload_batch_uploads_nothing_when_publishing_is_disabled(tmp_path):
    from scripts.publish_queue import upload_batch

    _batch_queue(tmp_path, 2)
    config = _batch_config(tmp_path, enabled=False)

    def service_factory():
        return FakeVideosInsertService(video_id="vid")

    assert upload_batch(service_factory, config) == []
    statuses = [entry["status"] for entry in load_queue(config.queue_path)["entries"]]
    assert statuses == [QUEUED, QUEUED]


def test_upload_batch_stops_cleanly_on_an_empty_queue(tmp_path):
    from scripts.publish_queue import upload_batch

    save_queue({"entries": []}, str(tmp_path / "queue.json"))

    assert upload_batch(lambda: FakeVideosInsertService(video_id="vid"), _batch_config(tmp_path)) == []


# --- the channel's own schedule beats this file's idea of it (2026-08-23) --


class FakeChannelService:
    """channels().list + playlistItems().list + videos().list, enough for
    fetch_channel_scheduled_slots. `videos` maps id -> (privacyStatus, publishAt).
    """

    def __init__(self, videos, pages=None, fail_on=None):
        self._videos = videos
        self._pages = pages or [list(videos.keys())]
        self._fail_on = fail_on
        self._call = None

    def channels(self):
        self._call = "channels"
        return self

    def playlistItems(self):
        self._call = "playlistItems"
        return self

    def videos(self):
        self._call = "videos"
        return self

    def list(self, **kwargs):
        self._kwargs = kwargs
        return self

    def execute(self):
        if self._fail_on == self._call:
            raise RuntimeError("boom")
        if self._call == "channels":
            return {"items": [{"contentDetails": {"relatedPlaylists": {"uploads": "UU_x"}}}]}
        if self._call == "playlistItems":
            index = 0 if self._kwargs.get("pageToken") is None else int(self._kwargs["pageToken"])
            page = self._pages[index]
            result = {"items": [{"contentDetails": {"videoId": v}} for v in page]}
            if index + 1 < len(self._pages):
                result["nextPageToken"] = str(index + 1)
            return result
        items = []
        for video_id in self._kwargs["id"].split(","):
            privacy, publish_at = self._videos[video_id]
            status = {"privacyStatus": privacy}
            if publish_at:
                status["publishAt"] = publish_at
            items.append({"id": video_id, "status": status})
        return {"items": items}


def test_fetch_channel_scheduled_slots_returns_only_pending_private_videos():
    from scripts.publish_queue import fetch_channel_scheduled_slots

    service = FakeChannelService({
        "a": ("private", "2026-08-25T01:00:00Z"),
        "b": ("public", None),
        "c": ("private", None),  # a plain draft, not scheduled
    })

    assert fetch_channel_scheduled_slots(service) == ["2026-08-25T01:00:00Z"]


def test_fetch_channel_scheduled_slots_walks_every_page():
    from scripts.publish_queue import fetch_channel_scheduled_slots

    service = FakeChannelService(
        {"a": ("private", "2026-08-25T01:00:00Z"), "b": ("private", "2026-08-25T05:00:00Z")},
        pages=[["a"], ["b"]],
    )

    assert sorted(fetch_channel_scheduled_slots(service)) == [
        "2026-08-25T01:00:00Z", "2026-08-25T05:00:00Z",
    ]


def test_fetch_channel_scheduled_slots_fails_open_on_an_api_error(capsys):
    from scripts.publish_queue import fetch_channel_scheduled_slots

    service = FakeChannelService({"a": ("private", "2026-08-25T01:00:00Z")}, fail_on="videos")

    assert fetch_channel_scheduled_slots(service) == []
    assert "channel's own schedule" in capsys.readouterr().err


def test_extra_scheduled_keeps_a_slot_taken_outside_this_queue_from_being_reused(tmp_path):
    queue_path = str(tmp_path / "queue.json")
    video_path = tmp_path / "clip1.mp4"
    video_path.write_bytes(b"")
    queue = load_queue(queue_path)
    entry = enqueue(
        queue, clip_id="clip-1", video_path=str(video_path), metadata_path="clip1.txt",
        title="Title 1", description="Desc 1", tags=[],
    )
    fake_service = FakeVideosInsertService(video_id="vid")
    now = datetime(2026, 8, 23, 8, 0, tzinfo=timezone.utc)

    upload_and_schedule(
        queue, entry, lambda: fake_service, FakePublishConfig(enabled=True),
        now=now, queue_path=queue_path,
        # the first free slot as far as this queue knows is already taken on
        # the channel, so the upload has to move on to the one after it.
        extra_scheduled=[f"2026-08-23T{DAILY_SLOTS_UTC[0]}:00Z"],
    )

    assert entry["publish_at"] == f"2026-08-23T{DAILY_SLOTS_UTC[1]}:00Z"


def test_reconcile_all_scheduled_adopts_youtubes_publish_at_when_it_was_moved():
    queue = {
        "entries": [
            make_entry(
                clip_id="clip-1", seq=1, status=SCHEDULED, video_id="vid1",
                publish_at="2026-08-25T05:00:00Z",
            )
        ]
    }
    service = FakeVideosListService({
        "vid1": {
            "id": "vid1",
            "status": {"privacyStatus": "private", "publishAt": "2026-08-25T01:00:00Z"},
            "snippet": {},
        }
    })

    reconcile_all_scheduled(queue, lambda: service, now=datetime(2026, 8, 23, 8, 0, tzinfo=timezone.utc))

    entry = queue["entries"][0]
    assert entry["status"] == SCHEDULED
    assert entry["publish_at"] == "2026-08-25T01:00:00Z"


class TestAQuotaIsNotTheClipsFault:
    """The attempt counter exists to stop one broken clip holding the queue. A daily quota
    is not a broken clip: it fails identically every tick until midnight Pacific and then
    stops. Counting it turned an evening of quota exhaustion into a queue where every
    entry was BLOCKED by morning - after the quota had already come back - and each one
    needed --resume by hand. Before the counter existed, that same night fixed itself.
    """

    def _config(self, tmp_path):
        class _Config:
            queue_path = str(tmp_path / "queue.json")
            notifications_path = str(tmp_path / "notifications.log")
            enabled = True

        return _Config()

    def _queue_with(self, config, count=2):
        queue = {"entries": []}
        for n in range(count):
            enqueue(queue, f"clip{n}", f"/v/{n}.mp4", f"/m/{n}.json",
                    f"Заголовок {n}", "описание", ["тег"])
        save_queue(queue, config.queue_path)
        return queue

    def _quota_error(self):
        error = RuntimeError("quota exceeded")
        error.error_details = [{"reason": "quotaExceeded"}]
        return error

    def test_it_does_not_spend_an_attempt(self, tmp_path, monkeypatch):
        config = self._config(tmp_path)
        queue = self._queue_with(config, 1)
        error = self._quota_error()
        monkeypatch.setattr(publish_queue, "upload_and_schedule",
                            lambda *a, **kw: (_ for _ in ()).throw(error))

        for _ in range(5):
            publish_queue._upload_one(queue["entries"][0], queue, lambda: None, config)

        assert queue["entries"][0].get("attempts", 0) == 0
        assert queue["entries"][0]["status"] == "queued"

    def test_the_clip_publishes_when_the_quota_comes_back(self, tmp_path, monkeypatch):
        config = self._config(tmp_path)
        queue = self._queue_with(config, 1)
        error = self._quota_error()
        calls = []

        def sometimes(queue_arg, entry, *args, **kwargs):
            calls.append(1)
            if len(calls) <= 4:
                raise error
            entry["publish_at"] = "2026-08-27T09:00:00Z"
            return {"video_id": "vid-1"}

        monkeypatch.setattr(publish_queue, "upload_and_schedule", sometimes)

        moved = False
        for _ in range(5):
            # Four ticks against an exhausted quota, then the reset. The entry has to
            # still be the one the selector hands over on that fifth tick.
            entry = publish_queue.select_next_due(queue)
            assert entry is not None
            moved = publish_queue._upload_one(entry, queue, lambda: None, config)

        assert moved is True
        assert len(calls) == 5

    def test_a_rate_limit_is_treated_the_same_way(self, tmp_path, monkeypatch):
        config = self._config(tmp_path)
        queue = self._queue_with(config, 1)
        error = RuntimeError("slow down")
        error.resp = type("R", (), {"status": 429})()
        monkeypatch.setattr(publish_queue, "upload_and_schedule",
                            lambda *a, **kw: (_ for _ in ()).throw(error))

        for _ in range(4):
            publish_queue._upload_one(queue["entries"][0], queue, lambda: None, config)

        assert queue["entries"][0]["status"] != "blocked"

    def test_a_real_fault_still_blocks(self, tmp_path, monkeypatch):
        """The counter still has to do its job: a title over the limit is the clip's
        fault and will be until somebody edits it."""
        config = self._config(tmp_path)
        queue = self._queue_with(config, 1)
        monkeypatch.setattr(publish_queue, "upload_and_schedule",
                            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("title too long")))

        for _ in range(3):
            publish_queue._upload_one(queue["entries"][0], queue, lambda: None, config)

        assert queue["entries"][0]["status"] == "blocked"

    def test_the_error_is_still_recorded(self, tmp_path, monkeypatch):
        config = self._config(tmp_path)
        queue = self._queue_with(config, 1)
        error = self._quota_error()
        monkeypatch.setattr(publish_queue, "upload_and_schedule",
                            lambda *a, **kw: (_ for _ in ()).throw(error))

        publish_queue._upload_one(queue["entries"][0], queue, lambda: None, config)

        assert "quota" in queue["entries"][0]["last_error"].lower()
        assert "[error]" in open(config.notifications_path, encoding="utf-8").read()


class TestKillingABlockedEntryStaysLocal:
    """An entry blocked before the insert has no video_id, so there is nothing on YouTube
    to take down. BLOCKED was added to the status set and to the selector but not to the
    kill path, so killing one opened a real OAuth session and then asked the API to update
    the video with id None - the operator got a traceback and the entry stayed blocked."""

    def test_no_service_is_built(self, tmp_path):
        queue = {"entries": []}
        entry = enqueue(queue, "clip0", "/v/0.mp4", "/m/0.json", "Заголовок", "описание", ["тег"])
        entry["status"] = publish_queue.BLOCKED
        entry["attempts"] = 3

        def no_network():
            raise AssertionError("a blocked entry has nothing to cancel remotely")

        assert publish_queue.kill_item(queue, "clip0", no_network)["status"] == "killed"

    def test_an_entry_with_a_video_id_still_goes_to_the_api(self, tmp_path):
        """The guard is the missing video_id, not the status - a blocked entry that did
        get as far as an insert has a real video to unschedule."""
        queue = {"entries": []}
        entry = enqueue(queue, "clip0", "/v/0.mp4", "/m/0.json", "Заголовок", "описание", ["тег"])
        entry["status"] = publish_queue.BLOCKED
        entry["video_id"] = "vid-1"
        reached = []

        with pytest.raises(Exception):
            publish_queue.kill_item(
                queue, "clip0", lambda: reached.append(1) or (_ for _ in ()).throw(RuntimeError("boom"))
            )

        assert reached == [1]


class TestOneBadItemDoesNotStopTheQueue:
    """The docstring on _upload_one always promised this; the code raised instead.

    select_next_due picks the lowest seq every tick, so an entry that fails the same way
    each time - a title over 100 characters, a deleted file, a revoked token - was chosen
    again forever and nothing behind it was ever published. That is the incident this
    queue was built after, reached by a different road.
    """

    def _config(self, tmp_path, enabled=True):
        class _Config:
            queue_path = str(tmp_path / "queue.json")
            notifications_path = str(tmp_path / "notifications.log")

        _Config.enabled = enabled
        return _Config()

    def _queue_with(self, config, count):
        queue = {"entries": []}
        for n in range(count):
            enqueue(queue, f"clip{n}", f"/v/{n}.mp4", f"/m/{n}.json",
                    f"Заголовок {n}", "описание", ["тег"])
        save_queue(queue, config.queue_path)
        return queue

    def test_a_failure_no_longer_escapes_the_call(self, tmp_path, monkeypatch):
        config = self._config(tmp_path)
        queue = self._queue_with(config, 1)
        monkeypatch.setattr(publish_queue, "upload_and_schedule",
                            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("title too long")))

        moved = publish_queue._upload_one(queue["entries"][0], queue, lambda: None, config)

        assert moved is False

    def test_the_failure_is_counted_on_the_entry(self, tmp_path, monkeypatch):
        config = self._config(tmp_path)
        queue = self._queue_with(config, 1)
        monkeypatch.setattr(publish_queue, "upload_and_schedule",
                            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("boom")))

        publish_queue._upload_one(queue["entries"][0], queue, lambda: None, config)

        entry = load_queue(config.queue_path)["entries"][0]
        assert entry["attempts"] == 1
        assert "boom" in entry["last_error"]
        assert entry["status"] == QUEUED

    def test_it_is_set_aside_after_the_third_failure(self, tmp_path, monkeypatch):
        config = self._config(tmp_path)
        queue = self._queue_with(config, 1)
        monkeypatch.setattr(publish_queue, "upload_and_schedule",
                            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("boom")))

        for _ in range(MAX_UPLOAD_ATTEMPTS):
            queue = load_queue(config.queue_path)
            publish_queue._upload_one(queue["entries"][0], queue, lambda: None, config)

        assert load_queue(config.queue_path)["entries"][0]["status"] == BLOCKED

    def test_a_blocked_entry_is_never_selected(self, tmp_path):
        config = self._config(tmp_path)
        queue = self._queue_with(config, 2)
        queue["entries"][0]["status"] = BLOCKED

        assert select_next_due(queue)["clip_id"] == "clip1"

    def test_resuming_clears_the_count(self, tmp_path):
        """Somebody fixed whatever was wrong. Leaving the counter at the limit would set
        the entry aside again on the first hiccup after that."""
        config = self._config(tmp_path)
        queue = self._queue_with(config, 1)
        queue["entries"][0].update(status=BLOCKED, attempts=3, last_error="boom")

        entry = resume_item(queue, "clip0")

        assert entry["status"] == QUEUED
        assert entry["attempts"] == 0
        assert "last_error" not in entry

    def test_a_batch_gets_past_a_bad_item(self, tmp_path, monkeypatch):
        """Nine good clips must not wait on one bad title - and the loop must terminate,
        which it would not if the same entry were selected every iteration."""
        config = self._config(tmp_path)
        self._queue_with(config, 3)

        def upload(queue, entry, *a, **kw):
            if entry["clip_id"] == "clip0":
                raise RuntimeError("title too long")
            entry["status"] = PUBLISHED
            entry["publish_at"] = "2026-08-26T18:00:00Z"
            save_queue(queue, config.queue_path)
            return {}

        monkeypatch.setattr(publish_queue, "upload_and_schedule", upload)
        monkeypatch.setattr(publish_queue, "reconcile_all_uploading", lambda *a, **kw: None)
        monkeypatch.setattr(publish_queue, "reconcile_all_scheduled", lambda *a, **kw: None)
        monkeypatch.setattr(publish_queue, "fetch_channel_scheduled_slots", lambda service: [])

        uploaded = publish_queue.upload_batch(lambda: None, config)

        assert [entry["clip_id"] for entry in uploaded] == ["clip1", "clip2"]

    def test_the_selection_can_skip_what_already_failed(self, tmp_path):
        config = self._config(tmp_path)
        queue = self._queue_with(config, 2)

        assert select_next_due(queue, frozenset({"clip0"}))["clip_id"] == "clip1"


class TestAQuotaErrorIsNotAMissingVideo:
    """403 covers an exhausted quota and a token without videos.update as well as a
    video that is not ours. Reading all of them as "already gone" marked entries KILLED
    while the video was alive and still scheduled - the operator believes the release is
    cancelled and it publishes anyway."""

    class _Error(Exception):
        def __init__(self, status, reason=None, content=None):
            super().__init__("api error")
            self.resp = type("Resp", (), {"status": status})()
            if reason is not None:
                self.error_details = [{"reason": reason}]
            if content is not None:
                self.content = content

    def test_a_deleted_video_is_gone(self):
        assert publish_queue._video_is_gone(self._Error(404)) is True

    def test_an_exhausted_quota_is_not_gone(self):
        assert publish_queue._video_is_gone(
            self._Error(403, "quotaExceeded")) is False

    def test_a_token_without_permission_is_not_gone(self):
        """The exact case the UPLOAD_SCOPE comment in this module describes."""
        assert publish_queue._video_is_gone(
            self._Error(403, "insufficientPermissions")) is False

    def test_a_video_that_is_not_ours_is_gone(self):
        assert publish_queue._video_is_gone(self._Error(403, "forbidden")) is True

    def test_an_unrecognised_403_is_treated_as_a_real_failure(self):
        """A kill that loudly did not work is recoverable; one that silently did not
        work is not."""
        assert publish_queue._video_is_gone(self._Error(403, "somethingNew")) is False

    def test_the_reason_is_read_from_the_body_too(self):
        body = b'{"error": {"errors": [{"reason": "quotaExceeded"}], "code": 403}}'
        assert publish_queue._video_is_gone(self._Error(403, content=body)) is False

    def test_a_kill_during_a_quota_outage_raises_instead_of_lying(self, tmp_path):
        queue = {"entries": []}
        enqueue(queue, "clip0", "/v/0.mp4", "/m/0.json", "Заголовок", "описание", ["тег"])
        entry = queue["entries"][0]
        entry.update(status=SCHEDULED, video_id="vid123")
        error = self._Error(403, "quotaExceeded")

        def service_factory():
            class _Service:
                def videos(self):
                    raise error
            return _Service()

        with pytest.raises(Exception):
            kill_item(queue, "clip0", service_factory)

        assert queue["entries"][0]["status"] == SCHEDULED


class TestTheManifestSurvivesACrashMidWrite:
    """load_queue refuses to parse a broken manifest on purpose - a silent reset would
    re-publish everything. So a half-written file stops the entire publish path until
    somebody repairs it by hand, and the upload path writes this file two or three times
    per clip."""

    def test_the_previous_manifest_survives_a_write_that_dies_half_way(self, tmp_path, monkeypatch):
        """Cut off mid-write, with the bytes already going somewhere.

        Stubbing the write so it raises before opening anything proves nothing: the old
        implementation wrote straight to the target and would have passed that too, since
        nothing was ever truncated. The failure has to happen with a partial document
        already on disk, which is the only version of this that tells the two apart.
        """
        path = str(tmp_path / "queue.json")
        good = {"entries": []}
        enqueue(good, "clip0", "/v/0.mp4", "/m/0.json", "Заголовок", "описание", ["тег"])
        save_queue(good, path)

        class DiesPartWay:
            """Writes half the document and then runs out of disk."""

            def __init__(self, handle):
                self._handle = handle

            def write(self, text):
                self._handle.write(text[: len(text) // 2])
                raise OSError("no space left on device")

            def flush(self):
                self._handle.flush()

            def fileno(self):
                return self._handle.fileno()

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                self._handle.close()
                return False

        real_open = io.open

        def half_write(file, mode="r", *args, **kwargs):
            handle = real_open(file, mode, *args, **kwargs)
            return DiesPartWay(handle) if "w" in str(mode) else handle

        monkeypatch.setattr(publish_queue, "open", half_write, raising=False)

        with pytest.raises(OSError):
            save_queue({"entries": [], "мусор": True}, path)

        monkeypatch.undo()
        assert load_queue(path)["entries"][0]["clip_id"] == "clip0"

    def test_the_bytes_go_to_the_temporary_name_not_the_manifest(self, tmp_path, monkeypatch):
        """The other half of the same guarantee: the target is never opened for writing,
        so there is no window in which it holds half a document."""
        path = str(tmp_path / "queue.json")
        save_queue({"entries": []}, path)

        opened = []
        real_open = io.open

        def spy(file, mode="r", *args, **kwargs):
            if "w" in str(mode) or "a" in str(mode):
                opened.append(str(file))
            return real_open(file, mode, *args, **kwargs)

        monkeypatch.setattr(publish_queue, "open", spy, raising=False)
        save_queue({"entries": []}, path)
        monkeypatch.undo()

        assert opened == [path + ".tmp"]

    def test_no_temporary_file_is_left_where_the_loader_looks(self, tmp_path):
        path = str(tmp_path / "queue.json")
        save_queue({"entries": []}, path)

        assert not (tmp_path / "queue.json.tmp").exists()


def test_build_insert_body_strips_mature_disclaimer_from_description():
    body = build_insert_body(
        title="Заголовок",
        description="Панчлайн.\nСодержит ненормативную лексику (замаскирована).\n\n#тег",
        tags=["тег"],
        publish_at="2026-09-01T09:00:00Z",
        seq=7,
    )
    assert body["snippet"]["description"] == "Панчлайн.\n\n#тег"


def test_enqueue_carries_the_opening_label(tmp_path):
    # Carried for the same reason moment_tag is: the queue is what the retention
    # analysis reads months later, and a label recorded nowhere else is a
    # comparison that can never be made.
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"")
    queue = {"entries": []}

    entry = enqueue(
        queue, clip_id="clip-1", video_path=str(clip), metadata_path="clip.txt",
        title="T", description="D", tags=[], opening="standalone",
    )

    assert entry["opening"] == "standalone"


def test_enqueue_leaves_the_opening_label_empty_when_not_given(tmp_path):
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"")
    queue = {"entries": []}

    entry = enqueue(
        queue, clip_id="clip-1", video_path=str(clip), metadata_path="clip.txt",
        title="T", description="D", tags=[],
    )

    assert entry["opening"] is None
