# Project Research Summary

**Project:** shorts-maker - next milestone (6 new capabilities on top of the existing local AI shorts-cutting pipeline)
**Domain:** Local video-processing / creator-tooling pipeline extension (Claude-orchestrated CLI/ETL, no server)
**Researched:** 2026-07-07
**Confidence:** MEDIUM-HIGH

## Executive Summary

This milestone adds six capabilities to an already-working, fully local shorts-cutting pipeline: platform publishing APIs (YouTube/TikTok/Instagram), monetization-risk flagging, creator-style-learned titling, LLM-generated titles/tags, context-driven transition selection, and compilation of sub-threshold highlight moments. Experts building this kind of tool (OpusClip, Choppity, Vizard, Eklipse) treat title/tag generation and basic transitions as table stakes, but none of them do per-platform monetization-risk flagging, creator-history-personalized titling, or context-aware transition selection - these three are genuine, defensible differentiators for a single-channel tool, not features to copy from a competitor.

The recommended approach is additive, not a rewrite: every new capability is a new sibling script under scripts/ that reads/writes structured JSON fields onto the existing candidates.json / PLAN.json artifacts, never a gating pass/fail decision in Python (semantic judgment stays advisory data for Claude/the human to weigh, matching the existing no-semantic-judgment-in-Python architecture rule). Stack choices lean on official, already-integrated SDKs (Google API client, reused OAuth pattern) plus purpose-built local libraries (pyacoustid/Chromaprint, scenedetect, librosa, opencv optical flow) rather than any paid SaaS or unofficial scraping wrapper - this preserves the no-permanent-cloud-backend constraint everywhere except an optional, swappable Claude Haiku call for titling (with a local Ollama fallback).

The primary risk is external, not technical: TikToks Content Posting API restricts unaudited clients to SELF_ONLY (private) posting, and Instagrams Graph API requires a Business/Creator account plus Meta App Review - both are multi-week, non-code lead-time items that must be kicked off early and treated as blocking dependencies, independent of when the corresponding code is written. The secondary risk is scope-creep on the two hardest features (context-driven transitions, sub-threshold compilation) - both are HIGH complexity and should be sequenced last, after the cheaper wins (titling, deterministic monetization rules, YouTube-only auto-publish) are shipped and validated. Note: dedicated pitfalls research (PITFALLS.md) did not complete for this run - the pitfall content below is assembled second-hand from risk/anti-pattern material embedded in STACK/FEATURES/ARCHITECTURE, and is not as exhaustive as a dedicated pitfalls pass would be.

## Key Findings

### Recommended Stack

The stack is four independent additions layered onto an unchanged existing pipeline (faster-whisper/moviepy/ffmpeg core). Each new capability reuses an existing pattern (OAuth client, fail-open philosophy, local-first default) rather than introducing new infrastructure classes.

**Core technologies:**
- google-api-python-client + google-auth-oauthlib (already in use): YouTube upload via videos.insert - add the youtube.upload scope to the existing OAuth client, no new dependency
- TikTok Content Posting API (direct REST, no SDK) + Instagram Graph API (direct REST via requests): the only sanctioned programmatic posting paths - both gated by platform app-review processes with multi-week lead times
- pyacoustid + fpcalc (Chromaprint binary): local audio fingerprinting to flag likely-licensed music, the industry-standard technique Content ID itself is modeled on
- Rule-based keyword classifier (custom, no library) + post-upload status check: cheap deterministic monetization-risk tier plus ground-truth confirmation loop
- Anthropic Claude API (claude-haiku-4-5) for title/tag generation, with local Ollama (Llama 3.3/Qwen3 8B-class) as an offline/zero-cost fallback - cloud recommended as default for quality, local as configurable fallback
- scenedetect + opencv-python (optical flow) + librosa (audio energy/onset/beat) composed together, feeding ffmpegs existing xfade filter: the correct level of abstraction for transition selection - no need for a heavier video-understanding model

### Expected Features

Six new capabilities were researched against OpusClip/Choppity/Vizard/Eklipse as the competitive baseline.

**Must have (table stakes):**
- Per-clip title + description (already 80% built via naming.py/metadata.py - this milestone graduates it to LLM-authored)
- Per-platform metadata formatting (character limits, hashtag conventions) - already exists, extend schema for tags
- Basic content-safety/profanity awareness - baseline deterministic tier is table stakes; nuanced LLM tier is a stretch goal
- Manual review/approval before publish - no credible competitor auto-publishes blind; extends the existing CANDIDATES.md approval-gate pattern

**Should have (differentiators - genuinely absent from every researched competitor):**
- Per-platform demonetization-risk flagging in exported metadata (no competitor does this - they optimize virality, not policy risk)
- Style-learning from the creators own upload history (few-shot prompt context, not fine-tuning) - no competitor personalizes per-individual-creator
- Context-driven transition selection per clip-boundary - no mainstream short-clipper does scene-aware transitions
- Compilation of sub-threshold highlights grouped by theme similarity - closest competitor analog (Eklipse) still only auto-trims to one moment, does not cluster leftovers

**Defer (v2+):**
- TikTok/Instagram auto-publish (blocked on external app-review/audit, not code)
- LLM/nuance-tier monetization flagging (hate-speech vs. banter judgment) - ship deterministic tier first
- Context-driven transitions and compilation - both HIGH complexity, sequence-dependent, defer until P1 wins validate

### Architecture Approach

The existing 6-stage pipeline (transcribe -> chunk -> score -> merge/approve -> refine/render -> render) is extended, not replaced, with one new pre-stage (Stage 0: offline creator-style profiling) and one new post-stage (Stage 7: scheduled publish, deliberately decoupled from the per-video /make-shorts flow). All new logic lands as structured JSON fields on existing artifacts (candidates.json gains theme_tags/below_threshold; PLAN.json gains tags[], risk{}, transition{}, segments[]) rather than new pass/fail gates - this preserves the codebases hard rule that semantic/legal judgment stays advisory (weighed by Claude/human), never silently enforced in Python.

**Major components:**
1. scripts/style_profile.py (new, Stage 0) - reads youtube_analytics.py cache, derives long-lived cross-video naming/selection patterns into work/_profile/style_profile.json, read-only by later stages
2. scripts/monetization_risk.py (new, Stage 5c) - scores transcript/tags against per-platform YAML rule tables, returns structured risk dict, never blocks
3. scripts/compilation.py (new, Stage 4) - clusters below-threshold candidates by theme-tag similarity, purely a graph transform over already-scored data, no new semantic pass
4. scripts/transitions.py (new, Stage 5d) - analyzes frames.py stills + audio_energy.py boundary windows, picks a transition type, hands off params to render.pys existing filter-graph builder
5. scripts/publish.py (new, Stage 7) - OAuth upload per platform, dry-run flag, resumable schedule/pause state file, deliberately NOT wired into the main /make-shorts SKILL.md flow

### Critical Pitfalls (assembled from embedded risk material - dedicated PITFALLS.md did not complete)

1. Encoding monetization/legal judgment as a hard pass/fail gate in Python - violates the existing no-semantic-judgment-in-Python rule and removes human/Claude nuance from a fuzzy, context-dependent call (a joking gambling mention vs. actual promotion). Avoid by always emitting an advisory risk dict, never an auto-block.
2. TikTok/Instagram app-review lead time treated as a code task instead of a process task - TikToks unaudited-client SELF_ONLY restriction and Metas App Review are multi-week external processes, not something a sprint can shortcut. Avoid by starting registration/audit submission immediately, independent of when the corresponding code is written, and building a private-draft/dry-run fallback from day one.
3. Building compilation (Feature 5) before transitions (Feature 4) - stitching multi-segment clips with only hard cuts, then retrofitting smart transitions, means redoing the stitching logic twice. Avoid by sequencing transitions before or alongside compilation.
4. Keyword-blocklist-only demonetization flagging - high false-positive rate on gaming vocabulary (kill/die is normal FPS trash-talk) and high false-negative rate on context-dependent violations (gambling discussion vs. promotion). Avoid with a two-tier design: deterministic rules for unambiguous triggers, LLM judgment pass for nuance-requiring cases.
5. Unofficial platform API wrappers for posting (instagrapi for publishing, TikTok scraping libs) - ToS violation and real account-ban risk, directly conflicting with the projects own auto-publish-is-hard-to-undo concern. Avoid by using only official Content Posting API / Graph API, accepting the review lead time as a real project cost.
6. Style-profile / analytics cache committed to git - both are derived from private channel data and must stay gitignored, matching the existing privacy constraint already enforced for youtube_analytics.pys cache.

## Implications for Roadmap

Based on combined research (Feature Prioritization Matrix + Architecture Suggested Build Order agree closely), suggested phase structure:

### Phase 1: Monetization-Risk Flagging (deterministic tier) + Creator Style Profiling
**Rationale:** Both are independent of every other feature and of each other - can be built in parallel. Lowest complexity, validates the rule-table + structured-flag pattern before reusing it in later phases (transitions, publish gating).
**Delivers:** scripts/monetization_risk.py + data/monetization_rules.yaml; scripts/style_profile.py + work/_profile/style_profile.json
**Addresses:** Feature 1 (deterministic tier only) and the data dependency for Feature 2/3
**Avoids:** Pitfall 1 (advisory-only design), Pitfall 6 (gitignore discipline), Pitfall 4 (two-tier flagging design decided upfront even if LLM tier deferred)

### Phase 2: LLM Title/Tag Generation
**Rationale:** Softly depends on Phase 1s style profile for quality (in-voice titles) but must ship a standalone fallback path (works without style profile, e.g. new channel or fetch failure). Lowest implementation cost of all six features, highest immediately-visible value.
**Delivers:** Claude Haiku (or local Ollama) call grounded in style_profile.json + docs/metadata-writing-ru.md, writing into metadata.py input; extends PLAN.json with tags[]
**Uses:** anthropic SDK / ollama client from STACK.md
**Implements:** Stage 5b of the extended pipeline (Architecture)

### Phase 3: Scheduled Auto-Publish - YouTube Only
**Rationale:** YouTube has no audit-gate friction (existing OAuth client just needs one more scope/consent), unlike TikTok/Instagram. Validates the scheduling/numbering/dry-run mechanics on the lowest-risk platform before tackling the other twos review processes. Depends on Phase 1 (risk flags) and Phase 2 (final titles/tags) being present in the metadata schema.
**Delivers:** scripts/publish.py (Stage 7, decoupled entry point) with dry-run flag, pause/resume state file, sequential numbering - YouTube adapter only
**Addresses:** Feature 6 (YouTube slice)
**Avoids:** Anti-Pattern 4 (never couple publish.py into the main /make-shorts flow)

### Phase 4: Context-Driven Transition Selection
**Rationale:** HIGH complexity but technically independent enough to validate standalone on any two-segment test case; sequence before compilation so compilation does not need reworking later. Realistic MVP scope is a decision tree over 2-3 cheap signals (audio-energy delta, motion magnitude via optical flow, silence-gap), not true CV shot-matching.
**Delivers:** scripts/transitions.py + render.pys build_transition_filter()
**Uses:** scenedetect, opencv optical flow, librosa from STACK.md
**Implements:** Stage 5d / Anti-Pattern 3 guard (analysis stays a separate script from render execution)

### Phase 5: Compilation of Sub-Threshold Highlights
**Rationale:** Depends on Phase 4 existing so multi-segment stitching is not built twice; also depends on a Stage-3 schema addition (theme_tags/below_threshold on candidates). Highest-complexity feature alongside transitions - deliberately last among the core features.
**Delivers:** scripts/compilation.py, compilation_groups.json, extended CANDIDATES.md compilation-candidates section
**Addresses:** Feature 5
**Avoids:** Anti-Pattern 2 (clustering stays a Stage 4 graph transform, never a per-chunk Stage 3 responsibility)

### Phase 6: TikTok / Instagram Auto-Publish (conditional, external-dependency-gated)
**Rationale:** Blocked on TikTok app audit and Instagram Business-account + Meta App Review - both multi-week external processes that should be kicked off in parallel with Phase 1-5s code work, not scheduled sequentially after it. This phase only proceeds once those external gates clear (or a private-draft-only fallback is accepted as sufficient).
**Delivers:** publish.py adapters for TikTok/Instagram, isolated per-platform so one outage/rate-limit does not block the other (or YouTube)
**Addresses:** Feature 6 remainder

### Phase Ordering Rationale

- Phases 1-2 are the cheapest, most independent wins and should ship first to validate patterns (rule-table scoring, LLM grounding) reused everywhere downstream.
- Phase 3 (YouTube publish) is sequenced before the harder creative features (4, 5) because it has no platform-approval blocker and lets the team start accumulating real publish/schedule experience while TikTok/Instagrams external review clocks run in parallel.
- Phases 4-5 are ordered transitions-before-compilation specifically to avoid the build-compilation-twice pitfall identified independently in both FEATURES.md and ARCHITECTURE.md.
- Phase 6 is last and explicitly external-dependency-gated - start the TikTok/Meta registration and review process as early as Phase 1, in parallel with code work, so the multi-week lead time does not sit entirely at the end of the roadmap.

### Research Flags

Phases likely needing deeper research during planning:
- Phase 3 (YouTube publish) and Phase 6 (TikTok/Instagram publish): platform API specifics (OAuth scope details, TikTok chunk-upload/status-poll mechanics, Instagram container-based media/media_publish flow, quota/rate-limit behavior) are MEDIUM confidence and platform-controlled - verify against current official docs at plan time, not just this research.
- Phase 4 (transitions): the mapping from optical-flow/audio-energy signal to specific xfade filter parameters (esp. glitch/whip-pan which have no native ffmpeg preset and need custom filter chains) needs a focused technical spike during planning.
- Phase 5 (compilation): the exact clustering approach (fixed tag taxonomy vs. embeddings) and how theme_tags vocabulary is seeded into Stage 3 subagent prompts needs concrete design during planning - architecture research recommends a small fixed taxonomy but the taxonomy itself is not defined yet.

Phases with standard patterns (skip research-phase):
- Phase 1 (monetization rules + style profiling): rule-table-driven scoring and read-only cache-derived profiling are both well-established patterns already used elsewhere in this codebase (config.example.yaml, youtube_analytics.py cache) - no deep research needed beyond what is already captured.
- Phase 2 (LLM titling): straightforward Claude/Ollama API call with structured output - well-documented, low ambiguity.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | MEDIUM-HIGH | Official platform docs (Google, TikTok, Meta, ffmpeg, librosa, PySceneDetect) are HIGH; monetization-risk heuristics and 2026-specific quota numbers are MEDIUM - platforms change these without notice, verify at plan time |
| Features | MEDIUM | Web-search-derived; TikTok Developer docs are HIGH-confidence primary source, competitor feature claims are largely vendor-self-reported (directional, not independently verified) |
| Architecture | HIGH | Grounded directly in existing codebase docs (.planning/codebase/ARCHITECTURE.md, STRUCTURE.md, PROJECT.md), not external speculation |
| Pitfalls | LOW (dedicated research incomplete) | PITFALLS.md was not produced by the pitfalls researcher for this run; the pitfall content above is assembled second-hand from risk/anti-pattern material embedded in STACK/FEATURES/ARCHITECTURE, which is not as exhaustive or systematically adversarial as a dedicated pitfalls pass would be |

**Overall confidence:** MEDIUM

### Gaps to Address

- Missing PITFALLS.md: No dedicated pitfalls research file was found at .planning/research/PITFALLS.md for this run - only STACK.md, FEATURES.md, and ARCHITECTURE.md were available. Recommend re-running the pitfalls researcher before/during roadmap creation, or explicitly flagging each phase for extra scrutiny during /gsd-plan-phase in lieu of dedicated pitfalls research.
- 2026-specific platform quota/rate-limit numbers: YouTubes Dec-2025 quota-cost change and a May-2026 undocumented hidden-quota/429 issue are flagged as unverified in STACK.md - validate against the actual account before committing to a publish cadence in Phase 3/6 planning.
- TikTok/Meta app-review timelines: Real lead time is unknown until actually submitted - treat Phase 6 start date as unknown until the applications are filed; recommend filing them as early as Phase 1 so the clock runs in parallel with lower-risk phases.
- theme_tags taxonomy for compilation clustering: Not yet defined - needs concrete design work during Phase 5 planning (or earlier, since Stage 3 candidate schema needs the taxonomy before Phase 5 can consume it).

## Sources

### Primary (HIGH confidence)
- .planning/codebase/ARCHITECTURE.md, .planning/codebase/STRUCTURE.md, .planning/PROJECT.md - existing codebase, primary source for Architecture Approach
- TikTok Content Posting API Reference - Direct Post (official TikTok Developers docs)
- Meta: Publish Content using the Instagram Platform (official Graph API docs)
- YouTube Data API - Videos: insert (official docs)
- PySceneDetect official docs, OpenCV optical flow tutorial, librosa official docs, FFmpeg xfade filter documentation
- Claude API Pricing - Platform Docs (official Anthropic pricing)
- TikTok Community Guidelines - Regulated Goods/Gambling (official policy)

### Secondary (MEDIUM confidence)
- TikTok API Rate Limits 2026, YouTube Data API 2026 quotas/costs, Instagram Reels API Publishing Guide 2026 - third-party aggregators corroborating official flows
- YouTube demonetization guides (Mediacube, Gyre, Ganknow) - cross-checked claims on trending-audio license windows and advertiser-unfriendly categories
- OpusClip/Choppity/Eklipse vendor sites and comparisons - self-reported competitor feature claims

### Tertiary (LOW confidence)
- Local LLM vs Cloud API 2026 cost breakdown - directional cost/quality framing only
- Single-vendor blog posts on demonetization and TikTok monetization requirements - not independently verified

---
*Research completed: 2026-07-07*
*Ready for roadmap: yes, with the caveat that PITFALLS.md should be regenerated or the gap explicitly accepted*
