from __future__ import annotations

"""Local Instagram publish-queue + upload layer.

Tracks finished shorts through their own manifest (work/_publish/
instagram_queue.json - kept separate from YouTube's queue.json and
TikTok's tiktok_queue.json so an Instagram permission/access-tier issue or
bug can never touch either already-live pipeline, 06-RESEARCH.md Standard
Stack). Mirrors scripts/publish_queue.py's enqueue/select_next_due/pause/
resume state machine exactly; the only new logic is the Instagram-specific
HTTP calls (resumable-upload media container create, local-file byte
upload to rupload.facebook.com, status polling, media_publish) and the
one-time interactive OAuth consent flow.

Critically, unlike scripts/tiktok_publish.py, this module implements the
user's explicit decision on 06-RESEARCH.md's Open Question 1 (Standard vs
Advanced Access): it does NOT implement a TikTok-style pre-publish gating
check (no creator_info/query-equivalent function anywhere in this module).
It attempts the real publish directly via Standard Access, and only fails
closed with a distinct, actionable InstagramAccessError if Meta's API
itself reports a permission/access-tier problem on a live call - never a
silent skip, never an opaque crash.

This module covers the queue lifecycle, OAuth credential handling, the
Graph API resumable-upload HTTP layer, and the orchestration/reconciliation
functions - everything needed to actually publish one queued clip to
Instagram Reels. It deliberately does NOT include pause/kill's CLI wrapper
or kill_item itself - both are Plan 06-06's job (see must_haves).

`requests` is imported at module top level (unlike
google-api-python-client's deferred-import pattern) since it is a
lightweight, always-installed dependency, not an optional extra.
"""

import http.server
import json
import random
import re
import string
import time
import urllib.parse
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from scripts.publish_queue import append_notification

# Status enum - the full lifecycle an Instagram queue entry can move
# through. No SCHEDULED status: Instagram's media_publish is immediate once
# invoked, no publishAt-style native schedule (06-RESEARCH.md Pitfall 4).
# QUEUED -> UPLOADING -> PUBLISHED is the whole lifecycle.
QUEUED = "queued"
UPLOADING = "uploading"
PUBLISHED = "published"
KILLED = "killed"
PAUSED = "paused"

VALID_STATUSES = frozenset({QUEUED, UPLOADING, PUBLISHED, KILLED, PAUSED})

# Queue manifest + notification-log locations (paths only - no file is
# created by importing this module).
DEFAULT_QUEUE_PATH = "work/_publish/instagram_queue.json"
DEFAULT_NOTIFICATIONS_PATH = "work/_publish/notifications.log"  # SHARED, D-06

# V4 scope minimization - never request instagram_business_manage_messages/
# instagram_business_manage_comments, which this phase has no use for.
INSTAGRAM_SCOPES = ["instagram_business_basic", "instagram_business_content_publish"]

GRAPH_API_VERSION = "v23.0"

# --- OAuth endpoints --------------------------------------------------------
INSTAGRAM_AUTHORIZE_URL = "https://www.instagram.com/oauth/authorize"
# Short-lived token exchange (authorization_code grant).
INSTAGRAM_TOKEN_EXCHANGE_URL = "https://api.instagram.com/oauth/access_token"
# Short-lived -> 60-day long-lived token exchange (ig_exchange_token grant).
INSTAGRAM_LONG_LIVED_EXCHANGE_URL = "https://graph.instagram.com/access_token"
# Long-lived token refresh (ig_refresh_token grant).
INSTAGRAM_REFRESH_URL = "https://graph.instagram.com/refresh_access_token"

# A long-lived token must be at least 24h old before Instagram allows a
# refresh call against it; refreshing any time after that (well inside the
# 60-day validity window) keeps it perpetually fresh with zero user
# interaction after the one-time initial consent (06-RESEARCH.md Pattern 3).
REFRESH_AFTER_SECONDS = 24 * 60 * 60


class InstagramAccessError(ValueError):
    """Raised when Meta's API itself reports a permission/access-tier
    rejection on a live call - see _check_meta_permission_error. This is
    the ONLY mechanism this module uses to detect an access-tier problem;
    there is deliberately no pre-publish gating/permission-check call
    anywhere in this module (unlike scripts/tiktok_publish.py's
    creator_info/query), per the user's explicit build-both-scenarios
    decision (06-CONTEXT.md Open Question 1 / 06-RESEARCH.md Assumption
    A2): attempt Standard Access directly, fail closed only if Meta itself
    rejects it.
    """


# Instagram's own field limits (V5 input validation, 06-RESEARCH Security
# Domain) - a violation fails this one queue item, not the whole run.
MAX_CAPTION_LENGTH = 2200
MAX_HASHTAGS = 30
MAX_MENTIONS = 20

_HASHTAG_PATTERN = re.compile(r"#\w+")
_MENTION_PATTERN = re.compile(r"@\w+")

# poll_container_status's terminal status_code values (06-RESEARCH.md
# Pattern 2). Only FINISHED is eligible for publish_container; ERROR/EXPIRED
# are terminal-but-failed and reset the entry on reconciliation.
TERMINAL_CONTAINER_STATUSES = frozenset({"FINISHED", "ERROR", "EXPIRED"})

# Best-effort heuristic substrings (case-insensitive) that flag a Meta error
# response as permission/access-tier related. This is documented as
# best-effort since this project has no verified real 403 response to test
# against yet (06-RESEARCH.md's own "no live API call made this session"
# caveat) - should be verified against a real Meta error response once
# credentials exist (STATE.md Blockers/Concerns should track this the same
# way Phase 3 tracked its kill-path verification).
_PERMISSION_ERROR_SUBSTRINGS = (
    "permission",
    "access level",
    "access_level",
    "advanced access",
    "not authorized",
    "unauthorized",
    "does not have permission",
    "requires app review",
    "app review",
)


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
    (scripts/metadata.py's platforms_data["instagram"]["caption"] field) -
    this function never regenerates metadata. Unlike YouTube's queue entry
    there is no description/tags/publish_at field: Instagram's media_publish
    is immediate once invoked, no native schedule (06-RESEARCH.md
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
        "container_id": None,
        "media_id": None,
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


def load_credentials(client_secret_path: str, token_path: str, session=requests) -> str:
    """Loads a cached Instagram long-lived access token, silently
    refreshing via grant_type=ig_refresh_token once the cached token is
    older than REFRESH_AFTER_SECONDS (24h - Instagram's own minimum age
    before a refresh call is accepted; refreshing any time after that,
    well inside the 60-day validity window, keeps it perpetually fresh).
    Raises FileNotFoundError with an actionable message if token_path does
    not exist yet - first-time consent is a manual, one-time interactive
    step (run_instagram_oauth_consent), matching
    youtube_analytics.py::load_credentials's "only interactive on the very
    first run" contract (06-RESEARCH.md Pattern 3).
    """
    token_file = Path(token_path)
    if not token_file.exists():
        raise FileNotFoundError(
            f"{token_path} not found - run the one-time interactive Instagram "
            "OAuth consent flow first (scripts.instagram_publish.run_instagram_oauth_consent)"
        )
    token_data = json.loads(token_file.read_text(encoding="utf-8"))

    age_seconds = time.time() - token_data["obtained_at"]
    if age_seconds < REFRESH_AFTER_SECONDS:
        return token_data["access_token"]

    response = session.get(
        INSTAGRAM_REFRESH_URL,
        params={
            "grant_type": "ig_refresh_token",
            "access_token": token_data["access_token"],
        },
    )
    response.raise_for_status()
    refreshed = response.json()

    now = time.time()
    token_data["access_token"] = refreshed["access_token"]
    token_data["obtained_at"] = now
    token_data["expires_at"] = now + refreshed["expires_in"]
    token_file.write_text(
        json.dumps(token_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return token_data["access_token"]


def _build_redirect_server(host: str, port: int):
    """Constructs (but does not run) the one-shot local OAuth redirect
    listener, bound explicitly to `host` (the caller always passes
    "127.0.0.1", never "0.0.0.0" - T-06-05/V4 spoofing mitigation). Split
    out from _capture_oauth_redirect_code so the bind address itself is
    directly assertable in tests without needing a real HTTP round-trip.
    Own local copy (not imported from scripts.tiktok_publish) - hand-rolled
    per platform per this project's established "not a new one invented per
    platform, and not a shared library" convention.
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
                "Instagram authorization received - you can close this tab.".encode("utf-8")
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
        raise InstagramAccessError("no authorization code received on the OAuth redirect")
    return code


def run_instagram_oauth_consent(
    client_secret_path: str, token_path: str, port: int = 8766, session=requests
) -> str:
    """One-time interactive Instagram Login Business OAuth consent flow:
    builds the authorize URL, opens it via webbrowser.open, blocks on a
    local redirect-capture listener bound to 127.0.0.1 (never 0.0.0.0) for
    exactly one request, exchanges the returned code for a short-lived
    token (POST api.instagram.com/oauth/access_token), immediately
    exchanges that for a 60-day long-lived token (GET
    graph.instagram.com/access_token?grant_type=ig_exchange_token), and
    writes the token file in the shape load_credentials expects. Uses a
    DIFFERENT fixed port (8766) than tiktok_publish.py's consent helper
    (8765) so both one-time flows can be registered as distinct redirect
    URIs without collision, even though they are never run simultaneously
    in practice.
    """
    client = json.loads(Path(client_secret_path).read_text(encoding="utf-8"))
    redirect_uri = f"http://127.0.0.1:{port}/callback"
    state = "".join(random.choices(string.ascii_letters + string.digits, k=16))

    authorize_url = (
        f"{INSTAGRAM_AUTHORIZE_URL}?client_id={client['client_id']}"
        f"&redirect_uri={urllib.parse.quote(redirect_uri, safe='')}"
        "&response_type=code"
        f"&scope={','.join(INSTAGRAM_SCOPES)}"
        f"&state={state}"
    )
    webbrowser.open(authorize_url)

    code = _capture_oauth_redirect_code("127.0.0.1", port)

    short_lived_response = session.post(
        INSTAGRAM_TOKEN_EXCHANGE_URL,
        data={
            "client_id": client["client_id"],
            "client_secret": client["client_secret"],
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
            "code": code,
        },
    )
    short_lived_response.raise_for_status()
    short_lived_token = short_lived_response.json()["access_token"]

    long_lived_response = session.get(
        INSTAGRAM_LONG_LIVED_EXCHANGE_URL,
        params={
            "grant_type": "ig_exchange_token",
            "client_secret": client["client_secret"],
            "access_token": short_lived_token,
        },
    )
    long_lived_response.raise_for_status()
    long_lived_data = long_lived_response.json()

    now = time.time()
    token_data = {
        "access_token": long_lived_data["access_token"],
        "obtained_at": now,
        "expires_at": now + long_lived_data["expires_in"],
    }
    token_file = Path(token_path)
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(
        json.dumps(token_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return token_data["access_token"]


# --- Caption validation + pure body builder -------------------------------


def validate_caption(caption: str) -> None:
    """Raises ValueError if caption exceeds Instagram's own field limits
    (V5 input validation, 06-RESEARCH Security Domain) - a violation fails
    only this queue item, not the whole run."""
    if len(caption) > MAX_CAPTION_LENGTH:
        raise ValueError(
            f"caption exceeds Instagram's {MAX_CAPTION_LENGTH}-char limit ({len(caption)} chars)"
        )
    hashtag_count = len(_HASHTAG_PATTERN.findall(caption))
    if hashtag_count > MAX_HASHTAGS:
        raise ValueError(
            f"caption has {hashtag_count} hashtags, exceeding Instagram's "
            f"{MAX_HASHTAGS}-hashtag limit"
        )
    mention_count = len(_MENTION_PATTERN.findall(caption))
    if mention_count > MAX_MENTIONS:
        raise ValueError(
            f"caption has {mention_count} mentions, exceeding Instagram's "
            f"{MAX_MENTIONS}-mention limit"
        )


def build_media_container_params(caption: str) -> dict[str, Any]:
    """Pure function - validates the caption first, then returns the exact
    media container params. No network call (mirrors
    scripts/publish_queue.py::build_insert_body's pure-body-builder-
    separate-from-network-call convention)."""
    validate_caption(caption)
    return {"media_type": "REELS", "upload_type": "resumable", "caption": caption}


# --- Fail-closed permission handling ---------------------------------------


def _check_meta_permission_error(response) -> None:
    """Inspects a non-2xx response's JSON body for Meta's standard
    {"error": {"message", "type", "code", ...}} shape. If the status code is
    403, or the error object's type/message/code look like a
    permissions/access-tier rejection (heuristic - see
    _PERMISSION_ERROR_SUBSTRINGS), raises InstagramAccessError with a
    message that (a) quotes Meta's original error message, (b) states in
    plain language that this account may need Advanced Access / Meta App
    Review, and (c) points at docs/publish-queue.md's Instagram section.

    For any other non-2xx response, calls response.raise_for_status()
    normally (propagates as a plain requests.HTTPError) - non-permission
    errors are never swallowed or reinterpreted into InstagramAccessError.
    A 2xx response is a no-op (nothing to check).
    """
    if response.status_code < 400:
        return

    try:
        body = response.json()
    except ValueError:
        body = {}

    error = body.get("error", {}) if isinstance(body, dict) else {}
    message = str(error.get("message", ""))
    error_type = str(error.get("type", ""))
    error_code = str(error.get("code", ""))
    combined = f"{message} {error_type} {error_code}".lower()

    is_permission_flavored = response.status_code == 403 or any(
        substring in combined for substring in _PERMISSION_ERROR_SUBSTRINGS
    )
    if is_permission_flavored:
        raise InstagramAccessError(
            f"Meta API rejected this request with a permission/access-tier "
            f"error: {message or 'unknown error'!r}. This Instagram Business "
            "account may need Advanced Access / Meta App Review before this "
            "app can publish to it - see docs/publish-queue.md's Instagram "
            "section for next steps."
        )

    response.raise_for_status()


# --- Graph API resumable-upload HTTP layer ---------------------------------


def create_resumable_container(
    ig_user_id: str, access_token: str, params: dict[str, Any], session=requests
) -> str:
    """POSTs params to /{ig_user_id}/media with access_token, routes any
    error response through _check_meta_permission_error before
    raise_for_status(), returns response.json()["id"]."""
    response = session.post(
        f"https://graph.facebook.com/{GRAPH_API_VERSION}/{ig_user_id}/media",
        params={**params, "access_token": access_token},
    )
    _check_meta_permission_error(response)
    response.raise_for_status()
    return response.json()["id"]


def upload_local_video(
    container_id: str, access_token: str, video_path: str, session=requests
) -> None:
    """POSTs the raw video bytes to rupload.facebook.com (NOT
    graph.facebook.com - the one host divergence, do not "normalize" it)
    with offset/file_size headers, routes errors through
    _check_meta_permission_error."""
    file_size = Path(video_path).stat().st_size
    with open(video_path, "rb") as handle:
        data = handle.read()
    response = session.post(
        f"https://rupload.facebook.com/ig-api-upload/{GRAPH_API_VERSION}/{container_id}",
        headers={
            "Authorization": f"OAuth {access_token}",
            "offset": "0",
            "file_size": str(file_size),
        },
        data=data,
    )
    _check_meta_permission_error(response)
    response.raise_for_status()


def poll_container_status(container_id: str, access_token: str, session=requests) -> str:
    """GETs /{container_id}?fields=status_code, returns
    response.json()["status_code"]."""
    response = session.get(
        f"https://graph.facebook.com/{GRAPH_API_VERSION}/{container_id}",
        params={"fields": "status_code", "access_token": access_token},
    )
    response.raise_for_status()
    return response.json()["status_code"]


def publish_container(
    ig_user_id: str, access_token: str, creation_id: str, session=requests
) -> str:
    """POSTs to /{ig_user_id}/media_publish with creation_id + access_token,
    routes errors through _check_meta_permission_error, returns
    response.json()["id"]."""
    response = session.post(
        f"https://graph.facebook.com/{GRAPH_API_VERSION}/{ig_user_id}/media_publish",
        params={"creation_id": creation_id, "access_token": access_token},
    )
    _check_meta_permission_error(response)
    response.raise_for_status()
    return response.json()["id"]


# --- Orchestration (dry-run gate, attempt-then-fail-closed, write-ahead) --


def upload_and_publish(
    queue: dict[str, Any],
    entry: dict[str, Any],
    credentials_factory,
    config,
    ig_user_id: str,
    session=requests,
    queue_path: str = DEFAULT_QUEUE_PATH,
    poll_interval_seconds: float = 2.0,
) -> dict[str, Any]:
    """Orchestrates the dry-run gate -> write-ahead uploading -> container
    create -> write-ahead container_id -> byte upload -> poll -> publish
    flow for one queue entry.

    If not config.instagram_enabled, this is the LITERAL FIRST statement -
    before load_credentials or any requests call - so dry-run makes NO
    credential load and NO network call (PUB-03 parity). Returns
    {"dry_run": True} and leaves entry["status"] untouched.

    If enabled: sets entry["status"]=UPLOADING and persists (write-ahead
    #1, before create_resumable_container). Per the user's explicit
    decision, create_resumable_container is called directly with NO prior
    gating/permission-check call, unlike TikTok's creator_info/query.
    entry["container_id"] is persisted (write-ahead #2, before
    upload_local_video's byte upload starts). Polls poll_container_status
    in a loop until status_code is terminal (FINISHED or ERROR/EXPIRED) -
    publish_container is never called before FINISHED is observed.

    On FINISHED: publish_container publishes, entry["status"]=PUBLISHED,
    entry["media_id"] set, persisted, returns {"media_id": media_id}. On
    ERROR/EXPIRED: raises RuntimeError describing the container's failed
    state, entry status stays UPLOADING for the next reconcile pass.

    Any InstagramAccessError raised by create_resumable_container/
    upload_local_video/publish_container propagates up through this
    function unchanged (it is a ValueError subclass, callers catch it same
    as any other Exception) - it is never caught/reinterpreted here.

    Deliberately does NOT read config.daily_slots_utc anywhere (06-RESEARCH
    Open Question 3): Instagram's media_publish is immediate once invoked,
    with no publishAt-equivalent to schedule against.
    """
    if not config.instagram_enabled:
        return {"dry_run": True}

    access_token = credentials_factory()

    entry["status"] = UPLOADING
    entry["updated_at"] = datetime.now(timezone.utc).isoformat()
    save_queue(queue, queue_path)

    params = build_media_container_params(entry["caption"])
    container_id = create_resumable_container(ig_user_id, access_token, params, session)

    entry["container_id"] = container_id
    entry["updated_at"] = datetime.now(timezone.utc).isoformat()
    save_queue(queue, queue_path)

    upload_local_video(container_id, access_token, entry["video_path"], session)

    status_code = poll_container_status(container_id, access_token, session)
    while status_code not in TERMINAL_CONTAINER_STATUSES:
        time.sleep(poll_interval_seconds)
        status_code = poll_container_status(container_id, access_token, session)

    if status_code != "FINISHED":
        raise RuntimeError(
            f"Instagram media container failed for clip_id={entry['clip_id']!r}: "
            f"status_code={status_code!r}"
        )

    media_id = publish_container(ig_user_id, access_token, container_id, session)
    entry["status"] = PUBLISHED
    entry["media_id"] = media_id
    entry["updated_at"] = datetime.now(timezone.utc).isoformat()
    save_queue(queue, queue_path)

    return {"media_id": media_id}


def _success_notification_text(entry: dict[str, Any]) -> str:
    return f"залил {entry['seq']} в Instagram"


def _error_notification_text(entry: dict[str, Any], reason: str) -> str:
    return f"[error] Instagram {entry['seq']}: {reason}"


def _upload_one(
    entry: dict[str, Any],
    queue: dict[str, Any],
    credentials_factory,
    config,
    ig_user_id: str,
    session=requests,
) -> None:
    """Mirrors scripts/publish_queue.py::_upload_one's error-vs-success
    branching. Wraps upload_and_publish in try/except, appends an error
    notification (using str(error), which for an InstagramAccessError
    already contains the actionable Advanced-Access-may-be-needed guidance)
    and re-raises on any Exception - this is the "fail closed with a
    clear, actionable error message, not a silent skip, not a crash"
    behavior the user explicitly required: the error is loud (notified +
    raised), never silently swallowed. On a dry-run result, prints/returns
    without notifying. On success, appends a "залил {seq} в Instagram"
    style success notification (no SELF_ONLY-equivalent branch - Instagram
    has no analog to TikTok's D-05 trap, per 06-CONTEXT.md D-05's
    TikTok-only scope).
    """
    try:
        result = upload_and_publish(
            queue, entry, credentials_factory, config, ig_user_id,
            session=session, queue_path=config.instagram_queue_path,
        )
    except Exception as error:
        append_notification(
            _error_notification_text(entry, str(error)), config.notifications_path
        )
        raise

    if isinstance(result, dict) and result.get("dry_run"):
        print("dry-run: skipped (instagram_enabled disabled)")
        return

    append_notification(_success_notification_text(entry), config.notifications_path)
    print(_success_notification_text(entry))


# --- Reconciliation of a stuck UPLOADING entry ---------------------------


def reconcile_uploading(
    queue: dict[str, Any],
    entry: dict[str, Any],
    credentials_factory,
    ig_user_id: str,
    session=requests,
) -> dict[str, Any]:
    """Resolves a manifest entry stuck in UPLOADING.

    - Already has a media_id: nothing to do (already terminal), untouched.
    - No container_id recorded (crash before create_resumable_container
      returned): reset to QUEUED directly, no API call - nothing was
      created on Instagram's side.
    - Has a container_id but no media_id: polls poll_container_status.
      FINISHED -> calls publish_container to complete the interrupted flow
      (status=PUBLISHED, save). Meta's behavior on a media_publish retry
      against an already-published creation_id is unverified against a
      live account (06-RESEARCH.md never captured this from a real call),
      so this is a best-effort completion, not a guaranteed-safe
      idempotent replay. ERROR/EXPIRED -> reset to QUEUED, clear
      container_id. Any other in-flight status -> left untouched
      (legitimately still processing).
    - A poll_container_status call error (expired/invalid container_id)
      resets to QUEUED and clears container_id so a clean retry can happen.
    """
    if entry.get("media_id"):
        return entry

    if not entry.get("container_id"):
        entry["status"] = QUEUED
        entry["updated_at"] = datetime.now(timezone.utc).isoformat()
        return entry

    access_token = credentials_factory()
    try:
        status_code = poll_container_status(entry["container_id"], access_token, session)
    except Exception:
        entry["status"] = QUEUED
        entry["container_id"] = None
        entry["updated_at"] = datetime.now(timezone.utc).isoformat()
        return entry

    if status_code == "FINISHED":
        media_id = publish_container(ig_user_id, access_token, entry["container_id"], session)
        entry["status"] = PUBLISHED
        entry["media_id"] = media_id
        entry["updated_at"] = datetime.now(timezone.utc).isoformat()
    elif status_code in ("ERROR", "EXPIRED"):
        entry["status"] = QUEUED
        entry["container_id"] = None
        entry["updated_at"] = datetime.now(timezone.utc).isoformat()
    # else: still in-flight - leave untouched, this is legitimately not
    # done yet.
    return entry


def reconcile_all_uploading(
    queue: dict[str, Any], credentials_factory, ig_user_id: str, session=requests
) -> None:
    """Reconciles every UPLOADING entry before any new selection happens -
    wired as the mandatory first step before select_next_due is ever
    called (mirrors scripts/publish_queue.py::reconcile_all_uploading).
    """
    for entry in queue["entries"]:
        if entry["status"] == UPLOADING:
            reconcile_uploading(queue, entry, credentials_factory, ig_user_id, session)
