# Project Research Summary

**Project:** shorts-maker — new milestone (6 new capabilities on an existing local video-clipping pipeline)
**Domain:** Local video-clipping / creator-tooling pipeline extension (Claude-orchestrated CLI/ETL, no server)
**Researched:** 2026-07-07
**Confidence:** MEDIUM-HIGH

## Executive Summary

This milestone adds six capabilities to an already-working local shorts-cutting pipeline: monetization-risk flagging, creator-style-learned naming, LLM-generated titles/tags, context-driven transition selection, sub-threshold highlight compilation, and scheduled cross-platform auto-publish (YouTube/TikTok/Instagram). All six extend the existing stage-based architecture additively — new sibling scripts under `scripts/`, new fields appended to existing JSON artifacts (`candidates.json`, `PLAN.json`) — rather than replacing anything. Expert practice in this space (per feature/competitor research) is that no mainstream clipping tool (OpusClip, Choppity, Vizard) does per-platform monetization-risk flagging, creator-specific style learning, or native scheduled cross-platform publish — these are genuine differentiators if built carefully, while LLM titling and basic transitions are table stakes the project is merely catching up to.

The recommended approach is: keep all "judgment" (is this risky, is this funny, does this sound like the creator) in Claude/prose, and all "mechanical scoring" (keyword rule tables, motion/audio signal extraction, platform API calls) in small, single-purpose Python scripts that never gate or block silently — matching the project's existing anti-pattern guard against encoding semantic judgment in Python. Stack choices are almost entirely reuse of already-adjacent, mature local libraries (scenedetect, opencv, librosa, pyacoustid/Chromaprint) plus one new LLM dependency (Claude Haiku via the anthropic SDK, with an optional local-Ollama fallback for the fully-offline purist path) and official platform SDKs/REST APIs only — no unofficial scraping wrappers, ever, for publishing.

The dominant risk across this milestone is NOT technical difficulty — it's external gatekeeping and irreversibility. TikTok's Content Posting API forces unaudited clients into SELF_ONLY (private) uploads, an app-review process that takes days-to-weeks and is entirely outside developer control; Instagram similarly requires Business/Creator account linkage plus Meta App Review. Auto-publish itself is a one-way door — a bad clip published live cannot be "git reverted." Both risks push hard toward a draft/dry-run/pause/human-approval design from day one for the publish phase, and toward framing monetization-risk output as strictly advisory (never a pass/fail gate) throughout. A secondary but concrete risk is repeating this project's own real prior incident (leaked per-channel data in a commit) at 3x scale once three platforms' write-scoped OAuth tokens plus new derived-from-real-history caches (style profile, publish state, LLM logs) enter the picture.

## Key Findings

### Recommended Stack

Almost the entire new stack is either already-adjacent to existing dependencies or a thin, official-SDK-only integration. No new heavy ML infra is required — the "smart" features (transition selection, monetization risk) are built from composed cheap signal-processing (optical flow, audio energy, keyword rules), not new models.

**Core technologies:**
- google-api-python-client + google-auth-oauthlib (already in use) — add youtube.upload scope to the existing OAuth client for YouTube publishing; zero new library risk.
- TikTok Content Posting API (direct REST via requests, no SDK) — the only sanctioned posting path; requires app audit before public (non-SELF_ONLY) posting.
- Instagram/Meta Graph API (direct REST via requests) — requires Business/Creator account + Meta App Review; container-based upload needs a publicly fetchable video_url.
- pyacoustid + fpcalc/Chromaprint — local audio fingerprinting to flag likely-licensed music (feeds monetization-risk).
- Anthropic Claude API (claude-haiku-4-5 via anthropic SDK) — LLM title/tag generation; cheap, structured-output-friendly, natural fit since the project is already Claude-orchestrated. Optional local ollama fallback preserves the fully-offline path.
- scenedetect (PySceneDetect) + opencv-python (dense optical flow) + librosa (+soundfile) — compose shot-boundary detection, motion-vector analysis, and audio-energy/onset analysis to drive transition-type selection; ffmpeg's existing xfade filter renders the chosen transition (no new "glitch"/"whip-pan" presets exist natively — build via filter-chain composition).

**What NOT to use:** unofficial TikTok/Instagram posting wrappers (instagrapi, scraping libs) — ToS violation and account-ban risk, directly conflicting with the project's own irreversibility concerns; any "will this get demonetized" classifier claiming certainty; third-party paid fingerprinting SaaS; generic multi-platform "social-scheduler" packages that hide platform-specific nuance.

### Expected Features

Full detail in FEATURES.md; six features total, ranked by risk/dependency, not by number.

**Must have (table stakes, mostly already 80% built):**
- Per-clip title + per-platform metadata formatting (character limits, hashtag conventions) — graduating existing naming.py/metadata.py.
- Baseline content-safety/profanity flagging.
- Cut/crossfade default transitions with a "fancier" option.
- Manual review/approval step before any publish — non-negotiable given irreversibility.
- Idempotent/cached per-video processing for all new stages (matches existing caching contract).

**Should have (genuine differentiators, none done well by competitors):**
- Per-platform demonetization-risk flagging in exported metadata (deterministic rule tier first; LLM/nuance tier later).
- Style-learning from the creator's own upload history (few-shot prompt grounding, NOT fine-tuning).
- LLM-generated titles+tags, most valuable combined with style-learning.
- Native scheduled cross-platform auto-publish tied to the same pipeline (competitors only integrate with generic external schedulers).

**Defer (v2+, genuinely hard, sequence-dependent):**
- Context-driven transition selection — start with a cheap 2-3-signal decision tree, not true CV shot-matching.
- Sub-threshold highlight compilation — depends on transitions landing first, or the stitching logic gets built twice.

### Architecture Approach

The existing 6-stage pipeline (transcribe -> chunk -> score -> merge/approve -> refine/render -> render) is extended, not replaced, with one new pre-pass (Stage 0: style profiling, long-lived/cross-video, gitignored) and one new post-pass (Stage 7: scheduled publish, deliberately decoupled from the per-video /make-shorts flow). All new "signal" scripts (monetization_risk.py, compilation.py, transitions.py) are pure functions that append structured fields to existing JSON artifacts and never gate/block — matching the existing "signals not gates" pattern already used for energy_spikes/speaker detection.

**Major components:**
1. scripts/style_profile.py (new, Stage 0) — derives naming/selection patterns from the existing youtube_analytics.py cache; long-lived cache in work/_profile/, read-only by later stages.
2. scripts/monetization_risk.py (new, Stage 5 support) — rule-table-driven (YAML data, not hardcoded Python) scoring producing an advisory risk dict, never a pass/fail gate.
3. scripts/compilation.py (new, Stage 4 support) — clusters below-threshold candidates by a small fixed theme_tags taxonomy; operates only on already-merged candidates.json, never per-chunk (preserves Stage 3 subagent parallelism).
4. scripts/transitions.py (new, Stage 5 support) — consumes frames.py stills + audio_energy.py output to choose a transition type per clip boundary, handed off to render.py's new build_transition_filter().
5. scripts/publish.py (new, Stage 7, standalone entry point) — OAuth upload per platform, dry-run flag, pause/resume state file, sequential numbering; deliberately NOT wired into the main /make-shorts flow.

Recommended build order (dependency-driven): (1) monetization-risk and (2) style-profile can be built in parallel first (both independent); (3) LLM titling softly depends on (2); (4) compilation depends only on a Stage-3 schema addition; (5) transitions should follow (4) so there's a real multi-segment plan to design against; (6) auto-publish comes last, since it consumes (1)/(3)/(4)/(5) outputs and carries the highest irreversibility risk.

### Critical Pitfalls

1. **TikTok unaudited-client visibility trap** — an unaudited API client silently forces uploads to SELF_ONLY (private); the upload call returns success, masking the fact that nothing is actually public. Submit for TikTok app audit before building scheduling logic around it; add a post-publish visibility-verification check; build TikTok as an isolated swappable module so YouTube/Instagram can ship independently.
2. **Monetization-risk flags treated as ground truth** — platform Content ID/ad-suitability models are opaque and get it wrong in both directions (YouTube's own transparency data shows real false-claim rates). Frame all output as advisory only, never auto-block, keep the ruleset in editable/versioned config with a visible date stamp, and close the loop with post-upload status checks where possible.
3. **Auto-publish becomes irreversible-by-default** — a scheduling bug or crash-restart can double-publish or publish in wrong order across three platforms simultaneously, with no "force-with-lease" equivalent. Design dry-run + a persistent pause flag + an idempotency/already-published manifest BEFORE writing any real upload-API code, not as a later polish item.
4. **OAuth credentials for three platforms repeat this project's real prior incident at higher stakes** — this project already had a leaked-data incident requiring history rewrite. Write-scoped tokens for 3 platforms are a much bigger target than the current read-only Analytics token. Move all credential files structurally outside the repo tree, add a pre-commit secret-grep hook, and apply the same gitignored-cache discipline to every new derived-from-real-history artifact (style profile, publish state, LLM logs).
5. **LLM titles drift into generic "AI voice"** — if phase 3 doesn't concretely wire phase 2's real historical titles into the prompt as few-shot examples (not just prose description), output regresses to generic clickbait, undermining the entire point of style-learning. Treat the phase 2->3 handoff as a hard contract requiring structured (not prose-only) style-profile output, with an explicit "does this sound like us" review step.

## Implications for Roadmap

Based on combined research, suggested phase structure (six roadmap phases mapping 1:1 to the six PROJECT.md features, sequenced by actual dependency, not by feature-list order):

### Phase 1: Monetization-Risk Flagging (deterministic rule tier)
**Rationale:** No dependency on anything else; establishes the "rule-table + structured advisory flag, never a gate" pattern that later phases reuse. Cheapest, highest-confidence win — ship first to validate the pattern.
**Delivers:** scripts/monetization_risk.py + data/monetization_rules.yaml; risk dict appended to PLAN.json/metadata output.
**Addresses:** FEATURES.md item (1), deterministic tier only — defer LLM/nuance tier to v1.x.
**Avoids:** PITFALLS #2 (flags-as-ground-truth) — explicit advisory framing and editable/versioned ruleset baked in from the start.

### Phase 2: Creator Style/Naming Profile
**Rationale:** Independent of Phase 1; can be built in parallel. Must land before Phase 3 to avoid a costly redo of the LLM prompt contract.
**Delivers:** scripts/style_profile.py, long-lived work/_profile/style_profile.json derived from the existing youtube_analytics.py cache.
**Uses:** Existing analytics cache only — no new stack dependency.
**Implements:** ARCHITECTURE.md Stage 0 (offline/manual pre-pass, read-only by later stages).

### Phase 3: LLM Title/Tag Generation
**Rationale:** Softly depends on Phase 2 for grounding quality; can ship a stubbed fallback if Phase 2 isn't ready, but the prompt interface must be designed to accept style-profile input from day one.
**Delivers:** Claude-call (Haiku 4.5) grounded in style profile + docs/metadata-writing-ru.md; writes tags/titles into metadata.py input; optional local-Ollama fallback path for offline operation.
**Uses:** anthropic SDK (cloud default), ollama (configurable fallback) from STACK.md.
**Avoids:** PITFALLS #5 (generic AI-voice drift) via few-shot real-title injection, and #6 (cloud-LLM breaking fail-open principle) via mandatory fallback + per-transcript-hash caching.

### Phase 4: Sub-Threshold Highlight Compilation
**Rationale:** Depends only on a Stage-3 schema addition (theme_tags/below_threshold fields), not on transitions — can produce multi-segment plans that render as simple hard-cut concatenation initially.
**Delivers:** scripts/compilation.py, compilation_groups.json, extended CANDIDATES.md with a compilation-candidates section.
**Addresses:** FEATURES.md item (5) — genuine market gap, no competitor productizes this well.
**Avoids:** PITFALLS #8 (narratively-incoherent clustering) via separating "cluster" from "order" (chronological default) and capping cluster size/duration.

### Phase 5: Context-Driven Transition Selection
**Rationale:** Logically layers on top of Phase 4 (compilations are the primary consumer of non-trivial transitions) so there's a real multi-segment plan to design against, avoiding speculative interface design — but is technically independent enough to validate standalone on a two-segment test case first.
**Delivers:** scripts/transitions.py (scenedetect + optical flow + librosa signal composition) + render.py's new build_transition_filter().
**Uses:** scenedetect, opencv-python, librosa/soundfile, ffmpeg xfade from STACK.md.
**Avoids:** PITFALLS #7 (black-box jarring transitions) via a config-level manual override, confidence-threshold fallback to crossfade/cut, and logging the signals behind each choice.

### Phase 6: Scheduled Cross-Platform Auto-Publish
**Rationale:** Sequenced last — consumes outputs of Phases 1, 3, 4, 5 (needs stable metadata/tags/risk schema, not a moving one) and carries by far the highest blast radius (irreversible public action across 3 platforms). TikTok/Instagram external audit/review lead times (days-to-weeks) should be kicked off in parallel with earlier phases' code work, not after.
**Delivers:** scripts/publish.py, per-platform OAuth (isolated modules, fail-open per platform), dry-run flag, pause/resume state file, idempotency manifest, sequential numbering. YouTube ships first (no audit gate); TikTok/Instagram gated on external app review.
**Addresses:** FEATURES.md item (6), MVP-scoped to YouTube-only first per the FEATURES.md MVP definition.
**Avoids:** PITFALLS #1 (TikTok unaudited-visibility trap), #3 (irreversible-by-default publish), #4 (OAuth/credential leakage repeat) — all three require the safety mechanism (dry-run/pause/idempotency/credentials-outside-repo) designed BEFORE any upload-API code is written.

### Phase Ordering Rationale

- Phases 1 and 2 are mutually independent and have no external blockers — ship first to build momentum and validate core patterns (rule-table scoring, style-profile caching).
- Phase 3 softly depends on Phase 2's output shape; sequencing it third lets the LLM prompt design against a real (not speculative) style-profile schema.
- Phases 4 and 5 are explicitly sequenced (compilation before transitions) per both FEATURES.md and ARCHITECTURE.md build-order analysis — building transitions first would mean guessing at multi-segment plan shape; building compilation first without transitions means simple hard-cut stitching now, smart transitions bolted on next without redoing the stitching logic.
- Phase 6 is last by design: it is the only phase with genuine external gatekeeping (TikTok audit, Meta App Review) and the only one with irreversible real-world consequences, so it should integrate against a stable, already-validated metadata/risk/transition schema rather than a moving one. Its OAuth/audit lead time should be started in parallel with Phase 1-2 work to avoid it becoming a pure critical-path blocker later.

### Research Flags

Needs deeper research during planning (/gsd-plan-phase --research-phase N):
- **Phase 5 (transitions):** Composing scenedetect + optical flow + librosa signals into a reliable decision tree is a genuinely novel integration with no off-the-shelf "transition recommender" reference implementation — expect to iterate on thresholds during planning.
- **Phase 6 (auto-publish):** TikTok/Instagram API audit requirements, current quota figures, and OAuth credential-storage design (moving off in-repo client_secret.json/token.json) all need verification against live docs at implementation time — platform policies and quota costs are documented as changing without notice (e.g., YouTube's Dec-2025 quota-cost reduction).

Phases with standard, well-documented patterns (can likely skip deep research-phase):
- **Phase 1 (monetization-risk, deterministic tier):** Rule-table pattern is simple and well-understood; main design work is the ruleset content, not the mechanism.
- **Phase 2 (style profile):** Pure function over already-cached data the project already owns; no new external integration.
- **Phase 3 (LLM titling):** Standard Claude API call with structured output; the interesting design work (few-shot grounding) is prompt engineering, not infrastructure.
- **Phase 4 (compilation):** Clustering over an existing fixed tag taxonomy is a simple, well-scoped data transform.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | MEDIUM-HIGH | Official platform docs (TikTok, Meta, Google, ffmpeg, PySceneDetect, librosa) are HIGH confidence; 2026-specific quota numbers and monetization-heuristic specifics are MEDIUM — platforms change these without notice. |
| Features | MEDIUM | Web-search-derived; TikTok Developer docs are HIGH-confidence primary source, but most competitor-feature claims (OpusClip, Choppity, Vizard) are vendor marketing or third-party comparison blogs, cross-checked but not independently verified. |
| Architecture | HIGH | Grounded directly in this project's own existing codebase docs (.planning/codebase/ARCHITECTURE.md, STRUCTURE.md, PROJECT.md) rather than external speculation — the extension design is a direct, low-risk continuation of already-proven patterns. |
| Pitfalls | HIGH | Platform API constraints, quota figures, and OAuth storage guidance verified against current vendor docs; monetization-detection and LLM-voice pitfalls are MEDIUM (no authoritative "correct" threshold exists) but grounded in this project's own real prior incident history, which is a strong signal. |

**Overall confidence:** MEDIUM-HIGH

### Gaps to Address

- **TikTok/Instagram audit timelines and current API terms:** Explicitly time-sensitive (days-to-weeks, policy-dependent) — re-verify against live developer docs at the start of Phase 6 planning, not just at research time.
- **Actual per-clip quality of local-Ollama title generation vs. cloud Claude:** STACK.md flags this as "good enough per 2026 benchmarks" but this is directional, not benchmarked against this project's actual Russian-language gaming-commentary use case — validate with a real side-by-side comparison during Phase 3 UAT.
- **Monetization-risk ruleset content itself (what keywords/categories to include):** The research establishes the mechanism (rule-table, advisory framing) but not the actual initial ruleset — this needs a first-pass content decision during Phase 1 planning, informed by TikTok's official Community Guidelines and YouTube's ad-suitability guidelines directly.
- **Where exactly OAuth credentials should live outside the repo, and whether to add OS-keyring/encryption-at-rest:** PITFALLS.md recommends a directory like ~/.config/shorts-maker/credentials/ plus possibly Windows Credential Manager, but this is a design decision to finalize (not just verify) during Phase 6 planning, including migrating the existing YouTube token off its current in-repo location.
- **Stage-3 schema change for theme_tags/below_threshold:** ARCHITECTURE.md assumes a small fixed taxonomy will work for compilation clustering, but the actual taxonomy content (which tags) needs to be decided during Phase 4 planning, not deferred to implementation.

## Sources

### Primary (HIGH confidence)
- D:\shorts-maker\.planning\codebase\ARCHITECTURE.md, STRUCTURE.md, .planning\PROJECT.md, .planning\codebase\CONCERNS.md — existing pipeline architecture, constraints, and real incident history
- TikTok Content Posting API Reference / Getting Started FAQ (developers.tiktok.com) — audit gate, SELF_ONLY visibility restriction
- Meta: Publish Content using the Instagram Platform / Content Publishing Limit reference (developers.facebook.com)
- YouTube Data API — Videos: insert / quota calculator (developers.google.com)
- PySceneDetect official docs, OpenCV optical flow tutorial, librosa official docs, FFmpeg xfade filter documentation
- Claude API Pricing (platform.claude.com), YouTube Content ID (support.google.com)
- Google OAuth 2.0 Best Practices (developers.google.com)

### Secondary (MEDIUM confidence)
- TikTok API Rate Limits 2026 (getphyllo.com), YouTube Data API 2026 quota/cost analysis (socialcrawl.dev), corroborated by a live GitHub issue on hidden upload quotas
- Instagram Reels API Publishing Guide 2026 (postproxy.dev), Instagram API Upload Video guide (bundle.social)
- Mediacube/Gyre/Ganknow on YouTube demonetization and trending-audio license windows (cross-checked across sources)
- OpusClip, Choppity, Eklipse vendor/comparison sources for competitor feature analysis
- Obsidian Security on OAuth refresh-token storage best practices

### Tertiary (LOW confidence)
- Local LLM vs Cloud API 2026 cost breakdown (fungies.io) — directional only, not authoritative benchmarks
- InfluenceFlow TikTok monetization roadmap guide — single-vendor aggregator

---
*Research completed: 2026-07-07*
*Ready for roadmap: yes*
