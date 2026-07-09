# Phase 6: TikTok & Instagram Auto-Publish - Pattern Map

**Mapped:** 2026-07-10
**Files analyzed:** 6 (2 new modules, 1 extended module, 2 new test files, 1 extended requirements file)
**Analogs found:** 6 / 6

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|--------------------|------|-----------|-----------------|---------------|
| `scripts/tiktok_publish.py` (new) | service (queue/upload/kill orchestration, own manifest) | CRUD (queue) + request-response (chunked HTTP upload) | `scripts/publish_queue.py` (whole file) | role-match (same concern, new platform + new HTTP layer) |
| `scripts/instagram_publish.py` (new) | service (queue/upload/kill orchestration, own manifest) | CRUD (queue) + request-response (resumable HTTP upload) | `scripts/publish_queue.py` (whole file) | role-match |
| `scripts/config.py::PublishConfig` (extended) | config (dataclass) | CRUD (add fields) | itself, existing `PublishConfig` (lines 189-200) | exact (same file, additive fields) |
| `tests/test_tiktok_publish.py` (new) | test | unit (hand-written fake HTTP layer) | `tests/test_youtube_analytics.py` (`FakeVideosService`-style) + `tests/test_publish_queue.py` (`FakePublishConfig`/`FakeVideosInsertService` house style) | role-match |
| `tests/test_instagram_publish.py` (new) | test | unit (hand-written fake HTTP layer) | same as above | role-match |
| `requirements.txt` (extended) | config | — | itself, existing optional-dependency comment style | exact |

## Pattern Assignments

### `scripts/tiktok_publish.py` (new module — service, CRUD+request-response)

**Analog:** `scripts/publish_queue.py` (whole file) — mirror its shape function-for-function, applied to a TikTok-only manifest (`work/_publish/tiktok_queue.json`) per RESEARCH.md's "own separate queue manifest" recommendation (structural isolation for Success Criterion 3).

**Module docstring + import-safety pattern** (mirror `scripts/publish_queue.py` lines 1-18):
```python
from __future__ import annotations

"""Local TikTok publish-queue + upload/kill layer.

Tracks finished shorts through their own manifest (work/_publish/
tiktok_queue.json - kept separate from YouTube's queue.json so a TikTok
audit delay or bug can never touch the already-live YouTube pipeline,
06-RESEARCH.md Standard Stack). Mirrors scripts/publish_queue.py's
enqueue/select_next_due/pause/kill state machine exactly; the only new
logic is the TikTok-specific HTTP calls (video/init, chunked PUT,
status/fetch, creator_info/query) and the D-05 SELF_ONLY gating check.
Stays import-safe with the standard library only until a live call is
actually made - `requests` is imported at module top level (unlike
google-api-python-client's deferred-import pattern) since it is a
lightweight, always-installed dependency, not an optional extra.
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
```

**Status enum + queue load/save — copy verbatim, only the path constant changes** (`scripts/publish_queue.py` lines 20-73):
```python
QUEUED = "queued"
UPLOADING = "uploading"
PUBLISHED = "published"
KILLED = "killed"
PAUSED = "paused"

VALID_STATUSES = frozenset({QUEUED, UPLOADING, PUBLISHED, KILLED, PAUSED})
DEFAULT_QUEUE_PATH = "work/_publish/tiktok_queue.json"
DEFAULT_NOTIFICATIONS_PATH = "work/_publish/notifications.log"  # SHARED, D-06

# load_queue / save_queue: copy scripts/publish_queue.py lines 52-73 verbatim,
# only DEFAULT_QUEUE_PATH differs. No `SCHEDULED` status exists here (Pitfall
# 4 - neither platform supports a publishAt-style native schedule; QUEUED ->
# UPLOADING -> PUBLISHED is the whole lifecycle, no SCHEDULED intermediate).
```

**Enqueue pattern — copy shape, drop schedule-specific fields** (mirror `enqueue`, lines 76-117): same idempotent-on-`clip_id`, sequential-`seq` shape; `entry` drops `publish_at` (no native scheduling exists for TikTok per Pitfall 4) and adds nothing else — title/caption still taken verbatim from already-rendered metadata (Don't Hand-Roll table: reuse `scripts/metadata.py` output, never regenerate).

**OAuth credential loader — `load_credentials`-shaped, hand-rolled per RESEARCH.md Pattern 3** (signature contract copied from `scripts/youtube_analytics.py::load_credentials` lines 30-55, body reimplemented with `requests` since TikTok's OAuth isn't Google's):
```python
TIKTOK_TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"


def load_credentials(client_key_path: str, token_path: str) -> str:
    """Loads a cached TikTok access token, silently refreshing via
    grant_type=refresh_token when expired. Raises FileNotFoundError if no
    cached token exists yet - first-time consent is a manual, one-time
    interactive step (browser authorize URL), matching
    youtube_analytics.py::load_credentials's "only interactive on the very
    first run" contract (RESEARCH.md Pattern 3)."""
    token_file = Path(token_path)
    if not token_file.exists():
        raise FileNotFoundError(
            f"{token_path} not found - run the one-time interactive TikTok "
            "OAuth consent flow first (see docs/publish-queue.md setup steps)"
        )
    token_data = json.loads(token_file.read_text(encoding="utf-8"))
    if time.time() < token_data["expires_at"]:
        return token_data["access_token"]

    client = json.loads(Path(client_key_path).read_text(encoding="utf-8"))
    response = requests.post(
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
    token_file.write_text(json.dumps(refreshed, ensure_ascii=False, indent=2), encoding="utf-8")
    return refreshed["access_token"]
```
(06-RESEARCH.md Pattern 3, full source cited there — copy verbatim, do not re-derive.)

**Chunked-upload + status/fetch + creator_info/query HTTP calls** — copy verbatim from 06-RESEARCH.md Pattern 1 (`init_direct_post`, `upload_video_chunks`, `fetch_post_status`) and Pattern 4 (`check_tiktok_publish_gate`). These are the only genuinely new HTTP-layer functions; everything else in this module is queue-lifecycle reuse.

**Dry-run gate — copy `upload_and_schedule`'s ordering exactly** (`scripts/publish_queue.py` lines 211-287): `if not config.tiktok_enabled: return {"dry_run": True}` MUST be the first line, before any credential load or network call (PUB-03/T-03-05 precedent). Write-ahead: persist `UPLOADING` to `tiktok_queue.json` before `init_direct_post` is called (same crash-safety rationale as lines 257-263).

**D-05 SELF_ONLY notification** — call `check_tiktok_publish_gate` immediately before `init_direct_post`; if `is_still_gated` is `True` and the entry expected a real (non-test) publish, call `append_notification` (reused verbatim, see Shared Patterns) with a distinct D-05-style line, then proceed to post with `privacy_level="SELF_ONLY"` rather than failing the item — this mirrors `_upload_one`'s error-vs-success notification branching (`scripts/publish_queue.py` lines 570-592) but adds a third branch (success-but-still-gated) that YouTube's module has no equivalent for.

**Pause/kill — copy `_NOT_YET_UPLOADED_STATUSES`/`pause_item`/`resume_item`/`select_next_due` verbatim** (`scripts/publish_queue.py` lines 290-332). **`kill_item` diverges from the YouTube analog per Pitfall 4**: there is no `cancel_scheduled_release`/`verify_killed` equivalent — once an entry has reached `UPLOADING` with a `publish_id` recorded, kill can only flip the local status; it cannot revert an already-published TikTok post. Document this explicitly in the function docstring rather than silently no-op:
```python
def kill_item(queue: dict[str, Any], clip_id: str) -> dict[str, Any]:
    """Kills a queue entry. Unlike YouTube's kill_item, there is NO API call
    that can revert an already-PUBLISHED TikTok post (Pitfall 4 - Direct
    Post has no publishAt-style schedule to cancel). For QUEUED/PAUSED/
    UPLOADING-without-publish_id entries this is local-only (matches
    publish_queue.py). For an entry that already reached PUBLISHED, this
    raises RuntimeError rather than silently marking KILLED - it is NOT
    possible to un-publish, and pretending otherwise would be misleading.
    """
```

**CLI wrapper — copy `build_argument_parser`/`run_command`/`main` shape** (`scripts/publish_queue.py` lines 595-720), swapping `--client-secret`/`--token` defaults to `tiktok_client_key.json`/`tiktok_token.json` and `service_factory` for a plain `access_token` string (no `googleapiclient.discovery.build` step needed — TikTok calls are raw `requests`).

---

### `scripts/instagram_publish.py` (new module — service, CRUD+request-response)

**Analog:** `scripts/publish_queue.py` (whole file), same reuse contract as `tiktok_publish.py` above — manifest at `work/_publish/instagram_queue.json`.

**Everything from the `tiktok_publish.py` section above applies identically** (module docstring shape, status enum, `load_queue`/`save_queue`, `enqueue`, dry-run-gate-first ordering, write-ahead persistence, pause/kill with the same Pitfall-4 "cannot un-publish" caveat, CLI wrapper shape) — only the platform-specific pieces below differ.

**OAuth credential loader** — same `load_credentials`-shaped contract (RESEARCH.md Pattern 3), refresh call swapped for Instagram's:
```python
def load_credentials(client_secret_path: str, token_path: str) -> str:
    """Same contract as tiktok_publish.py::load_credentials. Instagram
    long-lived tokens are valid 60 days, refreshable any time between 24h
    and expiry via GET graph.instagram.com/refresh_access_token -
    refresh-if-older-than-N-days (e.g. weekly) keeps it perpetually fresh
    with zero user interaction after the one-time initial consent
    (RESEARCH.md Pattern 3)."""
    # same cache-check/read/write shape as tiktok_publish.py; refresh call:
    # requests.get("https://graph.instagram.com/refresh_access_token",
    #     params={"grant_type": "ig_refresh_token", "access_token": token})
```

**Resumable-upload HTTP calls** — copy verbatim from 06-RESEARCH.md Pattern 2 (`create_resumable_container`, `upload_local_video`, `poll_container_status`, `publish_container`). Note the one host divergence documented there: `upload_local_video` targets `rupload.facebook.com`, not `graph.facebook.com` — do not "normalize" this to match the other three calls.

**No D-05-equivalent gating check** — Instagram has no analog to TikTok's `creator_info/query`/SELF_ONLY trap (per CONTEXT.md D-05, scoped to TikTok only); `instagram_publish.py` should NOT invent one. If Open Question #1 (Standard vs Advanced Access) resolves such that App Review is genuinely required, that gate is a config-level `instagram_enabled` flag check only — no post-hoc visibility detection exists to build (RESEARCH.md Common Pitfalls, Manual-Only Verifications row 3).

**Publish-only-after-FINISHED sequencing** — the orchestration function (`instagram_publish.py`'s equivalent of `upload_and_schedule`) must poll `poll_container_status` in a loop until `status_code == "FINISHED"` before ever calling `publish_container` — mirrors `upload_and_schedule`'s `while response is None: next_chunk()` polling shape (`scripts/publish_queue.py` lines 278-279) but polls a GET status endpoint instead of driving a chunked upload object.

---

### `scripts/config.py::PublishConfig` (extended — config, CRUD)

**Analog:** itself (existing dataclass, lines 189-200) — additive only, per RESEARCH.md's concrete "PublishConfig Extension Proposal" (do not create sibling dataclasses).

**Extension pattern (copy exactly)**:
```python
@dataclasses.dataclass
class PublishConfig:
    # --- existing (YouTube, unchanged) ---
    enabled: bool = False
    daily_slots_utc: list[str] = dataclasses.field(
        default_factory=lambda: ["09:00", "15:00", "20:00"]
    )
    queue_path: str = "work/_publish/queue.json"
    notifications_path: str = "work/_publish/notifications.log"
    client_secret_path: str = "client_secret.json"
    upload_token_path: str = "upload_token.json"

    # --- new: TikTok (PUB-06) ---
    tiktok_enabled: bool = False
    tiktok_queue_path: str = "work/_publish/tiktok_queue.json"
    tiktok_client_key_path: str = "tiktok_client_key.json"
    tiktok_token_path: str = "tiktok_token.json"

    # --- new: Instagram (PUB-07) ---
    instagram_enabled: bool = False
    instagram_queue_path: str = "work/_publish/instagram_queue.json"
    instagram_client_secret_path: str = "instagram_client_secret.json"
    instagram_token_path: str = "instagram_token.json"
```
Every new field defaults to `False`/a fixed path string, matching the existing `enabled: bool = False` dry-run-default discipline (PUB-03) and the `MonetizationConfig`/`DiarizationConfig` opt-in-bool-per-feature convention. No new `_validate()` rule is needed (see RESEARCH.md rationale) — bool/path fields need no extra validation, same precedent as `MonetizationConfig`.

---

### `tests/test_tiktok_publish.py` / `tests/test_instagram_publish.py` (new — unit tests)

**Analog:** `tests/test_youtube_analytics.py`'s `FakeVideosService`-style hand-written fakes (lines 46-61) + `tests/test_publish_queue.py`'s `FakePublishConfig`/`FakeVideosInsertService`/`FakeVideosUpdateService` house style (lines 219-263, 409-424). **Per 06-VALIDATION.md Wave 0 requirement and this project's explicit test-layer convention: use hand-written fakes, NOT `unittest.mock`/`pytest-mock`.**

**Fake HTTP-layer pattern to copy** — since `tiktok_publish.py`/`instagram_publish.py` call `requests.post`/`requests.put`/`requests.get` directly (not an SDK object like `service.videos().insert()`), the fake needs a level below `FakeVideosService`'s "fake resource object" shape: a **fake `requests`-module-shaped session** injected via a parameter, following the same "records calls, returns a pre-configured response" contract:
```python
class FakeResponse:
    """Stands in for requests.Response - only the methods/attrs this
    project's HTTP-layer code actually calls, same minimalism as
    FakeVideosService only exposing .execute()."""

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
    assert on Content-Range headers, request bodies, etc. Returns responses
    from a pre-loaded queue, house style per tests/test_youtube_analytics.py's
    FakeVideosService (list of responses, .pop(0) per call) and
    tests/test_publish_queue.py's FakeVideosInsertService (records
    insert_calls for later assertion)."""

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
```
Each HTTP-calling function in `tiktok_publish.py`/`instagram_publish.py` should accept an injectable `session=requests` parameter (mirrors the project's `runner=subprocess.run` injectable pattern, CLAUDE.md Key Abstractions) so tests pass `FakeSession(...)` instead of monkeypatching the `requests` module globally.

**`FakePublishConfig`-equivalent** — copy `tests/test_publish_queue.py`'s `FakePublishConfig` shape (lines 219-229) verbatim, renamed `FakeTikTokPublishConfig`/`FakeInstagramPublishConfig`, exposing only the fields each module's orchestration function actually reads (`tiktok_enabled`, `tiktok_queue_path`, etc.).

**Dry-run test** — mirror `tests/test_publish_queue.py`'s existing dry-run test shape exactly: assert `session.calls == []` (no HTTP call at all) when `tiktok_enabled=False`/`instagram_enabled=False`, matching PUB-03/T-03-05's "no credential load and no network call" contract already proven for YouTube.

**Isolation test (06-VALIDATION.md row 06-03-01)** — new pattern, no direct prior analog: construct one `tiktok_queue.json` and one `instagram_queue.json` (and optionally `queue.json`) in a tmp dir, kill/pause an entry in one, assert the other two files are byte-for-byte unchanged (`Path(...).read_text()` equality before/after) — proves structural isolation, not just a status-field convention (RESEARCH.md Standard Stack rationale).

---

## Shared Patterns

### Dry-run-gate-first ordering (PUB-03)
**Source:** `scripts/publish_queue.py::upload_and_schedule` lines 246-247 (`if not config.enabled: return {"dry_run": True}` as the literal first statement, before any deferred import or credential call).
**Apply to:** both new modules' orchestration functions — `tiktok_enabled`/`instagram_enabled` checked first, unconditionally, before `load_credentials` or any `requests` call.

### Write-ahead manifest persistence before any network call
**Source:** `scripts/publish_queue.py::upload_and_schedule` lines 257-263 (`entry["status"] = UPLOADING; ...; save_queue(...)` persisted BEFORE the `.insert()`/chunk-upload call).
**Apply to:** both new modules — persist `UPLOADING` (and, for TikTok, the `publish_id` as soon as `video/init` returns it; for Instagram, the `container_id` as soon as `create_resumable_container` returns it) before starting the actual byte-upload loop, so a crash mid-upload is reconcilable rather than silently duplicated on retry (RESEARCH.md Pitfall 5 / Don't Hand-Roll table).

### `load_credentials`-shaped OAuth helper (pattern reuse, not library reuse)
**Source:** `scripts/youtube_analytics.py::load_credentials` (lines 30-55) — signature/behavior contract (cache → refresh-if-expired → raise-if-never-consented), reimplemented per-platform with `requests` instead of `google-auth-oauthlib`.
**Apply to:** `tiktok_publish.py::load_credentials`, `instagram_publish.py::load_credentials` — both hand-rolled per RESEARCH.md Pattern 3, exact code given there.

### Shared append-only notification log (D-06)
**Source:** `scripts/publish_queue.py::append_notification`/`read_unread_notifications` (lines 494-537) — reused **verbatim, unchanged, same file path** (`work/_publish/notifications.log`), not reimplemented per platform.
**Apply to:** both new modules import and call `append_notification` from `scripts.publish_queue` directly (the one sanctioned cross-script import for this phase — CLAUDE.md's "no script imports another script's logic" constraint is about not folding *domain* logic back and forth; a shared, already-generic utility function is the documented exception this project already established for `scripts/render.py` reusing nothing and `scripts/compilation.py` importing `scripts.candidates.Candidate` read-only in Phase 5's precedent).

### Pause/kill local-only semantics for not-yet-uploaded items
**Source:** `scripts/publish_queue.py::_NOT_YET_UPLOADED_STATUSES`/`pause_item`/`resume_item` (lines 290-332).
**Apply to:** both new modules, copied verbatim — the only divergence is `kill_item`'s post-publish branch (see Pattern Assignments above, Pitfall 4: no un-publish call exists for either platform, unlike YouTube's `cancel_scheduled_release`).

### `runner`/`session`-injectable HTTP layer for testability
**Source:** CLAUDE.md Key Abstractions — `runner=subprocess.run` injectable default parameter pattern (`scripts/render.py::probe_video`, `scripts/silence.py::measure_loudness`).
**Apply to:** every new HTTP-calling function in both modules should accept a `session=requests` parameter, exactly analogous in spirit — tests inject `FakeSession`, only a (nonexistent, per 06-VALIDATION.md "no real-network integration tests planned") integration test would use the real `requests` module.

### Custom exception subclassing a builtin
**Source:** `class ConfigError(ValueError): pass` (`scripts/config.py`), `class RenderError(ValueError): pass` (`scripts/render.py:43`).
**Apply to:** if either new module needs a domain-specific error type (e.g. a SELF_ONLY-gated-post-when-not-expected condition that should hard-fail rather than notify), follow the same `class TikTokPublishError(ValueError): pass` shape — not a bare `Exception` subclass.

## No Analog Found

None — every file in scope has a strong same-repo analog. `scripts/publish_queue.py` is the load-bearing analog for both new modules (whole-file reuse of shape, per CONTEXT.md D-02's explicit instruction to mirror it); the two genuinely new pieces of logic (TikTok's chunked-PUT + `creator_info/query` gating, Instagram's resumable-upload host-switch) are fully specified with working code in 06-RESEARCH.md Patterns 1/2/4, not novel unverified code this pattern map needed to derive independently.

## Metadata

**Analog search scope:** `scripts/` (`publish_queue.py`, `youtube_analytics.py`, `config.py` full reads), `tests/` (`test_publish_queue.py`, `test_youtube_analytics.py` targeted reads for fake-HTTP-layer convention)
**Files scanned:** `scripts/publish_queue.py` (full, 721 lines), `scripts/youtube_analytics.py` (targeted: `load_credentials` lines 30-63), `scripts/config.py` (targeted: `PublishConfig` lines 189-203), `tests/test_youtube_analytics.py` (targeted: `FakeVideosService`/`FakeChannelsService`/`FakeAnalyticsService` lines 13-77), `tests/test_publish_queue.py` (targeted: `FakePublishConfig`/`FakeVideosInsertService`/`FakeVideosUpdateService`/`FakeCliPublishConfig` lines 219-263, 409-424, 899-914), `06-RESEARCH.md` (full Patterns 1-4, PublishConfig Extension Proposal, Common Pitfalls sections)
**Pattern extraction date:** 2026-07-10
