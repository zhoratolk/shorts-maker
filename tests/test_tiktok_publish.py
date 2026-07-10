import json
import threading
import time
import urllib.request
from pathlib import Path

import pytest
import requests

import scripts.tiktok_publish as tiktok_publish
from scripts.tiktok_publish import (
    PAUSED,
    PUBLISHED,
    QUEUED,
    TIKTOK_SCOPES,
    UPLOADING,
    VALID_STATUSES,
    _capture_oauth_redirect_code,
    _find_entry,
    enqueue,
    load_credentials,
    load_queue,
    pause_item,
    resume_item,
    run_tiktok_oauth_consent,
    save_queue,
    select_next_due,
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
