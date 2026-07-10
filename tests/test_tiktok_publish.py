import json
import threading
import time
import urllib.request
from pathlib import Path

import pytest
import requests

import scripts.tiktok_publish as tiktok_publish
from scripts.tiktok_publish import (
    KILLED,
    MAX_TITLE_LENGTH,
    PAUSED,
    PUBLISHED,
    QUEUED,
    TIKTOK_SCOPES,
    UPLOADING,
    VALID_STATUSES,
    _capture_oauth_redirect_code,
    _find_entry,
    _upload_one,
    build_argument_parser,
    build_direct_post_body,
    check_tiktok_publish_gate,
    enqueue,
    fetch_post_status,
    init_direct_post,
    kill_item,
    load_credentials,
    load_queue,
    pause_item,
    reconcile_all_uploading,
    reconcile_uploading,
    resume_item,
    run_command,
    run_tiktok_oauth_consent,
    save_queue,
    select_next_due,
    upload_and_publish,
    upload_video_chunks,
    validate_title_length,
)


# --- Task 1: queue lifecycle -------------------------------------------


def test_valid_statuses_contains_exactly_five_states():
    assert VALID_STATUSES == frozenset(
        {"queued", "uploading", "published", "killed", "paused"}
    )


def test_load_queue_returns_empty_entries_when_file_missing(tmp_path):
    queue_path = str(tmp_path / "does_not_exist" / "tiktok_queue.json")

    queue = load_queue(queue_path)

    assert queue == {"entries": []}


def test_save_queue_creates_parent_dirs_and_writes_utf8_json(tmp_path):
    queue_path = str(tmp_path / "nested" / "tiktok_queue.json")
    queue = {"entries": [{"caption": "приветик"}]}

    save_queue(queue, queue_path)

    written = Path(queue_path).read_text(encoding="utf-8")
    assert "приветик" in written
    assert json.loads(written) == queue


def test_enqueue_is_idempotent_on_clip_id(tmp_path):
    queue = load_queue(str(tmp_path / "tiktok_queue.json"))

    entry1 = enqueue(
        queue, clip_id="clip-1", video_path="clip1.mp4",
        metadata_path="clip1.txt", caption="caption 1",
    )
    entry2 = enqueue(
        queue, clip_id="clip-1", video_path="clip1.mp4",
        metadata_path="clip1.txt", caption="caption 1",
    )

    assert entry1 is entry2
    assert len(queue["entries"]) == 1


def test_enqueue_sequential_numbering_and_shape(tmp_path):
    queue = load_queue(str(tmp_path / "tiktok_queue.json"))

    entry1 = enqueue(
        queue, clip_id="clip-1", video_path="clip1.mp4",
        metadata_path="clip1.txt", caption="caption 1",
    )
    entry2 = enqueue(
        queue, clip_id="clip-2", video_path="clip2.mp4",
        metadata_path="clip2.txt", caption="caption 2",
    )

    assert entry1["seq"] == 1
    assert entry2["seq"] == 2
    assert entry1["status"] == QUEUED
    assert entry1["publish_id"] is None
    assert entry1["video_share_url"] is None
    assert "description" not in entry1
    assert "tags" not in entry1
    assert "publish_at" not in entry1


def test_select_next_due_skips_non_queued_statuses(tmp_path):
    queue = load_queue(str(tmp_path / "tiktok_queue.json"))
    enqueue(queue, clip_id="clip-1", video_path="c1.mp4", metadata_path="c1.txt", caption="c1")
    entry2 = enqueue(queue, clip_id="clip-2", video_path="c2.mp4", metadata_path="c2.txt", caption="c2")
    enqueue(queue, clip_id="clip-3", video_path="c3.mp4", metadata_path="c3.txt", caption="c3")

    entry2["status"] = PAUSED
    queue["entries"][0]["status"] = UPLOADING
    queue["entries"][2]["status"] = PUBLISHED

    assert select_next_due(queue) is None


def test_select_next_due_returns_lowest_seq_queued(tmp_path):
    queue = load_queue(str(tmp_path / "tiktok_queue.json"))
    enqueue(queue, clip_id="clip-1", video_path="c1.mp4", metadata_path="c1.txt", caption="c1")
    enqueue(queue, clip_id="clip-2", video_path="c2.mp4", metadata_path="c2.txt", caption="c2")

    due = select_next_due(queue)

    assert due["clip_id"] == "clip-1"


def test_pause_then_resume_round_trip(tmp_path):
    queue = load_queue(str(tmp_path / "tiktok_queue.json"))
    enqueue(queue, clip_id="clip-1", video_path="c1.mp4", metadata_path="c1.txt", caption="c1")

    pause_item(queue, "clip-1")
    assert _find_entry(queue, "clip-1")["status"] == PAUSED

    resume_item(queue, "clip-1")
    assert _find_entry(queue, "clip-1")["status"] == QUEUED


def test_isolation_pause_tiktok_queue_never_touches_youtube_queue(tmp_path):
    from scripts.publish_queue import enqueue as yt_enqueue
    from scripts.publish_queue import load_queue as yt_load_queue
    from scripts.publish_queue import save_queue as yt_save_queue

    yt_queue_path = tmp_path / "queue.json"
    yt_queue = yt_load_queue(str(yt_queue_path))
    yt_enqueue(
        yt_queue, clip_id="yt-clip-1", video_path="v.mp4", metadata_path="m.txt",
        title="T", description="D", tags=["a"],
    )
    yt_save_queue(yt_queue, str(yt_queue_path))
    before = yt_queue_path.read_text(encoding="utf-8")

    tt_queue_path = tmp_path / "tiktok_queue.json"
    tt_queue = load_queue(str(tt_queue_path))
    enqueue(tt_queue, clip_id="tt-clip-1", video_path="v.mp4", metadata_path="m.txt", caption="c")
    save_queue(tt_queue, str(tt_queue_path))
    pause_item(tt_queue, "tt-clip-1")
    save_queue(tt_queue, str(tt_queue_path))

    after = yt_queue_path.read_text(encoding="utf-8")
    assert after == before


def test_tiktok_scopes_are_minimal():
    assert TIKTOK_SCOPES == ["video.publish", "video.upload"]


# --- Fake HTTP layer (shared by Task 1 credential tests and later tasks) --


class FakeResponse:
    """Stands in for requests.Response - only the methods/attrs this
    project's HTTP-layer code actually calls."""

    def __init__(self, json_data, status_code=200):
        self._json_data = json_data
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")

    def json(self):
        return self._json_data


class FakeSession:
    """Records every post/put/get call (method, url, kwargs) so tests can
    assert on Content-Range headers, request bodies, etc."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return self.responses.pop(0)

    def put(self, url, **kwargs):
        self.calls.append(("PUT", url, kwargs))
        return self.responses.pop(0)

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return self.responses.pop(0)


# --- Task 1: OAuth credential handling ----------------------------------


def test_load_credentials_returns_cached_token_when_unexpired(tmp_path):
    token_path = tmp_path / "tiktok_token.json"
    token_path.write_text(json.dumps({
        "access_token": "cached-token",
        "refresh_token": "refresh-token",
        "expires_at": time.time() + 3600,
    }), encoding="utf-8")

    session = FakeSession([])
    access_token = load_credentials("tiktok_client_key.json", str(token_path), session=session)

    assert access_token == "cached-token"
    assert session.calls == []


def test_load_credentials_refreshes_expired_token(tmp_path):
    client_key_path = tmp_path / "tiktok_client_key.json"
    client_key_path.write_text(json.dumps({"client_key": "ck", "client_secret": "cs"}), encoding="utf-8")

    token_path = tmp_path / "tiktok_token.json"
    token_path.write_text(json.dumps({
        "access_token": "old-token",
        "refresh_token": "refresh-token",
        "expires_at": time.time() - 10,
    }), encoding="utf-8")

    session = FakeSession([
        FakeResponse({"access_token": "new-token", "refresh_token": "refresh-token", "expires_in": 86400}),
    ])

    access_token = load_credentials(str(client_key_path), str(token_path), session=session)

    assert access_token == "new-token"
    method, url, kwargs = session.calls[0]
    assert method == "POST"
    assert url == tiktok_publish.TIKTOK_TOKEN_URL
    assert kwargs["data"]["grant_type"] == "refresh_token"
    assert kwargs["data"]["refresh_token"] == "refresh-token"

    saved = json.loads(token_path.read_text(encoding="utf-8"))
    assert saved["access_token"] == "new-token"
    assert "expires_at" in saved


def test_load_credentials_raises_file_not_found_when_no_cached_token(tmp_path):
    token_path = tmp_path / "does_not_exist.json"

    with pytest.raises(FileNotFoundError):
        load_credentials("tiktok_client_key.json", str(token_path))


# --- Task 1: one-time interactive OAuth consent -------------------------


def test_capture_oauth_redirect_server_binds_to_localhost_only():
    server, captured = tiktok_publish._build_redirect_server("127.0.0.1", 8799)
    try:
        assert server.server_address[0] == "127.0.0.1"
        assert server.server_address[0] != "0.0.0.0"
    finally:
        server.server_close()


def test_capture_oauth_redirect_code_returns_code_from_single_request():
    port = 8798

    def send_request():
        time.sleep(0.2)
        urllib.request.urlopen(f"http://127.0.0.1:{port}/callback?code=abc123&state=xyz", timeout=5)

    thread = threading.Thread(target=send_request)
    thread.start()
    code = _capture_oauth_redirect_code("127.0.0.1", port, timeout_seconds=5)
    thread.join()

    assert code == "abc123"


def test_run_tiktok_oauth_consent_full_flow(tmp_path, monkeypatch):
    client_key_path = tmp_path / "tiktok_client_key.json"
    client_key_path.write_text(json.dumps({"client_key": "ck", "client_secret": "cs"}), encoding="utf-8")
    token_path = tmp_path / "tiktok_token.json"

    opened_urls = []
    monkeypatch.setattr(tiktok_publish.webbrowser, "open", lambda url: opened_urls.append(url))

    port = 8797

    def hit_redirect():
        time.sleep(0.2)
        urllib.request.urlopen(f"http://127.0.0.1:{port}/callback?code=abc123&state=xyz", timeout=5)

    thread = threading.Thread(target=hit_redirect)
    thread.start()

    session = FakeSession([
        FakeResponse({"access_token": "tok", "refresh_token": "ref", "expires_in": 86400}),
    ])

    access_token = run_tiktok_oauth_consent(
        str(client_key_path), str(token_path), port=port, session=session
    )
    thread.join()

    assert access_token == "tok"
    assert opened_urls
    assert "client_key=ck" in opened_urls[0]
    assert "scope=video.publish,video.upload" in opened_urls[0]
    assert f"redirect_uri=http%3A%2F%2F127.0.0.1%3A{port}%2Fcallback" in opened_urls[0]

    saved = json.loads(token_path.read_text(encoding="utf-8"))
    assert saved["access_token"] == "tok"
    assert saved["refresh_token"] == "ref"
    assert "expires_at" in saved


# --- Task 2: TikTok HTTP upload layer ------------------------------------


def test_validate_title_length_raises_for_oversized_title():
    with pytest.raises(ValueError):
        validate_title_length("x" * (MAX_TITLE_LENGTH + 1))


def test_validate_title_length_allows_max_length_title():
    validate_title_length("x" * MAX_TITLE_LENGTH)  # must not raise


def test_build_direct_post_body_shapes_file_upload_source():
    body = build_direct_post_body(
        title="My Clip", privacy_level="SELF_ONLY",
        video_size=1000, chunk_size=1000, total_chunk_count=1,
    )

    assert body == {
        "post_info": {"title": "My Clip", "privacy_level": "SELF_ONLY"},
        "source_info": {
            "source": "FILE_UPLOAD",
            "video_size": 1000,
            "chunk_size": 1000,
            "total_chunk_count": 1,
        },
    }


def test_build_direct_post_body_raises_before_any_session_call_on_oversized_title():
    session = FakeSession([])

    with pytest.raises(ValueError):
        build_direct_post_body(
            title="x" * (MAX_TITLE_LENGTH + 1), privacy_level="SELF_ONLY",
            video_size=1000, chunk_size=1000, total_chunk_count=1,
        )

    assert session.calls == []


def test_init_direct_post_posts_body_and_returns_data():
    session = FakeSession([
        FakeResponse({"data": {"publish_id": "pub-1", "upload_url": "https://upload.example/put"}}),
    ])
    body = {"post_info": {"title": "t", "privacy_level": "SELF_ONLY"}, "source_info": {}}

    data = init_direct_post("token-123", body, session=session)

    assert data == {"publish_id": "pub-1", "upload_url": "https://upload.example/put"}
    method, url, kwargs = session.calls[0]
    assert method == "POST"
    assert url == tiktok_publish.TIKTOK_INIT_URL
    assert kwargs["headers"]["Authorization"] == "Bearer token-123"
    assert kwargs["json"] == body


def test_upload_video_chunks_single_chunk_covers_whole_file(tmp_path):
    video_path = tmp_path / "clip.mp4"
    content = b"0123456789"
    video_path.write_bytes(content)

    session = FakeSession([FakeResponse({})])
    upload_video_chunks("https://upload.example/put", str(video_path), chunk_size=1024, session=session)

    assert len(session.calls) == 1
    method, url, kwargs = session.calls[0]
    assert method == "PUT"
    assert url == "https://upload.example/put"
    assert kwargs["data"] == content
    assert kwargs["headers"]["Content-Range"] == f"bytes 0-{len(content) - 1}/{len(content)}"
    assert kwargs["headers"]["Content-Length"] == str(len(content))


def test_upload_video_chunks_multi_chunk_covers_whole_file(tmp_path):
    video_path = tmp_path / "clip.mp4"
    content = bytes(range(256)) * 4  # 1024 bytes
    video_path.write_bytes(content)

    session = FakeSession([FakeResponse({}), FakeResponse({}), FakeResponse({})])
    upload_video_chunks("https://upload.example/put", str(video_path), chunk_size=400, session=session)

    assert len(session.calls) == 3
    ranges = [kwargs["headers"]["Content-Range"] for _, _, kwargs in session.calls]
    assert ranges == [
        "bytes 0-399/1024",
        "bytes 400-799/1024",
        "bytes 800-1023/1024",
    ]
    reconstructed = b"".join(kwargs["data"] for _, _, kwargs in session.calls)
    assert reconstructed == content


def test_fetch_post_status_posts_publish_id_and_returns_data():
    session = FakeSession([
        FakeResponse({"data": {"status": "PUBLISH_COMPLETE", "fail_reason": ""}}),
    ])

    data = fetch_post_status("token-123", "pub-1", session=session)

    assert data == {"status": "PUBLISH_COMPLETE", "fail_reason": ""}
    method, url, kwargs = session.calls[0]
    assert method == "POST"
    assert url == tiktok_publish.TIKTOK_STATUS_URL
    assert kwargs["json"] == {"publish_id": "pub-1"}


def test_check_tiktok_publish_gate_public_available():
    session = FakeSession([
        FakeResponse({"data": {"privacy_level_options": ["PUBLIC_TO_EVERYONE", "SELF_ONLY"]}}),
    ])

    privacy_level, is_still_gated = check_tiktok_publish_gate("token-123", session=session)

    assert privacy_level == "PUBLIC_TO_EVERYONE"
    assert is_still_gated is False


def test_check_tiktok_publish_gate_self_only():
    session = FakeSession([
        FakeResponse({"data": {"privacy_level_options": ["SELF_ONLY"]}}),
    ])

    privacy_level, is_still_gated = check_tiktok_publish_gate("token-123", session=session)

    assert privacy_level == "SELF_ONLY"
    assert is_still_gated is True


# --- Task 3: orchestration (dry-run gate, D-05, write-ahead), reconcile --


class FakeTikTokPublishConfig:
    """Minimal stand-in for scripts.config.PublishConfig - only the fields
    upload_and_publish/_upload_one actually read."""

    def __init__(self, tiktok_enabled, tiktok_queue_path="tiktok_queue.json",
                 notifications_path="notifications.log"):
        self.tiktok_enabled = tiktok_enabled
        self.tiktok_queue_path = tiktok_queue_path
        self.notifications_path = notifications_path


class SpyingSession(FakeSession):
    """Extends FakeSession to snapshot the on-disk queue file at the moment
    the first PUT (chunk upload) call fires - proves write-ahead
    persistence (Pitfall 5) actually landed on disk before the byte-upload
    loop started (mirrors publish_queue.py's spying-insert test technique).
    """

    def __init__(self, responses, queue_path):
        super().__init__(responses)
        self.queue_path = queue_path
        self.publish_id_at_first_put = "NOT_YET_CALLED"

    def put(self, url, **kwargs):
        if self.publish_id_at_first_put == "NOT_YET_CALLED":
            saved = json.loads(Path(self.queue_path).read_text(encoding="utf-8"))
            self.publish_id_at_first_put = saved["entries"][0].get("publish_id")
        return super().put(url, **kwargs)


def make_tiktok_entry(**overrides):
    entry = {
        "seq": 1,
        "clip_id": "clip-1",
        "video_path": "clip1.mp4",
        "metadata_path": "clip1.txt",
        "caption": "caption 1",
        "status": QUEUED,
        "publish_id": None,
        "video_share_url": None,
        "enqueued_at": "2026-07-10T00:00:00Z",
        "updated_at": "2026-07-10T00:00:00Z",
    }
    entry.update(overrides)
    return entry


# --- Task 4: kill_item (Pitfall 4 divergence from YouTube's revert+verify) -


def test_kill_item_queued_is_local_only_no_publish_id():
    queue = {"entries": [make_tiktok_entry(status=QUEUED, publish_id=None)]}

    kill_item(queue, "clip-1")

    assert queue["entries"][0]["status"] == KILLED


def test_kill_item_paused_is_local_only():
    queue = {"entries": [make_tiktok_entry(status=PAUSED, publish_id=None)]}

    kill_item(queue, "clip-1")

    assert queue["entries"][0]["status"] == KILLED


def test_kill_item_uploading_no_publish_id_is_local_only():
    queue = {"entries": [make_tiktok_entry(status=UPLOADING, publish_id=None)]}

    kill_item(queue, "clip-1")

    assert queue["entries"][0]["status"] == KILLED


def test_kill_item_uploading_with_publish_id_is_still_local_only():
    # An in-flight upload that already has a publish_id is not public yet -
    # kill must remain local-only, no network call attempted (Pitfall 4/5).
    queue = {"entries": [make_tiktok_entry(status=UPLOADING, publish_id="pub-1")]}

    kill_item(queue, "clip-1")

    assert queue["entries"][0]["status"] == KILLED


def test_kill_item_published_raises_runtime_error_and_leaves_status_untouched():
    queue = {"entries": [make_tiktok_entry(status=PUBLISHED, publish_id="pub-1")]}

    with pytest.raises(RuntimeError):
        kill_item(queue, "clip-1")

    # A PUBLISHED entry must never be silently marked KILLED - this is the
    # one behavior that must NOT silently succeed (Pitfall 4).
    assert queue["entries"][0]["status"] == PUBLISHED


def test_kill_item_takes_no_credentials_factory_parameter():
    import inspect

    sig = inspect.signature(kill_item)
    assert list(sig.parameters) == ["queue", "clip_id"]


def test_dry_run_default_no_upload(tmp_path):
    queue_path = tmp_path / "tiktok_queue.json"
    queue = load_queue(str(queue_path))
    entry = enqueue(queue, clip_id="clip-1", video_path="c.mp4", metadata_path="c.txt", caption="cap")
    config = FakeTikTokPublishConfig(tiktok_enabled=False, tiktok_queue_path=str(queue_path))
    session = FakeSession([])

    def credentials_factory():
        raise AssertionError("credentials_factory must not be called during dry-run")

    result = upload_and_publish(
        queue, entry, credentials_factory, config, session=session, queue_path=str(queue_path)
    )

    assert result == {"dry_run": True}
    assert session.calls == []
    assert entry["status"] == QUEUED


def test_upload_and_publish_full_success_flow_persists_write_ahead(tmp_path):
    video_path = tmp_path / "clip.mp4"
    video_path.write_bytes(b"0123456789")
    queue_path = tmp_path / "tiktok_queue.json"

    queue = load_queue(str(queue_path))
    entry = enqueue(
        queue, clip_id="clip-1", video_path=str(video_path), metadata_path="c.txt", caption="cap"
    )
    save_queue(queue, str(queue_path))

    config = FakeTikTokPublishConfig(tiktok_enabled=True, tiktok_queue_path=str(queue_path))

    session = SpyingSession([
        FakeResponse({"data": {"privacy_level_options": ["PUBLIC_TO_EVERYONE", "SELF_ONLY"]}}),
        FakeResponse({"data": {"publish_id": "pub-1", "upload_url": "https://upload.example/put"}}),
        FakeResponse({}),
        FakeResponse({"data": {
            "status": "PUBLISH_COMPLETE", "fail_reason": "",
            "publicaly_available_post_id": ["share-1"],
        }}),
    ], queue_path=str(queue_path))

    result = upload_and_publish(
        queue, entry, lambda: "access-token-123", config,
        session=session, queue_path=str(queue_path),
    )

    assert result == {"publish_id": "pub-1", "is_still_gated": False}
    assert entry["status"] == PUBLISHED
    assert entry["publish_id"] == "pub-1"
    # Write-ahead #2 (Pitfall 5): publish_id must be on disk BEFORE the
    # chunk PUT loop starts, so a crash mid-upload is reconcilable.
    assert session.publish_id_at_first_put == "pub-1"


def test_idempotent_retry_no_duplicate_init_on_reconcile():
    entry = make_tiktok_entry(status=UPLOADING, publish_id="pub-1")
    queue = {"entries": [entry]}
    session = FakeSession([
        FakeResponse({"data": {
            "status": "PUBLISH_COMPLETE", "fail_reason": "",
            "publicaly_available_post_id": ["share-1"],
        }}),
    ])

    reconcile_uploading(queue, entry, lambda: "access-token-123", session=session)

    assert entry["status"] == PUBLISHED
    urls_called = [url for _, url, _ in session.calls]
    assert tiktok_publish.TIKTOK_INIT_URL not in urls_called
    assert session.calls[0][1] == tiktok_publish.TIKTOK_STATUS_URL


def test_reconcile_uploading_no_publish_id_resets_to_queued_without_api_call():
    entry = make_tiktok_entry(status=UPLOADING, publish_id=None)
    queue = {"entries": [entry]}
    session = FakeSession([])

    def credentials_factory():
        raise AssertionError("credentials_factory must not be called when no publish_id recorded")

    reconcile_uploading(queue, entry, credentials_factory, session=session)

    assert entry["status"] == QUEUED
    assert session.calls == []


def test_reconcile_uploading_failed_resets_to_queued_and_clears_publish_id():
    entry = make_tiktok_entry(status=UPLOADING, publish_id="pub-1")
    queue = {"entries": [entry]}
    session = FakeSession([
        FakeResponse({"data": {"status": "FAILED", "fail_reason": "oops"}}),
    ])

    reconcile_uploading(queue, entry, lambda: "token", session=session)

    assert entry["status"] == QUEUED
    assert entry["publish_id"] is None


def test_reconcile_uploading_still_in_flight_is_left_untouched():
    entry = make_tiktok_entry(status=UPLOADING, publish_id="pub-1")
    queue = {"entries": [entry]}
    session = FakeSession([
        FakeResponse({"data": {"status": "PROCESSING_UPLOAD", "fail_reason": ""}}),
    ])

    reconcile_uploading(queue, entry, lambda: "token", session=session)

    assert entry["status"] == UPLOADING
    assert entry["publish_id"] == "pub-1"


def test_reconcile_uploading_status_fetch_error_resets_to_queued():
    entry = make_tiktok_entry(status=UPLOADING, publish_id="pub-1")
    queue = {"entries": [entry]}
    session = FakeSession([FakeResponse({}, status_code=404)])

    reconcile_uploading(queue, entry, lambda: "token", session=session)

    assert entry["status"] == QUEUED
    assert entry["publish_id"] is None


def test_reconcile_all_uploading_skips_non_uploading_entries():
    queued_entry = make_tiktok_entry(clip_id="clip-1", status=QUEUED)
    uploading_entry = make_tiktok_entry(
        clip_id="clip-2", seq=2, status=UPLOADING, publish_id=None
    )
    queue = {"entries": [queued_entry, uploading_entry]}
    session = FakeSession([])

    reconcile_all_uploading(queue, lambda: "token", session=session)

    assert queued_entry["status"] == QUEUED
    assert uploading_entry["status"] == QUEUED  # reset, no publish_id, no api call


def test_upload_one_self_only_appends_distinct_notification_not_normal_success(tmp_path):
    video_path = tmp_path / "clip.mp4"
    video_path.write_bytes(b"0123456789")
    queue_path = tmp_path / "tiktok_queue.json"
    notifications_path = tmp_path / "notifications.log"

    queue = load_queue(str(queue_path))
    entry = enqueue(
        queue, clip_id="clip-1", video_path=str(video_path), metadata_path="c.txt", caption="cap"
    )
    save_queue(queue, str(queue_path))

    config = FakeTikTokPublishConfig(
        tiktok_enabled=True, tiktok_queue_path=str(queue_path),
        notifications_path=str(notifications_path),
    )

    session = FakeSession([
        FakeResponse({"data": {"privacy_level_options": ["SELF_ONLY"]}}),
        FakeResponse({"data": {"publish_id": "pub-1", "upload_url": "https://upload.example/put"}}),
        FakeResponse({}),
        FakeResponse({"data": {
            "status": "PUBLISH_COMPLETE", "fail_reason": "",
            "publicaly_available_post_id": ["share-1"],
        }}),
    ])

    _upload_one(entry, queue, lambda: "token", config, session=session)

    log_text = notifications_path.read_text(encoding="utf-8")
    assert "SELF_ONLY" in log_text
    assert "залил 1 в TikTok" not in log_text


def test_upload_one_success_appends_normal_notification_when_public(tmp_path):
    video_path = tmp_path / "clip.mp4"
    video_path.write_bytes(b"0123456789")
    queue_path = tmp_path / "tiktok_queue.json"
    notifications_path = tmp_path / "notifications.log"

    queue = load_queue(str(queue_path))
    entry = enqueue(
        queue, clip_id="clip-1", video_path=str(video_path), metadata_path="c.txt", caption="cap"
    )
    save_queue(queue, str(queue_path))

    config = FakeTikTokPublishConfig(
        tiktok_enabled=True, tiktok_queue_path=str(queue_path),
        notifications_path=str(notifications_path),
    )

    session = FakeSession([
        FakeResponse({"data": {"privacy_level_options": ["PUBLIC_TO_EVERYONE", "SELF_ONLY"]}}),
        FakeResponse({"data": {"publish_id": "pub-1", "upload_url": "https://upload.example/put"}}),
        FakeResponse({}),
        FakeResponse({"data": {
            "status": "PUBLISH_COMPLETE", "fail_reason": "",
            "publicaly_available_post_id": ["share-1"],
        }}),
    ])

    _upload_one(entry, queue, lambda: "token", config, session=session)

    log_text = notifications_path.read_text(encoding="utf-8")
    assert "залил 1 в TikTok" in log_text
    assert "SELF_ONLY" not in log_text


def test_upload_one_appends_error_notification_and_reraises_on_failure(tmp_path):
    video_path = tmp_path / "clip.mp4"
    video_path.write_bytes(b"0123456789")
    queue_path = tmp_path / "tiktok_queue.json"
    notifications_path = tmp_path / "notifications.log"

    queue = load_queue(str(queue_path))
    entry = enqueue(
        queue, clip_id="clip-1", video_path=str(video_path), metadata_path="c.txt", caption="cap"
    )
    save_queue(queue, str(queue_path))

    config = FakeTikTokPublishConfig(
        tiktok_enabled=True, tiktok_queue_path=str(queue_path),
        notifications_path=str(notifications_path),
    )

    session = FakeSession([
        FakeResponse({"data": {"privacy_level_options": ["PUBLIC_TO_EVERYONE"]}}),
        FakeResponse({"data": {"publish_id": "pub-1", "upload_url": "https://upload.example/put"}}),
        FakeResponse({}),
        FakeResponse({"data": {"status": "FAILED", "fail_reason": "video too long"}}),
    ])

    with pytest.raises(RuntimeError):
        _upload_one(entry, queue, lambda: "token", config, session=session)

    log_text = notifications_path.read_text(encoding="utf-8")
    assert "[error]" in log_text


def test_upload_one_dry_run_does_not_notify(tmp_path):
    queue_path = tmp_path / "tiktok_queue.json"
    notifications_path = tmp_path / "notifications.log"
    queue = load_queue(str(queue_path))
    entry = enqueue(queue, clip_id="clip-1", video_path="c.mp4", metadata_path="c.txt", caption="cap")
    save_queue(queue, str(queue_path))

    config = FakeTikTokPublishConfig(
        tiktok_enabled=False, tiktok_queue_path=str(queue_path),
        notifications_path=str(notifications_path),
    )
    session = FakeSession([])

    def credentials_factory():
        raise AssertionError("credentials_factory must not be called during dry-run")

    _upload_one(entry, queue, credentials_factory, config, session=session)

    assert not notifications_path.exists()


# --- Task 2: CLI wrapper ---------------------------------------------------


def make_cli_tiktok_queue(tmp_path, entries):
    queue_path = str(tmp_path / "tiktok_queue.json")
    save_queue({"entries": entries}, queue_path)
    return queue_path


def test_list_prints_seq_status_caption(tmp_path, capsys):
    queue_path = make_cli_tiktok_queue(
        tmp_path,
        [
            make_tiktok_entry(clip_id="clip-1", seq=1, status=QUEUED, caption="First"),
            make_tiktok_entry(clip_id="clip-2", seq=2, status=PUBLISHED, caption="Second"),
        ],
    )
    config = FakeTikTokPublishConfig(tiktok_enabled=False, tiktok_queue_path=queue_path)

    args = build_argument_parser().parse_args(["--list"])
    run_command(args, credentials_factory=lambda: "token", config=config)

    out = capsys.readouterr().out
    assert "1" in out
    assert "2" in out
    assert "First" in out
    assert "Second" in out


def test_check_dry_run_makes_zero_credential_calls(tmp_path, capsys):
    queue_path = make_cli_tiktok_queue(
        tmp_path, [make_tiktok_entry(clip_id="clip-1", seq=1, status=QUEUED)]
    )
    config = FakeTikTokPublishConfig(tiktok_enabled=False, tiktok_queue_path=queue_path)

    def credentials_factory():
        raise AssertionError("credentials_factory must never be called in dry-run")

    args = build_argument_parser().parse_args(["--check"])
    run_command(args, credentials_factory=credentials_factory, config=config)

    queue = load_queue(queue_path)
    assert queue["entries"][0]["status"] == QUEUED
    out = capsys.readouterr().out
    assert "dry-run" in out.lower()


def test_check_reconciles_before_selecting_and_uploads_at_most_one(tmp_path):
    video_path = tmp_path / "clip.mp4"
    video_path.write_bytes(b"fake video bytes")
    queued_entry_1 = make_tiktok_entry(
        clip_id="clip-1", seq=1, status=QUEUED, video_path=str(video_path)
    )
    stuck_entry = make_tiktok_entry(
        clip_id="clip-stuck", seq=2, status=UPLOADING, publish_id=None, video_path=str(video_path)
    )
    queued_entry_2 = make_tiktok_entry(
        clip_id="clip-2", seq=3, status=QUEUED, video_path=str(video_path)
    )
    queue_path = make_cli_tiktok_queue(tmp_path, [queued_entry_1, stuck_entry, queued_entry_2])
    notifications_path = str(tmp_path / "notifications.log")
    config = FakeTikTokPublishConfig(
        tiktok_enabled=True, tiktok_queue_path=queue_path, notifications_path=notifications_path
    )

    session = FakeSession([
        FakeResponse({"data": {"privacy_level_options": ["PUBLIC_TO_EVERYONE"]}}),
        FakeResponse({"data": {"publish_id": "pub-1", "upload_url": "https://upload.example/put"}}),
        FakeResponse({}),
        FakeResponse({"data": {
            "status": "PUBLISH_COMPLETE", "fail_reason": "",
            "publicaly_available_post_id": ["share-1"],
        }}),
    ])

    args = build_argument_parser().parse_args(["--check"])
    run_command(args, credentials_factory=lambda: "token", config=config, session=session)

    queue = load_queue(queue_path)
    stuck = next(e for e in queue["entries"] if e["clip_id"] == "clip-stuck")
    entry_1 = next(e for e in queue["entries"] if e["clip_id"] == "clip-1")
    entry_2 = next(e for e in queue["entries"] if e["clip_id"] == "clip-2")
    assert stuck["status"] == QUEUED  # reconciled first (no publish_id -> reset)
    assert entry_1["status"] == PUBLISHED  # lowest-seq due item picked up
    assert entry_2["status"] == QUEUED  # only one upload per --check


def test_now_targets_named_clip_via_same_upload_path(tmp_path):
    video_path = tmp_path / "clip.mp4"
    video_path.write_bytes(b"fake video bytes")
    queue_path = make_cli_tiktok_queue(
        tmp_path,
        [
            make_tiktok_entry(clip_id="clip-1", seq=1, status=QUEUED, video_path=str(video_path)),
            make_tiktok_entry(clip_id="clip-2", seq=2, status=QUEUED, video_path=str(video_path)),
        ],
    )
    notifications_path = str(tmp_path / "notifications.log")
    config = FakeTikTokPublishConfig(
        tiktok_enabled=True, tiktok_queue_path=queue_path, notifications_path=notifications_path
    )

    session = FakeSession([
        FakeResponse({"data": {"privacy_level_options": ["PUBLIC_TO_EVERYONE"]}}),
        FakeResponse({"data": {"publish_id": "pub-2", "upload_url": "https://upload.example/put"}}),
        FakeResponse({}),
        FakeResponse({"data": {
            "status": "PUBLISH_COMPLETE", "fail_reason": "",
            "publicaly_available_post_id": ["share-2"],
        }}),
    ])

    args = build_argument_parser().parse_args(["--now", "clip-2"])
    run_command(args, credentials_factory=lambda: "token", config=config, session=session)

    queue = load_queue(queue_path)
    entry_1 = next(e for e in queue["entries"] if e["clip_id"] == "clip-1")
    entry_2 = next(e for e in queue["entries"] if e["clip_id"] == "clip-2")
    assert entry_1["status"] == QUEUED
    assert entry_2["status"] == PUBLISHED


def test_now_unknown_clip_id_errors_cleanly_not_crash(tmp_path):
    queue_path = make_cli_tiktok_queue(
        tmp_path, [make_tiktok_entry(clip_id="clip-1", seq=1, status=QUEUED)]
    )
    config = FakeTikTokPublishConfig(tiktok_enabled=True, tiktok_queue_path=queue_path)

    args = build_argument_parser().parse_args(["--now", "does-not-exist"])
    with pytest.raises(SystemExit):
        run_command(args, credentials_factory=lambda: "token", config=config)


def test_kill_unknown_clip_id_errors_cleanly_not_crash(tmp_path):
    queue_path = make_cli_tiktok_queue(
        tmp_path, [make_tiktok_entry(clip_id="clip-1", seq=1, status=QUEUED)]
    )
    config = FakeTikTokPublishConfig(tiktok_enabled=True, tiktok_queue_path=queue_path)

    args = build_argument_parser().parse_args(["--kill", "does-not-exist"])
    with pytest.raises(SystemExit):
        run_command(args, credentials_factory=lambda: "token", config=config)


def test_kill_via_cli_on_published_entry_raises_not_system_exit(tmp_path):
    # A RuntimeError from kill_item (PUBLISHED entry) must propagate loudly,
    # not be caught into a clean SystemExit(2) like the unknown-clip_id case.
    queue_path = make_cli_tiktok_queue(
        tmp_path, [make_tiktok_entry(clip_id="clip-1", seq=1, status=PUBLISHED)]
    )
    config = FakeTikTokPublishConfig(tiktok_enabled=True, tiktok_queue_path=queue_path)

    args = build_argument_parser().parse_args(["--kill", "clip-1"])
    with pytest.raises(RuntimeError):
        run_command(args, credentials_factory=lambda: "token", config=config)


def test_kill_via_cli_flips_not_yet_uploaded_entry_to_killed(tmp_path):
    queue_path = make_cli_tiktok_queue(
        tmp_path, [make_tiktok_entry(clip_id="clip-1", seq=1, status=QUEUED)]
    )
    config = FakeTikTokPublishConfig(tiktok_enabled=True, tiktok_queue_path=queue_path)

    args = build_argument_parser().parse_args(["--kill", "clip-1"])
    run_command(args, credentials_factory=lambda: "token", config=config)

    assert load_queue(queue_path)["entries"][0]["status"] == KILLED


def test_pause_and_resume_via_cli_dispatch(tmp_path):
    queue_path = make_cli_tiktok_queue(
        tmp_path, [make_tiktok_entry(clip_id="clip-1", seq=1, status=QUEUED)]
    )
    config = FakeTikTokPublishConfig(tiktok_enabled=True, tiktok_queue_path=queue_path)

    pause_args = build_argument_parser().parse_args(["--pause", "clip-1"])
    run_command(pause_args, credentials_factory=lambda: "token", config=config)
    assert load_queue(queue_path)["entries"][0]["status"] == PAUSED

    resume_args = build_argument_parser().parse_args(["--resume", "clip-1"])
    run_command(resume_args, credentials_factory=lambda: "token", config=config)
    assert load_queue(queue_path)["entries"][0]["status"] == QUEUED


def test_help_flag_lists_all_six_flags(capsys):
    parser = build_argument_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--help"])
    out = capsys.readouterr().out
    for flag in ["--check", "--now", "--pause", "--kill", "--resume", "--list"]:
        assert flag in out
