# Phase 2: LLM Title/Tag Generation - Context

**Gathered:** 2026-07-07
**Status:** Ready for planning

<domain>
## Phase Boundary

Pipeline proposes ready-to-use titles and tags per clip, grounded in the creator's own naming style via few-shot examples from Phase 1's `style_profile.json`. This is a refinement of the *existing* metadata-writing step (`SKILL.md` step 5 / `scripts/metadata.py`), not a new subsystem — no new Python script, no new API client, no new billing path.

</domain>

<decisions>
## Implementation Decisions

### API Architecture
- **D-01:** No new Python script / no `anthropic` SDK dependency for Phase 2. Title/tag generation is done by the current Claude Code orchestrator session itself, extending `SKILL.md` step 5's existing metadata-writing prompt to read `work/_profile/style_profile.json` and use its `naming_examples` as concrete few-shot grounding when writing the title.
- **D-02 (rationale, ties to PROJECT.md "Локальность" constraint):** Calling the Claude API from a separate Python script would be a *second, separately-billed* Claude call duplicating work the orchestrator already does for free within the user's own Claude Code session — a genuinely new network/cost dependency the locality principle exists to avoid. Extending the existing orchestrator prompt adds zero new network dependency and zero new cost.
- **D-03 (deferred, not built now):** A standalone script with Anthropic SDK + Ollama fallback (matching the literal ROADMAP wording "falls back to Ollama if Claude API unavailable") is deferred to whenever a genuine headless/non-interactive runner exists — most likely alongside Phase 6 (scheduled auto-publish), which needs to generate metadata without a live Claude Code session watching it. TAGS-02 (Ollama fallback) is NOT implemented in Phase 2's plans; tracked as a Phase 6-adjacent follow-up.
- **Project-level principle reinforced (not phase-specific):** avoid recurring paid-API costs anywhere a free/local alternative exists — this is the same spirit as PROJECT.md's existing "Локальность" constraint, now explicitly confirmed to also mean "avoid a second paid LLM call when the current session can already do the job for free."

### Output Format
- **D-04:** Titles are **per-platform**, not one title reused everywhere — matches `metadata.py`'s existing per-platform structure (YouTube gets `title`+`description`+`tags[]`; TikTok/Instagram get `caption` only, hashtags inline in text). YouTube titles skew longer/SEO-leaning; TikTok/Instagram skew shorter and hookier, consistent with how `metadata.py` already separates YouTube from TikTok/Instagram fields.
- **Tags** (structured list) only exist for the YouTube platform field today — TikTok/Instagram tags are hashtags embedded in the caption text, not a separate field. Phase 2 does not need to invent a new tags field for TikTok/Instagram; it improves what's already generated for the `tags` list (YouTube) and caption hashtags (TikTok/Instagram) by grounding word choice/style in the profile.

### Few-Shot from Style Profile
- **D-05:** Phase 2 consumes only `style_profile.json`'s `naming_examples` field for few-shot title/tag grounding. `moment_examples` is explicitly NOT used or "fixed" in this phase.
- **D-06 (rationale):** `naming_examples` and `moment_examples` are currently byte-identical (`scripts/style_profile.py::derive_profile` builds both from the same `{title, signal}` ranked list) because the only data source (`youtube_analytics.py`) has no per-video moment/timestamp content — YouTube's API cannot return "which part of the video was clipped," and the only place that ever existed (`work/<video>/PLAN.json`) is gitignored/ephemeral and not reliably retained. Fixing `moment_examples` for real would require reconstructing historical `PLAN.json` data that likely doesn't exist on disk — out of scope for both Phase 1 (already shipped) and Phase 2 (different job: title/tag wording, not moment-selection).

### Claude's Discretion
- Exact number of few-shot examples pulled from `naming_examples` per generation call (profile already caps at top-10; planner/implementer may use fewer per prompt if it improves quality).
- Exact prompt wording/structure for injecting few-shot examples into the step 5 metadata-writing instructions.
- Tag count/length conventions per platform beyond what `metadata.py`/`docs/metadata-writing-ru.md` already establish.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase 1 artifacts (consumed by this phase)
- `scripts/style_profile.py` — produces `work/_profile/style_profile.json`; `naming_examples` is the field this phase consumes (see D-05/D-06 above for why `moment_examples` is out)
- `scripts/monetization_risk.py`, `scripts/monetization_audio.py` — sibling Phase 1 outputs merged into the same per-clip metadata; not directly relevant to title/tag generation but share the same metadata pipeline stage

### Existing metadata pipeline (this phase extends, does not replace)
- `scripts/metadata.py` — per-platform metadata rendering; defines the exact schema (`title`/`description`/`tags[]` for YouTube, `caption` for TikTok/Instagram) that generated titles/tags must fit into
- `scripts/config.py` (`MetadataConfig`, `METADATA_PLATFORMS`) — existing `metadata.enabled`/`platforms`/`language` config this phase's config additions (if any) should sit alongside
- `SKILL.md` step 5 — the existing Claude-orchestrated metadata-writing pass this phase's few-shot grounding is added to (exact doc TBD — planner should locate the step 5 instructions/prompt text, likely in `SKILL.md` itself or a referenced `docs/metadata-writing-ru.md`)

### Project-level constraints (apply to this phase)
- `.planning/PROJECT.md` — "Локальность" and "Fail-open" constraints directly shape D-01/D-02/D-03 above; "Приватность" constraint applies since style profile few-shot examples are read from a gitignored, non-committed cache

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `work/_profile/style_profile.json` (Phase 1 output) — ready to read as-is; `naming_examples: [{title, signal}]` top-10, no further processing needed
- `scripts/metadata.py::render_metadata_text` — existing per-platform rendering function; title/tags generated by this phase feed straight into its existing `platforms_data` dict shape, no schema change needed

### Established Patterns
- Fail-open: if `style_profile.json` is missing or empty (e.g., channel has no upload history yet, or Analytics API was unreachable per Phase 1's `load_analytics_cache` warning), the orchestrator must still generate a title/tags without few-shot grounding rather than aborting metadata generation — same pattern as diarization/audio-energy/analytics.
- Privacy: `naming_examples` titles are real historical channel data (creator's own past video titles) — this is why they live only in the gitignored `work/_profile/` cache, never committed. This phase must not copy those titles anywhere that could end up in git (docs, comments, committed fixtures).

### Integration Points
- `SKILL.md` step 5 (or its referenced metadata-writing doc) is the single integration point — this phase is a prompt/instruction change there, informed by whatever `work/_profile/style_profile.json` contains for the current run.

</code_context>

<specifics>
## Specific Ideas

- User explicitly rejected a new Anthropic-SDK script for this phase specifically because it would be a second paid Claude call duplicating what the current session already does for free — this is a strong, explicit preference, not just a cost estimate.
- Ollama fallback (TAGS-02) and a fully-local/free headless generation path are user-acknowledged as real future needs, tied to Phase 6 (scheduled auto-publish) rather than Phase 2.

</specifics>

<deferred>
## Deferred Ideas

- **TAGS-02 (Ollama fallback) implementation** — deferred until a genuine headless/non-interactive runner exists (expected around Phase 6, auto-publish). Phase 2's plans should not attempt to build Ollama fallback logic; REQUIREMENTS.md may need a note that TAGS-02 is satisfied later, not in Phase 2, if the planner can't find a way to meaningfully address it without the API-script architecture.
- **Fixing `style_profile.json`'s `moment_examples`** — would require recovering historical per-clip `PLAN.json` data that is gitignored/ephemeral and likely not retained; not attempted in Phase 2 or any currently-planned phase.
- **Fully-local/free headless generation (Ollama-only, no Claude at all)** — noted as the "genuinely free" option for a future automated/scheduled context; not needed now since Phase 2 already has zero marginal cost via the current session.

None — discussion stayed within phase scope beyond the items above.

</deferred>

---

*Phase: 02-llm-title-tag-generation*
*Context gathered: 2026-07-07*
