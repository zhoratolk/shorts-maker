# Phase 2: LLM Title/Tag Generation - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-07
**Phase:** 02-llm-title-tag-generation
**Areas discussed:** API Architecture, Ollama Fallback, Output Format, Few-Shot from Style Profile

---

## API Architecture

| Option | Description | Selected |
|--------|-------------|----------|
| New script (`llm_metadata.py`) | Anthropic SDK + Ollama client, own module like `youtube_analytics.py`. Matches ROADMAP wording literally, testable with mocks. Adds a new network dependency and a second, separately-billed Claude call on top of the already-running Claude Code session. | |
| Extend SKILL.md step 5 | Claude Code (already running) writes title/tags itself, reading few-shot from `style_profile.json`. Zero new network dependency, zero extra cost. Ollama fallback only meaningful in a hypothetical headless mode, which doesn't exist yet. | ✓ |

**User's choice:** Extend SKILL.md step 5 (Option B). User asked for a fuller explanation before deciding, then confirmed explicitly: "давай б" ("let's go with B").
**Notes:** User then asked whether it's possible to implement things "another way, for free" — clarified that Option B is already zero-marginal-cost (same Claude Code session, no separate API billing). User then stated the broader project philosophy: prefer free/local tooling wherever possible, including for future auto-publish — captured as a project-level principle reinforcement in CONTEXT.md, tied to the existing PROJECT.md "Локальность" constraint.

---

## Ollama Fallback

| Option | Description | Selected |
|--------|-------------|----------|
| Build now (script + fallback logic) | Only makes sense paired with the "new script" architecture option above. | |
| Defer to Phase 6 | No genuine "Claude API unavailable" scenario exists yet since Claude Code IS the generator; defer until a headless/scheduled runner exists (Phase 6, auto-publish). | ✓ |

**User's choice:** Deferred to Phase 6 (implicit, follows from the API Architecture decision — Option B has no fallback path to build).
**Notes:** TAGS-02 requirement is not implemented in Phase 2's plans as a result; see CONTEXT.md Deferred Ideas.

---

## Output Format

| Option | Description | Selected |
|--------|-------------|----------|
| One title for all platforms | Simpler, less work, single few-shot source. | |
| Per-platform title | YouTube longer/SEO, TikTok/Instagram shorter/hookier — matches how `metadata.py` already separates YouTube (title+description+tags[]) from TikTok/Instagram (caption only). | ✓ |

**User's choice:** Per-platform title.
**Notes:** No further questions on this area.

---

## Few-Shot from Style Profile

| Option | Description | Selected |
|--------|-------------|----------|
| Use only `naming_examples` | Sufficient for title/tag style grounding; `moment_examples` left as-is, not touched. | ✓ |
| Fix `moment_examples` in this phase | Would require reconstructing historical per-clip `PLAN.json` moment data, which is gitignored/ephemeral and likely not retained on disk — a different, out-of-scope job. | |

**User's choice:** Use only `naming_examples`.
**Notes:** User asked for a detailed explanation (in Russian) of why `naming_examples` and `moment_examples` are currently identical before agreeing. Explanation: YouTube's API has no per-video moment/timestamp data; the only place that ever existed (`work/<video>/PLAN.json`) is ephemeral/gitignored and not a reliable source. Fixing this is a separate, unscoped effort — not Phase 1's or Phase 2's job.

---

## Claude's Discretion

- Exact number of few-shot examples used per generation call (profile caps at top-10; fewer may be used per prompt).
- Exact prompt wording/structure for injecting few-shot examples into SKILL.md step 5.
- Tag count/length conventions per platform beyond what `metadata.py`/`docs/metadata-writing-ru.md` already establish.

## Deferred Ideas

- TAGS-02 (Ollama fallback) implementation — deferred to a Phase 6-adjacent effort once a headless/non-interactive runner exists.
- Fixing `style_profile.json`'s `moment_examples` — would need historical `PLAN.json` recovery; not attempted in any currently-planned phase.
- Fully-local/free headless generation (Ollama-only, no Claude at all) — noted as the genuinely-free option for a future automated/scheduled context.
