# Phase 6: TikTok & Instagram Auto-Publish - Research

**Researched:** 2026-07-09
**Domain:** TikTok Content Posting API (Direct Post) + Instagram Graph API (Reels publishing), OAuth credential patterns for non-Google platforms, multi-platform local publish-queue extension
**Confidence:** HIGH (API mechanics, verified directly against official `developers.tiktok.com`/`developers.facebook.com` docs) / MEDIUM (audit/review timelines — no official SLA published by either platform, only secondary-source estimates) / MEDIUM (Instagram App Review applicability to a self-owned-account use case — a real open question that may loosen CONTEXT.md D-04's stated gate, flagged explicitly below)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Build timing**
- **D-01:** Build both integrations now — do not wait for audit/review approval before writing code. Same dry-run-first posture as Phase 3 (PUB-03): code ships now, real (non-private) publishing gates behind a per-platform config flag that only flips on once that platform's audit is confirmed cleared.

**API connection setup (new for this phase, beyond Phase 3's scope)**
- **D-02:** This phase includes actually setting up the real API connections for both platforms — not just the code, the credentials/app registration too — mirroring how Phase 3 set up YouTube's `client_secret.json` → OAuth consent → `upload_token.json` flow. Concretely: TikTok app registration in the TikTok Developer portal (sandbox/dev credentials, usable pre-audit for private/self-only testing) and Instagram's Meta App + Business account setup (Graph API test-mode token, usable pre-review for the same account's own private testing). Follow `scripts/youtube_analytics.py::load_credentials`'s parameterized-scopes pattern for both new platforms' credential loading, same as `scripts/publish_queue.py` already does for YouTube's `UPLOAD_SCOPE`.
- **D-03 (rationale):** The user explicitly wants the actual API hookup done alongside the code in this phase, not deferred as a "someday, once audited" afterthought — audit approval only gates *going public*, not building/wiring the integration.

**Audit/review status (factual, carried into plan as a checklist)**
- **D-04:** As of this discussion, nothing has been submitted yet for either platform — no TikTok Content Posting API access request, no Instagram Business account/Meta App Review. The plan must include an explicit runbook step for the user to actually file both applications (external, days-to-weeks lead time per STATE.md Blockers/Concerns, outside developer control) — this is not something an executor agent can do on the user's behalf (requires the user's own developer/business accounts). Until each platform's audit clears, that platform's per-platform enable flag (see D-01) stays `false`, matching `publish.enabled`'s existing default-false discipline (PUB-03).

**SELF_ONLY visibility handling (TikTok pre-audit trap)**
- **D-05:** Pre-audit TikTok posting is restricted to `SELF_ONLY` (private) — the Content Posting API returns success even when nothing actually goes public (documented trap in STATE.md Blockers/Concerns). Handle this the same way Phase 3 already surfaces auto-publish results: detect the returned visibility/privacy status after posting, and if it's still `SELF_ONLY` when the queue entry expected a real publish, post a one-line chat notification (same style as Phase 3's periodic-check notification) — no automatic retry/visibility-flip call.

### Claude's Discretion

- Exact TikTok sandbox/dev-mode credential acquisition steps (TikTok Developer Portal specifics) and exact Meta App/Graph API test-mode setup steps — research to confirm current (2026) exact flow for both. **Resolved below** (see Architecture Patterns).
- Whether TikTok/Instagram get one shared `PublishConfig`-style per-platform enabled flag pattern (e.g. `publish.tiktok_enabled` / `publish.instagram_enabled` fields) or separate dataclasses per platform — planner's call, following the existing `PublishConfig` structure in `scripts/config.py`. **Concrete recommendation given below** (see Standard Stack > PublishConfig Extension Proposal).
- Credential file naming for the two new platforms (e.g. `tiktok_token.json`, `instagram_token.json`) — follow the existing `upload_token.json` naming convention, gitignored the same way. **Concrete naming given below.**

### Deferred Ideas (OUT OF SCOPE)

None — discussion stayed within phase scope.

</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| PUB-06 | TikTok Content Posting API integration — built and shipped as its own gated sub-phase, after YouTube, since unaudited clients are restricted to private-only posting until TikTok's app audit completes | Auth flow, `FILE_UPLOAD` chunked upload, `SELF_ONLY` detection, and audit-process findings below (see Architecture Patterns > Pattern 1, Pattern 4; Common Pitfalls 1-3) |
| PUB-07 | Instagram Graph API Reels integration — requires a Business account + Meta app review; same gated-sub-phase treatment as TikTok | Auth flow, resumable-upload local-file path, and the Standard-vs-Advanced-Access finding (which may loosen the "app review required" premise for a self-owned account) below (see Architecture Patterns > Pattern 2; Open Questions #1) |

</phase_requirements>

## Summary

Both platforms' mechanics are well-documented and, importantly, **both support direct local-file chunked upload** — no persistent public file host is required, satisfying this project's "Локальность" constraint exactly the way YouTube's `MediaFileUpload(resumable=True)` already does. TikTok's Content Posting API `FILE_UPLOAD` source type accepts a local file via `PUT` chunks (5-64MB per chunk, final chunk up to 128MB) against a one-hour-valid `upload_url`. Instagram's Graph API has two paths: the "standard" container flow needs a publicly-reachable `video_url` (Meta's servers fetch it), but a **resumable upload flow** (`upload_type: resumable`, `POST` to `rupload.facebook.com`) accepts a local file path directly — this is the path this phase should use, not the public-URL path.

**The two platforms' gating stories diverge more than CONTEXT.md's framing suggests, and this is the single most important finding of this research.** TikTok's `SELF_ONLY` restriction for unaudited clients is confirmed and unavoidable — every unaudited post is forced private regardless of the requested `privacy_level`, and lifting it requires a dedicated **Content Posting API audit** (a second, separate review beyond base app approval) with no published SLA (secondary sources estimate 4-10 weeks per scope, on top of 3-14 days for the base app review). Instagram's story is different: Meta's permission model has **two access tiers** — "Advanced Access" (requires formal App Review, ~2-4 weeks, needed only when publishing to accounts you don't own) and **"Standard Access"** (no App Review required at all, applies when the app publishes only to Instagram professional accounts the developer already owns/manages and has added to their own App Dashboard as an admin/tester). Since this project publishes exclusively to the creator's own single Instagram Business account, **Instagram may not need to wait on any Meta review at all** — it may be usable for real (non-test-only) publishing as soon as the Business account is added to the Meta App Dashboard in Development Mode. This directly affects D-04's premise that "both platforms need an audit filed" and is flagged as an explicit Open Question for the planner/user to confirm before committing to a review-gated `instagram_enabled` flag design (see Open Questions #1) — CONTEXT.md's locked decisions are not overridden here, but the underlying factual assumption they were built on deserves the user's explicit reconfirmation.

**Credential pattern reuse is a "reuse the shape, not the library" situation.** `youtube_analytics.py::load_credentials` is built entirely on `google-auth-oauthlib`/`google.oauth2.credentials` — Google-specific packages that have no bearing on TikTok's or Meta's own OAuth 2.0 implementations. What genuinely transfers is the *function shape* Phase 3 already established: `load_credentials(client_secret_path, token_path, scopes) -> credentials`, caching to a token file, refreshing silently when possible, falling back to an interactive consent flow only when necessary. This phase should hand-roll two new, small credential-loader functions (`scripts/tiktok_publish.py::load_credentials`, `scripts/instagram_publish.py::load_credentials`) using the already-installed `requests` library, following that exact signature/behavior contract — not a new one invented per platform, and not a third-party OAuth SDK (neither platform ships an official Python SDK; unofficial PyPI packages exist but are not vetted the way `google-api-python-client` is — see Package Legitimacy Audit).

**Primary recommendation:** Two new sibling modules (`scripts/tiktok_publish.py`, `scripts/instagram_publish.py`), each with its own gitignored credential files, its own `PublishConfig`-extension fields (`tiktok_enabled`/`instagram_enabled`), and — critically for Success Criterion 3's isolation requirement — its **own separate queue manifest file** (`work/_publish/tiktok_queue.json`, `work/_publish/instagram_queue.json`), rather than folding all three platforms into the single existing `work/_publish/queue.json`. Each module mirrors `publish_queue.py`'s function shapes (`enqueue`/`upload_and_schedule`-equivalent/`pause_item`/`kill_item`/`select_next_due`) applied to its own manifest, so a TikTok audit delay, an Instagram token expiry, or a bug in either new module cannot touch YouTube's already-working, already-live queue at all — true structural isolation, not just a status-field convention.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Queue management (per-platform numbering, status, idempotency manifest) | Local script / filesystem, per-platform manifest file | — | Same filesystem-as-message-bus pattern as Phase 3; separate files per platform is the mechanism that delivers Success Criterion 3's isolation guarantee, not just a status convention |
| Periodic trigger (every ~3h check) | OS (Windows Task Scheduler, existing `shorts-maker-publish` task extended) | Claude Code session (manual override only) | Reuses Phase 3's D-06 trigger mechanism unchanged — no new scheduling infrastructure needed, `--check` on each new module's CLI can be added to the same or a sibling scheduled task |
| Upload + publish (TikTok `video/init`+chunked PUT+`status/fetch`; Instagram `media` container + resumable upload + `media_publish`) | Platform API (external) | Local Python script | API call itself is each platform's own responsibility; script only constructs and sends requests, matching YouTube's split |
| OAuth token acquisition/refresh (TikTok `/v2/oauth/token/`; Instagram `/oauth/access_token` + `graph.instagram.com/refresh_access_token`) | Local script (new hand-rolled `load_credentials`-shaped function per platform) | External platform (external) | Neither platform's OAuth is Google's — cannot reuse `google-auth-oauthlib`; the *pattern* (cache-refresh-fallback-to-consent) is reused, the implementation is new, built on `requests` |
| SELF_ONLY / gating detection (D-05) | Local script (TikTok `creator_info/query` check before each post) + local config (`tiktok_enabled` flag) | — | TikTok's `status/fetch` response does not itself return the achieved privacy level; the correct check is `creator_info/query`'s `privacy_level_options` (does `PUBLIC_TO_EVERYONE` appear?) called before posting, not a post-hoc inspection of an already-published post |
| Pause/kill | Local queue flag (not-yet-uploaded) + platform API where a cancel/delete call exists | — | TikTok has no update/cancel for an already-published post (Direct Post is immediate/async, not scheduled-for-later like YouTube's `publishAt`) — pause/kill for TikTok/Instagram is necessarily a "don't upload it yet" local-only mechanism for queued-but-not-yet-uploaded items; see Common Pitfalls 4 |
| Chat notification surfacing | Claude Code session (interactive) | Local log file (durable buffer) | Reuses Phase 3's exact `work/_publish/notifications.log` + `append_notification`/`read_unread_notifications` mechanism unchanged — shared, append-only, safe across all three platforms |
| OAuth credential storage | Local filesystem (gitignored) | — | Same discipline as YouTube's `client_secret.json`/`upload_token.json`; two more credential pairs raise this project's real prior-incident blast radius, addressed in Security Domain below |

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `requests` | 2.34.2 (installed, verified via `pip show requests`) [VERIFIED: local pip environment] | Raw HTTP calls for both TikTok's and Instagram's REST APIs (OAuth token exchange/refresh, chunked video upload, container create/publish, status polling) | Already installed in this environment (transitive dependency today) and is the de facto standard Python HTTP client; neither TikTok nor Meta ships an official first-party Python SDK for these APIs, so a hand-rolled thin wrapper over `requests` is the standard approach every reference implementation in this research used [CITED: developers.tiktok.com, developers.facebook.com code samples] |

No other new core dependency is required — both platforms' APIs are plain REST/JSON over HTTPS with chunked-upload semantics `requests` handles natively (`requests.put(url, data=chunk, headers={...})`).

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| stdlib `json` | builtin | Per-platform queue manifest read/write, matching `publish_queue.py`'s existing `load_queue`/`save_queue` shape | Always — project convention |
| stdlib `datetime` | builtin | Token expiry tracking (TikTok 24h access/365d refresh; Instagram 60d long-lived, refreshable after 24h) | Deciding "does this cached token need a refresh call before use" |
| stdlib `argparse` | builtin | CLI wrapper for both new modules | Matches every other `scripts/*.py` module's CLI-plus-importable-function pattern |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Hand-rolled `requests`-based API client per platform | Third-party PyPI packages (e.g. `tiktok-api-client`, various unofficial "post-to-instagram" wrappers surfaced in this research's WebSearch results) | Rejected — these are unofficial, low-visibility community packages with no equivalent to `google-api-python-client`'s maintenance/audit trail; adopting one would introduce a real supply-chain risk for two credential-holding integrations in a project with a documented prior leaked-credential incident. See Package Legitimacy Audit. |
| Instagram resumable upload (local file, `rupload.facebook.com`) | Instagram standard container flow (`video_url` must be publicly reachable) | Standard flow would require standing up a public HTTP host for rendered clips before each publish — directly conflicts with this project's "Локальность" / no-persistent-cloud-backend constraint (CLAUDE.md). Resumable upload accepts a local file path exactly like YouTube's/TikTok's flows, so it is the only option consistent with existing architecture. |
| A single shared `work/_publish/queue.json` extended with a `platform` field | Separate per-platform queue files | A shared file technically works but weakens Success Criterion 3's isolation guarantee (a schema bug or corruption affecting one platform's entries risks the file the already-live YouTube pipeline depends on); separate files cost nothing extra given each platform already needs its own credential files and enable flag |

**Installation:**
```bash
# requests is already installed (transitive dependency); add it to requirements.txt
# explicitly since scripts/tiktok_publish.py and scripts/instagram_publish.py will
# import it directly (not just transitively) — same "declare what you use" discipline
# already followed for google-api-python-client/opencv-python-headless/librosa.
```
No `pip install` step is actually needed on this machine (already present), but `requirements.txt` should gain an explicit `requests>=2.32` line with a comment mirroring the existing optional-dependency comment style.

**Version verification:** `pip show requests` confirms `2.34.2` installed; `pip index versions requests` confirms this is a current, actively-published release (most recent of 100+ historical releases, `psf/requests` on GitHub — the canonical, official repository) [VERIFIED: local pip environment + registry check this session].

### PublishConfig Extension Proposal (concrete, resolves CONTEXT.md's Claude's-Discretion item)

Extend the existing `scripts/config.py::PublishConfig` dataclass in place — do **not** create sibling dataclasses — following the same flat, opt-in-bool-per-feature convention `MonetizationConfig`/`DiarizationConfig` already use:

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
    tiktok_client_key_path: str = "tiktok_client_key.json"   # client_key + client_secret pair
    tiktok_token_path: str = "tiktok_token.json"

    # --- new: Instagram (PUB-07) ---
    instagram_enabled: bool = False
    instagram_queue_path: str = "work/_publish/instagram_queue.json"
    instagram_client_secret_path: str = "instagram_client_secret.json"  # Meta app id + secret
    instagram_token_path: str = "instagram_token.json"
```

Rationale for each choice:
- **`enabled` is left untouched** (still gates only YouTube's real upload/schedule calls, exactly as today) rather than repurposed into a multi-platform switch — this avoids any behavior change to `publish_queue.py`'s already-live, already-tested contract, and matches D-01's "per-platform enable flag" wording literally (three independent flags, not one flag with a platform list).
- **`tiktok_enabled`/`instagram_enabled` default to `False`**, satisfying PUB-03's dry-run-default discipline per-platform (D-01) and matching every other opt-in feature flag in this config file.
- **`daily_slots_utc` stays shared** across all three platforms rather than forking into per-platform grids — each platform's own `next_free_slot`-equivalent only ever checks its *own* queue file's `SCHEDULED` entries, so three platforms independently drawing from the same time-of-day grid causes no collision or cross-platform coupling; introducing per-platform grids would be unjustified complexity CONTEXT.md never asked for.
- **`notifications_path` stays shared** — the append-only log is safe to share (Phase 3's own D-06 hybrid design already assumes multiple event sources can append to it), and a single log is what the user actually wants to read in chat ("did anything happen across any platform").
- Credential path naming (`tiktok_client_key_path`/`tiktok_token_path`, `instagram_client_secret_path`/`instagram_token_path`) mirrors the existing `client_secret_path`/`upload_token_path` naming convention exactly, satisfying CONTEXT.md's discretion item on file naming.
- No new `_validate()` rules are strictly required beyond what already exists (`daily_slots_utc` HH:MM validation already covers the shared grid) — optional bool+path fields need no extra validation, matching `MonetizationConfig`'s precedent.

## Package Legitimacy Audit

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| `requests` | PyPI | 14+ years (first released 2011; current `2.34.2` per `pip index versions`) | Not returned by the legitimacy-check tool this session (`unknown-downloads` signal) — independently one of the most-downloaded packages on PyPI historically, already installed and in active transitive use in this exact environment | `github.com/psf/requests` (official, canonical) [VERIFIED: `package-legitimacy check` seam output this session] | `SUS` (tool flag, reason: `unknown-downloads` only — no other risk signal fired) | **Approved, override documented** — the only flagged signal is a missing download-count data point, not a suspicious age/repo/postinstall signal; `psf/requests` is an unambiguously legitimate, PSF-maintained package already present in this project's dependency tree. Per protocol, planner should still add a lightweight `checkpoint:human-verify`-style confirmation before the `requirements.txt` line is added (not before use — it's already installed), purely to satisfy the SUS-verdict gate mechanically, not because there is a genuine legitimacy concern. |

**Packages removed due to [SLOP] verdict:** none.
**Packages flagged as suspicious [SUS]:** `requests` — flagged only for missing download-count telemetry in the legitimacy-check tool, not for any actual risk signal (repo, age, postinstall all clean). See Disposition above.

No dedicated TikTok or Instagram SDK is recommended for installation (see Alternatives Considered) — this keeps the package surface at exactly one new declared dependency.

## Architecture Patterns

### System Architecture Diagram

```text
                     [Task Scheduler, every ~3h — existing "shorts-maker-publish" task,
                      extended to also invoke the two new modules' --check]
                                          |
                +-------------------------+-------------------------+
                |                         |                         |
                v                         v                         v
      publish_queue.py --check   tiktok_publish.py --check   instagram_publish.py --check
      (UNCHANGED, Phase 3)        (NEW)                        (NEW)
                |                         |                         |
                v                         v                         v
      work/_publish/queue.json   work/_publish/tiktok_queue.json  work/_publish/instagram_queue.json
      (YouTube entries only,      (TikTok entries only,             (Instagram entries only,
       unchanged schema)           new manifest, mirrors             new manifest, mirrors
                                    queue.json's shape)                queue.json's shape)
                |                         |                         |
      is publish.enabled?      is publish.tiktok_enabled?   is publish.instagram_enabled?
        no -> dry-run skip       no -> dry-run skip           no -> dry-run skip
        yes -> pick next due     yes -> pick next due          yes -> pick next due
                |                         |                         |
                v                         v                         v
      load_credentials()        load_credentials()            load_credentials()
      (Google, unchanged)       (NEW, requests-based,          (NEW, requests-based,
                                  TikTok /v2/oauth/token/)       Instagram /oauth/access_token
                                                                  + graph.instagram.com/refresh)
                |                         |                         |
                v                         v                         v
      videos.insert()           creator_info/query first        media create
      (resumable, existing)     (check privacy_level_options    (upload_type=resumable,
                                  -> is PUBLIC_TO_EVERYONE        POST local file to
                                  available? D-05 detection)      rupload.facebook.com)
                                          |                         |
                                          v                         v
                                  video/init (FILE_UPLOAD)    poll container status
                                  -> PUT chunks to upload_url  (status_code=FINISHED)
                                  -> status/fetch poll                |
                                          |                            v
                                          v                    media_publish (creation_id)
                                  publish_id / PUBLISH_COMPLETE
                |                         |                         |
                +-------------------------+-------------------------+
                                          |
                          append line to work/_publish/notifications.log
                          (SHARED across all 3 platforms, D-06 pattern reused verbatim;
                           TikTok additionally appends a distinct D-05 "still SELF_ONLY"
                           line when creator_info/query shows the client is still
                           unaudited/restricted at post time)
                                          |
                                          v
                          [Claude Code session, next time it's open,
                           reads log, reports for all 3 platforms]

[Pause/Kill path, any time — per-platform, same local-flag semantics as YouTube
 for not-yet-uploaded items; NO cancel-after-publish call exists for either
 platform (see Common Pitfalls 4) — "kill" only prevents a not-yet-uploaded
 item from being uploaded, it cannot un-publish an already-posted TikTok/
 Instagram video the way YouTube's publishAt-based kill can]
```

### Recommended Project Structure

```
scripts/
├── publish_queue.py         # UNCHANGED (Phase 3) — YouTube only
├── tiktok_publish.py         # NEW — TikTok Content Posting API: OAuth, FILE_UPLOAD chunked
│                              #   upload, creator_info/query gating check, status/fetch poll,
│                              #   own queue manifest + pause/kill/notification reuse-in-shape
├── instagram_publish.py      # NEW — Instagram Graph API: Business Login OAuth, resumable
│                              #   upload (local file, no public host), media create -> poll
│                              #   -> media_publish, own queue manifest + pause/kill
work/
├── _publish/
│   ├── queue.json             # UNCHANGED — YouTube (Phase 3)
│   ├── tiktok_queue.json       # NEW — TikTok manifest, same shape as queue.json
│   ├── instagram_queue.json    # NEW — Instagram manifest, same shape as queue.json
│   └── notifications.log       # UNCHANGED — shared append-only log, all 3 platforms
tiktok_client_key.json          # NEW, gitignored — TikTok app client_key/client_secret
tiktok_token.json                # NEW, gitignored — cached TikTok OAuth token (access+refresh)
instagram_client_secret.json     # NEW, gitignored — Meta app id/secret
instagram_token.json             # NEW, gitignored — cached Instagram long-lived token
```

### Pattern 1: TikTok Direct Post via `FILE_UPLOAD` (chunked local upload)

**What:** Initialize an upload, PUT the local file in chunks to a short-lived `upload_url`, then poll status.
**When to use:** Every queued TikTok item's actual publish step.
**Example:**
```python
# Source: https://developers.tiktok.com/doc/content-posting-api-get-started-upload-content
#         https://developers.tiktok.com/doc/content-posting-api-reference-direct-post
import requests

def init_direct_post(access_token: str, title: str, privacy_level: str, video_size: int,
                      chunk_size: int, total_chunk_count: int) -> dict:
    """POSTs to /v2/post/publish/video/init/. privacy_level MUST come from a prior
    creator_info/query call's privacy_level_options (Pattern 4) - never hardcode
    PUBLIC_TO_EVERYONE, an unaudited client's account will reject it or silently
    downgrade depending on account state (see Common Pitfalls 1/2)."""
    response = requests.post(
        "https://open.tiktokapis.com/v2/post/publish/video/init/",
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
        json={
            "post_info": {"title": title, "privacy_level": privacy_level},
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": video_size,
                "chunk_size": chunk_size,
                "total_chunk_count": total_chunk_count,
            },
        },
    )
    response.raise_for_status()
    return response.json()["data"]  # {"publish_id": ..., "upload_url": ...}


def upload_video_chunks(upload_url: str, video_path: str, chunk_size: int) -> None:
    """PUTs the local file to upload_url in chunk_size pieces (5MB-64MB per chunk,
    final chunk may be up to 128MB per docs). upload_url is valid for 1 hour."""
    import os
    total_size = os.path.getsize(video_path)
    with open(video_path, "rb") as handle:
        offset = 0
        while offset < total_size:
            chunk = handle.read(chunk_size)
            end = offset + len(chunk) - 1
            requests.put(
                upload_url,
                headers={
                    "Content-Type": "video/mp4",
                    "Content-Length": str(len(chunk)),
                    "Content-Range": f"bytes {offset}-{end}/{total_size}",
                },
                data=chunk,
            ).raise_for_status()
            offset += len(chunk)


def fetch_post_status(access_token: str, publish_id: str) -> dict:
    """Returns {"status", "fail_reason", "publicaly_available_post_id", "uploaded_bytes"}.
    NOTE: does NOT return the achieved privacy_level - that must be inferred from
    creator_info/query (Pattern 4), not from this endpoint."""
    response = requests.post(
        "https://open.tiktokapis.com/v2/post/publish/status/fetch/",
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
        json={"publish_id": publish_id},
    )
    response.raise_for_status()
    return response.json()["data"]
```

### Pattern 2: Instagram Reels via resumable upload (local file, no public host)

**What:** Create a resumable-upload media container, PUT the local file's bytes to `rupload.facebook.com`, then publish.
**When to use:** Every queued Instagram item's actual publish step — this is the path that satisfies the "Локальность" constraint, not the public-`video_url` standard flow.
**Example:**
```python
# Source: https://developers.facebook.com/docs/instagram-platform/content-publishing/resumable-uploads/
#         https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user/media_publish/
import os
import requests

def create_resumable_container(ig_user_id: str, access_token: str, caption: str) -> str:
    """POSTs to /{ig-user-id}/media with upload_type=resumable, media_type=REELS.
    Returns the container id (used both for the binary upload and the publish call)."""
    response = requests.post(
        f"https://graph.facebook.com/v23.0/{ig_user_id}/media",
        params={
            "media_type": "REELS",
            "upload_type": "resumable",
            "caption": caption,
            "access_token": access_token,
        },
    )
    response.raise_for_status()
    return response.json()["id"]


def upload_local_video(container_id: str, access_token: str, video_path: str) -> None:
    """POSTs the raw video bytes to rupload.facebook.com (NOT graph.facebook.com) -
    this is the one Instagram call that targets a different host."""
    file_size = os.path.getsize(video_path)
    with open(video_path, "rb") as handle:
        response = requests.post(
            f"https://rupload.facebook.com/ig-api-upload/v23.0/{container_id}",
            headers={
                "Authorization": f"OAuth {access_token}",
                "offset": "0",
                "file_size": str(file_size),
            },
            data=handle.read(),
        )
    response.raise_for_status()


def poll_container_status(container_id: str, access_token: str) -> str:
    """Polls /{container-id}?fields=status_code until FINISHED (or ERROR)."""
    response = requests.get(
        f"https://graph.facebook.com/v23.0/{container_id}",
        params={"fields": "status_code", "access_token": access_token},
    )
    response.raise_for_status()
    return response.json()["status_code"]


def publish_container(ig_user_id: str, access_token: str, creation_id: str) -> str:
    """POSTs to /{ig-user-id}/media_publish once status_code == FINISHED. Returns
    the published media id."""
    response = requests.post(
        f"https://graph.facebook.com/v23.0/{ig_user_id}/media_publish",
        params={"creation_id": creation_id, "access_token": access_token},
    )
    response.raise_for_status()
    return response.json()["id"]
```

### Pattern 3: Hand-rolled `load_credentials`-shaped OAuth helpers (pattern reuse, not library reuse)

**What:** A same-signature-shaped function per platform (`load_credentials(client_secret_path, token_path) -> access_token`), cache-refresh-fallback-to-consent, matching `youtube_analytics.py::load_credentials`'s contract.
**When to use:** Any place `tiktok_publish.py`/`instagram_publish.py` needs a usable access token.
**Example:**
```python
# Source: pattern shape derived from scripts/youtube_analytics.py::load_credentials
# (reused per D-02's instruction), reimplemented with requests since neither
# platform's OAuth is Google's.
import json
import time
from pathlib import Path

import requests

TIKTOK_TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"


def load_tiktok_credentials(client_key_path: str, token_path: str) -> str:
    """Loads a cached TikTok access token, silently refreshing via grant_type=
    refresh_token if the cached access token has expired (access tokens last 24h,
    refresh tokens last 365 days - refresh needs no user interaction). Raises if
    no cached token exists at all (first-time consent is a manual, interactive
    step - browser-based authorize URL - performed once during setup, D-02)."""
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
The Instagram equivalent follows the identical shape, calling `GET https://graph.instagram.com/refresh_access_token?grant_type=ig_refresh_token&access_token=<token>` instead — long-lived tokens are valid 60 days and refreshable any time between 24h-old and expiry, so a refresh-if-older-than-N-days check (e.g. weekly, well inside the 60-day window) run from the same periodic Task Scheduler check keeps it perpetually fresh with zero user interaction after the one-time initial consent.

### Pattern 4: TikTok `creator_info/query` as the D-05 SELF_ONLY detection mechanism

**What:** Before every post, query `creator_info/query`; its `privacy_level_options` field lists which privacy levels are currently available for this creator+client combination.
**When to use:** Immediately before each TikTok upload, to (a) select a valid `privacy_level` for the `video/init` call, and (b) implement D-05's detection: if `PUBLIC_TO_EVERYONE` is absent from the options while the queue entry expected a real (non-test) publish, this is the SELF_ONLY trap firing — append the D-05 notification and post with `privacy_level: "SELF_ONLY"` instead of failing the item outright.
**Why this endpoint and not `status/fetch` after the fact:** `status/fetch`'s documented response fields (`status`, `fail_reason`, `publicaly_available_post_id`, `uploaded_bytes`) do not include an achieved-privacy-level field — there is nothing to introspect post-hoc to detect "it went private instead of public." The gating information only exists pre-post, in `creator_info/query`.
```python
# Source: https://developers.tiktok.com/doc/content-posting-api-reference-query-creator-info
def check_tiktok_publish_gate(access_token: str) -> tuple[str, bool]:
    """Returns (privacy_level_to_use, is_still_gated). is_still_gated=True means
    PUBLIC_TO_EVERYONE is not an available option right now (unaudited client
    and/or account set to private) - D-05's trigger for the chat notification."""
    response = requests.post(
        "https://open.tiktokapis.com/v2/post/publish/creator_info/query/",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    response.raise_for_status()
    options = response.json()["data"]["privacy_level_options"]
    if "PUBLIC_TO_EVERYONE" in options:
        return "PUBLIC_TO_EVERYONE", False
    return "SELF_ONLY", True
```

### Anti-Patterns to Avoid

- **Hardcoding `privacy_level: "PUBLIC_TO_EVERYONE"` on every TikTok post:** an unaudited client (or an account set to private) will reject or silently downgrade this — always derive the value from `creator_info/query`'s `privacy_level_options` per-call (Pattern 4).
- **Using the Instagram standard (`video_url`) container flow instead of resumable upload:** the standard flow needs a publicly-reachable URL Meta's servers can fetch from, which would require standing up a public host — violates the project's local-first constraint. Always use `upload_type: resumable` with a local file (Pattern 2).
- **Treating `status/fetch`/container-status polling as sufficient for D-05's SELF_ONLY detection:** neither platform's post-publish status endpoint tells you the achieved visibility directly for TikTok; check the gate *before* posting (Pattern 4), not after.
- **Assuming a `videos.update`-style cancel exists for an already-posted TikTok/Instagram item:** it doesn't (see Common Pitfalls 4) — pause/kill for these two platforms is a "prevent the not-yet-uploaded upload" mechanism only, not a "undo the already-public post" mechanism the way YouTube's `publishAt`-based kill is.
- **Copying `google-auth-oauthlib`'s `InstalledAppFlow` pattern verbatim:** it is Google-specific; reuse the *shape* of `load_credentials`, not the library (Pattern 3).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Chunked HTTP PUT with `Content-Range` headers | Custom byte-range chunking logic from scratch | `requests.put(url, data=chunk, headers={"Content-Range": ...})` in a simple loop (Pattern 1) | This is genuinely simple enough (unlike YouTube's resumable-upload session-URI protocol) that no library abstraction is needed or exists for it — the "don't hand-roll" risk here is getting the byte-range math wrong, not reinventing an existing library |
| OAuth token caching/refresh — the *behavior* | A bespoke ad-hoc "check expiry inline at every call site" pattern | The `load_credentials`-shaped helper functions (Pattern 3), one per platform, called once per script invocation the same way `youtube_analytics.py::load_credentials` already is | Keeps the token-freshness concern in exactly one place per platform, matching the existing codebase's separation of concerns |
| Queue/idempotency manifest mechanics (numbering, status transitions, write-ahead-before-network-call) | New idempotency logic from scratch for TikTok/Instagram | Copy `publish_queue.py`'s exact shape (`load_queue`/`save_queue`/`enqueue`/`select_next_due`/pause-kill state machine), applied to a new manifest path | Phase 3 already solved queue idempotency correctly (write-ahead UPLOADING state, reconciliation on crash) — this is directly reusable *logic*, not just a reusable *idea*; re-deriving it risks reintroducing Phase 3's Pitfall 3 (crash-mid-upload duplicate) |
| Per-platform metadata/caption text | New metadata rendering | `scripts/metadata.py::render_metadata_text`/`write_metadata_file`, entirely unchanged — `platforms_data["tiktok"]["caption"]`/`platforms_data["instagram"]["caption"]` already exist in the schema `METADATA_PLATFORMS` defines | Phase 1's metadata module already produces a `caption` field for both `tiktok` and `instagram` platform keys (see `scripts/metadata.py` line 45: non-YouTube platforms use `fields["caption"]`) — this phase only needs to *read* that already-rendered text as the `title`/`caption` API parameter, not generate it |

**Key insight:** Almost everything hard about this phase (idempotent queueing, credential caching, chat notification bridging) is already solved by Phase 3 and just needs re-application to two new manifests/credential pairs. The genuinely new work is narrow: two small REST clients (chunked-PUT for TikTok, resumable-upload for Instagram) and the D-05 pre-post gating check — everything else is composition of Phase 3's already-battle-tested pieces.

## Common Pitfalls

### Pitfall 1: Assuming TikTok's SELF_ONLY restriction is something the *code* can detect after the fact
**What goes wrong:** A natural instinct (matching how YouTube's kill-path works) is to look at the response of the publish/status call for a "did this actually go public" signal. TikTok's `status/fetch` response schema (`status`, `fail_reason`, `publicaly_available_post_id`, `uploaded_bytes`) has no such field — `status: "PUBLISH_COMPLETE"` means "the platform accepted and processed the post," not "it is publicly visible."
**Why it happens:** The API's own naming (`publicaly_available_post_id`) is misleading — it's an array used to construct a share-URL for the post, present regardless of whether the post is actually public or SELF_ONLY.
**How to avoid:** Check gating *before* posting via `creator_info/query`'s `privacy_level_options` (Pattern 4), and additionally treat "we know from local config that `tiktok_enabled` was recently flipped true but no audit-confirmation step has run yet" as a standing assumption to surface, not something to re-derive from the API every time.
**Warning signs:** A "success" notification that never mentions privacy level, followed later by the creator noticing the video never appeared publicly.

### Pitfall 2: TikTok's Content Posting API audit is a *separate*, *additional* review beyond base app approval
**What goes wrong:** Assuming "my TikTok developer app got approved" means Direct Post is unlocked. Secondary sources consistently describe **two** review gates: (1) base app review (getting the app itself usable at all, reported 3-14 days across sources), then (2) a dedicated Content Posting API / Direct Post audit specifically for lifting the `SELF_ONLY` restriction (reported 4-10 weeks per scope) [CITED: multiple secondary sources, cross-referenced against each other — TikTok's own docs confirm an audit exists but publish no timeline, see Assumptions Log A1].
**Why it happens:** TikTok's official docs use the word "audit" consistently but never explicitly separate it from "app review" in a single authoritative timeline table.
**How to avoid:** The plan's runbook step (D-04) should explicitly instruct the user to look for and complete *both* review stages, not stop at "app got approved."
**Warning signs:** `tiktok_enabled: true` flipped on, but every post still comes back `SELF_ONLY` — this is expected/normal until the *second* audit clears, not a bug.

### Pitfall 3: Instagram's App Review requirement may not apply to this project's actual use case at all
**What goes wrong:** Treating Instagram exactly like TikTok — "wait for review before going live" — when Meta's Standard-vs-Advanced-Access split means an app that only ever publishes to Instagram accounts the developer owns and has explicitly added to their own App Dashboard (Standard Access) does not require formal App Review in the first place; Advanced Access (and its ~2-4 week review) is only required for apps publishing on behalf of *other* people's accounts.
**Why it happens:** Most public guides/tutorials about Instagram App Review are written for third-party SaaS tools managing many *other* users' accounts (the Advanced Access case) — that is the dominant use case discussed online, not the "personal single-account tool" case this project actually is.
**How to avoid:** Before writing the runbook step, the user should add their own Instagram Business account as an admin/tester in the Meta App Dashboard and attempt a real publish in Development Mode — if it succeeds, no App Review was ever required for this project's use case, and D-04's "file the application" instruction can be skipped entirely for Instagram (see Open Questions #1 — this is a confirm-before-planning item, not something this research can settle with certainty from documentation alone).
**Warning signs:** None yet observed — this is a documentation-derived inference, not empirically tested against this project's actual Meta App (no app has been registered yet per D-04's factual premise).

### Pitfall 4: Neither TikTok nor Instagram has a YouTube-style "cancel a scheduled release" mechanism
**What goes wrong:** Assuming PUB-04's pause/kill semantics (which, for YouTube, can revert an already-`SCHEDULED`-but-not-yet-public video back to private via `videos.update`) transfer identically to TikTok/Instagram. Neither platform exposes native server-side scheduling the way YouTube's `publishAt` does — TikTok's Direct Post publishes (or fails) asynchronously shortly after the upload completes, and Instagram's `media_publish` call publishes immediately once invoked. There is no "private-until-timestamp-X" status to revert.
**Why it happens:** Phase 3's pause/kill design is built around YouTube's specific `privacyStatus`+`publishAt` scheduling primitive, which is not a universal platform capability.
**How to avoid:** For TikTok/Instagram, "kill" can only ever mean "prevent a not-yet-uploaded queue item from being uploaded" (the exact `_NOT_YET_UPLOADED_STATUSES` local-only branch `publish_queue.py::kill_item` already has for YouTube) — once an item has actually reached `video/init`+chunk-upload (TikTok) or `media_publish` (Instagram), there is no API call to revert it. Document this limitation explicitly rather than building a kill path that silently no-ops on an already-published item. If genuine post-hoc removal is ever needed, TikTok/Instagram both support delete-my-own-post endpoints (not researched in depth here, out of this phase's scope per PUB-04's "halt scheduled publishing," not "delete published content") — flag as a known gap, not attempt an unresearched delete-based kill in this phase.
**Warning signs:** A test that expects `kill_item()` on an already-`PUBLISH_COMPLETE` TikTok entry to revert visibility — this test would be testing a capability that does not exist for this platform and should not be written that way.

### Pitfall 5: TikTok upload URLs and chunk-size rules are stricter than YouTube's
**What goes wrong:** Reusing YouTube's `chunksize=-1` ("let the library pick optimal size") mental model. TikTok requires explicit chunk sizes between 5MB and 64MB (final chunk may exceed up to 128MB), and the returned `upload_url` is only valid for **one hour** — a slow/interrupted chunk sequence that takes longer than an hour will fail with an expired-URL error, requiring a fresh `video/init` call (which issues a new `publish_id`, another Pitfall 3-of-Phase-3-style idempotency concern to guard against: a retried `video/init` after a partial chunk sequence must not silently re-init and orphan the first attempt without the manifest noticing).
**Why it happens:** TikTok's chunked-upload protocol is simpler/less forgiving than Google's resumable-upload session-URI protocol, which handles arbitrarily long interruptions.
**How to avoid:** For this project's clip sizes (short vertical clips, well under a few hundred MB), a single well-sized chunk (or a small handful) uploading well within an hour on any reasonable connection should be routine — but the write-ahead manifest pattern (record `publish_id` immediately after `video/init`, before starting the chunk PUT loop) should be carried over from Phase 3's Pitfall 3 mitigation regardless, so a crash mid-chunk-upload is reconcilable rather than silently duplicated on retry.
**Warning signs:** A `video/init` retry loop that doesn't check for/reuse an already-issued `publish_id` from a previous attempt recorded in the manifest.

## Code Examples

### Constructing the TikTok Direct Post request body (already shown above, restated for the checklist)
See Pattern 1.

### Constructing the Instagram Reels container + resumable upload + publish sequence
See Pattern 2.

### One-time interactive OAuth consent (both platforms, illustrative shape)
```python
# TikTok: browser-based, matches google_auth_oauthlib.flow.InstalledAppFlow's
# "open a browser, capture the redirect" shape conceptually, but hand-rolled
# since no TikTok-specific Python OAuth library exists.
# Source: https://developers.tiktok.com/doc/oauth-user-access-token-management
TIKTOK_AUTHORIZE_URL = (
    "https://www.tiktok.com/v2/auth/authorize/"
    "?client_key={client_key}&scope=video.publish,video.upload"
    "&response_type=code&redirect_uri={redirect_uri}&state={state}"
)
# User visits this URL, approves, TikTok redirects to redirect_uri?code=...
# Exchange the code:
# POST https://open.tiktokapis.com/v2/oauth/token/
#   client_key, client_secret, code, grant_type=authorization_code, redirect_uri

# Instagram: Business Login, same browser-redirect shape.
# Source: https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/business-login
INSTAGRAM_AUTHORIZE_URL = (
    "https://www.instagram.com/oauth/authorize"
    "?client_id={client_id}&redirect_uri={redirect_uri}&response_type=code"
    "&scope=instagram_business_basic,instagram_business_content_publish"
)
# Exchange code: POST https://api.instagram.com/oauth/access_token
#   (short-lived token) -> exchange again for a 60-day long-lived token
#   via GET https://graph.instagram.com/access_token?grant_type=ig_exchange_token
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| TikTok "Share Video Kit" (older API, upload-to-inbox-for-manual-finish only) | Content Posting API with `video.publish` scope (true Direct Post, no manual finish step needed) | TikTok migration bulletin, referenced in this session's search results [CITED: developers.tiktok.com/bulletin/migration-notice-share-video-api] | This phase should target the Content Posting API exclusively — the older Share Video API is being deprecated/migrated away from and would not deliver PUB-06's "auto-published, no manual step" requirement anyway |
| Instagram's older scope names (`instagram_content_publish` under legacy Facebook Login for Business) | New Instagram-Login-native scopes (`instagram_business_basic`, `instagram_business_content_publish`, etc.) | Old scope values deprecated January 27, 2025 per Meta's own migration notice [CITED: developers.facebook.com, cross-referenced via WebSearch] | This phase should use the new `instagram_business_*` scope names and the Instagram-native Business Login flow (no Facebook Page linkage required), not the legacy Facebook-Login-for-Business path — simpler setup, one fewer prerequisite (no Facebook Page needed) |

**Deprecated/outdated:** TikTok's original Share Video API (superseded by Content Posting API); Instagram's legacy `instagram_content_publish`/Facebook-Login-for-Business scope names (superseded by `instagram_business_content_publish`/Instagram Login as of the Jan 2025 deprecation).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | TikTok's Content Posting API audit takes roughly 4-10 weeks per scope, on top of a 3-14 day base app review | Summary, Pitfall 2 | **[ASSUMED]** — sourced only from secondary blog/aggregator content (postpeer.dev, tokportal.com, zernio.com and similar), not TikTok's own docs, which state an audit exists but publish no timeline at all. If wrong (shorter or much longer), only the runbook's expectation-setting language needs updating, not the code — the per-platform `enabled` flag design is timeline-agnostic by construction. |
| A2 | Instagram App Review (Advanced Access, ~2-4 weeks) does NOT apply when an app only ever publishes to Instagram Business accounts the developer already owns/manages (Standard Access) | Summary, Pitfall 3, Open Questions #1 | **[ASSUMED]** — this is the single highest-impact assumption in this research. If wrong, D-04's "file both applications" premise holds for both platforms as originally stated, and the plan needs a review-gate runbook step for Instagram identical to TikTok's. If right, Instagram could go fully live (not just SELF_ONLY/test-mode) as soon as the Business account is registered in the App Dashboard — a materially faster path than CONTEXT.md assumed. **Recommend the planner treat this as a checkpoint:human-verify item**: register the Meta app, add the account as a tester, attempt one real (non-test) publish in Development Mode, and observe whether it succeeds before deciding whether `instagram_enabled` needs a review-completion gate at all. |
| A3 | Neither platform exposes a native server-side "schedule for later, cancel before it goes live" primitive equivalent to YouTube's `publishAt` | Architectural Responsibility Map, Pitfall 4 | Low risk if wrong in the direction of "actually TikTok/Instagram DO support this" (would just mean pause/kill could be strengthened later) — but this research found no evidence of such a mechanism in either platform's Content Posting/Graph API docs, and secondary sources consistently describe TikTok Direct Post and Instagram `media_publish` as immediate/near-immediate actions once invoked, not schedulable |
| A4 | TikTok's `status/fetch` response schema does not include an achieved-`privacy_level` field | Pattern 4, Pitfall 1 | Medium risk — this claim is based on a documented example response body (`status`/`fail_reason`/`publicaly_available_post_id`/`uploaded_bytes`) plus the absence of any privacy field in every reference/example this research found, not an exhaustive read of every response-field edge case in TikTok's evolving docs. If wrong, `creator_info/query` pre-check (Pattern 4) is still valid and safe to keep regardless — worst case, it becomes a redundant-but-harmless extra check rather than the only mechanism. |

## Open Questions

1. **Does Instagram actually require App Review for this project's single-owned-account use case, or does Standard Access cover it entirely? (Highest-impact open question)**
   - What we know: Meta's documented Standard-vs-Advanced-Access split states Advanced Access (with its App Review requirement) is needed only "if your app publishes on behalf of accounts you do not own" — this project publishes exclusively to the creator's own account.
   - What's unclear: Whether "own" in Meta's framing requires the account to be added as a registered tester/admin in the App Dashboard (likely yes, a one-time setup step) and whether Development Mode alone is sufficient for indefinite real (non-test) publishing, or whether some other gate (e.g., Meta Business Verification, unrelated to App Review) still applies to a Business account regardless of Advanced/Standard Access.
   - Recommendation: Before the plan commits to a review-gated `instagram_enabled` flag design mirroring TikTok's, the user should register the Meta App, add their own Instagram Business account as a tester/admin, and attempt one real publish. If it succeeds without any pending review, `instagram_enabled` can potentially flip to `true` immediately after D-02's setup step, with no audit-wait runbook item needed for Instagram at all — a materially different (faster) outcome than D-04 assumed. This should be an explicit `checkpoint:human-verify` task early in the plan, before the rest of the Instagram integration work is built around an assumption that may not hold.

2. **Exact chunk-size/upload strategy for TikTok given this project's typical clip file sizes**
   - What we know: chunks must be 5MB-64MB (final chunk up to 128MB), `upload_url` valid for 1 hour.
   - What's unclear: This project's rendered shorts are short (30-60s, or up to ~150s for Phase 5 compilations) vertical clips — likely well under 64MB in most cases, meaning a *single* chunk covering the whole file may be simplest (one PUT, no chunking loop needed) rather than a true multi-chunk loop.
   - Recommendation: The planner should size actual rendered output files (`ffprobe`/`os.path.getsize` on a few real Phase-1-through-5 outputs) before deciding whether the chunk loop needs to handle more than one chunk in practice, or whether a simple "single chunk if file fits in 64MB, else split" branch suffices — this is an implementation-sizing detail, not a research gap.

3. **Whether TikTok/Instagram publish attempts should participate in the same `daily_slots_utc` grid or fire immediately once due (no native scheduling exists per Pitfall 4)**
   - What we know: YouTube's grid exists because `publishAt` lets the upload happen ahead of the actual public release time. Neither TikTok nor Instagram supports this — publishing IS going live (or at minimum, going live-when-the-async-processing-finishes-in-seconds-to-minutes).
   - What's unclear: Whether "next free slot" still makes sense as a *queue-processing* pace-limiter (e.g., "don't upload more than one TikTok/Instagram item per 3h check cycle," matching D-05's YouTube "one at a time" cadence) even though there's no `publishAt` field to set, or whether the grid concept should be dropped entirely for these two platforms in favor of simply "upload the next due item, immediately, once per check."
   - Recommendation: Reuse `daily_slots_utc` as a pacing/rate-limit mechanism only (cap uploads to one per grid slot per platform, same "at most one per --check invocation" debounce Phase 3 already has) rather than as a real scheduled-release timestamp — no `publishAt`-equivalent field exists to set for either platform, so the grid's role narrows from "when it goes live" (YouTube) to "how often we're willing to check+upload" (TikTok/Instagram), which the planner should state explicitly in the plan so this isn't misread as a scheduling feature that doesn't actually exist for these platforms.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `requests` | Every TikTok/Instagram API call in this phase | Yes | 2.34.2 (already installed) | — |
| TikTok Developer Portal account + registered app (client_key/client_secret) | Any TikTok OAuth/API call at all | **Not yet created** — per D-04, nothing has been submitted/registered yet | — | Blocking for any live testing (even SELF_ONLY sandbox testing per D-02) until the user completes app registration; code can still be written and unit-tested against fakes in the meantime, matching Phase 3's precedent of building against test doubles before real credentials exist |
| TikTok Content Posting API audit (for public, non-SELF_ONLY posting) | Real (non-private) TikTok auto-publish | Not started | — | SELF_ONLY sandbox posting is usable pre-audit (D-02); real public posting fails open into the D-05 notification path until audit clears |
| Meta App + Instagram Business account setup | Any Instagram OAuth/API call at all | **Not yet created** — per D-04, nothing has been submitted/registered yet | — | Same as TikTok — code buildable now, live testing blocked until app registration |
| Meta App Review (Advanced Access) | Real Instagram publishing IF Advanced Access is actually required (see Open Questions #1) | Not started, and **may not be required at all** for this project's self-owned-account use case | — | If Open Questions #1 resolves in favor of "Standard Access suffices," this dependency may not block anything; treat as unresolved until the checkpoint:human-verify step runs |
| Internet connectivity to `open.tiktokapis.com` / `graph.facebook.com` / `rupload.facebook.com` | Every upload/publish call | Not tested this session (no live API call made — research/documentation only) | — | Fail-open per project convention: both new modules' periodic check should catch network errors and log-and-skip, matching `publish_queue.py`'s existing pattern |

**Missing dependencies with no fallback:** TikTok app registration and Meta app registration — both require the user's own developer/business accounts and cannot be performed by an executor agent (D-04). These block any *live* API testing, not the code itself.

**Missing dependencies with fallback:** Audit/review completion for both platforms is not a hard blocker for shipping code — D-01's dry-run-first posture means the integration can be built, tested against fakes, and even exercised for real in SELF_ONLY/test mode before either review completes.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.1.1 (verified: `python -m pytest --version`) |
| Config file | `pyproject.toml` (`[tool.pytest.ini_options]`: `pythonpath=["."]`, `testpaths=["tests"]`, `integration` marker registered) |
| Quick run command | `pytest tests/test_tiktok_publish.py tests/test_instagram_publish.py -x` |
| Full suite command | `pytest` (repo root) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PUB-06 | `video/init` request body construction (`FILE_UPLOAD` source, correct `post_info`/`source_info` shape) given mocked `requests` | unit | `pytest tests/test_tiktok_publish.py::test_init_direct_post_body -x` | ❌ Wave 0 |
| PUB-06 | Chunked PUT loop sends correct `Content-Range` headers and covers the whole file, given a fake HTTP layer (matching this project's hand-written-fake convention, not `unittest.mock`) | unit | `pytest tests/test_tiktok_publish.py::test_upload_video_chunks -x` | ❌ Wave 0 |
| PUB-06 | `creator_info/query` gating check correctly returns `is_still_gated=True` when `PUBLIC_TO_EVERYONE` is absent from `privacy_level_options` (D-05) | unit | `pytest tests/test_tiktok_publish.py::test_check_tiktok_publish_gate_self_only -x` | ❌ Wave 0 |
| PUB-06 | Dry-run default: with `publish.tiktok_enabled=false`, no HTTP call is attempted at all | unit | `pytest tests/test_tiktok_publish.py::test_dry_run_default_no_upload -x` | ❌ Wave 0 |
| PUB-06 | TikTok queue idempotency (write-ahead status before `video/init`, no re-upload on retry) — mirrors Phase 3's `test_idempotent_retry_no_duplicate` | unit | `pytest tests/test_tiktok_publish.py::test_idempotent_retry_no_duplicate -x` | ❌ Wave 0 |
| PUB-07 | Resumable-container creation request body (`media_type=REELS`, `upload_type=resumable`) given mocked `requests` | unit | `pytest tests/test_instagram_publish.py::test_create_resumable_container -x` | ❌ Wave 0 |
| PUB-07 | Local-file upload POSTs to `rupload.facebook.com` (not `graph.facebook.com`), correct `offset`/`file_size` headers | unit | `pytest tests/test_instagram_publish.py::test_upload_local_video -x` | ❌ Wave 0 |
| PUB-07 | Publish only fires after `status_code == FINISHED`, never before | unit | `pytest tests/test_instagram_publish.py::test_poll_then_publish_sequencing -x` | ❌ Wave 0 |
| PUB-07 | Dry-run default: with `publish.instagram_enabled=false`, no HTTP call is attempted at all | unit | `pytest tests/test_instagram_publish.py::test_dry_run_default_no_upload -x` | ❌ Wave 0 |
| PUB-06/PUB-07 | Isolation: killing/pausing a TikTok entry never touches `work/_publish/queue.json` (YouTube) or `work/_publish/instagram_queue.json`, and vice versa (Success Criterion 3) | unit | `pytest tests/test_tiktok_publish.py tests/test_instagram_publish.py -k isolation -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/test_tiktok_publish.py tests/test_instagram_publish.py -x`
- **Per wave merge:** `pytest` (full suite)
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/test_tiktok_publish.py` — new file, covers PUB-06 (all rows above), following `tests/test_publish_queue.py`'s hand-written-fake HTTP-layer convention (a `FakeResponse`/`FakeSession`-style test double, not `unittest.mock`/`pytest-mock`, matching this project's established `FakeVideosService`-style precedent from `tests/test_youtube_analytics.py`)
- [ ] `tests/test_instagram_publish.py` — new file, covers PUB-07 (all rows above), same fake-HTTP-layer convention
- [ ] No new shared fixtures strictly required, though a shared `conftest.py`-level fake-`requests`-session fixture would reduce duplication now that three modules (`publish_queue.py`, `tiktok_publish.py`, `instagram_publish.py`) all need HTTP test doubles — worth the planner's consideration, not a hard requirement
- [ ] Framework install: none — pytest already installed and configured

## Security Domain

> This project has no standalone `03-SECURITY.md`-style file for Phase 3 — its Security Domain analysis lives inside `03-RESEARCH.md`'s own `## Security Domain` section. This phase follows that exact same embedded convention (not a separate file), and yes, this section is required: `security_enforcement: true` in `.planning/config.json`, and this phase adds OAuth credentials for two more platforms on top of an already-documented prior real leaked-credential incident (STATE.md Blockers/Concerns explicitly flags this: "OAuth credentials for 3 platforms raise the stakes of this project's prior real leaked-data incident").

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | Yes | OAuth 2.0 authorization-code flow for both platforms — hand-rolled per Pattern 3 (no library exists to reuse), but the *protocol* itself (redirect, code exchange, refresh) is each platform's own standard, documented flow, not a custom auth scheme |
| V3 Session Management | No | No web session/cookie surface in this CLI-only project |
| V4 Access Control | Yes | Scope-minimization per platform: TikTok token requested with only `video.publish`+`video.upload` (not any broader scope TikTok's OAuth may offer); Instagram token requested with only `instagram_business_basic`+`instagram_business_content_publish` (not e.g. `instagram_business_manage_messages`/`instagram_business_manage_comments`, which this phase has no use for) — build-time verification item: grep the actual `scope=` values at each authorize-URL construction site |
| V5 Input Validation | Yes | Queue manifest entries (title/caption sourced from `metadata.py` output, reused verbatim per Don't Hand-Roll) should be validated against each platform's own field limits before submission: TikTok `title` ≤2200 UTF-16 runes; Instagram `caption` ≤2200 characters, ≤30 hashtags, ≤20 @mentions — a validation failure should fail the specific queue item only, not crash the whole periodic check, mirroring `publish_queue.py::build_insert_body`'s existing `ValueError`-per-field-limit pattern exactly |
| V6 Cryptography | No custom crypto | Token storage is plaintext JSON on local disk for both new platforms, matching the existing `upload_token.json`/`token.json` precedent exactly — no new crypto decision needed, same trust model (local machine, not shared/multi-tenant) already accepted for YouTube |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Leaked `tiktok_client_key.json`/`tiktok_token.json`/`instagram_client_secret.json`/`instagram_token.json` (this project's prior real incident, now with two more credential pairs) | Information Disclosure | Gitignore discipline (already required, matching D-02/D-09's precedent) + scope minimization (V4 above) shrinks blast radius per credential pair; document each new gitignored filename in this phase's operator-guide doc (mirroring `docs/publish-queue.md`'s existing role) so the discipline is explicit, not assumed |
| Duplicate/repeated upload on retry (same PUB-05-class concern Phase 3 already solved, now applying to two more platforms) | — (reliability/trust threat, not classic STRIDE) | Write-ahead manifest state (record `publish_id`/container id immediately after the platform accepts the init/create call, before the binary upload completes) + reconciliation-on-crash logic, directly reusing Phase 3's Pitfall 3 pattern per-platform (Don't Hand-Roll) |
| A malformed/adversarial queue manifest entry causing an unintended `privacy_level` (TikTok) or `caption`/`media_type` (Instagram) at submission time | Tampering | Same treatment as Phase 3's Pitfall/threat entry: validate the constructed request body against expected shape/types before calling `.execute()`-equivalent; the local manifest is trusted-but-verify, a bug that writes a bad entry should fail loud, not silently post with wrong settings |
| Two new OAuth consent flows opening a local HTTP listener / browser redirect during first-time setup (both platforms' authorization-code flow needs a `redirect_uri` the local script can receive) | Spoofing / Elevation of Privilege (if the redirect listener is bound too broadly) | Bind the local OAuth callback listener to `localhost`/`127.0.0.1` only (never `0.0.0.0`) during the one-time interactive consent step, matching the implicit safety of `google_auth_oauthlib`'s `flow.run_local_server(port=0)` behavior Phase 3 already relies on for YouTube — this is a new construction point (TikTok/Instagram don't ship this helper), so the planner must build it deliberately rather than assume it's automatic |

## Sources

### Primary (HIGH confidence — official docs, fetched/searched directly this session)
- [TikTok — Content Posting API Get Started](https://developers.tiktok.com/doc/content-posting-api-get-started) - OAuth scopes, unaudited/audited client distinction, SELF_ONLY restriction (fetched directly)
- [TikTok — Content Sharing Guidelines](https://developers.tiktok.com/doc/content-sharing-guidelines) - audit requirement, 5-users/24h cap, SELF_ONLY details (fetched directly)
- [TikTok — Direct Post API Reference](https://developers.tiktok.com/doc/content-posting-api-reference-direct-post) - `video/init` request/response shape, `post_info`/`source_info` fields, error codes (fetched directly)
- [TikTok — Get Post Status](https://developers.tiktok.com/doc/content-posting-api-reference-get-video-status) - `status/fetch` response fields (searched, cross-referenced)
- [TikTok — Query Creator Info](https://developers.tiktok.com/doc/content-posting-api-reference-query-creator-info) - `privacy_level_options` field, fetched directly
- [TikTok — OAuth User Access Token Management](https://developers.tiktok.com/doc/oauth-user-access-token-management) - token expiry (24h access/365d refresh), refresh flow (searched, cross-referenced)
- [Meta — Content Publishing Overview](https://developers.facebook.com/docs/instagram-platform/content-publishing/) - container flow, `video_url` requirement (searched, cross-referenced — direct WebFetch blocked by network error this session)
- [Meta — Resumable Uploads](https://developers.facebook.com/docs/instagram-platform/content-publishing/resumable-uploads/) - local-file upload flow, `rupload.facebook.com` host (searched, cross-referenced)
- [Meta — Business Login for Instagram](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/business-login) - OAuth flow, new `instagram_business_*` scopes (searched, cross-referenced)
- [Meta — Refresh Access Token](https://developers.facebook.com/docs/instagram-platform/reference/refresh_access_token/) - 60-day long-lived token refresh mechanics (searched, cross-referenced)
- `scripts/publish_queue.py`, `scripts/youtube_analytics.py`, `scripts/config.py`, `scripts/metadata.py`, `docs/publish-queue.md` (this repo) - existing patterns reused/extended [VERIFIED: read directly from repo]
- `pip show requests` / `pip index versions requests` [VERIFIED: local environment command output]
- `gsd-tools query package-legitimacy check` output for `requests` [VERIFIED: local seam output this session]

### Secondary (MEDIUM confidence — WebSearch, cross-checked across multiple independent sources)
- TikTok Content Posting API audit timelines (4-10 weeks/scope, 3-14 days base review) - postpeer.dev, tokportal.com, zernio.com and similar, no single authoritative source, cross-referenced against each other only (not against TikTok's own docs, which publish no timeline)
- Instagram App Review timeline (2-4 weeks) and Standard-vs-Advanced-Access distinction - postproxy.dev, phyllo, blotato and similar, cross-referenced against each other; the Standard-vs-Advanced-Access mechanism itself is corroborated by Meta's own App Review docs page description in search results, but this session's direct `WebFetch` of `developers.facebook.com/docs/instagram-platform/app-review/` failed (network error), so this is WebSearch-derived, not a direct official-doc fetch — flagged as Assumption A2
- Instagram 25-post/24h vs 100-post/24h publishing-limit discrepancy across sources - ayrshare.com, repostit.io and others disagree on the exact number; irrelevant to this project's low cadence either way, not treated as load-bearing

### Tertiary (LOW confidence)
- None used as load-bearing claims for API mechanics (all mechanics-level claims were corroborated by at least the official docs' own example payloads/field lists, even where direct WebFetch of a specific page failed and WebSearch summaries were used instead).

## Metadata

**Confidence breakdown:**
- Standard stack (`requests`-based hand-rolled clients, no SDK): HIGH - already-installed library, no new package risk beyond the documented SUS-but-clean `requests` flag
- Architecture (TikTok chunked upload, Instagram resumable upload, credential-pattern reuse shape): HIGH - every mechanics-level claim traced to official docs' own example request/response bodies, either fetched directly or corroborated via WebSearch summaries of the same official pages
- Architecture (Instagram Standard-vs-Advanced-Access applicability to this project — Open Questions #1 / Assumption A2): MEDIUM - the mechanism is real and documented, but this session could not directly fetch Meta's App Review page (network error) to confirm every nuance, and it has not been tested against this project's actual not-yet-registered Meta App; flagged as a checkpoint:human-verify item for the planner, not treated as settled fact
- Audit/review timelines (both platforms): MEDIUM - no official SLA published by either platform; secondary-source estimates only, explicitly logged as Assumption A1
- Pitfalls: HIGH for Pitfalls 1/4/5 (directly derived from documented API response shapes and the absence of documented cancel/schedule primitives), MEDIUM for Pitfalls 2/3 (dependent on the same timeline/access-tier uncertainty as A1/A2 above)

**Research date:** 2026-07-09
**Valid until:** 2026-07-23 (14 days) — shorter than Phase 3's 30-day window because both platforms' review/audit policies and API surfaces (TikTok's Content Posting API, Instagram's Graph API version numbers like `v23.0`) are documented as changing more frequently than YouTube's stable Data API v3; re-verify audit timelines and the Standard-vs-Advanced-Access mechanism specifically before planning proceeds if execution slips past this window.
