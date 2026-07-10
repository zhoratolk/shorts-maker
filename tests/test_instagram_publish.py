import json
import threading
import time
import urllib.request
from pathlib import Path

import pytest
import requests

import scripts.instagram_publish as instagram_publish
from scripts.instagram_publish import (
    GRAPH_API_VERSION,
    INSTAGRAM_SCOPES,
    MAX_CAPTION_LENGTH,
    MAX_HASHTAGS,
    MAX_MENTIONS,
    PAUSED,
    QUEUED,
    UPLOADING,
    VALID_STATUSES,
    PUBLISHED,
    InstagramAccessError,
    _capture_oauth_redirect_code,
    _check_meta_permission_error,
    _find_entry,
    _upload_one,
    build_media_container_params,
    create_resumable_container,
    enqueue,
    load_credentials,
    load_queue,
    pause_item,
    poll_container_status,
    publish_container,
    reconcile_all_uploading,
    reconcile_uploading,
    resume_item,
    run_instagram_oauth_consent,
    save_queue,
    select_next_due,
    upload_and_publish,
    upload_local_video,
    validate_caption,
)


# --- Task 1: queue lifecycle -------------------------------------------


def test_valid_statuses_contains_exactly_five_states():
    assert VALID_STATUSES == frozenset(
        {"queued", "uploading", "published", "killed", "paused"}
    )


def test_load_queue_returns_empty_entries_when_file_missing(tmp_path):
    queue_path = str(tmp_path / "does_not_exist" / "instagram_queue.json")

    queue = load_queue(queue_path)

    assert queue == {"entries": []}


def test_save_queue_creates_parent_dirs_and_writes_utf8_json(tmp_path):
    queue_path = str(tmp_path / "nested" / "instagram_queue.json")
    queue = {"entries": [{"caption": "приветик"}]}

    save_queue(queue, queue_path)

    written = Path(queue_path).read_text(encoding="utf-8")
    assert "приветик" in written
    assert json.loads(written) == queue


def test_enqueue_is_idempotent_on_clip_id(tmp_path):
    queue = load_queue(str(tmp_path / "instagram_queue.json"))

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
    queue = load_queue(str(tmp_path / "instagram_queue.json"))

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
    assert entry1["container_id"] is None
    assert entry1["media_id"] is None
    assert "description" not in entry1
    assert "tags" not in entry1
    assert "publish_at" not in entry1


def test_select_next_due_skips_non_queued_statuses(tmp_path):
    queue = load_queue(str(tmp_path / "instagram_queue.json"))
    enqueue(queue, clip_id="clip-1", video_path="c1.mp4", metadata_path="c1.txt", caption="c1")
    entry2 = enqueue(queue, clip_id="clip-2", video_path="c2.mp4", metadata_path="c2.txt", caption="c2")
    enqueue(queue, clip_id="clip-3", video_path="c3.mp4", metadata_path="c3.txt", caption="c3")

    entry2["status"] = PAUSED
    queue["entries"][0]["status"] = UPLOADING
    queue["entries"][2]["status"] = "published"

    assert select_next_due(queue) is None


def test_select_next_due_returns_lowest_seq_queued(tmp_path):
    queue = load_queue(str(tmp_path / "instagram_queue.json"))
    enqueue(queue, clip_id="clip-1", video_path="c1.mp4", metadata_path="c1.txt", caption="c1")
    enqueue(queue, clip_id="clip-2", video_path="c2.mp4", metadata_path="c2.txt", caption="c2")

    due = select_next_due(queue)

    assert due["clip_id"] == "clip-1"


def test_pause_then_resume_round_trip(tmp_path):
    queue = load_queue(str(tmp_path / "instagram_queue.json"))
    enqueue(queue, clip_id="clip-1", video_path="c1.mp4", metadata_path="c1.txt", caption="c1")

    pause_item(queue, "clip-1")
    assert _find_entry(queue, "clip-1")["status"] == PAUSED

    resume_item(queue, "clip-1")
    assert _find_entry(queue, "clip-1")["status"] == QUEUED


def test_isolation_pause_instagram_queue_never_touches_youtube_queue(tmp_path):
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

    ig_queue_path = tmp_path / "instagram_queue.json"
    ig_queue = load_queue(str(ig_queue_path))
    enqueue(ig_queue, clip_id="ig-clip-1", video_path="v.mp4", metadata_path="m.txt", caption="c")
    save_queue(ig_queue, str(ig_queue_path))
    pause_item(ig_queue, "ig-clip-1")
    save_queue(ig_queue, str(ig_queue_path))

    after = yt_queue_path.read_text(encoding="utf-8")
    assert after == before


def test_instagram_scopes_are_minimal():
    assert INSTAGRAM_SCOPES == ["instagram_business_basic", "instagram_business_content_publish"]


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
    assert on headers, request bodies, etc."""

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
    token_path = tmp_path / "instagram_token.json"
    token_path.write_text(json.dumps({
        "access_token": "cached-token",
        "obtained_at": time.time(),
        "expires_at": time.time() + 60 * 24 * 3600,
    }), encoding="utf-8")

    session = FakeSession([])
    access_token = load_credentials("instagram_client_secret.json", str(token_path), session=session)

    assert access_token == "cached-token"
    assert session.calls == []


def test_load_credentials_refreshes_aging_token(tmp_path):
    token_path = tmp_path / "instagram_token.json"
    token_path.write_text(json.dumps({
        "access_token": "old-token",
        "obtained_at": time.time() - (25 * 3600),  # older than 24h
        "expires_at": time.time() + (30 * 24 * 3600),
    }), encoding="utf-8")

    session = FakeSession([
        FakeResponse({"access_token": "new-token", "expires_in": 60 * 24 * 3600, "token_type": "bearer"}),
    ])

    access_token = load_credentials("instagram_client_secret.json", str(token_path), session=session)

    assert access_token == "new-token"
    method, url, kwargs = session.calls[0]
    assert method == "GET"
    assert url == instagram_publish.INSTAGRAM_REFRESH_URL
    assert kwargs["params"]["grant_type"] == "ig_refresh_token"
    assert kwargs["params"]["access_token"] == "old-token"

    saved = json.loads(token_path.read_text(encoding="utf-8"))
    assert saved["access_token"] == "new-token"
    assert "expires_at" in saved
    assert "obtained_at" in saved


def test_load_credentials_raises_file_not_found_when_no_cached_token(tmp_path):
    token_path = tmp_path / "does_not_exist.json"

    with pytest.raises(FileNotFoundError):
        load_credentials("instagram_client_secret.json", str(token_path))


# --- Task 1: one-time interactive OAuth consent -------------------------


def test_capture_oauth_redirect_server_binds_to_localhost_only():
    server, captured = instagram_publish._build_redirect_server("127.0.0.1", 8789)
    try:
        assert server.server_address[0] == "127.0.0.1"
        assert server.server_address[0] != "0.0.0.0"
    finally:
        server.server_close()


def test_capture_oauth_redirect_code_returns_code_from_single_request():
    port = 8788

    def send_request():
        time.sleep(0.2)
        urllib.request.urlopen(f"http://127.0.0.1:{port}/callback?code=abc123&state=xyz", timeout=5)

    thread = threading.Thread(target=send_request)
    thread.start()
    code = _capture_oauth_redirect_code("127.0.0.1", port, timeout_seconds=5)
    thread.join()

    assert code == "abc123"


def test_run_instagram_oauth_consent_full_flow(tmp_path, monkeypatch):
    client_secret_path = tmp_path / "instagram_client_secret.json"
    client_secret_path.write_text(json.dumps({"client_id": "cid", "client_secret": "csecret"}), encoding="utf-8")
    token_path = tmp_path / "instagram_token.json"

    opened_urls = []
    monkeypatch.setattr(instagram_publish.webbrowser, "open", lambda url: opened_urls.append(url))

    port = 8766

    def hit_redirect():
        time.sleep(0.2)
        urllib.request.urlopen(f"http://127.0.0.1:{port}/callback?code=abc123&state=xyz", timeout=5)

    thread = threading.Thread(target=hit_redirect)
    thread.start()

    session = FakeSession([
        FakeResponse({"access_token": "short-lived-tok", "user_id": "u1"}),
        FakeResponse({"access_token": "long-lived-tok", "token_type": "bearer", "expires_in": 60 * 24 * 3600}),
    ])

    access_token = run_instagram_oauth_consent(
        str(client_secret_path), str(token_path), port=port, session=session
    )
    thread.join()

    assert access_token == "long-lived-tok"
    assert opened_urls
    assert "client_id=cid" in opened_urls[0]
    assert "instagram_business_basic,instagram_business_content_publish" in opened_urls[0]
    assert f"redirect_uri=http%3A%2F%2F127.0.0.1%3A{port}%2Fcallback" in opened_urls[0]

    saved = json.loads(token_path.read_text(encoding="utf-8"))
    assert saved["access_token"] == "long-lived-tok"
    assert "expires_at" in saved
    assert "obtained_at" in saved

    # Two calls: short-lived exchange (POST api.instagram.com), then
    # long-lived exchange (GET graph.instagram.com/access_token).
    assert session.calls[0][0] == "POST"
    assert session.calls[1][0] == "GET"
    assert session.calls[1][1] == instagram_publish.INSTAGRAM_LONG_LIVED_EXCHANGE_URL


# --- Task 2: caption validation + pure body builder ----------------------


def test_validate_caption_raises_for_oversized_caption():
    with pytest.raises(ValueError):
        validate_caption("x" * (MAX_CAPTION_LENGTH + 1))


def test_validate_caption_allows_max_length_caption():
    validate_caption("x" * MAX_CAPTION_LENGTH)  # must not raise


def test_validate_caption_raises_for_too_many_hashtags():
    caption = " ".join(f"#tag{i}" for i in range(MAX_HASHTAGS + 1))
    with pytest.raises(ValueError):
        validate_caption(caption)


def test_validate_caption_allows_max_hashtags():
    caption = " ".join(f"#tag{i}" for i in range(MAX_HASHTAGS))
    validate_caption(caption)  # must not raise


def test_validate_caption_raises_for_too_many_mentions():
    caption = " ".join(f"@user{i}" for i in range(MAX_MENTIONS + 1))
    with pytest.raises(ValueError):
        validate_caption(caption)


def test_validate_caption_allows_max_mentions():
    caption = " ".join(f"@user{i}" for i in range(MAX_MENTIONS))
    validate_caption(caption)  # must not raise


def test_build_media_container_params_shapes_reels_resumable():
    params = build_media_container_params("hello #wow @friend")

    assert params == {
        "media_type": "REELS",
        "upload_type": "resumable",
        "caption": "hello #wow @friend",
    }


def test_build_media_container_params_raises_before_any_session_call_on_oversized_caption():
    session = FakeSession([])

    with pytest.raises(ValueError):
        build_media_container_params("x" * (MAX_CAPTION_LENGTH + 1))

    assert session.calls == []


# --- Task 2: resumable-upload HTTP layer ----------------------------------


def test_create_resumable_container_posts_exact_params_and_returns_id():
    session = FakeSession([
        FakeResponse({"id": "container-1"}),
    ])
    params = {"media_type": "REELS", "upload_type": "resumable", "caption": "hi"}

    container_id = create_resumable_container("ig-user-1", "token-123", params, session=session)

    assert container_id == "container-1"
    method, url, kwargs = session.calls[0]
    assert method == "POST"
    assert url == f"https://graph.facebook.com/{GRAPH_API_VERSION}/ig-user-1/media"
    assert kwargs["params"]["media_type"] == "REELS"
    assert kwargs["params"]["upload_type"] == "resumable"
    assert kwargs["params"]["caption"] == "hi"
    assert kwargs["params"]["access_token"] == "token-123"


def test_upload_local_video_posts_bytes_to_rupload_not_graph(tmp_path):
    video_path = tmp_path / "clip.mp4"
    content = b"0123456789"
    video_path.write_bytes(content)

    session = FakeSession([FakeResponse({})])
    upload_local_video("container-1", "token-123", str(video_path), session=session)

    assert len(session.calls) == 1
    method, url, kwargs = session.calls[0]
    assert method == "POST"
    assert url == f"https://rupload.facebook.com/ig-api-upload/{GRAPH_API_VERSION}/container-1"
    assert "graph.facebook.com" not in url
    assert kwargs["headers"]["offset"] == "0"
    assert kwargs["headers"]["file_size"] == str(len(content))
    assert kwargs["data"] == content


def test_poll_container_status_returns_status_code():
    session = FakeSession([
        FakeResponse({"status_code": "FINISHED"}),
    ])

    status_code = poll_container_status("container-1", "token-123", session=session)

    assert status_code == "FINISHED"
    method, url, kwargs = session.calls[0]
    assert method == "GET"
    assert url == f"https://graph.facebook.com/{GRAPH_API_VERSION}/container-1"
    assert kwargs["params"]["fields"] == "status_code"


def test_publish_container_posts_creation_id_and_returns_media_id():
    session = FakeSession([
        FakeResponse({"id": "media-1"}),
    ])

    media_id = publish_container("ig-user-1", "token-123", "container-1", session=session)

    assert media_id == "media-1"
    method, url, kwargs = session.calls[0]
    assert method == "POST"
    assert url == f"https://graph.facebook.com/{GRAPH_API_VERSION}/ig-user-1/media_publish"
    assert kwargs["params"]["creation_id"] == "container-1"


# --- Task 2: fail-closed permission handling ------------------------------


def test_check_meta_permission_error_403_raises_instagram_access_error():
    response = FakeResponse(
        {"error": {"message": "This account does not have permission to publish", "type": "OAuthException", "code": 10}},
        status_code=403,
    )

    with pytest.raises(InstagramAccessError):
        _check_meta_permission_error(response)


def test_create_resumable_container_403_permission_error_raises_instagram_access_error():
    session = FakeSession([
        FakeResponse(
            {"error": {"message": "requires advanced access", "type": "OAuthException", "code": 10}},
            status_code=403,
        ),
    ])
    params = {"media_type": "REELS", "upload_type": "resumable", "caption": "hi"}

    with pytest.raises(InstagramAccessError) as exc_info:
        create_resumable_container("ig-user-1", "token-123", params, session=session)

    assert "advanced access" in str(exc_info.value).lower() or "permission" in str(exc_info.value).lower()


def test_upload_local_video_403_permission_error_raises_instagram_access_error(tmp_path):
    video_path = tmp_path / "clip.mp4"
    video_path.write_bytes(b"0123456789")

    session = FakeSession([
        FakeResponse(
            {"error": {"message": "permission denied", "type": "OAuthException", "code": 10}},
            status_code=403,
        ),
    ])

    with pytest.raises(InstagramAccessError):
        upload_local_video("container-1", "token-123", str(video_path), session=session)


def test_publish_container_403_permission_error_raises_instagram_access_error():
    session = FakeSession([
        FakeResponse(
            {"error": {"message": "permission denied", "type": "OAuthException", "code": 10}},
            status_code=403,
        ),
    ])

    with pytest.raises(InstagramAccessError):
        publish_container("ig-user-1", "token-123", "container-1", session=session)


def test_create_resumable_container_non_permission_500_propagates_as_http_error():
    session = FakeSession([
        FakeResponse({"error": {"message": "internal server error", "type": "ServerError", "code": 1}}, status_code=500),
    ])
    params = {"media_type": "REELS", "upload_type": "resumable", "caption": "hi"}

    with pytest.raises(requests.HTTPError):
        create_resumable_container("ig-user-1", "token-123", params, session=session)


def test_check_meta_permission_error_no_op_on_success_response():
    response = FakeResponse({"id": "container-1"}, status_code=200)

    _check_meta_permission_error(response)  # must not raise


# --- Task 3: orchestration (dry-run gate, attempt-then-fail-closed, write-ahead), reconcile --


class FakeInstagramPublishConfig:
    """Minimal stand-in for scripts.config.PublishConfig - only the fields
    upload_and_publish/_upload_one actually read."""

    def __init__(self, instagram_enabled, instagram_queue_path="instagram_queue.json",
                 notifications_path="notifications.log"):
        self.instagram_enabled = instagram_enabled
        self.instagram_queue_path = instagram_queue_path
        self.notifications_path = notifications_path


class SpyingSession(FakeSession):
    """Extends FakeSession to snapshot the on-disk queue file at the moment
    the first POST to rupload.facebook.com fires - proves write-ahead
    persistence (container_id persisted before the byte upload starts)
    actually landed on disk before the upload call (mirrors
    tests/test_tiktok_publish.py's spying-PUT test technique)."""

    def __init__(self, responses, queue_path):
        super().__init__(responses)
        self.queue_path = queue_path
        self.container_id_at_first_rupload_post = "NOT_YET_CALLED"

    def post(self, url, **kwargs):
        if "rupload.facebook.com" in url and self.container_id_at_first_rupload_post == "NOT_YET_CALLED":
            saved = json.loads(Path(self.queue_path).read_text(encoding="utf-8"))
            self.container_id_at_first_rupload_post = saved["entries"][0].get("container_id")
        return super().post(url, **kwargs)


def make_instagram_entry(**overrides):
    entry = {
        "seq": 1,
        "clip_id": "clip-1",
        "video_path": "clip1.mp4",
        "metadata_path": "clip1.txt",
        "caption": "caption 1",
        "status": QUEUED,
        "container_id": None,
        "media_id": None,
        "enqueued_at": "2026-07-10T00:00:00Z",
        "updated_at": "2026-07-10T00:00:00Z",
    }
    entry.update(overrides)
    return entry


def test_dry_run_default_no_upload(tmp_path):
    queue_path = tmp_path / "instagram_queue.json"
    queue = load_queue(str(queue_path))
    entry = enqueue(queue, clip_id="clip-1", video_path="c.mp4", metadata_path="c.txt", caption="cap")
    config = FakeInstagramPublishConfig(instagram_enabled=False, instagram_queue_path=str(queue_path))
    session = FakeSession([])

    def credentials_factory():
        raise AssertionError("credentials_factory must not be called during dry-run")

    result = upload_and_publish(
        queue, entry, credentials_factory, config, ig_user_id="ig-user-1",
        session=session, queue_path=str(queue_path),
    )

    assert result == {"dry_run": True}
    assert session.calls == []
    assert entry["status"] == QUEUED


def test_upload_and_publish_full_success_flow_persists_write_ahead(tmp_path):
    video_path = tmp_path / "clip.mp4"
    video_path.write_bytes(b"0123456789")
    queue_path = tmp_path / "instagram_queue.json"

    queue = load_queue(str(queue_path))
    entry = enqueue(
        queue, clip_id="clip-1", video_path=str(video_path), metadata_path="c.txt", caption="cap"
    )
    save_queue(queue, str(queue_path))

    config = FakeInstagramPublishConfig(instagram_enabled=True, instagram_queue_path=str(queue_path))

    session = SpyingSession([
        FakeResponse({"id": "container-1"}),  # create_resumable_container
        FakeResponse({}),                      # upload_local_video (rupload)
        FakeResponse({"status_code": "FINISHED"}),  # poll_container_status
        FakeResponse({"id": "media-1"}),       # publish_container
    ], queue_path=str(queue_path))

    result = upload_and_publish(
        queue, entry, lambda: "access-token-123", config, ig_user_id="ig-user-1",
        session=session, queue_path=str(queue_path),
    )

    assert result == {"media_id": "media-1"}
    assert entry["status"] == PUBLISHED
    assert entry["media_id"] == "media-1"
    # Write-ahead #2: container_id must be on disk BEFORE upload_local_video's
    # POST to rupload.facebook.com starts, so a crash mid-upload is
    # reconcilable rather than silently duplicated.
    assert session.container_id_at_first_rupload_post == "container-1"


def test_upload_and_publish_no_pre_publish_gating_call(tmp_path):
    """The single most important behavioral test in this plan: no
    creator_info/query-equivalent call precedes create_resumable_container -
    the very first session call must be the real container-create POST."""
    video_path = tmp_path / "clip.mp4"
    video_path.write_bytes(b"0123456789")
    queue_path = tmp_path / "instagram_queue.json"

    queue = load_queue(str(queue_path))
    entry = enqueue(
        queue, clip_id="clip-1", video_path=str(video_path), metadata_path="c.txt", caption="cap"
    )
    save_queue(queue, str(queue_path))

    config = FakeInstagramPublishConfig(instagram_enabled=True, instagram_queue_path=str(queue_path))

    session = FakeSession([
        FakeResponse({"id": "container-1"}),
        FakeResponse({}),
        FakeResponse({"status_code": "FINISHED"}),
        FakeResponse({"id": "media-1"}),
    ])

    upload_and_publish(
        queue, entry, lambda: "access-token-123", config, ig_user_id="ig-user-1",
        session=session, queue_path=str(queue_path),
    )

    first_call_method, first_call_url, _ = session.calls[0]
    assert first_call_method == "POST"
    assert first_call_url == f"https://graph.facebook.com/{GRAPH_API_VERSION}/ig-user-1/media"
    assert "creator_info" not in first_call_url


def test_upload_and_publish_poll_then_publish_sequencing(tmp_path):
    """publish_container must never be called before poll_container_status
    returns FINISHED."""
    video_path = tmp_path / "clip.mp4"
    video_path.write_bytes(b"0123456789")
    queue_path = tmp_path / "instagram_queue.json"

    queue = load_queue(str(queue_path))
    entry = enqueue(
        queue, clip_id="clip-1", video_path=str(video_path), metadata_path="c.txt", caption="cap"
    )
    save_queue(queue, str(queue_path))

    config = FakeInstagramPublishConfig(instagram_enabled=True, instagram_queue_path=str(queue_path))

    session = FakeSession([
        FakeResponse({"id": "container-1"}),
        FakeResponse({}),
        FakeResponse({"status_code": "IN_PROGRESS"}),
        FakeResponse({"status_code": "FINISHED"}),
        FakeResponse({"id": "media-1"}),
    ])

    result = upload_and_publish(
        queue, entry, lambda: "access-token-123", config, ig_user_id="ig-user-1",
        session=session, queue_path=str(queue_path), poll_interval_seconds=0,
    )

    assert result == {"media_id": "media-1"}
    urls = [url for _, url, _ in session.calls]
    media_publish_index = next(i for i, u in enumerate(urls) if u.endswith("/media_publish"))
    finished_poll_index = max(
        i for i, (_, u, _) in enumerate(session.calls)
        if u == f"https://graph.facebook.com/{GRAPH_API_VERSION}/container-1"
    )
    assert finished_poll_index < media_publish_index


def test_upload_and_publish_container_error_raises_runtime_error_stays_uploading(tmp_path):
    video_path = tmp_path / "clip.mp4"
    video_path.write_bytes(b"0123456789")
    queue_path = tmp_path / "instagram_queue.json"

    queue = load_queue(str(queue_path))
    entry = enqueue(
        queue, clip_id="clip-1", video_path=str(video_path), metadata_path="c.txt", caption="cap"
    )
    save_queue(queue, str(queue_path))

    config = FakeInstagramPublishConfig(instagram_enabled=True, instagram_queue_path=str(queue_path))

    session = FakeSession([
        FakeResponse({"id": "container-1"}),
        FakeResponse({}),
        FakeResponse({"status_code": "ERROR"}),
    ])

    with pytest.raises(RuntimeError):
        upload_and_publish(
            queue, entry, lambda: "access-token-123", config, ig_user_id="ig-user-1",
            session=session, queue_path=str(queue_path),
        )

    assert entry["status"] == UPLOADING


def test_upload_and_publish_instagram_access_error_propagates_unchanged(tmp_path):
    video_path = tmp_path / "clip.mp4"
    video_path.write_bytes(b"0123456789")
    queue_path = tmp_path / "instagram_queue.json"

    queue = load_queue(str(queue_path))
    entry = enqueue(
        queue, clip_id="clip-1", video_path=str(video_path), metadata_path="c.txt", caption="cap"
    )
    save_queue(queue, str(queue_path))

    config = FakeInstagramPublishConfig(instagram_enabled=True, instagram_queue_path=str(queue_path))

    session = FakeSession([
        FakeResponse(
            {"error": {"message": "requires advanced access", "type": "OAuthException", "code": 10}},
            status_code=403,
        ),
    ])

    with pytest.raises(InstagramAccessError):
        upload_and_publish(
            queue, entry, lambda: "access-token-123", config, ig_user_id="ig-user-1",
            session=session, queue_path=str(queue_path),
        )


def test_upload_one_instagram_access_error_notified_and_reraised(tmp_path):
    video_path = tmp_path / "clip.mp4"
    video_path.write_bytes(b"0123456789")
    queue_path = tmp_path / "instagram_queue.json"
    notifications_path = tmp_path / "notifications.log"

    queue = load_queue(str(queue_path))
    entry = enqueue(
        queue, clip_id="clip-1", video_path=str(video_path), metadata_path="c.txt", caption="cap"
    )
    save_queue(queue, str(queue_path))

    config = FakeInstagramPublishConfig(
        instagram_enabled=True, instagram_queue_path=str(queue_path),
        notifications_path=str(notifications_path),
    )

    session = FakeSession([
        FakeResponse(
            {"error": {"message": "requires advanced access", "type": "OAuthException", "code": 10}},
            status_code=403,
        ),
    ])

    with pytest.raises(InstagramAccessError):
        _upload_one(entry, queue, lambda: "access-token-123", config, ig_user_id="ig-user-1", session=session)

    log_text = notifications_path.read_text(encoding="utf-8")
    assert "advanced access" in log_text.lower() or "permission" in log_text.lower()


def test_upload_one_success_appends_normal_notification(tmp_path):
    video_path = tmp_path / "clip.mp4"
    video_path.write_bytes(b"0123456789")
    queue_path = tmp_path / "instagram_queue.json"
    notifications_path = tmp_path / "notifications.log"

    queue = load_queue(str(queue_path))
    entry = enqueue(
        queue, clip_id="clip-1", video_path=str(video_path), metadata_path="c.txt", caption="cap"
    )
    save_queue(queue, str(queue_path))

    config = FakeInstagramPublishConfig(
        instagram_enabled=True, instagram_queue_path=str(queue_path),
        notifications_path=str(notifications_path),
    )

    session = FakeSession([
        FakeResponse({"id": "container-1"}),
        FakeResponse({}),
        FakeResponse({"status_code": "FINISHED"}),
        FakeResponse({"id": "media-1"}),
    ])

    _upload_one(entry, queue, lambda: "access-token-123", config, ig_user_id="ig-user-1", session=session)

    log_text = notifications_path.read_text(encoding="utf-8")
    assert "залил 1 в Instagram" in log_text


def test_reconcile_uploading_no_container_id_resets_to_queued_without_api_call():
    entry = make_instagram_entry(status=UPLOADING, container_id=None)
    queue = {"entries": [entry]}
    session = FakeSession([])

    def credentials_factory():
        raise AssertionError("credentials_factory must not be called when no container_id recorded")

    reconcile_uploading(queue, entry, credentials_factory, ig_user_id="ig-user-1", session=session)

    assert entry["status"] == QUEUED
    assert session.calls == []


def test_reconcile_uploading_already_has_media_id_is_noop():
    entry = make_instagram_entry(status=UPLOADING, container_id="container-1", media_id="media-1")
    queue = {"entries": [entry]}
    session = FakeSession([])

    def credentials_factory():
        raise AssertionError("credentials_factory must not be called when already terminal")

    reconcile_uploading(queue, entry, credentials_factory, ig_user_id="ig-user-1", session=session)

    assert entry["status"] == UPLOADING  # untouched
    assert session.calls == []


def test_reconcile_uploading_finished_completes_publish_no_duplicate_container_create():
    entry = make_instagram_entry(status=UPLOADING, container_id="container-1")
    queue = {"entries": [entry]}
    session = FakeSession([
        FakeResponse({"status_code": "FINISHED"}),
        FakeResponse({"id": "media-1"}),
    ])

    reconcile_uploading(queue, entry, lambda: "token", ig_user_id="ig-user-1", session=session)

    assert entry["status"] == PUBLISHED
    assert entry["media_id"] == "media-1"
    urls_called = [url for _, url, _ in session.calls]
    assert f"https://graph.facebook.com/{GRAPH_API_VERSION}/ig-user-1/media" not in urls_called


def test_reconcile_uploading_error_resets_to_queued_clears_container_id():
    entry = make_instagram_entry(status=UPLOADING, container_id="container-1")
    queue = {"entries": [entry]}
    session = FakeSession([
        FakeResponse({"status_code": "ERROR"}),
    ])

    reconcile_uploading(queue, entry, lambda: "token", ig_user_id="ig-user-1", session=session)

    assert entry["status"] == QUEUED
    assert entry["container_id"] is None


def test_reconcile_uploading_still_in_flight_is_left_untouched():
    entry = make_instagram_entry(status=UPLOADING, container_id="container-1")
    queue = {"entries": [entry]}
    session = FakeSession([
        FakeResponse({"status_code": "IN_PROGRESS"}),
    ])

    reconcile_uploading(queue, entry, lambda: "token", ig_user_id="ig-user-1", session=session)

    assert entry["status"] == UPLOADING
    assert entry["container_id"] == "container-1"


def test_reconcile_all_uploading_skips_non_uploading_entries():
    queued_entry = make_instagram_entry(clip_id="clip-1", status=QUEUED)
    uploading_entry = make_instagram_entry(
        clip_id="clip-2", seq=2, status=UPLOADING, container_id=None
    )
    queue = {"entries": [queued_entry, uploading_entry]}
    session = FakeSession([])

    reconcile_all_uploading(queue, lambda: "token", ig_user_id="ig-user-1", session=session)

    assert queued_entry["status"] == QUEUED
    assert uploading_entry["status"] == QUEUED  # reset, no container_id, no api call


def test_no_daily_slots_utc_reference_anywhere_in_module():
    """06-RESEARCH.md Open Question 3: Instagram's media_publish is
    immediate, no publishAt-equivalent to schedule against - this module
    must never read config.daily_slots_utc."""
    import inspect

    source = inspect.getsource(instagram_publish)
    assert "daily_slots_utc" not in source


def test_no_pre_publish_gating_function_exists_in_module():
    """Grep-equivalent check: no creator_info/query-equivalent gating
    function exists anywhere in this module (the single most important
    constraint of this plan)."""
    import inspect

    source = inspect.getsource(instagram_publish)
    assert "creator_info" not in source
    assert "publish_gate" not in source
