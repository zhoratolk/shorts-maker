# Phase 2: LLM Title/Tag Generation - Research

**Researched:** 2026-07-07
**Domain:** Prompt-engineering / few-shot grounding within an existing Claude-Code-orchestrated documentation step (SKILL.md step 5) — NOT a new software subsystem
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**API Architecture**
- **D-01:** No new Python script / no `anthropic` SDK dependency for Phase 2. Title/tag generation is done by the current Claude Code orchestrator session itself, extending `SKILL.md` step 5's existing metadata-writing prompt to read `work/_profile/style_profile.json` and use its `naming_examples` as concrete few-shot grounding when writing the title.
- **D-02 (rationale, ties to PROJECT.md "Локальность" constraint):** Calling the Claude API from a separate Python script would be a *second, separately-billed* Claude call duplicating work the orchestrator already does for free within the user's own Claude Code session — a genuinely new network/cost dependency the locality principle exists to avoid. Extending the existing orchestrator prompt adds zero new network dependency and zero new cost.
- **D-03 (deferred, not built now):** A standalone script with Anthropic SDK + Ollama fallback (matching the literal ROADMAP wording "falls back to Ollama if Claude API unavailable") is deferred to whenever a genuine headless/non-interactive runner exists — most likely alongside Phase 6 (scheduled auto-publish), which needs to generate metadata without a live Claude Code session watching it. TAGS-02 (Ollama fallback) is NOT implemented in Phase 2's plans; tracked as a Phase 6-adjacent follow-up.
- **Project-level principle reinforced (not phase-specific):** avoid recurring paid-API costs anywhere a free/local alternative exists — this is the same spirit as PROJECT.md's existing "Локальность" constraint, now explicitly confirmed to also mean "avoid a second paid LLM call when the current session can already do the job for free."

**Output Format**
- **D-04:** Titles are **per-platform**, not one title reused everywhere — matches `metadata.py`'s existing per-platform structure (YouTube gets `title`+`description`+`tags[]`; TikTok/Instagram get `caption` only, hashtags inline in text). YouTube titles skew longer/SEO-leaning; TikTok/Instagram skew shorter and hookier, consistent with how `metadata.py` already separates YouTube from TikTok/Instagram fields.
- Tags (structured list) only exist for the YouTube platform field today — TikTok/Instagram tags are hashtags embedded in the caption text, not a separate field. Phase 2 does not need to invent a new tags field for TikTok/Instagram; it improves what's already generated for the `tags` list (YouTube) and caption hashtags (TikTok/Instagram) by grounding word choice/style in the profile.

**Few-Shot from Style Profile**
- **D-05:** Phase 2 consumes only `style_profile.json`'s `naming_examples` field for few-shot title/tag grounding. `moment_examples` is explicitly NOT used or "fixed" in this phase.
- **D-06 (rationale):** `naming_examples` and `moment_examples` are currently byte-identical (`scripts/style_profile.py::derive_profile` builds both from the same `{title, signal}` ranked list) because the only data source (`youtube_analytics.py`) has no per-video moment/timestamp content — YouTube's API cannot return "which part of the video was clipped," and the only place that ever existed (`work/<video>/PLAN.json`) is gitignored/ephemeral and not reliably retained. Fixing `moment_examples` for real would require reconstructing historical `PLAN.json` data that likely doesn't exist on disk — out of scope for both Phase 1 (already shipped) and Phase 2 (different job: title/tag wording, not moment-selection).

### Claude's Discretion
- Exact number of few-shot examples pulled from `naming_examples` per generation call (profile already caps at top-10; planner/implementer may use fewer per prompt if it improves quality).
- Exact prompt wording/structure for injecting few-shot examples into the step 5 metadata-writing instructions.
- Tag count/length conventions per platform beyond what `metadata.py`/`docs/metadata-writing-ru.md` already establish.

### Deferred Ideas (OUT OF SCOPE)
- **TAGS-02 (Ollama fallback) implementation** — deferred until a genuine headless/non-interactive runner exists (expected around Phase 6, auto-publish). Phase 2's plans should not attempt to build Ollama fallback logic; REQUIREMENTS.md may need a note that TAGS-02 is satisfied later, not in Phase 2, if the planner can't find a way to meaningfully address it without the API-script architecture.
- **Fixing `style_profile.json`'s `moment_examples`** — would require recovering historical per-clip `PLAN.json` data that is gitignored/ephemeral and likely not retained; not attempted in Phase 2 or any currently-planned phase.
- **Fully-local/free headless generation (Ollama-only, no Claude at all)** — noted as the "genuinely free" option for a future automated/scheduled context; not needed now since Phase 2 already has zero marginal cost via the current session.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| TAGS-01 | Pipeline generates title + tag candidates per clip via Claude API | Reframed by CONTEXT.md D-01/D-02: satisfied by the *existing* orchestrator session (the Claude Code instance running SKILL.md IS the "Claude API" call — there is no second network hop). See "Reconciling ROADMAP Wording vs. Locked Architecture" section below for how the planner should phrase requirement coverage. |
| TAGS-02 | Falls back to local Ollama model if Claude API is unavailable | Explicitly deferred per CONTEXT.md D-03. Cannot be satisfied inside Option-B architecture: there is no "Claude API unavailable" failure mode to fall back from when Claude Code itself is the generator — if the orchestrator session is running at all, generation is available by construction. Planner must document this as "not applicable in Phase 2's architecture; revisit at Phase 6" rather than silently dropping it or building unneeded Ollama plumbing. |
| TAGS-03 | Uses STYLE profile few-shot examples as concrete grounding (not prose description) so generated titles match creator's own voice | Directly actionable this phase — `naming_examples` already exists in the exact concrete `{title, signal}` shape needed (verified in `scripts/style_profile.py`/`tests/test_style_profile.py`). See "Few-Shot Prompt Injection Pattern" below. |
</phase_requirements>

## Summary

Phase 2 is fundamentally a **prompt-engineering change to a Markdown orchestration file** (`SKILL.md` step 5, "Per-platform metadata"), not a software-engineering phase. There is no new Python module, no new dependency, no new network call, and — per the locked CONTEXT.md architecture — no literal "Claude API" invocation distinct from the orchestrator session already running. The entire deliverable is: (1) read `work/_profile/style_profile.json`'s `naming_examples` field when it exists and is non-empty, (2) inject those real title+signal pairs into step 5's existing title/caption-drafting instructions as concrete few-shot examples ("here are 10 of this channel's own real titles ranked by performance — write in this voice"), and (3) fail open to today's behavior (draft from `docs/metadata-writing-ru.md`/`register-ru.md` alone, no few-shot grounding) when the profile is missing/empty.

The core research finding is that **concrete few-shot examples reliably outperform prose style descriptions** for voice-matching tasks — this is exactly what Phase 1's `naming_examples` was built to provide (real titles + real performance signal, never a "the creator's style is X" summary), and it is a well-established prompting pattern, not something specific to this codebase. The main planning risk is **not** technical implementation difficulty (there is almost none — this is markdown authoring) but **process/reconciliation risk**: ROADMAP.md and REQUIREMENTS.md describe TAGS-01/02 in the literal language of a second API call with an Ollama fallback, an architecture the user explicitly rejected during discuss-phase. The planner must decide how PLAN.md's task list and coverage table represent TAGS-01 (reframe as "satisfied via existing orchestrator, no separate API call") and TAGS-02 (explicitly marked deferred/out-of-scope-this-phase with a pointer to Phase 6), rather than either silently building the rejected architecture or silently dropping requirement coverage without a paper trail.

**Primary recommendation:** Treat this phase as a `SKILL.md` step-5 prompt-instruction edit plus (optionally) a tiny pure-Python helper (`scripts/style_profile.py`-adjacent, e.g. a `load_naming_examples`/`format_few_shot_block` function) that the orchestrator's Bash step can call to read+format the few-shot block deterministically, so the prompt injection isn't ad hoc every run. No SDK, no billing path, no Ollama code. Update REQUIREMENTS.md traceability notes for TAGS-01 (reframed) and TAGS-02 (deferred to Phase 6) as part of this phase's plan, with explicit human sign-off since this changes how a shipped requirement is interpreted.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Title/tag/caption generation (semantic judgment) | Orchestrator (Claude Code session reading SKILL.md) | — | This project has no "backend" tier — `ARCHITECTURE.md`'s explicit anti-pattern is "encoding semantic judgment in Python." Title-writing is exactly this kind of judgment call and belongs in the orchestrator prompt, same as candidate-finding/trimming/crop-style already do. |
| Few-shot example loading/formatting | Python (deterministic helper, optional) | Orchestrator (can also just read the JSON file directly via a Read/Bash step) | Loading `naming_examples` from `style_profile.json` and formatting it into a fixed few-shot block is a pure, testable, mechanical transform — matches the existing pattern of `scripts/*.py` owning deterministic transforms while `SKILL.md` owns judgment (see `scripts/style_profile.py`, `scripts/candidates.py`). |
| Per-platform metadata schema (title/description/tags/caption) | Python (`scripts/metadata.py`) | — | Already exists, unchanged by this phase — `render_metadata_text`/`METADATA_PLATFORMS` define the exact shape generated content must fit into. No schema change needed (confirmed by CONTEXT.md D-04). |
| Fail-open behavior when profile missing/empty | Orchestrator (SKILL.md instruction) | Python (`style_profile.py` already fails open to `{naming_examples: []}`) | Matches existing diarization/audio-energy/analytics fail-open pattern (`ARCHITECTURE.md` Error Handling section) — the orchestrator must degrade gracefully to "draft without grounding" rather than aborting metadata generation. |
| Requirement-traceability reconciliation (TAGS-01 reframe, TAGS-02 defer) | Documentation (REQUIREMENTS.md, this phase's PLAN.md) | — | Not a code tier at all — a project-management/traceability concern that must be resolved in writing so future readers don't think TAGS-02 was silently dropped. |

## Standard Stack

This phase adds **zero new dependencies**. No package installation, no SDK, no new library.

### Core
No new libraries. This phase reuses:

| Library/Module | Version | Purpose | Why Standard (for this repo) |
|---------|---------|---------|--------------|
| `scripts/style_profile.py` (existing) | n/a (in-repo) | Produces `work/_profile/style_profile.json` with `naming_examples` | Phase 1 output — the exact concrete-few-shot artifact this phase consumes as-is, no changes needed to its schema |
| `scripts/metadata.py` (existing) | n/a (in-repo) | Renders final per-platform metadata text | Defines the exact output shape (`title`/`description`/`tags[]` YouTube; `caption` TikTok/Instagram) generated content must fit into |
| `SKILL.md` (Markdown, orchestrator prompt) | n/a | The actual site of this phase's change | Per CONTEXT.md D-01, this is the entire "implementation" |

### Supporting
| Optional helper | Purpose | When to Use |
|---------|---------|-------------|
| A small `scripts/style_profile.py`-adjacent function, e.g. `format_naming_examples_block(profile, limit=N) -> str` | Deterministically renders the top-N `naming_examples` into a fixed textual few-shot block (e.g. numbered list of `"{title}" (perf: {signal})`) that the orchestrator reads verbatim rather than reformatting ad hoc each run | Use if the planner wants prompt-injection formatting to be unit-testable and stable across runs (recommended — matches this repo's existing pattern of pure/testable helper functions backing every orchestrator step). Not required by CONTEXT.md, but low-cost and consistent with `naming.py`/`candidates.py`'s pure-function style. |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Orchestrator reads `style_profile.json` directly via a Read/cat step in SKILL.md, no Python helper | A new `format_naming_examples_block` pure function in `scripts/style_profile.py` | Direct-read is zero extra code and matches "prompt-engineering only" spirit most literally; the helper function adds one small testable unit but is not strictly required. Recommend the helper only if the planner wants deterministic/consistent formatting across runs and an automated test asserting fail-open behavior — otherwise direct read-and-format-in-prompt is acceptable and arguably more in the spirit of D-01 ("no new Python script"). |
| A standalone `scripts/generate_metadata.py` + `anthropic` SDK + Ollama fallback (the literal ROADMAP/REQUIREMENTS wording) | Extending SKILL.md step 5 in place (locked, D-01/D-02/D-03) | REJECTED by user during discuss-phase — do not propose this as an option to the planner; it is out of scope for Phase 2 entirely. |

**Installation:** None. No `pip install` step for this phase.

**Version verification:** Not applicable — no packages installed.

## Package Legitimacy Audit

**Not applicable.** This phase installs no external packages (no new Python script, no `anthropic` SDK, no Ollama client library) per CONTEXT.md D-01/D-02/D-03. Skip the Package Legitimacy Gate entirely — there is nothing to audit.

## Architecture Patterns

### System Architecture Diagram

```text
┌─────────────────────────────────────────────────────────────────────┐
│  SKILL.md Step 5 (existing, this phase extends in place)             │
│                                                                        │
│  1. Orchestrator reads work/_profile/style_profile.json (if exists)  │
│     └─ NEW in Phase 2: read + surface `naming_examples` field         │
│  2. IF naming_examples non-empty:                                     │
│       inject top-N {title, signal} pairs as a concrete few-shot       │
│       block into the title/caption drafting instructions              │
│     ELSE (missing/empty profile — fail open):                         │
│       draft using existing docs/metadata-writing-ru.md +              │
│       register-ru.md guidance alone, exactly as today                 │
│  3. Draft title/description/tags (YouTube) or caption (TikTok/IG)     │
│     grounded in: game_context.txt (if visual pass ran) +               │
│     hook-formula table + anti-AI-tone filter + NEW few-shot block      │
│  4. Run drafted text through existing anti-AI-tone / register filters │
│  5. Write per-platform JSON → scripts/metadata.py renders final .txt  │
└───────────────────────────────┬───────────────────────────────────────┘
                                 ▼
                  scripts/metadata.py::render_metadata_text
                  (UNCHANGED — same schema, same function)
                                 ▼
                  <output_dir>/<clip_filename_stem>.txt
                  (final artifact, sits beside rendered .mp4)
```

Entry point: SKILL.md step 5 (existing). Decision point: profile present/non-empty vs. missing/empty (fail-open branch). External dependency: none new — `work/_profile/style_profile.json` is Phase 1's own gitignored cache, read locally, no network call.

### Recommended Project Structure

No new files are structurally required. If the planner adds the optional formatting helper:

```
scripts/
├── style_profile.py       # MODIFIED (optional): add format_naming_examples_block()
docs/
├── metadata-writing-ru.md  # MODIFIED: add few-shot injection guidance (how/when to use naming_examples)
SKILL.md                    # MODIFIED: step 5 "Per-platform metadata" section
tests/
├── test_style_profile.py   # MODIFIED (if helper added): tests for format_naming_examples_block
```

### Pattern 1: Concrete Few-Shot Grounding (not prose style description)

**What:** Provide the LLM with N real, concrete examples of the target output (real past titles + a numeric performance signal) rather than a prose description like "the creator's style is punchy and uses numbers." Concrete examples let the model pattern-match on actual word choice, sentence length, and phrasing; prose descriptions get paraphrased into generic-sounding text.

**When to use:** Any generation task where "sound like X" is the goal and real X examples exist. This is exactly `naming_examples`'s purpose (see `scripts/style_profile.py::derive_profile` docstring: "Every example carries an actual title string plus its real performance signal — never a prose description of 'the creator's style'").

**Example (prompt-injection shape, not code — this is a Markdown/prompt pattern, not a library call):**
```text
# Source: established few-shot prompting practice (this repo's own Phase 1
# design already implements the concrete-example half of this pattern —
# scripts/style_profile.py's derive_profile docstring/tests)

Ground the title in the creator's own real historical titles below,
ranked by real performance signal (higher = performed better on this
channel). Match their tone, length, and structure — do not copy a title
verbatim, and do not write a generic-sounding "AI" title once you've
looked at these:

1. "{naming_examples[0].title}" (signal: {naming_examples[0].signal})
2. "{naming_examples[1].title}" (signal: {naming_examples[1].signal})
...
```

**Why ranking matters (performance signal in the prompt):** Including the numeric signal alongside each title gives the model an implicit weighting signal — "examples near the top of this list are the strongest reference for tone," without needing separate reasoning about which examples matter more. This is a low-cost addition since `naming_examples` already carries `signal` (Phase 1 output, unchanged).

### Pattern 2: Fail-Open Grounding (matches existing repo convention)

**What:** If `work/_profile/style_profile.json` doesn't exist, or exists but `naming_examples` is an empty list (e.g., brand-new channel with no upload history, or Phase 1's own fail-open path triggered because the Analytics cache was unreachable), the orchestrator must still draft a title/tags/caption using only the existing `docs/metadata-writing-ru.md`/`register-ru.md` guidance — never abort metadata generation, never block the pipeline on this.

**When to use:** Always — this is a hard requirement carried over from the existing pattern (`ARCHITECTURE.md`: "Fail-open optional features: diarization and audio-energy both degrade silently... rather than aborting"), and CONTEXT.md's Established Patterns section states it explicitly for this phase.

**Example (SKILL.md instruction shape):**
```text
Before drafting title/tags, check whether `work/_profile/style_profile.json`
exists and its `naming_examples` list is non-empty. If so, use it per
Pattern 1 above. If the file is missing, unreadable, or `naming_examples`
is empty, skip the few-shot block entirely and draft exactly as today —
this is not an error condition, do not mention it to the user unless they
ask.
```

### Pattern 3: Hook-Formula Rotation Still Applies (existing, unaffected)

**What:** SKILL.md step 5 already tracks which hook formula (Confession, Number shock, Inversion, etc. from `docs/metadata-writing-ru.md`) each clip in a run used, to avoid repeating the same formula across a batch. Few-shot grounding from `naming_examples` is a *complementary* signal (word choice/register/length), not a replacement for hook-formula selection (content/structure). Both apply together: pick a hook formula that fits the moment, then write it in the voice the few-shot examples demonstrate.

**When to use:** Every clip, exactly as today — Phase 2 does not change hook-rotation logic, only adds voice-grounding on top of it.

### Anti-Patterns to Avoid

- **Building a second Claude API call:** Explicitly rejected (CONTEXT.md D-01/D-02). Do not propose a `scripts/generate_metadata.py` with an `anthropic` SDK import, even as a "future-proofing" measure — that architecture is deferred to Phase 6, not built speculatively now.
- **Prose style summaries instead of concrete examples:** Do not have the orchestrator write itself a sentence like "this channel's style is punchy and short" and use that as the grounding — this defeats the entire purpose of `naming_examples` being concrete (PITFALLS.md Pitfall 5, referenced in Phase 1's own code comments and tests).
- **Copying a real title verbatim:** Few-shot examples are for tone-matching, not for reuse — a generated title identical or near-identical to a real past title both defeats the purpose (it's not describing *this* clip) and risks looking like duplicate/spam content if two clips end up with the same title.
- **Silently building Ollama fallback anyway "just in case":** TAGS-02 is deferred, not optional-but-nice-to-have-now — building it prematurely reintroduces the rejected architecture (a standalone script needing its own invocation path) without the headless-runner context (Phase 6) that would justify it.
- **Leaking real historical titles into committed files:** `naming_examples` titles are real per-channel data. Any doc/example/test fixture this phase adds must use fabricated example titles (e.g. "Boss Rage Quit Moment" — see `tests/test_style_profile.py`'s own fixtures), never copy-paste a real title from a live `style_profile.json` into a committed file.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| "Make the LLM sound like this channel" | A rules-engine that tries to encode "style" as parseable heuristics (banned-word lists, sentence-length caps enforced in Python, etc.) | Concrete few-shot examples in the prompt (Pattern 1) + existing `docs/metadata-writing-ru.md` anti-AI-tone filter (already a rules-based backstop, not a new one) | The project's own `ARCHITECTURE.md` anti-pattern already warns against "encoding semantic judgment in Python" — style-matching is squarely semantic judgment, and the anti-AI-tone filter already exists as the deterministic backstop; no new rules system needed. |
| "Detect whether the LLM successfully matched style" | An automated style-similarity scorer (embeddings/cosine-similarity against `naming_examples`) | Manual/human spot-check against real few-shot examples, as literally specified in the phase's own success criterion 3 ("verified by comparing against real few-shot examples") | Building an automated style-similarity metric is a v2-scale investment (embeddings pipeline, threshold tuning) disproportionate to a prompt-engineering phase; the ROADMAP success criterion itself specifies manual comparison, not an automated score. |

**Key insight:** This phase's entire "don't hand-roll" surface is narrow because there is almost no code — the temptation to over-engineer here is building software (a scorer, a rules engine, a fallback script) where a prompt instruction and a human spot-check suffice.

## Runtime State Inventory

**Not applicable — this is not a rename/refactor/migration phase.** Phase 2 adds prompt-instruction text and possibly one small pure-Python helper function; it does not rename any identifier, string, key, or file that could have runtime state elsewhere (no stored data keys change, no OS-registered state, no secrets renamed, no build artifacts affected). Confirmed by reviewing CONTEXT.md's Integration Points (single integration point: SKILL.md step 5) and the phase's own Locked Decisions (no new script, no new schema).

## Common Pitfalls

### Pitfall 1: Reframing TAGS-01 without a paper trail

**What goes wrong:** The planner marks TAGS-01 "complete" in PLAN.md's coverage table without noting that the *literal* requirement text ("via the Claude API") was reinterpreted — a future reader (or a `/gsd-verify-work` session) sees "TAGS-01: done" and assumes a genuine second API call exists, then is confused when they can't find it in the codebase.
**Why it happens:** REQUIREMENTS.md and ROADMAP.md were both written *before* the discuss-phase session that rejected the literal-API architecture; nothing currently marks the reinterpretation.
**How to avoid:** PLAN.md's requirement-coverage section must explicitly state the reframing (e.g., "TAGS-01 satisfied via the orchestrator session itself acting as the LLM call — no separate Claude API invocation or billing path; see 02-CONTEXT.md D-01/D-02 for the locked rationale"). Consider a one-line REQUIREMENTS.md annotation too, since this is a durable project-level clarification, not just a planning artifact.
**Warning signs:** If the PLAN.md verification/coverage table for TAGS-01 references any Python file, API key, or SDK call — that's a red flag the plan drifted back toward the rejected architecture.

### Pitfall 2: Silently dropping TAGS-02 instead of documenting deferral

**What goes wrong:** TAGS-02 quietly disappears from Phase 2's plan with no note, and a later audit (`gsd-audit-uat`, `gsd-verify-work`, or a human reviewer) can't tell whether it was forgotten, intentionally descoped, or actually implemented somewhere.
**Why it happens:** Since TAGS-02 genuinely cannot be satisfied within the Option-B architecture (there is no "Claude API unavailable" state to fall back from when the orchestrator itself is the generator), it's tempting to just omit it from the plan's requirement table entirely.
**How to avoid:** Include TAGS-02 in the plan's coverage table with an explicit status like "Deferred — not applicable to Phase 2's architecture (no separate API call exists to fail over from); tracked for Phase 6 (auto-publish/headless runner)" rather than omitting the row. Cross-reference `.planning/STATE.md`'s Blockers/Concerns or REQUIREMENTS.md's Traceability table so the deferral is visible project-wide, not just phase-locally.
**Warning signs:** REQUIREMENTS.md's Traceability table still shows "TAGS-02 | Phase 2 | Pending" after Phase 2 closes, with no note anywhere explaining the pending status is permanent-for-this-phase rather than an oversight.

### Pitfall 3: Treating `naming_examples` as if it always exists

**What goes wrong:** SKILL.md instructions assume `work/_profile/style_profile.json` is always present with data, breaking (or silently degrading in a confusing way) for: (a) a channel with zero upload history, (b) a fresh clone/setup where `scripts/youtube_analytics.py`'s OAuth flow was never run, (c) Phase 1's own fail-open path where `naming_examples` legitimately comes back as `[]`.
**Why it happens:** During phase planning/testing, the developer's own `style_profile.json` will likely already exist and be non-empty (Phase 1 shipped, presumably run at least once) — masking the missing/empty case until a real user without that history hits it.
**How to avoid:** Explicitly write and test the fail-open branch (Pattern 2) as its own instruction path in SKILL.md, and if a Python helper is added, unit-test its behavior on an empty `naming_examples` list the same way `tests/test_style_profile.py::test_derive_profile_empty_input_fails_open` already tests `derive_profile`.
**Warning signs:** SKILL.md's new step-5 wording reads "read the naming_examples and use them..." with no conditional language for the missing/empty case.

### Pitfall 4: Few-shot examples leaking into committed files

**What goes wrong:** A test fixture, a docs example, or debug output copies a *real* title from a live `style_profile.json` into something that gets committed — recreating the exact incident PROJECT.md documents (real channel stats leaked into `docs/viral-clips-ru.md`, requiring a git-history rewrite).
**Why it happens:** It's tempting to use "a realistic example" when writing prompt-injection documentation, and a developer might paste from their own actually-generated profile for authenticity.
**How to avoid:** Any illustrative example in `docs/metadata-writing-ru.md` or `SKILL.md` must use obviously-fabricated titles (following the existing convention in `tests/test_style_profile.py`, e.g. "Boss Rage Quit Moment", "Clutch 1v5 Ace") — never a real title, even a redacted-looking one.
**Warning signs:** Any commit diff touching `docs/*.md` or `SKILL.md` that includes a title string not already present in the existing fabricated-example vocabulary should be double-checked before committing.

### Pitfall 5: Generic-sounding output despite grounding (weak prompt injection)

**What goes wrong:** The few-shot block is added to the prompt, but worded so weakly (e.g., buried after other instructions, or phrased as "you may also look at these examples if helpful") that the model still defaults to generic AI-sounding phrasing — silently defeating success criterion 3 without any error or fail-open condition to catch it.
**Why it happens:** Prompt position and imperative framing both matter for how strongly a model weights few-shot examples; a passive/optional framing gets deprioritized against other instructions in the same step.
**How to avoid:** Place the few-shot block prominently (near the top of the title/caption-drafting instructions, not buried after unrelated content-warning/hook-rotation text) and phrase it as a direct instruction ("ground the title in these real examples," not "you may consider these"). Verify manually per the phase's own success criterion 3 — run the pipeline against a real profile and compare 2-3 generated titles against the `naming_examples` list side-by-side.
**Warning signs:** Generated titles read identically whether or not `naming_examples` was present/empty for the run — a sign the grounding instruction isn't actually changing model behavior.

## Code Examples

No conventional "code examples" apply — this phase's primary artifact is Markdown prompt instructions in `SKILL.md`, not a code library. The one illustrative "code-like" example is the optional Python helper function, shown here as a design sketch (not verified against any external library — this is original code following this repo's own existing conventions):

```python
# Source: original — follows this repo's existing scripts/style_profile.py
# conventions (pure function, from __future__ import annotations, no
# external deps). Illustrative design sketch, not verified against a
# library since none is involved.
from __future__ import annotations

def format_naming_examples_block(profile: dict, limit: int = 10) -> str:
    """Renders style_profile.json's naming_examples as a fixed few-shot
    text block for prompt injection. Returns "" when there are no
    examples (fail-open — caller checks for empty string, not exceptions)."""
    examples = profile.get("naming_examples") or []
    if not examples:
        return ""
    lines = [
        f'{i}. "{example["title"]}" (signal: {example["signal"]})'
        for i, example in enumerate(examples[:limit], start=1)
    ]
    return "\n".join(lines)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| ROADMAP.md's original TAGS-01/02 wording (separate Claude API script + Ollama fallback) | Extend existing orchestrator prompt in place, no separate API call, Ollama deferred | 2026-07-07, this phase's discuss-phase session | Zero new cost/dependency; TAGS-02 becomes a Phase 6-adjacent concern instead of a Phase 2 deliverable — this is a project-level architectural correction, not an industry trend shift. |

**Deprecated/outdated:** None from an external-ecosystem standpoint — this section is intentionally thin because the "state of the art" question here is really a project-internal reconciliation (see Summary), not a fast-moving external technology.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Concrete few-shot examples outperform prose style descriptions for LLM voice-matching tasks (general prompting knowledge, not verified via a specific benchmark this session) | Architecture Patterns > Pattern 1 | Low — this is a widely-corroborated prompting practice and is already the exact design Phase 1's own code/tests/docstrings assert (`derive_profile` docstring explicitly rejects prose descriptions); even if slightly imprecise in degree, the direction is correct and matches this repo's own established precedent. |
| A2 | Placing few-shot blocks prominently/early in an instruction set yields stronger adherence than placing them later/passively (Pitfall 5) | Common Pitfalls > Pitfall 5 | Low-medium — this is a reasonable prompt-engineering heuristic but not independently verified against Claude specifically in this session; if wrong, the fallback is simply the phase's own built-in verification method (manual comparison against real examples per success criterion 3), which would catch a weak-grounding failure regardless of the root cause. |

**If this table is empty:** N/A — see above; both assumptions are low-risk and self-verifying via the phase's own manual QA step.

## Open Questions

1. **Should `naming_examples` formatting be a Python helper or purely a SKILL.md-level Read+format instruction?**
   - What we know: CONTEXT.md leaves this to Claude's discretion ("Exact prompt wording/structure for injecting few-shot examples... is Claude's discretion"). Both are viable; the helper is more testable, the direct-read is more minimal/in-spirit with "no new Python script."
   - What's unclear: Whether the user's D-01 intent ("no new Python script") is meant to exclude even a small pure-formatting helper, or only excludes a new *API-calling* script.
   - Recommendation: Planner should default to the direct-read (no new Python) interpretation as the safer reading of D-01, but may add a tiny formatting helper if it improves testability — this is explicitly flagged as discretionary in CONTEXT.md, so either choice is defensible; just document which was chosen and why in the phase's SUMMARY.md.

2. **How exactly should REQUIREMENTS.md/ROADMAP.md be annotated for the TAGS-01 reframe and TAGS-02 deferral?**
   - What we know: CONTEXT.md flags this explicitly ("REQUIREMENTS.md may need a note that TAGS-02 is satisfied later, not in Phase 2, if the planner can't find a way to meaningfully address it without the API-script architecture").
   - What's unclear: Whether this should be a Phase 2 plan task (edit REQUIREMENTS.md directly) or left to the phase transition/`/gsd-progress` step that already updates traceability tables.
   - Recommendation: Include a plan task to add the annotation directly (small, low-risk doc edit) rather than relying on a later transition step to catch it — the discrepancy exists today and a future reader shouldn't have to cross-reference CONTEXT.md to understand it.

## Environment Availability

**Not applicable — no external dependencies.** This phase introduces no new tool, service, runtime, or CLI dependency. It reads an already-produced local file (`work/_profile/style_profile.json`, produced by Phase 1's `scripts/style_profile.py`, which itself has no new external dependency) and edits a Markdown file. No `pip install`, no API key, no service to probe.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest >= 7.4.0 (`requirements-dev.txt`) |
| Config file | `pyproject.toml` (`[tool.pytest.ini_options]`: `pythonpath=["."]`, `testpaths=["tests"]`, registers `integration` marker) |
| Quick run command | `pytest tests/test_style_profile.py -x` (if a formatting helper is added) |
| Full suite command | `pytest` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| TAGS-01 | Orchestrator drafts title+tags without manual authorship, grounded in the current session (no separate API script to test) | manual-only | N/A — no Python behavior change to unit test; verified by running the pipeline end-to-end and inspecting generated metadata `.txt` output | N/A |
| TAGS-02 | N/A — deferred, not implemented this phase | manual-only (documentation check) | N/A — verify REQUIREMENTS.md/PLAN.md carry the explicit deferral note (Pitfall 2) | N/A |
| TAGS-03 | Generated title/tags reflect `naming_examples` voice, verifiable against real few-shot examples | unit (if helper added) + manual | `pytest tests/test_style_profile.py -k naming_examples_block -x` (if helper added); manual side-by-side comparison of 2-3 generated titles against real `naming_examples` entries for the pipeline's own test/dev channel | Wave 0 — new test file/function if a Python helper is added; otherwise manual-only |

### Sampling Rate
- **Per task commit:** `pytest tests/test_style_profile.py -x` (only relevant if a Python helper is added this phase; otherwise there is no automated per-commit test to run — rely on the manual verification step below)
- **Per wave merge:** `pytest` (full suite — cheap, existing suite, confirms nothing else broke)
- **Phase gate:** Full suite green (trivially true if no code changed) + a manual run of the pipeline's step 5 against a real or realistic `style_profile.json` fixture, confirming: (a) the few-shot block appears when the profile is present/non-empty, (b) generation proceeds normally (fail-open, no abort) when the profile is missing/empty, (c) at least one generated title visibly echoes the voice/register of the fabricated few-shot examples used in the manual test.

### Wave 0 Gaps
- If a Python formatting helper is added: `tests/test_style_profile.py` needs new test functions (e.g. `test_format_naming_examples_block_renders_ranked_titles`, `test_format_naming_examples_block_empty_when_no_examples`) — extend the existing file, don't create a new one (matches this repo's 1:1 module-to-test-file convention).
- If no Python helper is added: **None** — this phase has no code to unit test; the entire verification surface is the manual SKILL.md-instruction-following check described above. This is expected and acceptable for a prompt-engineering-only phase; do not force a code-based test just to have one.

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | This phase touches no auth flow — it reads an already-cached local JSON file Phase 1 produced; no new credential, token, or auth surface. |
| V3 Session Management | No | No sessions involved — single-shot local file read within an already-running orchestrator session. |
| V4 Access Control | No | Single-user local tool; no access-control boundary crossed. |
| V5 Input Validation | Marginal | `naming_examples` entries are read from a local JSON file the pipeline itself produced (not external/untrusted input in the traditional sense), but since these are real historical title strings, the orchestrator should treat them as **data to quote, not instructions to follow** — i.e., a mischievous or garbled title string embedded in `naming_examples` should not be interpreted as a prompt-injection vector into the orchestrator's own instructions. This is a soft/prompt-hygiene concern, not a traditional input-validation vulnerability, since the data originates from the user's own YouTube channel via their own OAuth-authenticated pull (Phase 1), not from an untrusted third party. |
| V6 Cryptography | No | No cryptographic operation is added or modified by this phase. |

### Known Threat Patterns for this phase's stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Real channel data (via `naming_examples`) leaking into a committed file | Information Disclosure | Already mitigated at the source: `naming_examples` only ever lives in gitignored `work/_profile/style_profile.json` (Phase 1, verified by `tests/test_style_profile.py::test_privacy_write_profile_default_target_is_under_gitignored_work_dir`). This phase's own risk surface (Pitfall 4 above) is narrower: don't let a *fabricated example* accidentally resemble/be mistaken for real data, and never paste a real title into docs/SKILL.md/tests while authoring this phase. |
| Title/caption content embedding an injected instruction (a hypothetical adversarial past-video title containing prompt-injection-style text) | Tampering (of the orchestrator's own instruction-following) | Low realistic risk since `naming_examples` originates from the user's own channel's real historical titles via their own authenticated YouTube pull — not attacker-controlled input. Still, good practice: when the orchestrator's prompt quotes a `naming_examples` title, it should do so as clearly-delimited example data (e.g. inside quotes, in a numbered reference list) rather than as free-floating instruction text, so a coincidentally imperative-sounding old title (e.g. one that happens to contain "ignore previous instructions" as a joke/reference) can't be misconstrued as a directive. |

## Sources

### Primary (HIGH confidence)
- `D:\shorts-maker\scripts\style_profile.py` — read directly; confirms `naming_examples` schema and fail-open behavior
- `D:\shorts-maker\scripts\metadata.py` — read directly; confirms per-platform output schema this phase's generated content must fit
- `D:\shorts-maker\SKILL.md` step 5 — read directly; the exact existing instructions this phase extends
- `D:\shorts-maker\docs\metadata-writing-ru.md`, `D:\shorts-maker\docs\register-ru.md` — read directly; existing anti-AI-tone/register guidance this phase's grounding sits alongside
- `D:\shorts-maker\tests\test_style_profile.py` — read directly; confirms concrete-not-prose test coverage and fabricated-example convention
- `D:\shorts-maker\.planning\phases\02-llm-title-tag-generation\02-CONTEXT.md` — locked user decisions, read directly
- `D:\shorts-maker\.planning\REQUIREMENTS.md`, `.planning\STATE.md`, `.planning\PROJECT.md`, `.planning\codebase\ARCHITECTURE.md`, `.planning\codebase\STACK.md` — read directly

### Secondary (MEDIUM confidence)
- None — no web/external documentation lookup was needed for this phase; it is entirely an internal-codebase/prompt-engineering research task with no new library or API surface to verify against official docs.

### Tertiary (LOW confidence)
- General LLM few-shot prompting knowledge (Assumptions A1/A2) — training knowledge, not verified via web search this session since it did not materially affect any decision beyond what Phase 1's own code/tests already establish as the project's chosen pattern.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — zero new dependencies, fully verified against existing in-repo code
- Architecture: HIGH — directly derived from CONTEXT.md's locked decisions plus direct reading of SKILL.md/style_profile.py/metadata.py
- Pitfalls: HIGH — grounded in this repo's own documented incident history (PROJECT.md's real data-leak incident) and existing fail-open conventions, not speculative

**Research date:** 2026-07-07
**Valid until:** 90 days (this phase has no fast-moving external dependency; the only invalidation risk is a future Phase 1 schema change to `style_profile.json`, which would be caught by this phase's own tests if a helper is added)
