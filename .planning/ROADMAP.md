# Roadmap: shorts-maker

## Overview

This milestone adds six capabilities on top of the existing local shorts-cutting pipeline (transcribe → chunk → score → merge/approve → refine/render → render): monetization-risk flagging, creator-style-learned naming, LLM-generated titles/tags, scheduled YouTube auto-publish, context-driven transition selection, sub-threshold highlight compilation, and finally scheduled TikTok/Instagram auto-publish. The build order follows dependency, not feature-list order: independent/cheap wins ship first (monetization rules + style profile), LLM titling follows because it needs a real style-profile schema to ground against, YouTube publish ships next since it has no external audit gate, transitions and compilation follow (transitions first, since compilation's stitching step consumes the transition engine), and the two audit-gated platforms (TikTok, Instagram) ship last since their external app-review lead times should run in parallel with earlier phases, not block them.

## Phases

**Phase Numbering:**

- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Monetization-Risk Flagging & Creator Style Profile** - Clips carry advisory per-platform monetization-risk flags, and a style profile learned from the creator's own upload history is ready for later phases to consume (completed 2026-07-07)
- [x] **Phase 2: LLM Title/Tag Generation** - Pipeline proposes ready-to-use titles and tags per clip, grounded in the creator's own voice via few-shot style-profile examples (completed 2026-07-08)
- [x] **Phase 3: YouTube Scheduled Auto-Publish** - Finished shorts can be queued and auto-published to YouTube on a schedule, safely (dry-run default, pause/kill, no duplicate posts) (completed 2026-07-08)
- [ ] **Phase 4: Context-Driven Transitions** - Clip boundaries get a transition chosen from scene/audio context (not just a fixed cut/punch-zoom) when stitching multiple segments together
- [ ] **Phase 5: Sub-Threshold Highlight Compilation** - Moments too short to stand alone are grouped by similarity and stitched into one coherent full-length short instead of being discarded
- [ ] **Phase 6: TikTok & Instagram Auto-Publish** - The same scheduled auto-publish flow extends to TikTok and Instagram Reels once each platform's app-review/audit gate is cleared

## Phase Details

### Phase 1: Monetization-Risk Flagging & Creator Style Profile

**Goal**: Clips carry advisory per-platform monetization-risk flags, and a style profile learned from the creator's own upload history is ready for later phases to consume
**Mode:** mvp
**Depends on**: Nothing (first phase; both halves of this phase are independent of each other and can be built/verified in parallel)
**Requirements**: MONET-01, MONET-02, MONET-03, MONET-04, STYLE-01, STYLE-02, STYLE-03
**Success Criteria** (what must be TRUE):

  1. A rendered clip's metadata includes a monetization-risk section listing flags (e.g. detected copyrighted audio, risky keyword/topic hits) with a confidence level and last-checked date per flag, for YouTube Shorts, TikTok, and Instagram Reels separately
  2. Monetization flags never block or fail export — a clip with flags still renders and exports normally, flags are advisory-only in the output
  3. Running the style-profile step against the creator's real upload history (via existing `scripts/youtube_analytics.py`) produces a structured, gitignored style-profile artifact containing concrete few-shot naming/moment-selection examples (not prose summaries)
  4. No raw per-channel titles/stats/history ever appear in a committed file — the style-profile cache lives only in the existing gitignored cache location

**Plans**: 3/3 plans complete
**Wave 1**

- [x] 01-01-PLAN.md — Deterministic per-platform keyword/topic monetization-risk scorer (rule-table YAML, advisory flags with confidence + last-checked date, rendered into metadata) [MONET-02, MONET-03, MONET-04] (wave 1)
- [x] 01-03-PLAN.md — Creator style profile: structured few-shot naming/moment examples derived from the youtube_analytics.py cache into a gitignored artifact [STYLE-01, STYLE-02, STYLE-03] (wave 1)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 01-02-PLAN.md — Local Chromaprint/pyacoustid audio fingerprinting → copyrighted-audio flag merged into the risk dict, fail-open on missing binary [MONET-01, MONET-03] (wave 2)

### Phase 2: LLM Title/Tag Generation

**Goal**: Pipeline proposes ready-to-use titles and tags per clip, grounded in the creator's own voice via few-shot style-profile examples
**Mode:** mvp
**Depends on**: Phase 1 (consumes the style-profile artifact as few-shot grounding)
**Requirements**: TAGS-01, TAGS-02, TAGS-03
**Success Criteria** (what must be TRUE):

  1. For a given clip, the pipeline outputs a candidate title plus a list of tags generated via the Claude API, without the user having to write either by hand
  2. If the Claude API is unavailable, title/tag generation falls back to a local Ollama model automatically rather than aborting the run (matches existing fail-open pattern for diarization/audio-energy/analytics)
  3. Generated titles visibly reflect the creator's own historical phrasing/style (verified by comparing against real few-shot examples from the Phase 1 style profile), not generic AI-sounding phrasing

> **Reconciliation note (added post-`/gsd-discuss-phase 2`, human-confirmed):** Success Criterion 1's "via the Claude API" is satisfied by the existing Claude Code orchestrator session itself acting as the generator — no separate Claude API script/SDK/billing path, per 02-CONTEXT.md D-01/D-02. Success Criterion 2's Ollama fallback (TAGS-02) is deferred to Phase 6 (headless/non-interactive runner), not delivered in Phase 2, since there is no "Claude API unavailable" state to fall back from once the orchestrator itself is the generator, per D-03. These criteria's literal wording predates that architectural decision and should not be read as unmet after Phase 2 closes.

**Plans**: 2/2 plans complete

- [x] 02-01-PLAN.md
- [x] 02-02-PLAN.md

### Phase 3: YouTube Scheduled Auto-Publish

**Goal**: Finished shorts can be queued and auto-published to YouTube on a schedule, safely (dry-run default, pause/kill, no duplicate posts)
**Depends on**: Phase 2 (publishes clips carrying the generated titles/tags/metadata)
**Requirements**: PUB-01, PUB-02, PUB-03, PUB-04, PUB-05
**Success Criteria** (what must be TRUE):

  1. Finished shorts are queued with sequential local numbering visible before any publish happens
  2. Running the publish step in default (dry-run) mode never actually uploads anything to YouTube — a real upload requires an explicit opt-in flag/setting
  3. With opt-in enabled, a queued short is actually uploaded to YouTube via the existing OAuth client pattern (YouTube Data API), on schedule
  4. The user can pause or kill scheduled publishing at any time and no further uploads occur until resumed
  5. Re-running the publish step after a retry/crash does not create duplicate posts — an idempotency/already-published manifest prevents re-upload of the same clip

**Plans**: 4/4 plans complete

**Wave 1**

- [x] 03-01-PLAN.md — Local publish-queue state: sequential numbering + idempotent enqueue + PublishConfig dry-run default [PUB-01, PUB-03] (wave 1)

**Wave 2** *(blocked on Wave 1)*

- [x] 03-02-PLAN.md — Upload+schedule path: fixed-grid slot math (future-guard), videos.insert private+publishAt body, dry-run gate, write-ahead uploading state, upload_token.json gitignored [PUB-02, PUB-03, PUB-05] (wave 2)

**Wave 3** *(blocked on Wave 2)*

- [x] 03-03-PLAN.md — Safety layer: pause/kill (local + videos.update revert-to-private + verify) and crash-mid-upload reconciliation (no duplicate posts) [PUB-04, PUB-05] (wave 3)

**Wave 4** *(blocked on Wave 3)*

- [x] 03-04-PLAN.md — Trigger integration: --check/--now CLI, append-only notification log surfacing, Windows Task Scheduler setup guide [PUB-01, PUB-02, PUB-03, PUB-04, PUB-05] (wave 4)

### Phase 4: Context-Driven Transitions

**Goal**: Clip boundaries get a transition chosen from scene/audio context (not just a fixed cut/punch-zoom) when stitching multiple segments together
**Depends on**: Phase 1 (reuses existing render pipeline; independent of Phases 2-3, can in principle be built any time after Phase 1, but sequenced here per confirmed roadmap order)
**Requirements**: TRANS-01, TRANS-02, TRANS-03
**Success Criteria** (what must be TRUE):

  1. At a clip boundary between two segments, the pipeline analyzes motion (optical flow) and audio (energy/onset) and selects a transition type based on that analysis, rather than always using the same effect
  2. At least six transition types are available and selectable: cut, crossfade, whip pan, mask/wipe, glitch, match cut
  3. When the boundary analysis is inconclusive, the pipeline falls back to the existing cut/punch-zoom behavior instead of guessing or failing

**Plans**: 1/6 plans executed

**Wave 1**

- [x] 04-01-PLAN.md — Optional deps (opencv-python-headless + librosa) install behind a blocking-human legitimacy checkpoint, registered as optional in requirements.txt [TRANS-01] (wave 1)
- [ ] 04-02-PLAN.md — TransitionsConfig dataclass + validation + config.example.yaml section, and compute_boundary_gaps pure helper exposing per-boundary pause-gap seconds [TRANS-01, TRANS-03] (wave 1)

**Wave 2** *(blocked on Wave 1)*

- [ ] 04-03-PLAN.md — scripts/transitions.py signal layer: lazy-import fail-open motion (optical flow), audio onset (librosa), and match-cut histogram-similarity analysis + Wave-0 test scaffold [TRANS-01] (wave 2)

**Wave 3** *(blocked on Wave 2)*

- [ ] 04-04-PLAN.md — classify_transition (conservative 6-type tree) + adaptive per-video thresholds + select_boundary_transitions orchestration + select-transitions CLI [TRANS-02, TRANS-03] (wave 3)
- [ ] 04-05-PLAN.md — render.py: build_transition_filter (xfade/glitch) + build_jumpcut_command concat→hybrid fold with gap-borrowed overlap + render_clip wiring [TRANS-02, TRANS-03] (wave 3)

**Wave 4** *(blocked on Wave 3)*

- [ ] 04-06-PLAN.md — SKILL.md automatic transition-selection orchestration (fail-open, no review gate) + end-to-end real-ffmpeg integration test [TRANS-01, TRANS-02, TRANS-03] (wave 4)

### Phase 5: Sub-Threshold Highlight Compilation

**Goal**: Moments too short to stand alone are grouped by similarity and stitched into one coherent full-length short instead of being discarded
**Depends on**: Phase 4 (stitches grouped candidates together using the transition engine)
**Requirements**: COMP-01, COMP-02, COMP-03
**Success Criteria** (what must be TRUE):

  1. Candidates shorter than `config.clip.min_seconds` show up tagged with gameplay/theme tags in review output instead of silently disappearing
  2. Similar-tagged sub-threshold candidates (same gameplay situation or same joke/theme) from the same source video/session get grouped together and rendered as one full-length short, joined via Phase 4's transition engine
  3. Compilation groups never mix candidates from different source videos/sessions in this version

**Plans**: TBD

### Phase 6: TikTok & Instagram Auto-Publish

**Goal**: The same scheduled auto-publish flow extends to TikTok and Instagram Reels once each platform's app-review/audit gate is cleared
**Depends on**: Phase 3 (extends the same publish/dry-run/pause/idempotency mechanism to two more platforms)
**Requirements**: PUB-06, PUB-07
**Success Criteria** (what must be TRUE):

  1. A queued short can be auto-published to TikTok via the Content Posting API, following the same dry-run-default/pause/idempotency safety mechanism as YouTube in Phase 3
  2. A queued short can be auto-published to Instagram Reels via the Graph API (Business account + app review in place), following the same safety mechanism
  3. Each platform integration is isolated enough that one platform's audit/review delay (e.g. TikTok's SELF_ONLY restriction pre-audit) does not block the other platform or YouTube from publishing

**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5 → 6

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Monetization-Risk Flagging & Creator Style Profile | 3/3 | Complete   | 2026-07-07 |
| 2. LLM Title/Tag Generation | 2/2 | Complete   | 2026-07-08 |
| 3. YouTube Scheduled Auto-Publish | 4/4 | Complete   | 2026-07-08 |
| 4. Context-Driven Transitions | 1/6 | In Progress|  |
| 5. Sub-Threshold Highlight Compilation | 0/TBD | Not started | - |
| 6. TikTok & Instagram Auto-Publish | 0/TBD | Not started | - |
