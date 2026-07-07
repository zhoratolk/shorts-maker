# Architecture Research

**Domain:** Local video-processing pipeline extension (Claude-orchestrated CLI/ETL, no server)
**Researched:** 2026-07-07
**Confidence:** HIGH (grounded directly in existing codebase — `.planning/codebase/ARCHITECTURE.md`, `STRUCTURE.md`, `PROJECT.md` — not external ecosystem speculation)

## Standard Architecture

### System Overview — Existing Pipeline + 6 New Capabilities

```text
┌───────────────────────────────────────────────────────────────────────────┐
│ STAGE 0 (NEW, offline/manual) — Creator Style Profiling                    │
│ scripts/style_profile.py  (reads scripts/youtube_analytics.py cache)      │
│ → work/_profile/style_profile.json  (titling patterns, chosen-moment      │
│   patterns, tag vocabulary) — LONG-LIVED, cross-video, gitignored         │
└───────────────────────────────────┬───────────────────────────────────────┘
                                     │ read (not written) by Stage 3 & new Stage 5b
                                     ▼
┌───────────────────────────────────────────────────────────────────────────┐
│ STAGE 1 — Transcription & Signal Extraction  (UNCHANGED)                  │
│ transcribe.py / silence.py / diarize.py / audio_energy.py                 │
└───────────────────────────────────┬───────────────────────────────────────┘
                                     ▼
┌───────────────────────────────────────────────────────────────────────────┐
│ STAGE 2 — Chunking  (UNCHANGED)  scripts/chunker.py                       │
└───────────────────────────────────┬───────────────────────────────────────┘
                                     ▼
┌───────────────────────────────────────────────────────────────────────────┐
│ STAGE 3 — Moment-Finding / Scoring  (EXTENDED, not replaced)              │
│ Same Task-subagent-per-chunk pass. Reads style_profile.json (Stage 0) as  │
│ additional grounding context. Sub-threshold moments are NOT discarded —   │
│ candidates_chunk_NNNN.json gains a `below_threshold: bool` + `theme_tags` │
│ field instead of being filtered out.                                     │
└───────────────────────────────────┬───────────────────────────────────────┘
                                     ▼
┌───────────────────────────────────────────────────────────────────────────┐
│ STAGE 4 — Merge & Approval  (EXTENDED)  scripts/candidates.py             │
│ CANDIDATES.md gains a "Compilation candidates" section listing            │
│ below_threshold groups clustered by theme_tags similarity                 │
│ (new scripts/compilation.py:cluster_candidates)                          │
└───────────────────────────────────┬───────────────────────────────────────┘
                                     ▼
┌───────────────────────────────────────────────────────────────────────────┐
│ STAGE 5 — Refine / Trim / Plan  (EXTENDED, semantic — Claude)             │
│ Per approved candidate (standalone OR compilation-group):                 │
│  5a. trim/crop/jumpcuts/subtitles/naming (UNCHANGED scripts)              │
│  5b. NEW: title+tags generation — Claude call grounded in style_profile   │
│      + docs/metadata-writing-ru.md → writes into metadata.py input        │
│  5c. NEW: monetization-risk flagging — scripts/monetization_risk.py       │
│      scores transcript/tags against platform rule tables → risk metadata │
│  5d. NEW (compilation only): scripts/transitions.py analyzes clip-        │
│      boundary motion/audio (frames.py stills + audio_energy.py tail/head)│
│      and picks a transition type per boundary                            │
│  → writes work/<stem>/PLAN.json (entries gain: tags[], risk{}, transition)│
└───────────────────────────────────┬───────────────────────────────────────┘
                                     ▼
┌───────────────────────────────────────────────────────────────────────────┐
│ STAGE 6 — Render  (EXTENDED)  scripts/render.py                          │
│ Existing ffmpeg pipeline + NEW build_transition_filter() applied at       │
│ clip-boundary concat points (only used when PLAN entry has multiple       │
│ source segments = compilation). metadata.py already emits risk/tags text.│
└───────────────────────────────────┬───────────────────────────────────────┘
                                     ▼
┌───────────────────────────────────────────────────────────────────────────┐
│ STAGE 7 (NEW, post-render, separate script/cron) — Scheduled Publish      │
│ scripts/publish.py — reads config.yaml publish schedule + per-clip        │
│ metadata/risk, uploads via platform APIs (OAuth per platform, same        │
│ pattern as youtube_analytics.py), dry-run flag, pause/resume state file   │
└───────────────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility | Typical Implementation |
|-----------|----------------|------------------------|
| `scripts/style_profile.py` (new) | Read youtube_analytics.py cache, derive naming/selection patterns | Pure function over cached JSON, writes long-lived `style_profile.json`, no network |
| `scripts/monetization_risk.py` (new) | Score transcript/tags/theme against per-platform rule tables | Pure function, rule-table-driven (config/data, not hardcoded prose), returns structured risk dict |
| `scripts/compilation.py` (new) | Cluster below-threshold candidates by theme/gameplay similarity | Pure function over `candidates.json` (theme_tags, embeddings optional), no subprocess |
| `scripts/transitions.py` (new) | Pick transition type per clip-boundary from motion/audio deltas | Pure function consuming `frames.py` stills + `audio_energy.py` output, returns filter params consumed by `render.py` |
| Claude title+tag pass (extends Stage 5, no new script) | Generate title/tags per candidate, grounded in style profile + writing docs | Semantic — stays in `SKILL.md` prose, not Python (matches existing anti-pattern guard) |
| `scripts/publish.py` (new) | OAuth upload to platform APIs on schedule, dry-run, sequential numbering | CLI + small persistent schedule-state file (not a server); cron/Task-Scheduler invokes it |

## Recommended Project Structure

```
scripts/
├── style_profile.py       # NEW — Stage 0, offline/manual pre-pass
├── monetization_risk.py   # NEW — Stage 5 support, rule-table scoring
├── compilation.py         # NEW — Stage 4/5 support, candidate clustering
├── transitions.py         # NEW — Stage 5 support, boundary analysis -> transition choice
├── publish.py             # NEW — Stage 7, post-render, separate invocation
├── render.py              # EXTENDED — add build_transition_filter(), multi-segment concat
├── candidates.py          # EXTENDED — add compilation-candidates section to CANDIDATES.md
├── metadata.py            # EXTENDED — render risk flags + tags into per-platform .txt
├── config.py              # EXTENDED — add MonetizationConfig, CompilationConfig,
│                           #   TransitionsConfig, PublishConfig dataclasses
└── youtube_analytics.py   # UNCHANGED — already the OAuth pattern to replicate per platform
data/                       # NEW (or docs/) — rule tables, not prose
├── monetization_rules.yaml # per-platform (youtube/tiktok/reels) risk keyword/category tables
└── platform_specs.yaml     # upload API endpoints/limits per platform (feeds publish.py)
work/<video_stem>/
├── candidates/             # UNCHANGED, candidates_chunk_NNNN.json gains theme_tags/below_threshold
├── compilation_groups.json # NEW — clustered below-threshold candidate groups
├── PLAN.json               # EXTENDED — entries gain tags[], risk{}, transition{}, segments[]
└── publish_state.json      # NEW — per-clip schedule/upload status, pause flag
work/_profile/
└── style_profile.json      # NEW — cross-video, long-lived, gitignored (derived from private analytics cache)
```

### Structure Rationale

- **New scripts stay siblings under `scripts/`, never imported by each other** — matches the existing hard constraint ("no script imports another script's `main`"). `compilation.py` and `transitions.py` are consumed only by the orchestrator (`SKILL.md`), same as every existing stage.
- **Rule tables live in data files, not Python or prose** — monetization rules change frequently (platform policy updates) and are structured (category → keyword/pattern → severity), so they belong in `data/monetization_rules.yaml`, editable without touching code, and testable as pure data-in/data-out like `config.example.yaml`.
- **`work/_profile/` is a new top-level cache directory, not per-video** — style profile is a cross-video artifact (like `<output_dir>/transcripts/`), not a per-run one; keeping it out of `work/<video_stem>/` avoids recomputing it every run and avoids the "is this cache keyed by video or by channel" ambiguity.
- **`publish.py` is deliberately NOT wired into the per-video `SKILL.md` flow** — it's a separate, schedule-driven entry point (own `main()`, own invocation via cron/Task Scheduler), consistent with `youtube_analytics.py` already being "optional, run manually" rather than part of the `/make-shorts` critical path.

## Architectural Patterns

### Pattern 1: Metadata-flag stages produce structured JSON fields, never gating logic

**What:** Monetization-risk scoring and title/tag generation both append fields to existing artifacts (`candidates_chunk_NNNN.json`, `PLAN.json`) rather than creating parallel file trees or making pass/fail decisions in Python.
**When to use:** Any new "signal" that Claude should weigh but not have silently enforced by a script (matches existing `energy_spikes`/`speaker` pattern — signals, not gates).
**Trade-offs:** Keeps the human/Claude in the loop for judgment calls (a risky clip might still be worth publishing with an edit); avoids the anti-pattern of encoding "should we publish this" logic in Python.

**Example:**
```python
# scripts/monetization_risk.py
def score_monetization_risk(transcript_text: str, tags: list[str], platform: str,
                             rules: dict) -> dict:
    """Returns risk dict, never raises/blocks. Orchestrator decides what to do with it."""
    return {
        "platform": platform,
        "risk_level": "medium",       # low/medium/high
        "flags": ["gambling_reference"],
        "flagged_spans": [{"start": 12.4, "end": 15.1, "reason": "gambling_reference"}],
    }
```

### Pattern 2: Long-lived cross-video cache, separate from per-run `work/<stem>/`

**What:** `style_profile.json` (Stage 0) is computed once (or periodically refreshed) from the channel-wide analytics cache and read — never written — by every subsequent per-video run.
**When to use:** Any signal that depends on channel history rather than the single input video (naming patterns, past title style, tag vocabulary).
**Trade-offs:** Requires an explicit "is the profile stale" check (e.g. mtime vs. analytics cache mtime) but avoids expensive recomputation per video and keeps the privacy boundary clean — the profile file itself should also stay gitignored since it's derived from private channel data (same rule as the analytics cache per `PROJECT.md` Constraints).

### Pattern 3: Rule-table-driven scoring instead of hardcoded platform logic

**What:** Monetization rules (per-platform keyword/category/severity tables) and platform upload specs live in versioned YAML/JSON data files consumed by generic scoring/upload functions.
**When to use:** Whenever platform policy changes faster than code should be redeployed (monetization rules, API endpoint specs) — mirrors the existing `docs/*.md` reference-material pattern but as structured data for scripts rather than prose for Claude.
**Trade-offs:** Two parallel patterns now exist (prose docs for Claude's semantic judgment vs. YAML rule tables for scripts' mechanical scoring) — keep them clearly separated: "is this funny/good" stays prose in `docs/`, "does this phrase match a known-risky keyword pattern" is data in `data/`.

### Pattern 4: Compilation as a candidate-graph transform, not a new scoring pass

**What:** `compilation.py` operates purely on already-scored `candidates.json` (theme_tags assigned during Stage 3), clustering by tag/embedding similarity — it does not re-analyze raw transcript/audio.
**When to use:** Any cross-candidate aggregation step that should stay decoupled from the per-chunk semantic pass (keeps Stage 3 subagents parallel/independent — no cross-chunk coordination needed at scoring time).
**Trade-offs:** Requires Stage 3 to emit a consistent `theme_tags` vocabulary across independently-run subagents; mitigate by seeding the subagent prompt with a small fixed tag taxonomy (e.g. "boss-fight", "banter", "fail", "clutch") rather than free-form tags, so clustering in `compilation.py` is a simple set/string match, not a semantic-similarity computation requiring embeddings/LLM calls.

## Data Flow

### Request Flow (extended)

```
[/make-shorts <video>]
    ↓
[Stage 1-2: transcribe/chunk] → chunk_NNNN.json
    ↓
[Stage 3: Claude subagents, now grounded by style_profile.json]
    → candidates_chunk_NNNN.json { start, end, reason, theme_tags, below_threshold }
    ↓
[Stage 4: candidates.py merge] → CANDIDATES.md (standalone section + compilation-candidates section
                                   via compilation.py:cluster_candidates)
    ↓
[User approves subset — standalone clips AND/OR compilation groups]
    ↓
[Stage 5: per approved item, Claude]
    5a. trim/crop/jumpcuts/subtitles/naming (existing scripts, unchanged)
    5b. title+tags (Claude, grounded in style_profile.json + docs/metadata-writing-ru.md)
    5c. monetization_risk.py:score_monetization_risk() per target platform
    5d. (compilation groups only) transitions.py:choose_transition() per boundary
    → PLAN.json entries: { ...existing fields, tags[], risk{per-platform}, segments[]?, transition[]? }
    ↓
[Stage 6: render.py] → final .mp4 + metadata.py .txt (now includes tags + risk summary)
    ↓
[Stage 7, separate/scheduled: publish.py]
    reads PLAN.json + rendered output_dir, uploads via platform OAuth APIs,
    writes publish_state.json (sequence number, dry-run log, pause flag)
```

### Key Data Flows

1. **Style-profile grounding flow:** `youtube_analytics.py` cache → `style_profile.py` (offline, manual/periodic) → `style_profile.json` → read by Stage 3 (candidate framing) and Stage 5b (titling) prompts. One-way, no feedback loop within a single run.
2. **Compilation flow:** Stage 3 tags candidates with `theme_tags` + `below_threshold` → Stage 4's `compilation.py` clusters across the *whole* video's candidate set (needs all chunks merged first, hence it sits at Stage 4, after merge, not per-chunk) → clusters surfaced in `CANDIDATES.md` for approval like any other candidate → approved clusters flow through Stage 5 same as single candidates, except they carry multiple source segments (`segments: [{start,end}, ...]`) instead of one.
3. **Transition flow:** Only triggered for multi-segment PLAN entries (compilations, or optionally multi-clip stitches in general) → `transitions.py` reads `frames.py` stills near each boundary + `audio_energy.py` tail/head windows → returns a transition-type + params → threaded into `render.py`'s existing filter-graph builder as a new `build_transition_filter()` inserted at concat points, reusing the same ffmpeg-filter-graph pattern as `build_punch_zoom_filter`.
4. **Publish flow:** `publish.py` is decoupled from the render pipeline entirely — it scans `config.output_dir` + a schedule (config-driven), uploads via platform API using OAuth tokens (same on-disk pattern as `token.json`/`client_secret.json`, one per platform), and tracks state in its own file so it's resumable/pausable per `PROJECT.md`'s "необратимость авто-паблиша" constraint.

## Scaling Considerations

| Scale | Architecture Adjustments |
|-------|--------------------------|
| Single channel, current volume | Everything as described above is sufficient — no queue/server needed |
| Higher video throughput (batch processing multiple recordings) | `style_profile.py` refresh becomes the bottleneck if run per-video; make it a separate periodic job (e.g. run once daily via same cron slot as `publish.py`) rather than per-`/make-shorts` invocation |
| Multi-platform publish growing (3+ platforms, frequent schedule) | `publish.py`'s state file may need per-platform locking if a future multi-process scheduler runs concurrently; still not a real concern until publish frequency exceeds what a single sequential script can process in the schedule window |

### Scaling Priorities

1. **First bottleneck:** Style-profile recomputation cost if triggered every run — fix by decoupling it into its own periodic invocation (Pattern 2 above already assumes this).
2. **Second bottleneck:** `publish.py` OAuth token refresh/rate-limits across 3 platforms — fix by isolating per-platform upload functions so one platform's rate-limit/outage doesn't block others (fail-open per-platform, matching the existing fail-open philosophy).

## Anti-Patterns

### Anti-Pattern 1: Encoding monetization/legal judgment as hard pass/fail in Python

**What people do:** Write `is_safe_to_publish(clip) -> bool` that silently drops or blocks clips.
**Why it's wrong:** Violates the existing "no semantic judgment in Python" architectural rule (see `.planning/codebase/ARCHITECTURE.md` Anti-Patterns) and removes human/Claude judgment from a legally/financially consequential decision — platform rules are fuzzy and context-dependent (a "gambling" word in a joke vs. actual gambling promotion).
**Do this instead:** Produce a structured risk-flag dict (Pattern 1 above); let `SKILL.md` prose instruct Claude to weigh the flags when writing titles/deciding whether to surface a warning to the user before Stage 7 publish.

### Anti-Pattern 2: Making compilation a per-chunk Stage 3 responsibility

**What people do:** Try to have each chunk's subagent decide "this belongs in a compilation with chunk X" during the parallel scoring pass.
**Why it's wrong:** Subagents are parallel and chunk-isolated by design (`use_subagents=true` fans out independently) — cross-chunk clustering needs the full candidate set, which only exists after Stage 4's merge. Doing it earlier would require breaking subagent parallelism or adding inter-subagent coordination.
**Do this instead:** Keep Stage 3 subagents emitting only local `theme_tags` (a small fixed taxonomy); do clustering in `compilation.py` at Stage 4, after `candidates.py` has already merged everything into one `candidates.json`.

### Anti-Pattern 3: Building transitions as a `render.py`-only feature with no upstream analysis stage

**What people do:** Add transition *types* directly to `render.py`'s CLI flags and have Claude guess/hardcode which one to use in `SKILL.md` prose without any signal to base the choice on.
**Why it's wrong:** The whole point of "context-driven" selection (per `PROJECT.md`) is that it should be grounded in actual motion/audio deltas at the boundary — guessing from transcript text alone loses the visual signal `frames.py` already captures.
**Do this instead:** Add `transitions.py` as a genuine analysis step consuming `frames.py` stills + `audio_energy.py` output, producing a decision *before* `render.py` runs, exactly mirroring how `jumpcuts.py` computes keep-segments before `render.py` executes them — analysis and execution stay separate scripts.

### Anti-Pattern 4: Coupling `publish.py` into the main `/make-shorts` SKILL.md flow

**What people do:** Add auto-publish as the final step of the same orchestration that transcribes/edits, so every `/make-shorts` run also uploads.
**Why it's wrong:** Publishing is scheduled/sequenced across multiple already-rendered clips (not tied 1:1 to a single `/make-shorts` invocation), is irreversible/public (per `PROJECT.md` Constraints — needs dry-run and pause), and mixing it into the per-video skill would make every test run of `/make-shorts` a publish risk.
**Do this instead:** Keep `publish.py` a wholly separate entry point (own `main()`, own schedule/cron trigger), reading already-rendered output + `PLAN.json`/metadata, exactly like `youtube_analytics.py` is already "optional, run manually" and decoupled from the core pipeline.

## Integration Points

### External Services

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| YouTube Data/Upload API | OAuth via `client_secret.json`/`token.json` (extend existing `youtube_analytics.py` pattern into a sibling `youtube_upload.py` or a shared `platform_auth.py` helper) | Reuse the exact OAuth flow already proven in `youtube_analytics.py`; keep tokens gitignored |
| TikTok Content Posting API | New OAuth client, separate token file (e.g. `tiktok_token.json`) | Different auth flow/scopes than YouTube; isolate per-platform so one outage doesn't block others (fail-open per platform in `publish.py`) |
| Instagram (Reels) Graph API | New OAuth client (Meta), separate token file | Requires Business/Creator account linkage — verify eligibility before building; heavier setup than the other two |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| `style_profile.py` ↔ Stage 3/5b (Claude) | File read (`style_profile.json`) | One-directional; profile never written by per-video runs |
| `compilation.py` ↔ Stage 4 (`candidates.py`) | File read/write (`candidates.json` → `compilation_groups.json`) | `candidates.py` calls `compilation.py` as a library function during merge, or orchestrator invokes both CLIs in sequence — either is consistent with existing patterns |
| `transitions.py` ↔ `render.py` | File/dict hand-off via `PLAN.json` entry fields (`transition: {...}`) | Mirrors `jumpcuts.py` → `render.py` hand-off exactly; `render.py` stays a pure executor |
| `monetization_risk.py` ↔ `metadata.py` | `PLAN.json` entry field (`risk: {...}`) consumed when rendering the per-platform `.txt` | Additive field, no change to existing metadata schema required beyond a new optional section |
| `publish.py` ↔ rendered output + `PLAN.json`/metadata | Reads `config.output_dir`, no dependency on `work/<stem>/` (which is ephemeral/gitignored per-run) | Confirms `publish.py` must only depend on the *durable* output artifacts, not `work/` intermediates |

## Suggested Build Order

Given dependencies described above, and matching the numbering in `PROJECT.md` Active requirements:

1. **Monetization-risk flagging** (`scripts/monetization_risk.py` + `data/monetization_rules.yaml`) — no dependency on anything else; purely additive to Stage 5/6 metadata. Build first to validate the "rule-table + structured-flag" pattern before reusing it elsewhere.
2. **Creator style/naming analysis** (`scripts/style_profile.py`) — depends only on the existing `youtube_analytics.py` cache; independent of everything else. Can be built in parallel with (1).
3. **LLM title+tag generation** — depends on (2) for grounding quality (style profile makes titles "in-voice") but can ship a first version without it (falling back to `docs/metadata-writing-ru.md` alone); sequence after (2) if possible, otherwise stub the profile input.
4. **Compilation of sub-threshold moments** (`scripts/compilation.py`) — depends on Stage 3 emitting `theme_tags`/`below_threshold` fields (a schema change to `candidates_chunk_NNNN.json`), but does **not** depend on transitions being built first — compilation only needs candidate clustering; it can produce multi-segment `PLAN.json` entries that render as simple concatenation (existing jumpcut-splice mechanism) before transitions exist.
5. **Context-driven transition selection** (`scripts/transitions.py` + `render.py` extension) — logically layers on top of (4) because compilations are the primary consumer of non-trivial transitions (standalone clips rarely need mid-clip transitions beyond jumpcuts), but is technically independent enough to build standalone and validate on any two-segment test case. Build after (4) so there's a real multi-segment `PLAN.json` to integrate against, avoiding speculative interface design.
6. **Scheduled auto-publish** (`scripts/publish.py`) — depends on (1) and (3) being present in `PLAN.json`/metadata (so publish can show/withhold risky clips and use generated titles/tags), and benefits from (4)/(5) existing so compiled clips are also publishable — but its OAuth/scheduling machinery is independently buildable in parallel; sequence last because it's the highest-risk/irreversible capability and should integrate against a stable metadata/tags/risk schema rather than a moving one.

**Dependency summary:** (1) and (2) are independent and can be parallelized first. (3) softly depends on (2). (4) depends on a Stage-3 schema addition but not on (5). (5) depends on (4) existing (needs real multi-segment plans to design against) but is not a hard blocker — could be stubbed with a single default transition type if sequencing pressure requires. (6) should come last since it consumes the outputs of (1)/(3)/(4)/(5) and carries the highest risk (irreversible public action).

## Sources

- `D:\shorts-maker\.planning\codebase\ARCHITECTURE.md` (existing pipeline, stages 1-6, component responsibilities, anti-patterns, error-handling strategy) — HIGH confidence, primary source
- `D:\shorts-maker\.planning\codebase\STRUCTURE.md` (directory layout, naming conventions, "where to add new code" guidance) — HIGH confidence, primary source
- `D:\shorts-maker\.planning\PROJECT.md` (6 active requirements, constraints — privacy/locality/fail-open/git discipline/publish irreversibility, key decisions on transitions and compilation) — HIGH confidence, primary source

---
*Architecture research for: local video-processing pipeline extension (shorts-maker)*
*Researched: 2026-07-07*
