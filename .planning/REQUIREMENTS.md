# Requirements: shorts-maker

**Defined:** 2026-07-07
**Core Value:** Из сырой записи стрима автоматически получить готовый к публикации вертикальный клип — без ручной нарезки и без потери самых залипательных моментов.

## v1 Requirements

### MONET — Monetization-Risk Flagging

- [ ] **MONET-01**: Pipeline flags known-copyrighted audio in a clip via local fingerprinting (Chromaprint/pyacoustid) in clip metadata
- [x] **MONET-02**: Pipeline flags known demonetization-risk topics/keywords per platform (gambling, hate speech, etc.) as advisory metadata, deterministic rule-tier only — no LLM-nuance tier in v1
- [x] **MONET-03**: Every flag carries a confidence level and last-checked-date; flags are advisory only, never block export
- [x] **MONET-04**: Ruleset covers YouTube Shorts, TikTok, and Instagram Reels separately (rules differ per platform)

### STYLE — Creator Style/Naming Profile

- [x] **STYLE-01**: Pipeline reads creator's historical uploads via existing `scripts/youtube_analytics.py`
- [x] **STYLE-02**: Derives few-shot naming/moment-selection examples from that history (no fine-tuning — dataset too small, and fine-tuning would violate the project's no-persistent-service architecture)
- [x] **STYLE-03**: Style profile output stored in gitignored cache; never committed with raw titles/stats (same discipline as existing `youtube_analytics.py` cache)

### TAGS — LLM Title/Tag Generation

- [ ] **TAGS-01**: Pipeline generates title + tag candidates per clip via Claude API
- [ ] **TAGS-02**: Falls back to local Ollama model if Claude API is unavailable (fail-open, matches existing diarization/audio-energy/analytics pattern)
- [ ] **TAGS-03**: Uses STYLE profile few-shot examples as concrete grounding (not prose description) so generated titles match the creator's own voice, not generic AI phrasing

### TRANS — Context-Driven Transitions

- [ ] **TRANS-01**: Pipeline analyzes clip-boundary motion (optical flow) and audio (energy/onset via librosa) to choose a transition type at each clip boundary
- [ ] **TRANS-02**: Supports at least: cut, crossfade, whip pan, mask/wipe, glitch, match cut
- [ ] **TRANS-03**: Falls back to existing cut/punch-zoom behavior if boundary analysis is inconclusive

### COMP — Sub-Threshold Highlight Compilation

- [ ] **COMP-01**: Candidates shorter than `config.clip.min_seconds` are not discarded — tagged with gameplay/theme tags instead
- [ ] **COMP-02**: Similar-tagged sub-threshold candidates (same gameplay situation or same joke/theme) are grouped and stitched via the TRANS engine into one full-length short
- [ ] **COMP-03**: Compilation only groups candidates from the same source video/session by default (no cross-session mixing in v1)

### PUB — Scheduled Auto-Publish

- [ ] **PUB-01**: Finished shorts are queued with sequential local numbering
- [ ] **PUB-02**: Scheduled auto-publish to YouTube via YouTube Data API, reusing the existing OAuth client pattern
- [ ] **PUB-03**: Dry-run mode is the default; explicit opt-in required before any platform goes live
- [ ] **PUB-04**: Pause/kill mechanism to halt scheduled publishing at any time
- [ ] **PUB-05**: Idempotency/already-published manifest prevents duplicate posts on retry
- [ ] **PUB-06**: TikTok Content Posting API integration — built and shipped as its own gated sub-phase, after YouTube, since unaudited clients are restricted to private-only posting until TikTok's app audit completes (start the audit application early, in parallel with Phase 1)
- [ ] **PUB-07**: Instagram Graph API Reels integration — requires a Business account + Meta app review; same gated-sub-phase treatment as TikTok

## v2 Requirements

### MONET

- **MONET-05**: Nuanced/LLM-tier monetization detection (beyond deterministic rules) — no reliable ruleset exists yet for gaming-specific trash-talk vs. actual policy violations; revisit once MONET v1 has real usage data

### STYLE

- **STYLE-04**: Fine-tuned per-channel model — only worth revisiting if few-shot prompting proves insufficient at scale

## Out of Scope

| Feature | Reason |
|---------|--------|
| Fully-automatic public posting with no dry-run/review gate | Irreversible — a bad auto-post has no `git revert` equivalent; PUB-03/04 exist specifically to prevent this |
| Keyword-blocklist-only demonetization detection as the sole method | High false-positive rate on gaming trash-talk (research finding); v1 uses fingerprinting + advisory flags instead |
| Fine-tuning a custom LLM on one channel's upload history | Dataset far too small for fine-tuning; violates the project's local-first, no-persistent-service architecture |
| True CV-based match-cut detection via heavy ML models | No infrastructure for it; cheap proxies (scenedetect + optical flow + librosa) achieve the same practical result |
| Multi-channel/multi-streamer support | Pipeline is scoped to one creator's own channel (see PROJECT.md) |
| Manual per-platform web upload | Superseded by PUB (scheduled API auto-publish) |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| MONET-01 | Phase 1 | Pending |
| MONET-02 | Phase 1 | Complete |
| MONET-03 | Phase 1 | Complete |
| MONET-04 | Phase 1 | Complete |
| STYLE-01 | Phase 1 | Complete |
| STYLE-02 | Phase 1 | Complete |
| STYLE-03 | Phase 1 | Complete |
| TAGS-01 | Phase 2 | Pending |
| TAGS-02 | Phase 2 | Pending |
| TAGS-03 | Phase 2 | Pending |
| PUB-01 | Phase 3 | Pending |
| PUB-02 | Phase 3 | Pending |
| PUB-03 | Phase 3 | Pending |
| PUB-04 | Phase 3 | Pending |
| PUB-05 | Phase 3 | Pending |
| TRANS-01 | Phase 4 | Pending |
| TRANS-02 | Phase 4 | Pending |
| TRANS-03 | Phase 4 | Pending |
| COMP-01 | Phase 5 | Pending |
| COMP-02 | Phase 5 | Pending |
| COMP-03 | Phase 5 | Pending |
| PUB-06 | Phase 6 | Pending |
| PUB-07 | Phase 6 | Pending |

**Coverage:**

- v1 requirements: 23 total
- Mapped to phases: 23
- Unmapped: 0 ✓

---
*Requirements defined: 2026-07-07*
*Last updated: 2026-07-07 after initial definition*
