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
