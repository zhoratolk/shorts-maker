from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.publish_queue import (
    KILLED,
    PAUSED,
    QUEUED,
    SCHEDULED,
    UPLOADING,
    UPLOAD_SCOPE,
    VALID_STATUSES,
    append_notification,
    build_argument_parser,
    build_insert_body,
    cancel_scheduled_release,
    collect_scheduled_slots,
    enqueue,
    kill_item,
    load_queue,
    next_free_slot,
    pause_item,
    read_unread_notifications,
    reconcile_all_uploading,
    reconcile_uploading,
    resume_item,
    run_command,
    save_queue,
    select_next_due,
    set_thumbnail,
    upload_and_schedule,
    verify_killed,
    _try_set_thumbnail,
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


class FakeVideosSnippetService:
    """Fake videos().list(part="snippet", id=...) - returns description per
    video_id so reconcile_uploading can match the seq marker."""

    def __init__(self, descriptions_by_id):
        self.descriptions_by_id = descriptions_by_id
        self.calls = []

    def videos(self):
        return self

    def list(self, **kwargs):
        self.calls.append(kwargs)
        return self

    def execute(self):
        requested_ids = self.calls[-1]["id"].split(",")
        return {
            "items": [
                {"id": vid, "snippet": {"description": self.descriptions_by_id[vid]}}
                for vid in requested_ids
                if vid in self.descriptions_by_id
            ]
        }


class FakeReconcileService:
    """Combines channels/playlistItems/videos resources on one object -
    reconcile_uploading calls get_own_channel + list_uploaded_videos (both
    reused from youtube_analytics.py) then videos().list(part=snippet) for
    descriptions, all against the same service object."""

    def __init__(self, uploaded_videos, descriptions_by_id):
        self._channels = FakeChannelsServiceForReconcile()
        self._playlist = FakePlaylistItemsServiceForReconcile(uploaded_videos)
        self._snippets = FakeVideosSnippetService(descriptions_by_id)
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

    def list(self, **kwargs):
        return self._snippets.list(**kwargs)


def test_reconcile_uploading_adopts_video_id_when_marker_matches():
    queue = {
        "entries": [
            make_entry(clip_id="clip-1", seq=7, status=UPLOADING, video_id=None)
        ]
    }
    entry = queue["entries"][0]
    service = FakeReconcileService(
        uploaded_videos=[
            {"video_id": "vid_match", "title": "My Clip", "published_at": "2026-07-08T09:00:00Z"},
            {"video_id": "vid_other", "title": "Unrelated", "published_at": "2026-07-07T09:00:00Z"},
        ],
        descriptions_by_id={
            "vid_match": "A description\n\n[queue-id: 7]",
            "vid_other": "Something else entirely",
        },
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
        descriptions_by_id={"vid_other": "Something else entirely, no marker here"},
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
            {"video_id": "vid_match", "title": "My Clip", "published_at": "2026-07-08T09:00:00Z"},
        ],
        descriptions_by_id={"vid_match": "desc\n\n[queue-id: 3]"},
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
            {"video_id": "vid_match", "title": "Stuck Clip", "published_at": "2026-07-08T09:00:00Z"},
        ],
        descriptions_by_id={"vid_match": "desc\n\n[queue-id: 1]"},
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
