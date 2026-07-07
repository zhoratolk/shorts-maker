# Feature Research

**Domain:** AI video clipping / creator-tooling pipeline (subsequent milestone — 6 new capabilities added to an existing local shorts-cutting tool)
**Researched:** 2026-07-07
**Confidence:** MEDIUM (web-search-derived; no single source verified against official docs beyond TikTok Developer docs, which are HIGH-confidence primary source; cross-checked claims marked MEDIUM, single-source marked LOW)

## Feature Landscape

### Table Stakes (Users Expect These)

Features users assume exist in any serious AI clipping tool today. Missing these makes the product feel behind Opus.pro/Choppity/Vizard/vidIQ-tier competitors.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Per-clip title + description text output | Every competitor (OpusClip, Choppity, vidIQ, Vizard) auto-generates a title alongside the clip; this repo already has `scripts/naming.py`/`scripts/metadata.py` doing filename + flat metadata text, so this is graduating an existing capability | LOW | Already 80% built — item 3 below is "make it LLM-authored instead of rule-based," not "build from zero" |
| Per-platform metadata formatting (character limits, hashtag conventions) | YouTube (100 char title, hashtags below fold), TikTok (~150 char caption, hashtag-heavy), Instagram Reels (2200 char caption cap but front-load matters) all have different conventions; tools that dump one blob everywhere look amateurish | LOW | `scripts/metadata.py` already renders per-platform; extending schema for tags is incremental |
| Basic content-safety awareness (profanity/violence flag) | Every "monetization checker" tool and even OpusClip's "Virality Score" gate implicitly filters out content that would visibly tank reach; creators expect *some* signal, not silence | MEDIUM | This is item 1 below — but the *baseline* version (flag obvious profanity/violence) is table stakes; the *nuanced* per-platform-rule version is the differentiator |
| Cut/crossfade as default transition, with option for "fancier" transitions | Every editing tool (Clipchamp, Premiere, Descript) ships basic transitions; users expect at least fade/cut, and pure hard-cut-only feels unfinished for a "polish" pipeline | LOW | Repo already has jumpcuts + punch-zoom; adding crossfade/whip-pan is additive, not foundational |
| Manual review/approval step before publish | No credible tool auto-publishes without a preview step; TikTok/YouTube policies plus the irreversibility of a public post make blind auto-publish unacceptable to any serious creator | LOW–MEDIUM | Repo's existing `CANDIDATES.md` approval gate pattern extends naturally to a "review queue" before scheduled auto-publish |
| Idempotent/cached per-video processing | Users expect re-running the tool not to redo expensive work (already a MVP norm in this repo) | LOW | Already implemented; new features (style-learning, LLM titling) must respect the same caching contract or they'll feel slow/expensive on reruns |

### Differentiators (Competitive Advantage)

Features that set this product apart from Opus.pro/Choppity/Vizard/Eklipse. These align with the Core Value ("no manual cutting, no lost highlight moments") and should be built deliberately, not half-heartedly.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **(1) Per-platform demonetization-risk flagging in exported metadata** | No mainstream clipping tool (Opus.pro, Choppity, Vizard, vidIQ) actually flags *per-platform* monetization risk in the output metadata — they optimize for "virality score," not "will this get demonetized." This is a genuine gap in the market: creators currently check demonetization risk manually or not at all until after the fact | MEDIUM | Needs a **static rule table**, not an LLM classifier, for the well-known triggers: (a) copyrighted/trending audio used past its licensed short-form window (YouTube auto-licenses trending Shorts audio ≤60s; over that, Content ID treats it as unlicensed — MEDIUM confidence, cross-checked), (b) gambling/gambling-adjacent content (TikTok explicitly restricts "gambling-like activities" from FYF and monetization — MEDIUM confidence, TikTok Community Guidelines), (c) hate speech/harassment keyword/topic detection (LOW confidence without an actual classifier — this needs an LLM pass over transcript, not keyword matching, to avoid false positives on gaming trash-talk vs actual slurs), (d) reused/reaction content flags (YouTube's July-2025 "unoriginal content" crackdown specifically dings compilations-without-commentary and cross-platform reposts — relevant to feature 5 below) |
| **(2) Learning creator's own naming/moment-selection style from history** | This is the single most differentiated feature on this list — no competitor tool personalizes off a *specific creator's own upload history*; they all optimize toward generic "viral patterns" learned across all users. A style-matching feature keeps output voice-consistent for one channel, which single-streamer tools (this repo's exact use case) actually need | MEDIUM–HIGH | Feasible today because `scripts/youtube_analytics.py` already pulls real title/moment history (gitignored, correctly). Implementation should be a **prompt-context injection** (few-shot: "here are 20 of your past titles + which moments got picked"), not a fine-tuned model — fine-tuning is overkill for one channel's data volume and reintroduces the "encoding judgment in Python" anti-pattern this repo explicitly avoids (see ARCHITECTURE.md). Depends on channel having enough upload history to learn from; needs a graceful degrade path for brand-new channels |
| **(3) LLM-generated titles + tags per clip candidate** | Distinguishes from "template-filled metadata" — direct upgrade path from what already exists (`naming.py`/`metadata.py`). Every big competitor already does this (OpusClip's "auto-generated punchy titles," Choppity's "per-platform titles and captions" — MEDIUM confidence cross-checked across sources), so this alone is *catching up to table stakes*, not differentiating. The differentiator is combining it with #2 (style-matched) — that combination is what's actually novel | LOW–MEDIUM | Straightforward LLM call per candidate once transcript + context is available; the risk is generic "clickbait-y" output if not grounded in creator's real voice (hence dependency on #2) |
| **(4) Context-driven transition selection per clip-boundary** | No mainstream *short-clipping* tool does scene-aware transition selection (OpusClip/Choppity apply one uniform transition style across a whole video); this is more a traditional-NLE feature (Premiere/Descript let *humans* pick transitions per cut) than an AI-clipper feature. Doing this well is a real differentiator for a compilation-heavy pipeline like #5 | HIGH | Requires analyzing: motion vectors/optical flow at both clip boundaries (for whip-pan candidacy — needs actual camera-motion or in-game-view-rotation direction match), audio energy/loudness continuity (crossfade candidacy), scene similarity (match-cut candidacy — is there a similar shape/color/composition to match on?). This is genuinely hard to do reliably; **realistic MVP scope is a decision tree over 2–3 cheap signals** (audio loudness delta, motion magnitude via optical flow, "is there a natural silence gap" already computed by `silence.py`) rather than true match-cut detection, which needs real computer-vision shot analysis your Python layer doesn't have yet |
| **(5) Compilation of sub-threshold-length highlights, grouped by similarity** | This is where the pipeline stops being "clip finder" and becomes "editor" — genuinely rare among competitors. Existing tools discard short moments or force them into full standalone shorts; grouping by gameplay/thematic similarity into one coherent compilation is closer to what human editors do and nobody productizes well | HIGH | Two hard sub-problems: (a) similarity grouping — needs either an embedding-based clustering over candidate `reason`/transcript text (cheap, LLM-context-friendly) or actual game-state signals (harder, out of scope for this repo's stack); (b) coherent stitching — directly depends on #4 (transition selection) to not feel like a jarring supercut. **This feature should be sequenced after #4**, not before — building compilation stitching with only hard cuts available first, then bolting on smart transitions later, means redoing the stitching logic twice |
| **(6) Scheduled auto-publish with sequential numbering across platforms via APIs** | Real, tangible time-saver: zero competitor clipping tool combines *clip generation* and *cross-platform scheduled publish* well (OpusClip/Vizard integrate with generic schedulers like Buffer/Later at best); doing native per-platform API publish tied to the same pipeline that made the clip is a meaningful differentiator for a single-channel tool | HIGH (mostly due to API/OAuth surface area, not algorithmic complexity) | **Critical platform-specific gotcha**: TikTok's Content Posting API restricts **unaudited API clients to SELF_ONLY (private) posting** — public posting requires passing TikTok's app audit process (HIGH confidence, official TikTok developer docs). This means a naive local-script implementation *cannot auto-publish public TikToks* until the audit is completed — a multi-week/organizational process, likely infeasible for a personal single-user script. Instagram Graph API requires a Professional/Business account plus Meta app review with screen recordings (MEDIUM confidence). YouTube Data API has no such audit gate for a single channel uploading to its own account (much lower friction — OAuth consent screen "testing" mode is enough for personal use, matching the existing `youtube_analytics.py` OAuth pattern). **Net: YouTube auto-publish is realistic near-term; TikTok/Instagram auto-publish need to design for a private-draft/manual-final-publish fallback from day one**, not bolt it on later. Sequential numbering itself is trivial (increment a counter in metadata/filename) — the complexity is 100% the platform audit/OAuth friction, not the numbering logic |

### Anti-Features (Commonly Requested, Often Problematic)

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|------------------|-------------|
| Fully automatic public posting with no human review step | "Set it and forget it" is the appeal of every scheduling tool's marketing | PROJECT.md itself flags this as needing "dry-run + pause" — publishing is irreversible and public; a bad title/clip/flagged-content auto-published at 3am is a real reputation/demonetization risk with no undo. TikTok's own audit gate effectively forces a review step anyway for that platform | Scheduled *draft* creation + a lightweight approval/veto window (even a same-day one) before the actual publish call fires, consistent with the existing `CANDIDATES.md` human-approval pattern already in this pipeline |
| Keyword-blocklist-only demonetization flagging (regex for "banned words") | Looks cheap and fast to build, and superficially matches how some ad-friendliness checkers market themselves | High false-positive rate on gaming content specifically (trash-talk, violence-adjacent game terminology, "kill/die" language is normal FPS/gaming vocabulary but trips naive blocklists) and high false-negative rate on context-dependent violations (gambling *discussion* vs *promotion* is a meaningful legal distinction TikTok itself draws — MEDIUM confidence) | Two-tier flagging: cheap deterministic rules for unambiguous triggers (audio-length-vs-license-window, explicit gambling-platform-name/affiliate-link mentions) + an LLM pass with the transcript for judgment-requiring cases (hate speech vs. banter), matching this repo's existing "semantic judgment stays in Claude/SKILL.md, not Python" architecture principle |
| Fine-tuning a custom LLM/model on the creator's past titles | Sounds like "real" personalization/ML | Total upload history for one channel is almost certainly too small a dataset to fine-tune reliably (dozens–hundreds of examples, not thousands+); adds a training/serving pipeline this project has zero infrastructure for, and directly violates the existing anti-pattern ("no server/app process," "no persistent state beyond files") | Few-shot prompt context (inject N most similar/most recent historical titles + which moments they picked into the LLM prompt at generation time) — zero training infra, same on-device/local-first philosophy as the rest of the repo |
| True computer-vision shot/scene-matching for match-cut transitions (frame-level composition analysis) | "Do it like a real editor" is the natural ambition once you're picking transitions contextually | This requires real shot-detection/frame-embedding infrastructure (e.g., CLIP-embedding every frame pair at cut boundaries) that doesn't exist in this repo's stack and is a large net-new dependency for one transition type out of five | Approximate proxies already cheap to compute: reuse `audio_energy.py` loudness deltas + simple ffmpeg-derived motion/optical-flow magnitude at boundary frames to choose among {cut, crossfade, whip-pan, glitch}; treat true "match cut" as an LLM-suggested *candidate* (the orchestrator already looks at frames via `frames.py`) rather than an automatically detected one — cheaper and keeps semantic judgment where the architecture wants it |
| One-size-fits-all metadata across all three platforms | Simpler to implement, and it's tempting given `metadata.py` already renders "a" per-platform text | Users get penalized: TikTok favors punchy short hashtag-heavy captions, YouTube Shorts titles double as search/SEO surface (numbers/years help per research), Instagram Reels captions can be longer but front-loaded text matters most (algorithm truncates in feed) — treating them the same measurably underperforms | Keep the existing `metadata.py` per-platform-rendering pattern; extend the *tag/title generation* prompt (item 3) to be platform-aware, not just the text-wrapping layer |

## Feature Dependencies

```
(3) LLM-generated titles+tags
    └──enhanced-by──> (2) Style-learning from creator history
                          (2 makes 3's output voice-consistent; 3 works standalone but generically without 2)

(2) Style-learning from creator history
    └──requires──> existing scripts/youtube_analytics.py (real upload history data)
                       └──constrained-by──> Privacy/git-hygiene rule (PROJECT.md Constraints) —
                                             history data must stay gitignored cache, never committed

(1) Demonetization-risk flagging
    └──partially-overlaps──> (5) Compilation of sub-threshold highlights
                                 (YouTube's "unoriginal content"/compilation-without-commentary
                                 crackdown directly implicates how (5) should be built —
                                 (5)'s output must read as one coherent authored short,
                                 not a bare stitched supercut, or it inherits (1)'s risk flags)

(4) Context-driven transition selection
    └──required-by──> (5) Compilation of sub-threshold highlights
                          (stitching multiple short moments into one coherent short
                          needs smarter-than-hard-cut transitions to not feel like
                          a jarring supercut; building (5) before (4) means redoing
                          the stitching logic once (4) lands)

(6) Scheduled auto-publish
    └──requires──> (3) LLM-generated titles+tags (need final metadata before scheduling)
    └──requires──> (1) Demonetization-risk flagging (should gate/warn before an irreversible public post)
    └──conflicts-with──> naive "fully automatic" framing
                             (TikTok's audit gate + Instagram's app-review requirement
                             + PROJECT.md's own dry-run/pause requirement all push
                             toward draft-then-approve, not blind auto-post)
```

### Dependency Notes

- **(3) enhanced by (2):** LLM titling without style-context produces generic "viral-sounding" titles indistinguishable from any competitor's output; injecting the creator's own historical title patterns as few-shot context is what makes this differentiated rather than table-stakes. Build (3) so it can run standalone (fallback path when history is too sparse — e.g., new channel, or history fetch fails per the fail-open principle), but design its prompt interface to *accept* style context from (2) from day one, so this isn't a redo later.
- **(4) required by (5):** Grouping and stitching short highlight moments into one short is only as good as the seams between them. If (5) ships before (4), the compilation phase will need hard-cut-only stitching, then need to be revisited entirely once smarter transitions exist — better to sequence (4) before or alongside (5), not after.
- **(1) partially overlaps (5):** YouTube's current enforcement stance explicitly penalizes "compilations of others' clips" and low-originality stitched content (MEDIUM confidence, cross-checked across two independent sources). Since this repo's compilations are of the *creator's own* footage (not others'), the risk is lower — but (5)'s output should still carry enough original framing (subtitles, creator's own voice/commentary already in the audio) to avoid tripping the same enforcement pattern. Worth a specific flag in (1)'s rule table: "is this clip a stitched compilation? confirm it retains original creator audio/commentary throughout, not just game footage."
- **(6) requires (1) and (3):** Auto-publish is the last, irreversible step — it should not fire until both the metadata (3) is finalized and the monetization-risk flag (1) has been checked (ideally surfaced to the creator as a go/no-go signal before the scheduled post fires, not just logged after the fact).
- **(6) conflicts with "fully automatic" framing:** Both external platform policy (TikTok's unaudited-client SELF_ONLY restriction — HIGH confidence, official docs) and the project's own stated constraint (dry-run + pause mechanisms, PROJECT.md Constraints section) push this toward a **draft-and-approve** model rather than true blind automation, especially for TikTok in the near term.

## MVP Definition

### Launch With (v1 of these 6 features)

Minimum slice that delivers real value without the highest-risk/highest-uncertainty work.

- [ ] **(3) LLM-generated titles+tags** — lowest complexity, directly extends existing `naming.py`/`metadata.py`, immediately visible value, near-zero platform risk
- [ ] **(1) Demonetization-risk flagging (deterministic-rule tier only)** — the cheap, high-confidence rules (audio-license-window check, explicit gambling-keyword/affiliate-link check) can ship without an LLM classifier; defer the harder hate-speech/nuance tier
- [ ] **(6) Scheduled auto-publish — YouTube only, draft/dry-run first** — YouTube has no audit-gate friction like TikTok/Instagram; ship this platform first and validate the scheduling/numbering mechanics before tackling the other two platforms' API review processes

### Add After Validation (v1.x)

- [ ] **(2) Style-learning from creator history** — add once (3)'s baseline titling is validated and there's a clear "these outputs feel generic" signal to react to; also gives time to accumulate more upload history via (6)'s YouTube publishing
- [ ] **(1) Demonetization-risk flagging — LLM/nuance tier** — add the judgment-requiring classification (hate speech vs. banter, reused-content detection) once the deterministic tier's false-positive/negative rate is understood from real use
- [ ] **(6) Scheduled auto-publish — TikTok/Instagram** — only after (a) TikTok API client audit is submitted/passed, or a private-draft-only fallback is accepted as good enough, and (b) Instagram Business account + Meta app review is complete

### Future Consideration (v2+)

- [ ] **(4) Context-driven transition selection** — defer until the simpler wins above are shipped; start with the cheap 2–3-signal decision tree (audio delta + motion magnitude + silence-gap), not true CV shot-matching
- [ ] **(5) Compilation of sub-threshold highlights** — defer until (4) exists, since building it first means reworking the stitching logic once (4) lands; also benefits from (2)'s similarity/thematic grouping maturing first

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|----------------------|----------|
| (3) LLM titles+tags | HIGH | LOW | P1 |
| (1) Demonetization flagging (deterministic tier) | HIGH | LOW–MEDIUM | P1 |
| (6) Auto-publish — YouTube only | MEDIUM–HIGH | MEDIUM | P1 |
| (2) Style-learning from history | HIGH | MEDIUM–HIGH | P2 |
| (1) Demonetization flagging (LLM/nuance tier) | MEDIUM | MEDIUM | P2 |
| (6) Auto-publish — TikTok/Instagram | MEDIUM | HIGH (mostly audit/OAuth process, not code) | P2 (blocked on external audit) |
| (4) Context-driven transitions | MEDIUM | HIGH | P3 |
| (5) Sub-threshold highlight compilation | MEDIUM–HIGH | HIGH | P3 |

**Priority key:**
- P1: Ship first — low platform-approval risk, direct extension of existing architecture
- P2: Ship once P1 is validated and/or external prerequisites (audits, history volume) are met
- P3: Genuinely hard, sequence-dependent on P1/P2 features landing first

## Competitor Feature Analysis

| Feature | OpusClip | Choppity | Vizard/vidIQ/Spikes Studio | Our Approach |
|---------|----------|----------|------------------------------|--------------|
| Title/tag generation | Auto-generated punchy titles + "Virality Score" (0–100) | Per-platform titles/captions + engagement score, natural-language custom selection criteria | vidIQ scores viral likelihood from transcript; Spikes Studio trained on broadcast history | LLM titles grounded in creator's *own* historical voice (item 2+3 combo) — none of these competitors personalize per-individual-creator history, only generic cross-user "viral pattern" models |
| Demonetization/monetization-risk awareness | Not surfaced as a distinct feature in any researched source — optimizes for virality, not platform-policy risk | Same gap | Same gap | Genuine differentiator: explicit per-platform risk flags in exported metadata, not just virality scoring |
| Transition style | Fixed "smooth transitions" as part of a uniform auto-edit style | Not emphasized as configurable/contextual | Not found to be context-aware in any researched source | Context-driven selection per clip-boundary (item 4) — no competitor found doing this for short-form auto-clippers specifically |
| Compilation of short/sub-threshold moments | Discards or force-fits short moments; "Highlight Video Maker" tool exists but is a generic highlight-reel, not thematic-similarity clustering of otherwise-too-short moments | Not found | Eklipse "stitches gameplay clips into one vertical highlight reel," closest analog found, but auto-trims to hottest single moment per clip rather than clustering *sub-threshold* leftovers by theme | Genuine gap: explicit reuse of moments that fail the standalone-short bar, grouped by similarity — not found productized elsewhere |
| Scheduled cross-platform auto-publish | Not itself a publisher — pairs with external schedulers | Not itself a publisher | Not itself a publisher | Native pipeline-to-publish integration is a real differentiator, but must be designed around TikTok's audit gate and Instagram's app-review requirement from day one, not treated as "just another API call" |

## Sources

- [YouTube Demonetization in 2026: Still Possible, Yet Still Avoidable — Mediacube](https://mediacube.io/en-US/blog/youtube-demonetization) (MEDIUM — cross-checked with ganknow.com and uscreen.tv on advertiser-unfriendly content categories)
- [Using trending audio legally on YouTube: a 2026 creator's guide — Gyre](https://gyre.pro/blog/using-trending-audio-legally-a-guide-for-youtube-creators) (MEDIUM — specific claim about 60-second Shorts audio license window)
- [How to Avoid YouTube Demonetization in 2026 — Ganknow](https://ganknow.com/blog/youtube-demonetization/) (LOW-MEDIUM, single-vendor blog, but corroborates Mediacube)
- [TikTok Regulated Goods, Services, and Commercial Activities — Community Guidelines (official)](https://www.tiktok.com/community-guidelines/en/regulated-commercial-activities) (HIGH — primary source, official platform policy)
- [TikTok Creator Monetization Requirements Guide 2026 — InfluenceFlow](https://influenceflow.io/resources/tiktok-creator-monetization-requirements-guide-complete-2026-roadmap/) (LOW-MEDIUM, third-party aggregator)
- [OpusClip official site](https://www.opus.pro/) (HIGH for self-reported feature claims — primary vendor source, treat marketing claims as directional not independently verified)
- [12 Best Opus Clip Alternatives for 2026 — Choppity](https://www.choppity.com/blog/best-opus-clip-alternatives/) (MEDIUM — competitor-authored comparison, likely biased toward Choppity but factual feature descriptions cross-check with Opus's own site)
- [Eklipse AI Gaming Montage Maker](https://eklipse.gg/tool/ai-gaming-montage-maker/) (MEDIUM — primary vendor source for closest-analog compilation feature)
- [TikTok Content Posting API Reference — Direct Post (official TikTok Developers docs)](https://developers.tiktok.com/doc/content-posting-api-reference-direct-post) (HIGH — primary/official source; SELF_ONLY unaudited-client restriction is load-bearing for phase-6 sequencing)
- [TikTok Content Posting API in 2026: Direct Post, Audit, and Alternatives — PostPeer](https://www.postpeer.dev/blog/best-tiktok-posting-api) (MEDIUM — cross-checks official docs' audit/rate-limit claims)
- [Using APIs to Automate Video Uploads on YouTube, Instagram & TikTok — Phyllo](https://www.getphyllo.com/post/using-apis-to-automate-content-upload-on-youtube-instagram-tiktok) (MEDIUM — third-party API-aggregator technical guide)
- [Instagram API Upload Video: Complete Guide — bundle.social](https://bundle.social/blog/instagram-api-upload-video) (LOW-MEDIUM — third-party vendor guide; Professional-account + app-review requirement is a widely corroborated Meta platform constraint)
- [Video Transitions: The Ultimate Guide in 2026 — Descript](https://www.descript.com/blog/article/video-transitions) (MEDIUM — editing-tool vendor, standard definitions of match cut/whip pan/crossfade/glitch cross-check against StudioBinder and Clipchamp sources)
- [Video SEO Best Practices in 2026 — VdoCipher](https://www.vdocipher.com/blog/video-seo-best-practices/) (MEDIUM — title-length and title-phrasing claims cross-checked against Mavlers/Hootsuite sources)

---
*Feature research for: AI video clipping pipeline — monetization flagging, style-learned titling, LLM metadata, context-aware transitions, highlight compilation, scheduled cross-platform auto-publish*
*Researched: 2026-07-07*
