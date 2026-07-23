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

import argparse
import json
import math
import os
import random
import string
import sys
import time
import urllib.parse
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

# Makes `python scripts/tiktok_publish.py --check` etc. runnable standalone
# (the repo root, not just scripts/, must be on sys.path for the
# scripts.publish_queue cross-script import below to resolve) - same
# workaround scripts/transitions.py/scripts/render.py already use for their
# own sibling-module imports.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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

# TikTok's Login Kit rejects any loopback (127.0.0.1) redirect_uri outright
# for a Web-platform app - it must be a real URL under a domain the app
# owner has verified in the Developer Portal. This project's own verified
# GitHub Pages page displays whatever `code` TikTok appends for the operator
# to copy/paste (run_tiktok_oauth_consent) - see docs/tiktok-app/oauth-callback.html.
DEFAULT_REDIRECT_URI = "https://zhoratolk.github.io/shorts-maker/tiktok-app/oauth-callback.html"

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
        "privacy_level_achieved": None,
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


# --- Kill (PUB-04, TikTok's Pitfall-4 divergence) --------------------------

# Statuses a kill treats as "not yet live" - no Direct Post has actually gone
# public on TikTok yet, so a kill of these is purely local: no API call, just
# flip the manifest. Same shape as publish_queue.py's
# _NOT_YET_UPLOADED_STATUSES, but here UPLOADING stays local-only even once a
# publish_id has been recorded (write-ahead #2) - a recorded publish_id only
# means an in-flight, not-yet-terminal upload exists, never that anything is
# public (06-RESEARCH.md Pitfall 4/5).
_NOT_YET_UPLOADED_STATUSES = frozenset({QUEUED, PAUSED, UPLOADING})


def kill_item(queue: dict[str, Any], clip_id: str) -> dict[str, Any]:
    """Kills a queue entry (PUB-04), diverging from publish_queue.py's
    revert-then-verify PUBLISHED branch:

    - status in QUEUED/PAUSED/UPLOADING (with or without a publish_id
      already recorded): local-only - flips status to KILLED, no API call.
      TikTok has no equivalent of YouTube's "cancel a scheduled release"
      call for an in-flight-but-not-yet-public upload.
    - status is PUBLISHED: raises RuntimeError rather than silently
      succeeding or pretending to revert it - TikTok's Content Posting API
      has no un-publish/cancel endpoint for an already-completed Direct
      Post (06-RESEARCH.md Pitfall 4). The entry's status is left untouched,
      never marked KILLED, so an operator can never be misled into thinking
      a live TikTok post was pulled down when it wasn't.

    Unlike publish_queue.py's kill_item, this function takes no
    service_factory/credentials_factory parameter at all - it never makes a
    network call in any branch.
    """
    entry = _find_entry(queue, clip_id)

    if entry["status"] in _NOT_YET_UPLOADED_STATUSES:
        entry["status"] = KILLED
        entry["updated_at"] = datetime.now(timezone.utc).isoformat()
        return entry

    if entry["status"] == PUBLISHED:
        raise RuntimeError(
            f"kill_item: clip_id={clip_id!r} is already PUBLISHED to TikTok - "
            "TikTok's Content Posting API has no un-publish/cancel endpoint for "
            "an already-completed Direct Post (06-RESEARCH.md Pitfall 4); the "
            "entry's status is left untouched, not silently marked KILLED"
        )

    # Already KILLED - idempotent no-op re-flip, no API call either way.
    entry["status"] = KILLED
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
    # WR-02: merge into token_data rather than replacing the file wholesale
    # - TikTok's refresh grant response is not guaranteed to repeat every
    # field (e.g. refresh_token) on every call, and overwriting the whole
    # file would permanently drop anything it omits (mirrors
    # instagram_publish.py::load_credentials's merge pattern).
    token_data["access_token"] = refreshed["access_token"]
    token_data["refresh_token"] = refreshed.get("refresh_token", token_data["refresh_token"])
    token_data["expires_at"] = time.time() + refreshed["expires_in"]
    token_file.write_text(
        json.dumps(token_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return token_data["access_token"]


def run_tiktok_oauth_consent(
    client_key_path: str,
    token_path: str,
    redirect_uri: str = DEFAULT_REDIRECT_URI,
    session=requests,
    code_prompt=input,
) -> str:
    """One-time interactive TikTok OAuth consent flow: builds the authorize
    URL, opens it via webbrowser.open, then asks the operator to paste the
    authorization code back (code_prompt - defaults to input()) instead of
    capturing it automatically.

    TikTok's Login Kit rejects any loopback (127.0.0.1) redirect_uri outright
    for a Web-platform app, unlike Google's loopback-exception handling - it
    must be a real URL under a domain the app owner has verified in the
    Developer Portal (confirmed live 2026-07-23; an earlier local-listener +
    self-signed-cert approach was built assuming only the http-vs-https
    scheme mattered, and TikTok's own form rejected it regardless of scheme).
    redirect_uri therefore defaults to this project's own verified GitHub
    Pages page (docs/tiktok-app/oauth-callback.html), which displays
    whatever `code` TikTok put on the URL for the operator to copy - it never
    transmits the code anywhere itself.
    """
    client = json.loads(Path(client_key_path).read_text(encoding="utf-8"))
    state = "".join(random.choices(string.ascii_letters + string.digits, k=16))

    authorize_url = (
        f"{TIKTOK_AUTHORIZE_URL}?client_key={client['client_key']}"
        f"&scope={','.join(TIKTOK_SCOPES)}"
        "&response_type=code"
        f"&redirect_uri={urllib.parse.quote(redirect_uri, safe='')}"
        f"&state={state}"
    )
    webbrowser.open(authorize_url)

    code = code_prompt("Paste the authorization code shown on the TikTok consent page: ").strip()
    if not code:
        raise TikTokPublishError("no authorization code entered")

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
    entry["privacy_level_achieved"] = privacy_level
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
    entry["video_share_url"] = _extract_share_url(status_data)
    entry["updated_at"] = datetime.now(timezone.utc).isoformat()
    save_queue(queue, queue_path)

    return {"publish_id": entry["publish_id"], "is_still_gated": is_still_gated}


def _extract_share_url(status_data: dict[str, Any]) -> str | None:
    """TikTok's status/fetch returns `publicaly_available_post_id` as a list
    of URLs (per its API, confirmed by test fixtures), not a single string -
    this takes the first element (or None) so entry["video_share_url"] is
    never a raw list under a singular-named key (WR-03)."""
    post_ids = status_data.get("publicaly_available_post_id") or []
    return post_ids[0] if post_ids else None


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
    queue: dict[str, Any],
    entry: dict[str, Any],
    credentials_factory,
    session=requests,
    notifications_path: str = DEFAULT_NOTIFICATIONS_PATH,
) -> dict[str, Any]:
    """Resolves a manifest entry stuck in UPLOADING via status/fetch using
    the recorded publish_id - no blind re-init (T-06-04).

    - No publish_id recorded (crash before init_direct_post ever returned):
      reset to QUEUED directly, no API call - nothing was created on
      TikTok's side.
    - publish_id recorded, status/fetch errors (expired/invalid publish_id):
      reset to QUEUED, clear publish_id, so a clean retry can happen.
    - publish_id recorded, PUBLISH_COMPLETE: adopt - status=PUBLISHED, and
      (CR-01) notifies using the same SELF_ONLY-vs-success branching
      upload_and_publish's primary path uses, keyed off
      entry["privacy_level_achieved"] (persisted by upload_and_publish's
      write-ahead #2, alongside publish_id) - so a crash between
      init_direct_post and the poll loop finishing can never silently
      resolve to PUBLISHED with no trace of whether the account was still
      pre-audit SELF_ONLY (D-05).
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
        entry["video_share_url"] = _extract_share_url(status_data)
        entry["updated_at"] = datetime.now(timezone.utc).isoformat()
        if entry.get("privacy_level_achieved") == "SELF_ONLY":
            append_notification(_self_only_notification_text(entry), notifications_path)
        else:
            append_notification(_success_notification_text(entry), notifications_path)
    elif status == "FAILED":
        entry["status"] = QUEUED
        entry["publish_id"] = None
        entry["updated_at"] = datetime.now(timezone.utc).isoformat()
    # else: still in-flight (PROCESSING_UPLOAD/PROCESSING_DOWNLOAD) - leave
    # untouched, this is legitimately not done yet.
    return entry


def reconcile_all_uploading(
    queue: dict[str, Any],
    credentials_factory,
    session=requests,
    notifications_path: str = DEFAULT_NOTIFICATIONS_PATH,
) -> None:
    """Reconciles every UPLOADING entry before any new selection happens -
    wired as the mandatory first step before select_next_due is ever called
    (mirrors scripts/publish_queue.py::reconcile_all_uploading).
    """
    for entry in queue["entries"]:
        if entry["status"] == UPLOADING:
            reconcile_uploading(queue, entry, credentials_factory, session, notifications_path)


# --- CLI (--check / --now / --pause / --kill / --resume / --list) --------


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Local TikTok publish-queue CLI: periodic --check, manual --now override, "
        "--pause/--kill/--resume, and --list - both --check and --now route through the "
        "same upload_and_publish path, matching publish_queue.py's exact CLI contract"
    )
    parser.add_argument("--check", action="store_true", help="Periodic check: reconcile stuck uploads, then upload+publish the single next due item (or log a dry-run skip)")
    parser.add_argument("--now", metavar="CLIP_ID", help="Force-publish one specific queued clip_id out of band, via the same upload path")
    parser.add_argument("--pause", metavar="CLIP_ID", help="Pause a not-yet-uploaded queued clip_id")
    parser.add_argument("--kill", metavar="CLIP_ID", help="Kill a clip_id (local-only if not yet PUBLISHED - TikTok has no un-publish API for an already-PUBLISHED entry, Pitfall 4)")
    parser.add_argument("--resume", metavar="CLIP_ID", help="Resume a paused clip_id back to queued")
    parser.add_argument("--list", action="store_true", help="Print the queue's seq/status/caption so numbering is visible")
    parser.add_argument("--client-key", default="tiktok_client_key.json", help="TikTok client_key/client_secret JSON path")
    parser.add_argument("--token", default="tiktok_token.json", help="Cached TikTok OAuth token JSON path")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    return parser


def run_command(args: argparse.Namespace, credentials_factory, config, session=requests) -> None:
    """Dispatches one CLI invocation. Factored out from main() so tests can
    drive it with a fake credentials_factory + a config carrying tmp-path
    queue/notifications paths, without ever touching real OAuth (main()'s
    only job is parsing args, building the real credentials_factory + config,
    and calling this) - mirrors scripts/publish_queue.py::run_command's
    dispatch shape exactly (--list, --pause, --resume, --kill, --now,
    --check, fallback usage message).

    --check and --now both call _upload_one, which calls the identical
    upload_and_publish - no second/divergent publish code path. --check
    enforces "at most one item per invocation" by construction:
    select_next_due (after reconcile_all_uploading resolves anything stuck)
    returns at most one entry, and only that one entry is ever passed to
    _upload_one per call. Reconciliation happens even in dry-run mode
    (before the tiktok_enabled check) - only the actual upload is gated.
    """
    queue_path = config.tiktok_queue_path

    if args.list:
        queue = load_queue(queue_path)
        for entry in sorted(queue["entries"], key=lambda e: e["seq"]):
            print(f"{entry['seq']}\t{entry['status']}\t{entry['caption']}")
        return

    if args.pause:
        queue = load_queue(queue_path)
        try:
            pause_item(queue, args.pause)
        except KeyError:
            print(f"error: no queue entry with clip_id={args.pause!r}", file=sys.stderr)
            raise SystemExit(2)
        save_queue(queue, queue_path)
        print(f"paused {args.pause}")
        return

    if args.resume:
        queue = load_queue(queue_path)
        try:
            resume_item(queue, args.resume)
        except KeyError:
            print(f"error: no queue entry with clip_id={args.resume!r}", file=sys.stderr)
            raise SystemExit(2)
        save_queue(queue, queue_path)
        print(f"resumed {args.resume}")
        return

    if args.kill:
        queue = load_queue(queue_path)
        try:
            # No credentials_factory arg (unlike publish_queue.py's
            # kill_item) - kill_item never makes a network call. A
            # RuntimeError from an already-PUBLISHED entry is deliberately
            # NOT caught here - let it propagate to the CLI's default
            # traceback, since that is a genuine operator error the tool
            # should surface loudly, not swallow into a clean exit code.
            kill_item(queue, args.kill)
        except KeyError:
            print(f"error: no queue entry with clip_id={args.kill!r}", file=sys.stderr)
            raise SystemExit(2)
        save_queue(queue, queue_path)
        print(f"killed {args.kill}")
        return

    if args.now:
        queue = load_queue(queue_path)
        try:
            entry = _find_entry(queue, args.now)
        except KeyError:
            print(f"error: no queue entry with clip_id={args.now!r}", file=sys.stderr)
            raise SystemExit(2)
        _upload_one(entry, queue, credentials_factory, config, session=session)
        return

    if args.check:
        queue = load_queue(queue_path)
        # Reconcile-first: any crash-mid-upload entry must be resolved
        # before a fresh item is ever selected. Happens even in dry-run
        # mode - only the actual upload is gated by tiktok_enabled.
        reconcile_all_uploading(
            queue, credentials_factory, session=session, notifications_path=config.notifications_path
        )
        save_queue(queue, queue_path)

        if not config.tiktok_enabled:
            print("dry-run: skipped (tiktok_enabled disabled)")
            return

        entry = select_next_due(queue)
        if entry is None:
            print("check: nothing due")
            return

        # --check uploads AT MOST ONE item per invocation - this is also
        # the natural quota debounce.
        _upload_one(entry, queue, credentials_factory, config, session=session)
        return

    print("no action given - use --check/--now/--pause/--kill/--resume/--list")


def main() -> None:
    parser = build_argument_parser()
    args = parser.parse_args()

    from scripts.config import load_config

    config = load_config(args.config).publish

    def credentials_factory():
        return load_credentials(args.client_key, args.token, session=requests)

    run_command(args, credentials_factory, config)


if __name__ == "__main__":
    main()
