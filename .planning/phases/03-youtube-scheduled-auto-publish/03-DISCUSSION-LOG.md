# Phase 3: YouTube Scheduled Auto-Publish - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-08
**Phase:** 3-youtube-scheduled-auto-publish
**Areas discussed:** Metadata generation timing, Publish trigger, OAuth token scope, Scheduling grid

---

## Metadata Generation Timing

| Option | Description | Selected |
|--------|-------------|----------|
| Generated earlier, at make-shorts time | Metadata already ready when a short enters the queue — no headless runner needed | ✓ |
| Generated at publish time (headless) | Would require building the deferred TAGS-02 headless/Ollama architecture now | |

**User's choice:** Earlier, at make-shorts time.
**Notes:** Resolves the open question Phase 2's D-03 left about when a "genuine headless runner" would arrive — it hasn't; Phase 3 doesn't need one.

---

## Publish Trigger

| Option | Description | Selected |
|--------|-------------|----------|
| Windows Task Scheduler, one-shot script | Runs periodically, checks queue, publishes what's due, exits | |
| Standalone daemon/service | Long-running process with its own lifecycle | |
| Manual command only | User runs "publish what's ready" whenever | |

**User's choice:** Free text — "а мы можем выкладывать в отложенные, да и писать тебе в чат закидывай раз в 3 часа готовые видосы по одному заебись вариант" (publish via YouTube's own scheduled/deferred release, and have the assistant check + upload roughly every 3 hours, one at a time, notifying in chat).
**Notes:** Follow-up confirmed: fully automatic after a single opt-in (no per-item confirmation), notification-only after the fact. Second follow-up added a manual on-demand override: user can say "выложи X сейчас" at any time to force-publish immediately, independent of the 3h cadence. Exact trigger mechanism (harness ScheduleWakeup vs OS Task Scheduler) left open for research/planning (D-06).

---

## OAuth Token Scope

| Option | Description | Selected |
|--------|-------------|----------|
| Separate upload_token.json | Own file, scope `youtube.upload`, gitignored like existing token.json | ✓ |
| Extend existing token.json | One token, broader scope, smaller footprint | |

**User's choice:** Separate `upload_token.json`.
**Notes:** Smaller blast radius given the project's prior real leaked-data incident (STATE.md Blockers/Concerns).

---

## Scheduling Grid

| Option | Description | Selected |
|--------|-------------|----------|
| Fixed daily grid, next free slot | N slots/day at fixed times; next queued short takes next free slot | ✓ |
| Explicit date/time per short | User manually sets time per item | |

**User's choice:** Fixed daily grid, next free slot.
**Notes:** Exact N and times left to Claude's discretion.

---

## Claude's Discretion

- Exact trigger implementation (ScheduleWakeup/CronCreate vs Task Scheduler vs other) — D-06
- Number/timing of daily publish slots — D-07
- Local queue/manifest file format and location
- Exact chat notification wording after an auto-publish

## Deferred Ideas

- Headless/API-based metadata (re)generation at publish time — still deferred, TAGS-02 lineage; only relevant if a future need for post-hoc metadata edits at publish time emerges.
- TikTok/Instagram publish (PUB-06/07) — Phase 6, gated behind external app-review/audit.
