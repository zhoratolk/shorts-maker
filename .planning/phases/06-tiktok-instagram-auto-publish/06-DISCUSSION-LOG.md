# Phase 6: TikTok & Instagram Auto-Publish - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-09
**Phase:** 6-TikTok & Instagram Auto-Publish
**Areas discussed:** Build timing, Audit status, SELF_ONLY handling

---

## Build timing

| Option | Description | Selected |
|--------|-------------|----------|
| Build now, gate on config per-platform | Code + dry-run ready now; real publish flips on per-platform once audit clears | ✓ |
| Wait for audit confirmation first | Don't write code until at least one platform's audit clears | |

**User's choice:** Build now, gate on config per-platform.
**Notes:** User added: also wire up the actual platform API connections now (not just code) — same as how YouTube's connection was set up in Phase 3. Captured as D-02/D-03 in CONTEXT.md.

---

## Audit/review status

| Option | Description | Selected |
|--------|-------------|----------|
| Nothing submitted yet | Plan must include an "apply for audit" checklist step for the user | ✓ |
| Already submitted/in progress | Plan can reference real pending credentials | |

**User's choice:** Nothing submitted yet.
**Notes:** Both TikTok Content Posting API access and Instagram Business account/Meta App Review need to be filed by the user — external, days-to-weeks, cannot be done by an executor agent.

---

## SELF_ONLY visibility handling

| Option | Description | Selected |
|--------|-------------|----------|
| Detect + notify in chat | One-line chat notification if still SELF_ONLY post-publish, no auto-retry | ✓ |
| Detect + auto-retry visibility flip | Attempt an automatic visibility-change call first, notify only on failure | |

**User's choice:** Detect + notify in chat.
**Notes:** Matches Phase 3's existing auto-publish notification style — no new automated retry mechanism.

---

## Claude's Discretion

- Exact TikTok Developer Portal / Meta App test-mode credential acquisition steps (research to confirm 2026 flow)
- Per-platform config flag structure (shared PublishConfig fields vs. sibling dataclasses)
- Credential file naming for the two new platforms

## Deferred Ideas

None — discussion stayed within phase scope.
