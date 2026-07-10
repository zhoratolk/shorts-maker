from __future__ import annotations

"""Local TikTok publish-queue + upload layer.

Tracks finished shorts through their own manifest (work/_publish/
tiktok_queue.json - kept separate from YouTube's queue.json so a TikTok
audit delay or bug can never touch the already-live YouTube pipeline,
06-RESEARCH.md Standard Stack). Mirrors scripts/publish_queue.py's
enqueue/select_next_due/pause/resume state machine exactly; the only new
logic is the TikTok-specific HTTP calls (video/init, chunked PUT,
status/fetch, creator_info/query), the one-time interactive OAuth consent
flow, and the D-05 SELF_ONLY gating check.

This module covers the queue lifecycle, OAuth credential handling, the
Content Posting API HTTP layer, and the orchestration/reconciliation
functions - everything needed to actually publish one queued clip to
TikTok. It deliberately does NOT include kill_item (an already-PUBLISHED
TikTok post cannot be un-published, unlike YouTube's publishAt-based kill
- see 06-PATTERNS.md) or a CLI wrapper; both are Plan 06-05's job.

`requests` is imported at module top level (unlike
google-api-python-client's deferred-import pattern) since it is a
lightweight, always-installed dependency, not an optional extra.
"""

import http.server
import json
import math
import os
import random
import string
import time
import urllib.parse
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from scripts.publish_queue import append_notification

# Status enum - the full lifecycle a TikTok queue entry can move through.
# No SCHEDULED status: TikTok Direct Post has no publishAt-style native
# schedule (06-RESEARCH.md Pitfall 4) - QUEUED -> UPLOADING -> PUBLISHED
# is the whole lifecycle, no SCHEDULED intermediate.
QUEUED = "queued"
UPLOADING = "uploading"
PUBLISHED = "published"
KILLED = "killed"
PAUSED = "paused"

VALID_STATUSES = frozenset({QUEUED, UPLOADING, PUBLISHED, KILLED, PAUSED})

# Queue manifest + notification-log locations (paths only - no file is
# created by importing this module).
DEFAULT_QUEUE_PATH = "work/_publish/tiktok_queue.json"
DEFAULT_NOTIFICATIONS_PATH = "work/_publish/notifications.log"  # SHARED, D-06

# V4 scope minimization - never request a broader scope than these two.
TIKTOK_SCOPES = ["video.publish", "video.upload"]

TIKTOK_TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
TIKTOK_AUTHORIZE_URL = "https://www.tiktok.com/v2/auth/authorize/"
TIKTOK_INIT_URL = "https://open.tiktokapis.com/v2/post/publish/video/init/"
TIKTOK_STATUS_URL = "https://open.tiktokapis.com/v2/post/publish/status/fetch/"
TIKTOK_CREATOR_INFO_URL = "https://open.tiktokapis.com/v2/post/publish/creator_info/query/"

# TikTok's own field limit (V5 input validation, 06-RESEARCH Security
# Domain) - a violation fails this one queue item, not the whole run. This
# is a UTF-16-rune limit, approximated via Python str length per this
# project's existing len()-based limit-check convention
# (scripts/publish_queue.py::build_insert_body).
MAX_TITLE_LENGTH = 2200

# Within TikTok's documented 5MB-64MB per-chunk range. This project's clips
# are short (30-150s vertical shorts), so most uploads will be a single
# chunk in practice, but upload_video_chunks must still handle a genuinely
# multi-chunk file correctly.
CHUNK_SIZE_DEFAULT = 10 * 1024 * 1024

# fetch_post_status's documented terminal states (06-RESEARCH.md Pattern 1).
TERMINAL_STATUSES = frozenset({"PUBLISH_COMPLETE", "FAILED"})


class TikTokPublishError(ValueError):
    pass


# --- Queue lifecycle -----------------------------------------------------


def load_queue(path: str = DEFAULT_QUEUE_PATH) -> dict[str, Any]:
    """Loads the queue manifest, fail-open: a missing file yields an empty
    queue rather than crashing (matches scripts/publish_queue.py exactly).
    """
    queue_file = Path(path)
    if not queue_file.exists():
        return {"entries": []}
    return json.loads(queue_file.read_text(encoding="utf-8"))


def save_queue(queue: dict[str, Any], path: str = DEFAULT_QUEUE_PATH) -> None:
    """Writes the queue manifest as human-readable UTF-8 JSON, creating
    parent directories as needed (matches scripts/publish_queue.py exactly).
    """
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
    caption: str,
) -> dict[str, Any]:
    """Appends a new entry to queue["entries"] with a sequential seq number
    (max existing seq + 1, starting at 1) and status=QUEUED. Idempotent on
    clip_id: re-enqueuing an already-present clip_id is a no-op that returns
    the existing entry unchanged.

    caption is taken verbatim from the already-rendered per-clip metadata
    (scripts/metadata.py's platforms_data["tiktok"]["caption"] field) - this
    function never regenerates metadata. Unlike YouTube's queue entry there
    is no description/tags/publish_at field: TikTok's post_info only takes
    title+privacy_level, and there is no native scheduling (06-RESEARCH.md
    Pitfall 4).
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
        "caption": caption,
        "status": QUEUED,
        "publish_id": None,
        "video_share_url": None,
        "enqueued_at": now,
        "updated_at": now,
    }
    queue["entries"].append(entry)
    return entry


def _find_entry(queue: dict[str, Any], clip_id: str) -> dict[str, Any]:
    for entry in queue["entries"]:
        if entry["clip_id"] == clip_id:
            return entry
    raise KeyError(f"no queue entry with clip_id={clip_id!r}")


def select_next_due(queue: dict[str, Any]) -> dict[str, Any] | None:
    """Returns the lowest-seq QUEUED entry, or None if nothing is eligible.
    PAUSED/KILLED/UPLOADING/PUBLISHED entries are never returned.
    """
    eligible = [entry for entry in queue["entries"] if entry["status"] == QUEUED]
    if not eligible:
        return None
    return min(eligible, key=lambda entry: entry["seq"])


def pause_item(queue: dict[str, Any], clip_id: str) -> dict[str, Any]:
    """Flips a QUEUED entry to PAUSED so the next check/select_next_due
    skips it. Only touches status/updated_at.
    """
    entry = _find_entry(queue, clip_id)
    entry["status"] = PAUSED
    entry["updated_at"] = datetime.now(timezone.utc).isoformat()
    return entry


def resume_item(queue: dict[str, Any], clip_id: str) -> dict[str, Any]:
    """Flips a PAUSED entry back to QUEUED so it becomes eligible again."""
    entry = _find_entry(queue, clip_id)
    entry["status"] = QUEUED
    entry["updated_at"] = datetime.now(timezone.utc).isoformat()
    return entry


# --- OAuth credential handling --------------------------------------------


def load_credentials(client_key_path: str, token_path: str, session=requests) -> str:
    """Loads a cached TikTok access token, silently refreshing via
    grant_type=refresh_token when expired (access tokens last 24h, refresh
    tokens last 365 days - refresh needs no user interaction). Raises
    FileNotFoundError with an actionable message if no cached token exists
    yet - first-time consent is a manual, one-time interactive step
    (run_tiktok_oauth_consent), matching
    youtube_analytics.py::load_credentials's "only interactive on the very
    first run" contract (06-RESEARCH.md Pattern 3).
    """
    token_file = Path(token_path)
    if not token_file.exists():
        raise FileNotFoundError(
            f"{token_path} not found - run the one-time interactive TikTok "
            "OAuth consent flow first (scripts.tiktok_publish.run_tiktok_oauth_consent)"
        )
    token_data = json.loads(token_file.read_text(encoding="utf-8"))
    if time.time() < token_data["expires_at"]:
        return token_data["access_token"]

    client = json.loads(Path(client_key_path).read_text(encoding="utf-8"))
    response = session.post(
        TIKTOK_TOKEN_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "client_key": client["client_key"],
            "client_secret": client["client_secret"],
            "grant_type": "refresh_token",
            "refresh_token": token_data["refresh_token"],
        },
    )
    response.raise_for_status()
    refreshed = response.json()
    refreshed["expires_at"] = time.time() + refreshed["expires_in"]
    token_file.write_text(
        json.dumps(refreshed, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return refreshed["access_token"]


def _build_redirect_server(host: str, port: int):
    """Constructs (but does not run) the one-shot local OAuth redirect
    listener, bound explicitly to `host` (the caller always passes
    "127.0.0.1", never "0.0.0.0" - T-06-03/V4 spoofing mitigation). Split
    out from _capture_oauth_redirect_code so the bind address itself is
    directly assertable in tests without needing a real HTTP round-trip.
    Returns (server, captured), where `captured` is filled in with the
    request's `code` query param once a request is handled.
    """
    captured: dict[str, str] = {}

    class _RedirectHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib method name
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query)
            captured["code"] = params.get("code", [""])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                "TikTok authorization received - you can close this tab.".encode("utf-8")
            )

        def log_message(self, format_str: str, *args: Any) -> None:  # noqa: A002
            pass  # suppress default request logging to stderr

    server = http.server.HTTPServer((host, port), _RedirectHandler)
    return server, captured


def _capture_oauth_redirect_code(host: str, port: int, timeout_seconds: float = 300) -> str:
    """Blocks on a local HTTP listener bound to (host, port) for exactly one
    redirect request (handle_request(), never serve_forever() - bounded, no
    lingering listener), then returns the `code` query param from that one
    request.
    """
    server, captured = _build_redirect_server(host, port)
    server.timeout = timeout_seconds
    try:
        server.handle_request()
    finally:
        server.server_close()

    code = captured.get("code")
    if not code:
        raise TikTokPublishError("no authorization code received on the OAuth redirect")
    return code


def run_tiktok_oauth_consent(
    client_key_path: str, token_path: str, port: int = 8765, session=requests
) -> str:
    """One-time interactive TikTok OAuth consent flow: builds the authorize
    URL, opens it via webbrowser.open, blocks on a local redirect-capture
    listener bound to 127.0.0.1 (never 0.0.0.0) for exactly one request,
    exchanges the returned code for tokens, and writes the token file in the
    same shape load_credentials expects (access_token, refresh_token,
    expires_at). Uses a fixed port (not port=0 like Google's flow) since
    TikTok apps require an exact pre-registered redirect_uri, unlike
    Google's loopback-exception handling (06-RESEARCH.md Pattern 3 /
    Security Domain).
    """
    client = json.loads(Path(client_key_path).read_text(encoding="utf-8"))
    redirect_uri = f"http://127.0.0.1:{port}/callback"
    state = "".join(random.choices(string.ascii_letters + string.digits, k=16))

    authorize_url = (
        f"{TIKTOK_AUTHORIZE_URL}?client_key={client['client_key']}"
        f"&scope={','.join(TIKTOK_SCOPES)}"
        "&response_type=code"
        f"&redirect_uri={urllib.parse.quote(redirect_uri, safe='')}"
        f"&state={state}"
    )
    webbrowser.open(authorize_url)

    code = _capture_oauth_redirect_code("127.0.0.1", port)

    response = session.post(
        TIKTOK_TOKEN_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "client_key": client["client_key"],
            "client_secret": client["client_secret"],
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        },
    )
    response.raise_for_status()
    token_data = response.json()
    token_data["expires_at"] = time.time() + token_data["expires_in"]

    token_file = Path(token_path)
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(
        json.dumps(token_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return token_data["access_token"]


# --- Content Posting API HTTP layer ---------------------------------------


def validate_title_length(title: str) -> None:
    """Raises ValueError if title exceeds MAX_TITLE_LENGTH."""
    if len(title) > MAX_TITLE_LENGTH:
        raise ValueError(
            f"title exceeds TikTok's {MAX_TITLE_LENGTH}-char limit ({len(title)} chars)"
        )


def build_direct_post_body(
    title: str,
    privacy_level: str,
    video_size: int,
    chunk_size: int,
    total_chunk_count: int,
) -> dict[str, Any]:
    """Pure function - builds the exact video/init request body
    (06-RESEARCH.md Pattern 1). No network call. privacy_level MUST come
    from a prior check_tiktok_publish_gate call - never hardcode
    PUBLIC_TO_EVERYONE (06-RESEARCH.md Anti-Patterns).
    """
    validate_title_length(title)
    return {
        "post_info": {"title": title, "privacy_level": privacy_level},
        "source_info": {
            "source": "FILE_UPLOAD",
            "video_size": video_size,
            "chunk_size": chunk_size,
            "total_chunk_count": total_chunk_count,
        },
    }


def init_direct_post(access_token: str, body: dict[str, Any], session=requests) -> dict[str, Any]:
    """POSTs body to video/init, returns response.json()["data"]
    ({"publish_id", "upload_url"}).
    """
    response = session.post(
        TIKTOK_INIT_URL,
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
        json=body,
    )
    response.raise_for_status()
    return response.json()["data"]


def upload_video_chunks(
    upload_url: str, video_path: str, chunk_size: int, session=requests
) -> None:
    """PUTs the local file to upload_url in chunk_size pieces (5MB-64MB per
    chunk per TikTok's docs), with correct Content-Range headers covering
    the whole file - works correctly for both a single-chunk file under
    chunk_size and a genuinely multi-chunk file (06-RESEARCH.md Pattern 1).
    upload_url is valid for 1 hour.
    """
    total_size = os.path.getsize(video_path)
    with open(video_path, "rb") as handle:
        offset = 0
        while offset < total_size:
            chunk = handle.read(chunk_size)
            end = offset + len(chunk) - 1
            response = session.put(
                upload_url,
                headers={
                    "Content-Type": "video/mp4",
                    "Content-Length": str(len(chunk)),
                    "Content-Range": f"bytes {offset}-{end}/{total_size}",
                },
                data=chunk,
            )
            response.raise_for_status()
            offset += len(chunk)


def fetch_post_status(access_token: str, publish_id: str, session=requests) -> dict[str, Any]:
    """POSTs {"publish_id": publish_id} to status/fetch, returns
    response.json()["data"]. NOTE: does NOT return the achieved
    privacy_level - that must be inferred from check_tiktok_publish_gate,
    not from this endpoint (06-RESEARCH.md Pitfall 1).
    """
    response = session.post(
        TIKTOK_STATUS_URL,
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
        json={"publish_id": publish_id},
    )
    response.raise_for_status()
    return response.json()["data"]


def check_tiktok_publish_gate(access_token: str, session=requests) -> tuple[str, bool]:
    """Returns (privacy_level_to_use, is_still_gated). is_still_gated=True
    means PUBLIC_TO_EVERYONE is not an available option right now (unaudited
    client and/or account set to private) - D-05's trigger for the chat
    notification. Checked BEFORE every video/init call (06-RESEARCH.md
    Pattern 4) - status/fetch has no achieved-privacy-level field to infer
    this from after the fact (Pitfall 1).
    """
    response = session.post(
        TIKTOK_CREATOR_INFO_URL,
        headers={"Authorization": f"Bearer {access_token}"},
    )
    response.raise_for_status()
    options = response.json()["data"]["privacy_level_options"]
    if "PUBLIC_TO_EVERYONE" in options:
        return "PUBLIC_TO_EVERYONE", False
    return "SELF_ONLY", True


# --- Orchestration (dry-run gate, D-05 detection, write-ahead) -----------


def upload_and_publish(
    queue: dict[str, Any],
    entry: dict[str, Any],
    credentials_factory,
    config,
    session=requests,
    queue_path: str = DEFAULT_QUEUE_PATH,
    poll_interval_seconds: float = 2.0,
) -> dict[str, Any]:
    """Orchestrates the dry-run gate -> write-ahead uploading -> gate-check
    -> init -> write-ahead publish_id -> chunked upload -> poll -> publish
    flow for one queue entry (06-RESEARCH.md Pattern 1/4, Shared Patterns).

    If config.tiktok_enabled is False, this is the VERY FIRST thing checked
    - before credentials_factory is ever called - so dry-run makes NO
    credential load and NO network call (PUB-03 parity). Returns
    {"dry_run": True} and leaves entry["status"] untouched.

    If enabled: sets entry["status"]=UPLOADING and persists (write-ahead #1,
    before creator_info/query or init_direct_post); checks the D-05 gate;
    builds the video/init body from the actual file size; calls
    init_direct_post and immediately persists entry["publish_id"]
    (write-ahead #2, Pitfall 5's specific point - persisted before the
    chunk PUT loop starts, so a crash mid-upload leaves a durable trace);
    uploads the chunks; polls status/fetch until a terminal state.

    On PUBLISH_COMPLETE: status=PUBLISHED, persists, returns
    {"publish_id", "is_still_gated"}. On FAILED: raises RuntimeError with
    the fail_reason - entry status stays UPLOADING for the next
    reconcile_uploading pass to resolve.
    """
    if not config.tiktok_enabled:
        return {"dry_run": True}

    access_token = credentials_factory()

    entry["status"] = UPLOADING
    entry["updated_at"] = datetime.now(timezone.utc).isoformat()
    save_queue(queue, queue_path)

    privacy_level, is_still_gated = check_tiktok_publish_gate(access_token, session)

    video_size = os.path.getsize(entry["video_path"])
    chunk_size = CHUNK_SIZE_DEFAULT
    total_chunk_count = max(1, math.ceil(video_size / chunk_size))

    body = build_direct_post_body(
        title=entry["caption"],
        privacy_level=privacy_level,
        video_size=video_size,
        chunk_size=chunk_size,
        total_chunk_count=total_chunk_count,
    )
    data = init_direct_post(access_token, body, session)

    entry["publish_id"] = data["publish_id"]
    entry["updated_at"] = datetime.now(timezone.utc).isoformat()
    save_queue(queue, queue_path)

    upload_video_chunks(data["upload_url"], entry["video_path"], chunk_size, session)

    status_data = fetch_post_status(access_token, entry["publish_id"], session)
    while status_data["status"] not in TERMINAL_STATUSES:
        time.sleep(poll_interval_seconds)
        status_data = fetch_post_status(access_token, entry["publish_id"], session)

    if status_data["status"] == "FAILED":
        raise RuntimeError(
            f"TikTok publish failed for clip_id={entry['clip_id']!r}: "
            f"{status_data.get('fail_reason', 'unknown reason')}"
        )

    entry["status"] = PUBLISHED
    entry["video_share_url"] = status_data.get("publicaly_available_post_id")
    entry["updated_at"] = datetime.now(timezone.utc).isoformat()
    save_queue(queue, queue_path)

    return {"publish_id": entry["publish_id"], "is_still_gated": is_still_gated}


def _success_notification_text(entry: dict[str, Any]) -> str:
    return f"залил {entry['seq']} в TikTok"


def _self_only_notification_text(entry: dict[str, Any]) -> str:
    """D-05's distinct wording - never silently report success as if it
    were public when the account is still pre-audit/SELF_ONLY."""
    return (
        f"TikTok {entry['seq']}: залито, но аккаунт всё ещё SELF_ONLY "
        "(аудит Content Posting API не пройден) - видео приватное"
    )


def _error_notification_text(entry: dict[str, Any], reason: str) -> str:
    return f"[error] TikTok {entry['seq']}: {reason}"


def _upload_one(
    entry: dict[str, Any],
    queue: dict[str, Any],
    credentials_factory,
    config,
    session=requests,
) -> None:
    """Mirrors scripts/publish_queue.py::_upload_one's error-vs-success
    branching, with a third branch (success-but-still-gated, D-05) YouTube's
    module has no equivalent for - the account being SELF_ONLY must never
    be reported as a normal success.
    """
    try:
        result = upload_and_publish(
            queue, entry, credentials_factory, config,
            session=session, queue_path=config.tiktok_queue_path,
        )
    except Exception as error:
        append_notification(
            _error_notification_text(entry, str(error)), config.notifications_path
        )
        raise

    if isinstance(result, dict) and result.get("dry_run"):
        print("dry-run: skipped (tiktok_enabled disabled)")
        return

    if result.get("is_still_gated"):
        append_notification(_self_only_notification_text(entry), config.notifications_path)
        print(_self_only_notification_text(entry))
        return

    append_notification(_success_notification_text(entry), config.notifications_path)
    print(_success_notification_text(entry))


# --- Reconciliation of a stuck UPLOADING entry ---------------------------


def reconcile_uploading(
    queue: dict[str, Any], entry: dict[str, Any], credentials_factory, session=requests
) -> dict[str, Any]:
    """Resolves a manifest entry stuck in UPLOADING via status/fetch using
    the recorded publish_id - no blind re-init (T-06-04).

    - No publish_id recorded (crash before init_direct_post ever returned):
      reset to QUEUED directly, no API call - nothing was created on
      TikTok's side.
    - publish_id recorded, status/fetch errors (expired/invalid publish_id):
      reset to QUEUED, clear publish_id, so a clean retry can happen.
    - publish_id recorded, PUBLISH_COMPLETE: adopt - status=PUBLISHED.
    - publish_id recorded, FAILED: reset to QUEUED, clear publish_id.
    - publish_id recorded, still PROCESSING_UPLOAD/PROCESSING_DOWNLOAD:
      leave untouched - legitimately still in flight.
    """
    if not entry.get("publish_id"):
        entry["status"] = QUEUED
        entry["updated_at"] = datetime.now(timezone.utc).isoformat()
        return entry

    access_token = credentials_factory()
    try:
        status_data = fetch_post_status(access_token, entry["publish_id"], session)
    except Exception:
        entry["status"] = QUEUED
        entry["publish_id"] = None
        entry["updated_at"] = datetime.now(timezone.utc).isoformat()
        return entry

    status = status_data.get("status")
    if status == "PUBLISH_COMPLETE":
        entry["status"] = PUBLISHED
        entry["video_share_url"] = status_data.get("publicaly_available_post_id")
        entry["updated_at"] = datetime.now(timezone.utc).isoformat()
    elif status == "FAILED":
        entry["status"] = QUEUED
        entry["publish_id"] = None
        entry["updated_at"] = datetime.now(timezone.utc).isoformat()
    # else: still in-flight (PROCESSING_UPLOAD/PROCESSING_DOWNLOAD) - leave
    # untouched, this is legitimately not done yet.
    return entry


def reconcile_all_uploading(queue: dict[str, Any], credentials_factory, session=requests) -> None:
    """Reconciles every UPLOADING entry before any new selection happens -
    wired as the mandatory first step before select_next_due is ever called
    (mirrors scripts/publish_queue.py::reconcile_all_uploading).
    """
    for entry in queue["entries"]:
        if entry["status"] == UPLOADING:
            reconcile_uploading(queue, entry, credentials_factory, session)
