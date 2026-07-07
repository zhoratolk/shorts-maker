# Pitfalls Research

**Domain:** Local video-clipping pipeline adding monetization-risk flagging, style-learning, LLM titling, context-aware transitions, highlight compilation, and multi-platform scheduled auto-publish (YouTube/TikTok/Instagram)
**Researched:** 2026-07-07
**Confidence:** HIGH (platform API constraints, quota figures, and OAuth storage guidance verified against current vendor docs/search results; monetization-detection and LLM-voice pitfalls are MEDIUM — inherently no authoritative "correct" threshold exists, assessed from documented platform behavior and this project's own incident history)

## Critical Pitfalls

### Pitfall 1: Building auto-publish against TikTok's "unaudited" API tier and hitting a wall in production

**What goes wrong:**
An unaudited TikTok API client can only post 1 video per user per 24-hour window in earlier docs, or up to 5 users/24h under newer wording — and critically, every video uploaded through an unaudited client is forced to `SELF_ONLY` (private) visibility. A team builds phase 6 auto-publish, tests it, sees videos land in the account successfully, and only later discovers the clips are silently private — never visible to followers or the For You feed. Since this project publishes to one personal channel, "1 user" caps still apply, but the bigger trap is the private-visibility default going unnoticed because the API call itself returns success.

**Why it happens:**
TikTok's audit process requires submitting the app for review (days to two weeks) and demonstrating ToS compliance before lifting the visibility restriction. Teams treat "the upload API call succeeded" as equivalent to "the video is public," because that's true on YouTube and (mostly) Instagram, but not on TikTok pre-audit.

**How to avoid:**
Treat TikTok as the long pole in phase 6. Apply for Content Posting API access and complete the audit *before* building the scheduling/numbering logic around it, not after. Add an explicit post-publish verification step that reads back the video's visibility status via API and surfaces a loud warning (not just a log line) if it comes back `SELF_ONLY`. Build TikTok publish as an isolated, swappable module so YouTube/Instagram auto-publish can ship even if TikTok audit is still pending.

**Warning signs:**
Upload call returns 200/success but the video doesn't appear on the public profile when checked manually; TikTok developer dashboard shows "unaudited" status; the app was never submitted for review.

**Phase to address:**
Phase 6 (scheduled auto-publish). Flag as needing the deepest pre-implementation research of all 6 phases — this is a real external gatekeeping process outside the developer's control, with multi-day-to-two-week lead time.

---

### Pitfall 2: Treating monetization-risk flags as ground truth instead of a heuristic hint

**What goes wrong:**
Content ID and platform-side "limited/no ads" classifiers are opaque, inconsistent, and get it wrong in both directions — YouTube's own transparency reporting shows roughly 1% of claims (over 2 million videos in one half-year period) were reinstated as false claims, and gaming footage specifically is disproportionately affected because in-game licensed music, TV-broadcast game footage (e.g. Forza mistaken for real racing), and streamer-mode audio can all still trigger claims even when a creator did everything "right." A locally-computed monetization-risk score built by this project (keyword/topic heuristics for gambling talk, hype speech, copyright-adjacent themes) will inevitably diverge from what the platform actually decides, in both directions: it will flag clean clips as risky (chilling effect on good content) and miss real problems it has no visibility into (a specific licensed track playing faintly in a game, a rights holder's undisclosed Content ID fingerprint).

**Why it happens:**
Platforms deliberately don't expose their full Content ID fingerprint databases or ad-suitability model internals — there's no local dataset that can fully replicate their decision. Developers building a "monetization safety scanner" often present its score as authoritative because it feels systematic, when it's actually a best-effort proxy correlated with, not equal to, the platform's real verdict. Platform policies also change frequently (ad-suitability guideline updates, new "hype speech"/gambling enforcement waves) without API notice, so a hardcoded ruleset silently goes stale.

**How to avoid:**
Frame the feature explicitly as advisory metadata ("possible risk factors detected," not "will/won't be monetized"). Never auto-block or auto-edit a clip based solely on the local score — surface it as an annotation the creator reviews before publish. Keep the ruleset in an editable, versioned config (not hardcoded in Python) so policy-language drift can be patched without a code change, and date-stamp the ruleset so staleness is visible. Where possible, cross-check against the platform's actual post-upload signal (e.g. YouTube Data API/Studio can report claim status after upload) as a feedback loop rather than trying to predict it perfectly beforehand.

**Warning signs:**
The flagging logic hasn't been updated since it was written while the underlying platform guidelines page has newer revision dates; users start ignoring the flags because false-positive rate is high ("crying wolf"); a clip flagged "safe" gets claimed/demonetized after publish with no mechanism to feed that outcome back into the ruleset.

**Phase to address:**
Phase 1 (monetization-risk metadata flagging). Needs explicit UAT criteria stating what confidence level is claimed (advisory only) so later phases (6) don't accidentally start treating the flag as a publish/no-publish gate.

---

### Pitfall 3: Auto-publish becomes irreversible-by-default with no dry-run or pause path

**What goes wrong:**
A scheduled multi-platform publish pipeline is built, tested against personal test accounts, and then pointed at the real channel. A bug in sequential-numbering logic, a stale/duplicate clip in the queue, or a scheduler that fires twice (e.g. after a crash-and-restart re-reads an already-processed queue item) results in duplicate or wrong-order public uploads across three platforms simultaneously. Unlike a bad git push, this cannot be `force-with-lease`'d away — a public video, once live even briefly, may already be indexed, screenshotted, or seen by subscribers, and deleting it after the fact looks worse than leaving a mistake.

**Why it happens:**
Teams build the "happy path" first (successful auth, successful upload, correct order) and treat dry-run/pause as a nice-to-have polish item added at the end, if there's time. Because local dev/test cycles almost always use small test batches and manual triggering, the failure mode that matters — an unattended scheduled run going wrong while nobody is watching — is exactly the scenario least likely to get exercised before "done."

**How to avoid:**
Design the safety mechanism first, not last: a global dry-run flag that runs the entire pipeline (auth, metadata build, ordering) but stops immediately before the actual upload API call, logging exactly what would have been posted, to where, in what order. A persistent, easily-toggled "paused" state (a file or config flag checked at the start of every scheduled run) that a human can flip without needing to understand the codebase. Idempotency keys / a processed-manifest so a crash-and-restart never re-publishes an already-published item. Treat the first N real scheduled runs as supervised (require a manual confirmation step) before fully unattended mode is trusted.

**Warning signs:**
No `--dry-run` flag exists in the phase 6 CLI; the only way to stop a scheduled run is to kill the process or edit code; there's no local record of "this clip/this platform/this timestamp was already published" that survives a crash.

**Phase to address:**
Phase 6 (scheduled auto-publish) — this is the single highest-blast-radius phase in the whole milestone and should have the dry-run/pause/idempotency mechanism specified before any upload-API code is written, per the project's own stated constraint on auto-publish irreversibility.

---

### Pitfall 4: OAuth credentials for three platforms repeat (and multiply) this project's one real security incident

**What goes wrong:**
This project already had a real incident: a commit containing per-channel view/stat data reached a public repo and required a `git rebase` history rewrite + force-push to scrub. Phase 6 introduces OAuth client secrets and refresh/access tokens for *three* platforms (YouTube, TikTok, Instagram) instead of one (today only YouTube Analytics read-only creds exist). The current pattern already found in `CONCERNS.md` — `client_secret.json`/`token.json` living in the repo root, defaulted to by CLI args — is a lower-stakes version of exactly the pattern that caused the original incident (secrets/data sitting in the tracked working tree, relying on `.gitignore` discipline alone rather than being structurally outside the repo). Scaling that pattern to three platforms' worth of write-scoped upload credentials (not read-only Analytics scopes) triples the blast radius: a slip on any one of three `.gitignore` entries, an accidental `git add -A`, or a zipped project folder shared for support, now leaks credentials that can *publish content on the creator's behalf*, not just read view counts.

**Why it happens:**
It's the path of least resistance during development — dropping `client_secret.json` next to the code that reads it "just works" locally, and `.gitignore` feels like sufficient protection until one command (`git add .`, a merge, a rebase gone wrong) bypasses it. The existing YouTube Analytics integration already established this convention, so new platform integrations naturally copy it rather than questioning it.

**How to avoid:**
Move ALL OAuth material (all three platforms, going forward — and ideally migrate the existing YouTube ones too) to a directory structurally outside the project tree (e.g. `~/.config/shorts-maker/credentials/`), never under `D:\shorts-maker` at all, so there is no `.gitignore` reliance — the files physically cannot be `git add`ed by accident. Add a pre-commit safeguard (simple grep-based hook checking staged diffs for patterns like `client_secret`, `refresh_token`, `access_token`, channel-specific numeric IDs) so a slip is caught before it's committed, not after it's pushed. Since these are now *write/upload*-scoped tokens (higher stakes than the existing read-only Analytics scope), also apply at-rest encryption or OS keyring storage (Windows Credential Manager) rather than plaintext JSON — plaintext OAuth token storage is explicitly called out as unsafe in current OAuth security guidance regardless of gitignore status, because local-disk/backup/zip exposure is a real channel (already flagged as a live concern for the existing token.json). Document the "no personal/channel/credential data in the repo" constraint at the top of any new phase-6 script file as an explicit repeated warning, not just in PROJECT.md.
Also watch the *other three* new data types phase 6 and phases 2/6 introduce that are just as leakable as the original view-count incident: (a) naming/style-history analysis output (phase 2) derived from real past video titles — must stay in the same gitignored cache tier as `youtube_analytics.py` output, not get written into a tracked `docs/` file the way the original incident happened; (b) the auto-publish sequential-numbering/scheduling state (phase 6) which necessarily contains real upload timestamps, real clip filenames, and real per-platform post IDs; (c) any LLM-call logs/cache (phase 3) if a cloud LLM is used, since prompts will contain real transcript excerpts and possibly real channel context.

**Warning signs:**
Any new script in phases 2, 3, or 6 defaults a `--credentials`/`--token`/`--cache` path to somewhere inside the repo tree; a new `docs/*.md` file references specific real clip titles, view counts, or scheduling timestamps instead of pointing at a gitignored cache; `git status` ever shows an untracked-but-not-ignored file containing OAuth material or real channel names.

**Phase to address:**
All of phases 1, 2, 3, and 6 should re-verify this constraint, but phase 6 is where it becomes acute (three platforms' write-scoped credentials + a persistent scheduling/history state file). Recommend a dedicated "secrets and data locality" check as an explicit UAT/verification item in phase 6's plan, mirroring the existing `CONCERNS.md` recommendation to relocate `client_secret.json`/`token.json` outside the repo root.

---

### Pitfall 5: LLM-generated titles/tags drift into generic "AI voice" and break the channel's established style

**What goes wrong:**
Phase 3 (LLM-generated titles/tags) sits directly downstream of phase 2 (learning the creator's own naming/style history). If phase 3 is implemented as a bare "summarize this clip and give it a catchy YouTube Shorts title" prompt without concretely feeding in the phase-2 style profile, the LLM defaults to generic clickbait patterns (excessive emoji, "You WON'T believe...", title-case-every-word, over-punctuated) that are recognizably AI-generated and don't match the creator's actual voice — undermining the entire point of building phase 2 first. This is a well-documented LLM tendency: without strong few-shot grounding in real examples, generation regresses to the model's training-data-average style for the genre, not the individual creator's idiolect.

**Why it happens:**
It's much easier to write "generate a good title for this gaming clip" than to build a proper few-shot prompt that injects N real past titles + extracted stylistic patterns (capitalization habits, emoji usage, length, specific slang/catchphrases, language mix — this channel appears to be Russian-language given the codebase). Teams treat phase 2 (style learning) and phase 3 (LLM generation) as separable rather than tightly coupled, and only in QA does someone notice the generated titles "don't sound like the channel."

**How to avoid:**
Do not treat phase 2's output as passive documentation — wire its concrete artifacts (real title examples, detected patterns/language) directly into phase 3's prompt as few-shot examples, not just a prose style description. Build an explicit "does this sound like us" review step into phase 3's UAT: generate titles for a handful of already-published clips and compare against what the creator actually titled them. Keep a human-approval gate before any auto-generated title/tag set is used (especially once phase 6 wires titles straight into auto-publish) — this is cheap insurance against a bad title going live unattended. Consider constraining generation with a hard style checklist derived from phase 2 (max length, required/forbidden words, capitalization rule, language) as a post-generation validator rather than relying purely on prompt-following.

**Warning signs:**
Generated titles use English clickbait patterns on a Russian-language channel; titles are generic enough they could apply to any gaming clip on any channel; phase 2's extracted style profile isn't actually referenced anywhere in phase 3's prompt construction, only mentioned in comments/docs.

**Phase to address:**
Phase 3 (LLM titles/tags), but the prevention work (structured style-profile output, not prose) belongs in phase 2's deliverable shape. Flag phase 2→3 handoff as needing explicit contract definition during roadmap/planning, since a loose handoff here is the single biggest risk to phase 3 output quality.

---

### Pitfall 6: Cloud LLM calls silently break the "fully local, fail-open" pipeline principle

**What goes wrong:**
The project's existing architecture is local-first with explicit fail-open behavior for every optional network-touching feature (diarization, audio-energy, YouTube Analytics grounding — all degrade gracefully if unavailable). Phase 3 (LLM titles/tags) is the first feature that likely *requires* a capable LLM, and if a cloud API (rather than a local model) is chosen for quality reasons, it introduces: a new failure mode if the network/API is down mid-batch-run, per-clip latency/cost that scales with the number of clips (compilation phase 5 could multiply this), and a new place where clip transcript content (potentially containing anything said on stream) leaves the machine.

**Why it happens:**
Cloud LLMs (GPT/Claude/Gemini-class) are meaningfully better at natural, on-voice short-form titling than what's practical to self-host on typical creator hardware alongside Whisper + ffmpeg + video rendering already running locally. Teams pick the cloud option for quality and treat the "it's a new external dependency" tradeoff as a footnote rather than an architectural decision requiring the same fail-open treatment as existing optional features.

**How to avoid:**
Apply the existing fail-open pattern explicitly: if the LLM call fails or times out, fall back to a non-LLM heuristic title (e.g. existing transcript-derived or timestamp-based default) rather than blocking the whole pipeline run. Cache LLM responses per-clip (keyed on transcript hash) so re-runs of the same clip don't re-spend cost/latency — this project already caches Whisper output for the same reason. Batch/rate-limit calls if compilation (phase 5) means many small clips get titled at once, to control cost and avoid provider-side rate limits. Decide and document explicitly whether transcript content sent to a cloud LLM is acceptable given this is personal streaming content — if the creator would be uncomfortable with a third party seeing raw transcript excerpts, this pushes toward a local model instead, which is a real architectural fork worth deciding deliberately rather than defaulting into.

**Warning signs:**
No fallback path exists if the LLM API call throws/times out — the whole run aborts; no caching layer means every re-run of the pipeline re-calls the LLM for identical content; nobody explicitly decided whether cloud-LLM data handling is acceptable, it just happened because that's what got coded first.

**Phase to address:**
Phase 3 (LLM titles/tags) primarily; also touches phase 5 (compilation) if it needs to title/tag merged highlight clips, and should reuse phase 3's same fallback/caching mechanism rather than reinventing it.

---

### Pitfall 7: Context-driven transition selection (phase 4) becomes a black box that occasionally picks a jarring transition with no override

**What goes wrong:**
Building an automatic "analyze scene/audio at the clip boundary, pick match-cut vs whip-pan vs glitch vs crossfade" system is inherently heuristic and will sometimes choose a transition that looks wrong for reasons the analysis can't see (e.g. a whip-pan chosen because motion vectors matched, but the visual content was actually just camera shake, not an intentional pan). Because this replaces the previously fixed, predictable cut/punch-zoom set with a nondeterministic-feeling choice, a bad pick is now harder to reason about ("why did it choose glitch here?") and — if there's no manual override — harder to fix than just re-running with a fixed transition.

**Why it happens:**
Motion/audio heuristics are proxies, not ground truth about "does this look good," same category of problem as Pitfall 2's monetization heuristics — a scene-analysis signal correlates with but doesn't guarantee a good transition choice. Teams building the smart-selection logic tend to validate it on a handful of hand-picked examples that happen to work, not the long tail of real boundary content.

**How to avoid:**
Keep the fixed transition set (cut, punch-zoom, crossfade) as an always-available fallback/override, selectable per-boundary manually or via config, so context-driven selection is additive rather than a forced replacement. Log the chosen transition + the signals that drove the choice (motion score, audio energy delta, etc.) alongside the render output, so a bad pick is debuggable after the fact rather than a mystery. Treat this as a ranking/scoring problem with a confidence threshold — below a certain confidence, fall back to a safe default (crossfade or cut) rather than forcing an exotic transition (glitch/whip-pan) on ambiguous signals.

**Warning signs:**
No way to force a specific transition for a specific boundary without editing code; no log of which signals produced which transition choice; exotic transitions (glitch, whip-pan) appear disproportionately often relative to how rarely their triggering conditions should actually occur in typical gameplay footage.

**Phase to address:**
Phase 4 (context-driven transitions). Lower severity than phases 2/3/6 (this is a quality/UX pitfall, not a security or irreversibility one) but worth a config-level escape hatch from day one since retrofitting an override mechanism later is more work than building it in from the start.

---

### Pitfall 8: Highlight-compilation clustering (phase 5) produces a coherent-looking but nonsensical narrative by grouping on the wrong similarity axis

**What goes wrong:**
Phase 5 groups sub-threshold moments "by similarity" (gameplay situation or joke/callback) into one compiled short. If the similarity metric is naive (e.g. purely semantic/embedding similarity on transcript text) it can group moments that are topically similar but narratively incompatible — stitching together three different jokes about the same game mechanic from three different points in the stream, in an order that makes the compilation feel randomly shuffled rather than a coherent "best-of" reel, even though each individual moment reads fine as a similarity match.

**Why it happens:**
Semantic similarity (what the existing candidate-finding pipeline already uses) is good at "these are about the same topic" but doesn't capture "these belong together as a satisfying sequence" — ordering, pacing, and callback/reference relationships between moments require a different signal than topical clustering, and it's tempting to reuse the exact same similarity infrastructure from moment-finding without adapting it for the compilation use case.

**How to avoid:**
Treat clustering and ordering as two separate steps: cluster for "belongs in the same compiled short" (topic/situation similarity is fine here), then order for "plays well as a sequence" (chronological order within a cluster is a safe, simple default rather than trying to also optimize narrative flow automatically). Cap cluster size and total compiled-short duration so this doesn't produce an unbounded mega-compilation from a single overused joke format. Include the transitions system (phase 4) here too — compiled shorts stitching many short moments together are exactly where transition choice matters most and where a bad automatic pick (Pitfall 7) will be most visible.

**Warning signs:**
Compiled shorts feel like a random shuffle rather than a highlight reel when watched back; cluster sizes are unbounded (a single recurring joke format could theoretically absorb dozens of sub-threshold moments into one overlong compilation); the same similarity function/threshold from moment-finding was copy-pasted without adjustment for the compilation use case.

**Phase to address:**
Phase 5 (compilation of sub-threshold moments). Depends on phase 4's transition system being solid first (compiled shorts are the heaviest user of transitions), so sequencing phase 5 after phase 4 in the roadmap is advisable.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|-----------------|-----------------|
| Hardcoding monetization-risk keyword rules in Python instead of an external config | Faster to ship phase 1 | Platform policy changes require a code change + redeploy every time; no way for the creator to tune sensitivity without touching code | Only for an initial throwaway prototype, never for the phase-1 deliverable |
| Storing OAuth tokens as plaintext JSON in a config directory (even outside the repo) | Simplest to implement, matches existing `youtube_analytics.py` pattern | Write-scoped (upload) tokens for 3 platforms are a much higher-value target than the existing read-only Analytics token; plaintext at rest is flagged unsafe by current OAuth guidance regardless of git status | Never for write/upload-scoped tokens; marginal for read-only single-platform tokens if disk access is already trusted |
| Reusing the moment-finding similarity function unmodified for phase 5 clustering | Fast to implement, no new infra | Produces topically-correct but narratively-incoherent compilations (Pitfall 8) | Only as a first pass to validate the pipeline shape, not the final phase-5 implementation |
| Skipping the dry-run flag in early phase-6 builds "to move faster" | Simpler initial implementation | First real unattended scheduled run becomes the first-ever test of the failure path, with public irreversible consequences | Never — dry-run should exist before the first real scheduled run, not be retrofitted |
| Letting the LLM (phase 3) run with no per-clip response cache | Simpler first implementation | Every pipeline re-run re-spends latency/cost identically to a Whisper cache miss on every run — this project already learned this lesson once with Whisper caching | Acceptable only for a manual one-off test, not for the shipped feature |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|-------------------|
| YouTube Data API (upload) | Assuming the old 1,600-unit `videos.insert` cost still applies and over-engineering quota-conserving batching | Verify current quota cost against `developers.google.com/youtube/v3/determine_quota_cost` at implementation time — Google reduced `videos.insert` from ~1,600 to ~100 units in a Dec-2025 update, materially changing how many uploads/day the default 10,000-unit quota supports (now up to ~100/day rather than ~6/day) |
| TikTok Content Posting API | Building and testing against an unaudited client, assuming "upload succeeded" means "video is public" | Submit for API audit before relying on public visibility; verify visibility status post-upload; budget days-to-two-weeks lead time for the audit in the phase-6 timeline |
| Instagram Graph API (content publishing) | Scheduling more than 25 posts per rolling 24h window per account, or targeting a personal (non-Business/Creator) account | Track a rolling-window publish counter per account before queuing; confirm the target Instagram account is a Business or Creator account (Graph API content publishing doesn't support plain personal accounts) |
| All 3 platforms' OAuth | Refresh-token expiry/revocation handled reactively (crash on 401) rather than proactively | Detect near-expiry/refresh failures explicitly, alert instead of silently failing a scheduled publish, and never assume a token obtained once during setup stays valid indefinitely — Google/Meta/TikTok can all revoke tokens on policy changes, password resets, or extended inactivity |
| Any cloud LLM API (phase 3) | Treating it like the existing local, always-available Whisper step with no fail-open path | Explicit try/fallback to a heuristic non-LLM title/tag generator on API failure/timeout, mirroring the project's existing fail-open pattern for diarization/audio-energy/Analytics |

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|-----------------|
| Calling an LLM once per candidate clip with no batching | Linear cost/latency growth as clip count grows, worst with phase 5 compilation generating extra merged clips | Batch multiple clips per LLM call where the API supports it; cache per-transcript-hash | Noticeable once a single stream session produces double-digit clip candidates, which this project's existing moment-finding already can |
| Re-running monetization-risk analysis on every pipeline invocation instead of caching per-transcript | Redundant CPU/analysis time on every re-render of the same source video | Cache risk-flag output keyed the same way existing Whisper transcription is cached | Becomes noticeable once render iteration (adjusting punch-zoom, transitions) requires re-running the full pipeline multiple times per source video |
| Sequential (not parallelized) per-platform upload in phase 6 | Total publish-window time scales linearly with number of platforms × number of clips, risking scheduling drift if run close to a scheduled slot | Run per-platform uploads concurrently where API rate limits allow, respecting Instagram's 25/24h cap and TikTok's per-user cap independently | Becomes relevant once more than a couple of clips are scheduled per run across all 3 platforms |

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Storing 3 platforms' OAuth client secrets/tokens inside the repo tree relying only on `.gitignore` | Repeat of this project's real incident, but worse — write/upload-scoped credentials could publish content on the creator's behalf, not just leak view stats | Move all credential files to a directory structurally outside the repo (e.g. `~/.config/shorts-maker/`); add a pre-commit grep hook for secret-shaped strings as defense in depth |
| Writing naming/style-history analysis output (phase 2) or scheduling/publish-history state (phase 6) into a tracked `docs/` or config file | Recreates the exact original incident (real per-channel data in a tracked file) via a new code path | Route all derived-from-real-channel-data artifacts through the same gitignored cache tier already established for `youtube_analytics.py` output; never write real titles/timestamps/view-counts into anything intended to be committed |
| Logging full LLM prompts/responses (phase 3) or full OAuth request/response payloads (phase 6) to disk without redaction | Log files become a second, easily-overlooked leakage surface containing transcript content or token material | Redact tokens from any logged HTTP request/response; treat log files as sensitive and gitignored by default, same tier as the token cache |
| No idempotency check before calling a platform's upload endpoint in phase 6 | A crash-and-restart of the scheduler could double-publish the same clip to the same platform | Maintain a persisted "already published: platform+clip+timestamp" manifest checked before every upload call |

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-------------------|
| Monetization-risk flags shown with no explanation of why | Creator doesn't trust or understand the flag, ignores it entirely (defeats the feature) | Show which specific signal(s) triggered the flag (detected keyword/topic, timestamp) so the creator can make an informed call |
| LLM-generated titles auto-applied with no review step before phase-6 auto-publish picks them up | A single bad/off-voice/hallucinated title goes live publicly with no human ever seeing it first | Require an approval step (even a lightweight one, e.g. a review file the creator glances at) between generation and publish, at least until the pipeline has a track record |
| Context-driven transitions with no visibility into what was picked and why | Creator can't tell if an odd-looking cut was intentional (context-driven) or a bug | Overlay/log the transition decision per boundary, even if not shown in the final render, for debuggability |
| Auto-publish scheduling with no single place to see "what's queued to go out, to where, when" | Creator loses track of what's about to happen unattended, increasing the chance a mistake goes unnoticed until it's already public | A simple queue-status view/command (even CLI-only) listing pending scheduled publishes per platform before they fire |

## "Looks Done But Isn't" Checklist

- [ ] **Monetization-risk flagging (phase 1):** Often missing a "confidence/advisory only" framing — verify the output metadata explicitly says "possible risk" not "will be demonetized," and that the ruleset is externally editable, not hardcoded.
- [ ] **Style/naming history learning (phase 2):** Often missing enforcement that its output never touches a tracked file — verify by running `git status` after generating style-profile output and confirming nothing new and non-gitignored appears.
- [ ] **LLM titles/tags (phase 3):** Often missing a no-network/API-failure fallback path — verify by simulating an API timeout/error and confirming the pipeline still produces a usable (if less polished) title rather than aborting.
- [ ] **Context-driven transitions (phase 4):** Often missing a manual override/fixed-transition escape hatch — verify a specific boundary's transition can be forced via config without editing code.
- [ ] **Highlight compilation (phase 5):** Often missing a cap on cluster size/compiled-short duration — verify with a synthetic case having many similar sub-threshold moments that the output doesn't become an unbounded mega-compilation.
- [ ] **Scheduled auto-publish (phase 6):** Often missing dry-run mode, pause mechanism, and idempotent/already-published tracking — verify all three exist and are exercised in a test run before the first real unattended scheduled publish; also verify TikTok's audit status and Instagram's 25/24h rolling counter are both accounted for, not just YouTube's quota.

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|-----------------|
| OAuth credential/personal data committed to git (repeat of the original incident) | HIGH | Follow the same pattern already used successfully once: `git rebase` to drop the offending commit(s), `git push --force-with-lease` only after explicit user confirmation per this project's git discipline constraint; then rotate/revoke the exposed credentials at the provider (Google Cloud Console, TikTok/Meta developer dashboard) since history-scrubbing doesn't undo exposure if the repo was ever public/cloned |
| A bad clip auto-published to a platform via phase 6 | HIGH (partially irreversible — visibility already happened) | Immediately use the platform's own API/dashboard to delete or set the video to private; do NOT rely on git-style history rewriting, there is no equivalent; add the incident's specific trigger condition to the idempotency/dry-run test suite so it can't recur |
| TikTok client stuck in unaudited/private-only mode discovered after phase-6 build is "complete" | MEDIUM | Submit for TikTok API audit immediately (days-to-two-weeks lead time); in the interim, keep TikTok publish routed through manual upload rather than blocking the whole auto-publish feature for YouTube/Instagram |
| LLM-generated title/tags found to be off-voice or hallucinated after being used | LOW–MEDIUM | Because phase 3 output should already be human-reviewed before publish (see UX Pitfalls), catch happens pre-publish; if it slipped through to a live video, edit title/description directly via platform API/dashboard, and add the specific failure example to phase 2/3's few-shot grounding set to prevent recurrence |
| Monetization-risk flag proven wrong after the fact (platform claimed a "safe"-flagged clip, or didn't claim a "risky"-flagged one) | LOW | Log the outcome against the original flag as a feedback data point; periodically review these mismatches to tune the ruleset — no urgent recovery action needed since the flag was always advisory, not a gate |

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| TikTok unaudited-client visibility trap | Phase 6 | Confirm TikTok API audit approved and a post-upload visibility check exists before relying on public TikTok auto-publish |
| Monetization-risk flags treated as ground truth | Phase 1 | UAT explicitly confirms output metadata is framed as advisory, ruleset lives in editable config with a date stamp |
| Auto-publish irreversibility / no dry-run or pause | Phase 6 | Dry-run mode and pause flag both exist and are exercised in a test run; idempotency manifest verified to survive a simulated crash-restart |
| OAuth/personal-data leakage repeat across 3 platforms + phase 2/6 derived data | Phases 1, 2, 3, 6 (cross-cutting) | `git status`/`git log` checked clean of credentials and real channel data after each phase; credential files confirmed to live outside the repo tree |
| LLM titles drifting to generic "AI voice" | Phases 2 → 3 (handoff) | Side-by-side comparison of generated titles against real historical titles for the same channel, reviewed by the creator |
| Cloud LLM breaking local-first fail-open principle | Phase 3 (and phase 5 reuse) | Simulated API failure/timeout still produces a usable fallback title without aborting the pipeline |
| Context-driven transition black box / no override | Phase 4 | Config-level manual override exists per boundary; transition decision + signals logged per render |
| Highlight-compilation clustering incoherence | Phase 5 | Manual review of a compiled short's ordering/coherence; cluster size and total duration capped and verified against a synthetic stress case |

## Sources

- [YouTube Data API v3 quota calculator](https://developers.google.com/youtube/v3/determine_quota_cost) — HIGH confidence, official Google docs
- [YouTube API Quota Limits 2026 guide](https://www.getphyllo.com/post/youtube-api-limits-how-to-calculate-api-usage-cost-and-fix-exceeded-api-quota) — MEDIUM confidence, third-party but corroborates the Dec-2025 `videos.insert` cost reduction (~1600 → ~100 units) against the official calculator
- [TikTok Content Posting API — Getting Started](https://developers.tiktok.com/doc/content-posting-api-get-started) — HIGH confidence, official TikTok developer docs (unaudited-client caps, SELF_ONLY visibility restriction)
- [TikTok Getting Started FAQ](https://developers.tiktok.com/doc/getting-started-faq) — HIGH confidence, official docs (app review timeline)
- [Instagram Graph API — Content Publishing Limit reference](https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user/content_publishing_limit/) — HIGH confidence, official Meta developer docs (25 posts/rolling-24h)
- [Ayrshare: Instagram Graph API Error 9 — 25-Post Daily Limit](https://www.ayrshare.com/solutions/instagram-graph-api-error-9-the-25-post-daily-limit-how-to-fix-it/) — MEDIUM confidence, third-party, corroborates official limit and adds rolling-window behavior detail
- [YouTube Help: How Content ID works](https://support.google.com/youtube/answer/2797370) — HIGH confidence, official YouTube docs
- [Content ID false-claim reinstatement transparency data / gaming-footage claim examples](https://bai-gaming.com/tech-guides/video-game-youtube-copyright-claim-list/) — MEDIUM confidence, third-party aggregation, used only for illustrating known false-positive patterns, not exact current statistics
- [Google OAuth 2.0 Best Practices](https://developers.google.com/identity/protocols/oauth2/resources/best-practices) — HIGH confidence, official Google docs
- [OAuth refresh token security best practices (Obsidian Security)](https://www.obsidiansecurity.com/blog/refresh-token-security-best-practices) — MEDIUM confidence, third-party security vendor, corroborates plaintext-storage-is-unsafe consensus
- `D:\shorts-maker\.planning\PROJECT.md` — project's own incident history and constraints (primary source for Pitfall 4's framing)
- `D:\shorts-maker\.planning\codebase\CONCERNS.md` — existing OAuth-on-disk finding, confirms current credential-storage pattern predates this milestone

---
*Pitfalls research for: local video-clipping pipeline — monetization flagging, style learning, LLM titling, smart transitions, highlight compilation, multi-platform scheduled auto-publish*
*Researched: 2026-07-07*
