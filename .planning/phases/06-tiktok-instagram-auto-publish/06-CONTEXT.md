# Phase 6: TikTok & Instagram Auto-Publish - Context

**Gathered:** 2026-07-09
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 3 already built the full YouTube auto-publish mechanism: dry-run-default, native scheduled-publish, pause/kill safety, periodic + on-demand triggers, fixed daily-slot grid, and a separate-OAuth-token credential pattern. This phase extends the *same* mechanism to TikTok (Content Posting API) and Instagram Reels (Graph API), each gated independently so one platform's app-review/audit delay never blocks the other or YouTube (Success Criteria #3). Scope is: build both integrations now (code + real API app connections), keep them in dry-run/private-only until each platform's own audit clears, and add the TikTok-specific SELF_ONLY post-publish visibility check. Not in scope: changing YouTube's existing behavior, or building a new trigger/scheduling mechanism (reuse Phase 3's).

</domain>

<decisions>
## Implementation Decisions

### Build timing
- **D-01:** Build both integrations now — do not wait for audit/review approval before writing code. Same dry-run-first posture as Phase 3 (PUB-03): code ships now, real (non-private) publishing gates behind a per-platform config flag that only flips on once that platform's audit is confirmed cleared.

### API connection setup (new for this phase, beyond Phase 3's scope)
- **D-02:** This phase includes actually setting up the real API connections for both platforms — not just the code, the credentials/app registration too — mirroring how Phase 3 set up YouTube's `client_secret.json` → OAuth consent → `upload_token.json` flow. Concretely: TikTok app registration in the TikTok Developer portal (sandbox/dev credentials, usable pre-audit for private/self-only testing) and Instagram's Meta App + Business account setup (Graph API test-mode token, usable pre-review for the same account's own private testing). Follow `scripts/youtube_analytics.py::load_credentials`'s parameterized-scopes pattern for both new platforms' credential loading, same as `scripts/publish_queue.py` already does for YouTube's `UPLOAD_SCOPE`.
- **D-03 (rationale):** The user explicitly wants the actual API hookup done alongside the code in this phase, not deferred as a "someday, once audited" afterthought — audit approval only gates *going public*, not building/wiring the integration.

### Audit/review status (factual, carried into plan as a checklist)
- **D-04:** As of this discussion, nothing has been submitted yet for either platform — no TikTok Content Posting API access request, no Instagram Business account/Meta App Review. The plan must include an explicit runbook step for the user to actually file both applications (external, days-to-weeks lead time per STATE.md Blockers/Concerns, outside developer control) — this is not something an executor agent can do on the user's behalf (requires the user's own developer/business accounts). Until each platform's audit clears, that platform's per-platform enable flag (see D-01) stays `false`, matching `publish.enabled`'s existing default-false discipline (PUB-03).

### SELF_ONLY visibility handling (TikTok pre-audit trap)
- **D-05:** Pre-audit TikTok posting is restricted to `SELF_ONLY` (private) — the Content Posting API returns success even when nothing actually goes public (documented trap in STATE.md Blockers/Concerns). Handle this the same way Phase 3 already surfaces auto-publish results: detect the returned visibility/privacy status after posting, and if it's still `SELF_ONLY` when the queue entry expected a real publish, post a one-line chat notification (same style as Phase 3's periodic-check notification) — no automatic retry/visibility-flip call.

### Claude's Discretion
- Exact TikTok sandbox/dev-mode credential acquisition steps (TikTok Developer Portal specifics) and exact Meta App/Graph API test-mode setup steps — research to confirm current (2026) exact flow for both.
- Whether TikTok/Instagram get one shared `PublishConfig`-style per-platform enabled flag pattern (e.g. `publish.tiktok_enabled` / `publish.instagram_enabled` fields) or separate dataclasses per platform — planner's call, following the existing `PublishConfig` structure in `scripts/config.py`.
- Credential file naming for the two new platforms (e.g. `tiktok_token.json`, `instagram_token.json`) — follow the existing `upload_token.json` naming convention, gitignored the same way.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope & requirements
- `.planning/ROADMAP.md` — Phase 6 section (Goal, Depends on: Phase 3, Requirements PUB-06/PUB-07, Success Criteria)
- `.planning/REQUIREMENTS.md` — PUB-06, PUB-07 (lines 46-47, 95-96)

### Phase 3 mechanism being extended (MUST reuse, not reinvent)
- `.planning/phases/03-youtube-scheduled-auto-publish/03-CONTEXT.md` — all of D-01 through D-09 (dry-run default, native scheduled-publish, pause/kill semantics, trigger cadence, daily-slot grid, credential-separation pattern and its leaked-scope-widening rationale)
- `scripts/publish_queue.py` — `enqueue`, `upload_and_schedule`, `cancel_scheduled_release`, `kill_item`, `UPLOAD_SCOPE` — the exact mechanism to mirror per-platform
- `scripts/youtube_analytics.py::load_credentials` — parameterized-scopes OAuth credential loader pattern to reuse for TikTok/Instagram tokens
- `scripts/config.py::PublishConfig` (lines 189-199) — `enabled` default-False discipline, `daily_slots_utc`, `client_secret_path`/`upload_token_path` naming pattern

### Known traps / blockers (from live Phase 3 incident + this project's own tracking)
- `.planning/STATE.md` Blockers/Concerns — TikTok SELF_ONLY pre-audit trap, external audit lead-time note, credential-storage-discipline note tied to this project's prior leaked-data incident
- `docs/publish-queue.md` — Phase 3's kill-path verification section, same safety-mechanism bar this phase's TikTok/Instagram integrations must meet

### Project-level constraints
- `.claude/CLAUDE.md` — "Необратимость авто-паблиша" constraint (dry-run mode, pausable schedule are architectural requirements, not one-off decisions) and "Приватность" constraint (no real channel data/credentials committed)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `scripts/youtube_analytics.py::load_credentials` — generic OAuth credential loader, already parameterized by scopes and token path; TikTok/Instagram credential loading should follow the same signature shape
- `scripts/publish_queue.py::enqueue`/`upload_and_schedule`/`kill_item` — the queue/upload/kill lifecycle this phase's two new platforms plug into, not duplicate
- `scripts/config.py::PublishConfig` — existing dataclass to extend (or sibling dataclasses to add) for per-platform settings

### Established Patterns
- **Dry-run-default, explicit opt-in to go live** (PUB-03, `PublishConfig.enabled: bool = False`) — the same default-False discipline must apply per-platform for TikTok/Instagram, not just globally.
- **Gitignored credential files** (`client_secret.json`, `token.json`, `upload_token.json`) — TikTok/Instagram credential files follow the same discipline, given this project's prior real leaked-data incident.
- **Chat notification on auto-action** (Phase 3's periodic-check "залил X, выйдет в HH:MM" pattern) — the SELF_ONLY detection (D-05) reuses this same notification channel/style rather than inventing a new one.

### Integration Points
- New TikTok/Instagram upload paths are new *callers* into the existing `publish_queue.py` queue/kill lifecycle, parameterized by platform — planner decides whether this is new functions in `publish_queue.py` or new sibling modules (e.g. `scripts/tiktok_publish.py`, `scripts/instagram_publish.py`), following the project's one-module-per-concern convention.

</code_context>

<specifics>
## Specific Ideas

- User explicitly wants the actual platform API connections (app registration, OAuth/token setup) done as part of this phase's work, in parallel with the code — not deferred until "after the audit clears" (D-02/D-03).

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 6-TikTok-Instagram-Auto-Publish*
*Context gathered: 2026-07-09*
