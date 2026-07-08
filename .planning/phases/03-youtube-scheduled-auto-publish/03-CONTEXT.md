# Phase 3: YouTube Scheduled Auto-Publish - Context

**Gathered:** 2026-07-08
**Status:** Ready for planning

<domain>
## Phase Boundary

Finished shorts (video + metadata already produced by the existing make-shorts pipeline) are queued with sequential local numbering and auto-published to YouTube on a schedule, using YouTube's own native scheduled-publish feature (`privacyStatus: private` + `publishAt`). Dry-run is the default; a single explicit opt-in unlocks live behavior. Pause/kill and an idempotency manifest prevent runaway or duplicate posts. Covers PUB-01 through PUB-05. TikTok/Instagram (PUB-06/07) are out of scope — Phase 6.

</domain>

<decisions>
## Implementation Decisions

### Metadata Timing (resolves Phase 2's D-03 headless question for this phase)
- **D-01:** Titles/tags are generated **at make-shorts time** (during the interactive Claude Code session), same as today — NOT regenerated headlessly at publish time. Phase 3 only reads an already-finished `metadata.json`/equivalent per clip and uploads it as-is.
- **D-02 (rationale):** This means Phase 3 does **not** need the deferred headless-generation architecture (Ollama fallback / standalone Anthropic-SDK script, TAGS-02) — that remains deferred. "Finished shorts" in the ROADMAP wording means fully finished, metadata included, before they ever reach the publish queue.

### Publish Mechanism
- **D-03:** Actual "going live" uses YouTube's native scheduled-publish: video is uploaded now with `status.privacyStatus: "private"` and `status.publishAt` set to the target slot — YouTube itself flips it public at that timestamp. This is NOT our own pause-then-cron-push-public logic.
- **D-04:** Pause/kill (PUB-04) means: for videos NOT YET uploaded, skip/hold them in the local queue. For videos already uploaded-and-scheduled on YouTube, "kill" = call the Data API to set `privacyStatus` back to `private` with no `publishAt` (cancels the scheduled release) before the `publishAt` timestamp passes.

### Trigger / Cadence
- **D-05:** Two trigger paths, both required:
  1. **Periodic auto-check** — roughly every 3 hours, check the local queue for the next due item and upload+schedule it, then post a one-line notification in chat ("залил X, выйдет в HH:MM"). No per-item confirmation needed once live mode is opted into (single opt-in gates all future auto-uploads, satisfying PUB-03).
  2. **Manual on-demand override** — user can say "выложи X сейчас" at any time, independent of the 3h cadence, to force-publish a specific queued item immediately (still goes through the same upload+schedule path, just triggered out of band).
- **D-06 (open technical question for research/planning):** The exact mechanism behind "roughly every 3 hours" is NOT locked — user described the desired *behavior* (assistant periodically checks and acts, notifies in chat), not a specific OS mechanism. Two realistic options for research to evaluate: (a) this harness's own `ScheduleWakeup`/`CronCreate` self-waking mechanism (ties publishing to an active Claude Code session), or (b) a standalone Windows Task Scheduler entry running a one-shot `publish_queue.py` (works even without an open session, but can't post a chat notification — would need another way to surface status, e.g. writing to a log/manifest the user can check). Planner should pick one and justify it; either satisfies the locked behavior in D-05.

### Scheduling Grid
- **D-07:** `publishAt` slots come from a **fixed daily grid** (e.g., N slots/day at fixed times), not per-video manual dates. The next queued (lowest-numbered/oldest) finished short takes the next free slot. Exact N and times are Claude's discretion (research typical upload cadence / no strong user preference stated beyond "fixed grid").

### OAuth Credential Storage
- **D-08:** Upload uses a **separate `upload_token.json`** (own OAuth consent, scope `https://www.googleapis.com/auth/youtube.upload`), distinct from `youtube_analytics.py`'s existing read-only `token.json` (scopes: `youtube.readonly` + `yt-analytics.readonly`). Reuses the same `load_credentials()`-style pattern (parameterized by scopes/token path already exists in `scripts/youtube_analytics.py`) rather than inventing a new OAuth flow.
- **D-09 (rationale):** Smaller blast radius if one token leaks — directly relevant given this project's prior real leaked-data incident (see STATE.md Blockers/Concerns). `client_secret.json`/`token.json`/`upload_token.json` all stay gitignored, same discipline as the existing pattern.

### Claude's Discretion
- Exact trigger implementation (ScheduleWakeup vs Task Scheduler vs other) — see D-06.
- Exact number/timing of daily publish slots (D-07).
- Local queue file format/location (likely a manifest alongside existing `work/` conventions — planner to decide, consistent with idempotency manifest requirement PUB-05).
- Exact wording/format of the chat notification after an auto-publish.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Existing OAuth/upload pattern (this phase extends)
- `scripts/youtube_analytics.py` — `load_credentials(client_secret_path, token_path, scopes)` (lines ~30-55): existing generic OAuth pattern (InstalledAppFlow, token caching, refresh) to reuse for the new upload-scoped token. Current scopes are read-only (`youtube.readonly`, `yt-analytics.readonly`) — Phase 3 needs `youtube.upload` added via a separate token file (D-08).
- `.gitignore` — already excludes `client_secret.json` and `token.json`; add `upload_token.json` to the same list.

### Phase 2 artifacts (consumed by this phase)
- `.planning/phases/02-llm-title-tag-generation/02-CONTEXT.md` — D-01/D-02/D-03 established that metadata generation happens in the orchestrator session, not a headless script; D-03 explicitly named a future "headless runner" as the trigger for revisiting TAGS-02 — this phase's D-01/D-02 above confirm that trigger has NOT arrived yet (metadata is still baked in before the queue, not regenerated headlessly).
- `scripts/metadata.py` — per-platform metadata schema; Phase 3 reads whatever this already produces for YouTube (`title`/`description`/`tags[]`), does not modify it.

### Requirements / roadmap
- `.planning/REQUIREMENTS.md` — PUB-01 through PUB-05 (Phase 3 scope), PUB-06/07 (Phase 6, out of scope here)
- `.planning/ROADMAP.md` — Phase 3 detail block

### Project-level constraints (apply to this phase)
- `.planning/PROJECT.md` — "Приватность"/OAuth credential discipline directly shapes D-08/D-09
- `.planning/STATE.md` Blockers/Concerns — prior leaked-data incident is why token separation (D-08) matters, not just theoretical hygiene

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `scripts/youtube_analytics.py::load_credentials` — generic, already parameterized by `client_secret_path`/`token_path`/`scopes` — reusable as-is for the upload token, just call it with a different token path and the upload scope.
- `scripts/metadata.py` — per-clip metadata already in the shape the YouTube upload call needs (`title`, `description`, `tags[]`).

### Established Patterns
- Fail-open pattern used throughout Phase 1/2 (missing profile/analytics data degrades gracefully) — Phase 3's dry-run default (PUB-03) is this same philosophy applied to publishing: default OFF for anything irreversible until explicit opt-in.
- Gitignored credential files (`client_secret.json`, `token.json`) — same treatment required for `upload_token.json`.

### Integration Points
- New local queue/manifest tracking: which finished shorts are queued, their sequential numbers (PUB-01), publish status, and already-published state (idempotency, PUB-05) — no existing manifest to extend; this is new state.
- YouTube Data API `videos.insert` (upload) + `videos.update` (privacyStatus/publishAt changes for pause/kill) — new API surface beyond the existing read-only Data/Analytics calls in `youtube_analytics.py`.

</code_context>

<specifics>
## Specific Ideas

- User's exact words on cadence: "закидывай раз в 3 часа готовые видосы по одному" (throw in the ready videos one at a time every 3 hours) — one video per cycle, not a batch dump.
- User explicitly also wants an out-of-band manual override: "я мог написать сейчас выложи это '...' и да должно автоматически" (I could write right now 'publish this' and yes it should be automatic) — no separate confirmation gate for the manual path either, once live mode is opted in.
- Publish mechanism should lean on YouTube's own scheduled-publish feature rather than the pipeline holding videos back and pushing them public itself — user confirmed with "выкладывать в отложенные" (publish as scheduled/deferred).

</specifics>

<deferred>
## Deferred Ideas

- **Headless/API-based metadata (re)generation at publish time** — still deferred (TAGS-02 lineage); not needed since D-01 confirms metadata is baked in before the queue. Revisit only if a future need for post-hoc metadata edits at publish time emerges.
- **TikTok/Instagram publish** (PUB-06/07) — explicitly Phase 6, gated behind external app-review/audit; not discussed here.

None else — discussion stayed within phase scope beyond the items above.

</deferred>

---

*Phase: 03-youtube-scheduled-auto-publish*
*Context gathered: 2026-07-08*
