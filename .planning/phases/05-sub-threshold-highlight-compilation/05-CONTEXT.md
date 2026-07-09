# Phase 5: Sub-Threshold Highlight Compilation - Context

**Gathered:** 2026-07-09
**Status:** Ready for planning

<domain>
## Phase Boundary

Today, a candidate moment shorter than `config.clip.min_seconds` (after step 5's best trim) has no path to publication — it either gets padded unnaturally to hit the floor or never gets approved as its own clip. This phase gives sub-threshold moments a second path: tag them with a gameplay-situation/theme description, match them against other sub-threshold moments from the *same source video/session* that share a similar situation or theme, and when a match exists, stitch the group into one coherent full-length compilation short using Phase 4's transition engine at each stitch point instead of discarding them. Scope is the tagging + same-session grouping + stitching mechanics — not a new candidate-finding pass, not cross-session/cross-video mixing (explicitly excluded by COMP-03), not a new platform target.

</domain>

<decisions>
## Implementation Decisions

### Tagging & matching
- **D-01:** Tags are free-form, Claude-assigned short descriptions of the gameplay situation or theme (e.g. "died to same boss", "chat spam reaction"), not a fixed enum/category list — consistent with how `reason` is already written today in step 3 candidate-finding.
- **D-02:** Matching sub-threshold candidates into a group is a semantic-similarity judgment (does this read as the same situation/theme), not exact string equality on the tag text. This is a Claude judgment call at compilation-grouping time, the same kind of call already made for `coherence` scoring — not a Python string-matching function.

### Unmatched leftovers
- **D-03:** A sub-threshold candidate that finds no same-session match this run is not silently dropped — it is surfaced in `CANDIDATES.md` marked as unmatched/ungrouped, so the creator can see it existed even though nothing renders from it. No cross-run persistence of unmatched candidates in v1 — consistent with COMP-03's same-session-only scope and the existing per-run ephemeral `work/<video_stem>/` architecture (nothing else in this pipeline persists candidate state across separate runs either).

### Ordering & length inside a compilation
- **D-04:** Sub-clips within a compilation are ordered strongest-moment-first (the best hook leads), not source-video chronological order — consistent with `docs/viral-clips-ru.md`'s hook-window-near-the-front guidance already applied to single clips in step 5.
- **D-05:** A compilation is allowed its own length ceiling above the normal `config.clip.max_seconds` — it is explicitly a different output shape ("full-length short" per ROADMAP goal, not a normal single-moment clip). Claude's discretion on the exact cap (see below) since the user did not specify a number, only that it shouldn't be forced into the single-clip ceiling.

### Visual treatment across sub-clips
- **D-06:** One uniform `crop_style` (and other per-clip visual choices normally made per-moment in step 5) applies to the whole compilation, not chosen independently per stitched sub-clip — picked so the compilation reads as one consistent roll rather than a patchwork of differently-framed moments. Punch-zoom, subtitles, and other per-clip settings follow the same "whole compilation, not per-sub-clip" rule for the same consistency reason.

### Claude's Discretion
- Exact compilation length cap (D-05) — no number was specified. Recommend a generous multiple of `config.clip.max_seconds` (e.g. ~2-3x) rather than no cap at all, so a compilation can't runaway to an unpublishable length if many sub-threshold candidates match the same theme; planner should pick and document a concrete default.
- Exact mechanics of the semantic-match pass (D-02) — e.g. whether it's a dedicated Claude pass over all sub-threshold candidates from a session, or folded into an existing step. Downstream research/planning decides the wiring, following the existing one-module-per-concern convention (same framing already used for Phase 4's transitions.py placement).
- Whether a compilation's title/metadata generation (Phase 2's LLM title/tag flow) runs once over the whole compilation's combined theme vs. per sub-clip — not raised by the user; default to once-per-compilation (matches D-04/D-06's "reads as one thing" direction) unless research surfaces a reason otherwise.
- Minimum group size (implied 2+ — a "group" of one sub-threshold candidate is just an unmatched leftover per D-03, not a compilation).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope & requirements
- `.planning/ROADMAP.md` — Phase 5 section (Goal, Depends on: Phase 4, Requirements COMP-01/02/03, Success Criteria)
- `.planning/REQUIREMENTS.md` — COMP-01, COMP-02, COMP-03 (lines 35-37, 92-94)

### Transition engine reuse (Phase 4 dependency)
- `.planning/phases/04-context-driven-transitions/04-CONTEXT.md` §Integration Points — explicitly scopes Phase 4's transition engine as boundary-only within a single clip, and flags Phase 5 (this phase) as the consumer for stitching separate clips together
- `scripts/transitions.py` — `select_boundary_transitions`, `classify_transition`, `TRANSITION_TYPES` (6 types) — the engine this phase stitches through
- `scripts/render.py::build_jumpcut_command` / `_build_transition_fold` — current single-source multi-segment splice+xfade fold; a compilation spans multiple *approved candidates* (each its own start/end, potentially non-adjacent in source time), which is structurally different from today's single-clip `keep_segments` splice — planner/research must resolve this gap
- `.claude/skills/make-shorts/SKILL.md` step 5 "Context-driven transitions" — shows today's per-clip invocation pattern (`select-transitions` CLI, fail-open per TRANS-03) that a compilation's cross-candidate stitching should follow the same fail-open philosophy for

### Creative/ordering guidance
- `docs/viral-clips-ru.md` — hook-window-near-front, length sweet spot, self-contained-vs-needs-context guidance; backs D-04 (strongest moment first)

### Candidate schema & pipeline (what this phase extends)
- `.claude/skills/make-shorts/SKILL.md` step 3 "Find candidates (pass 1)" — current candidate JSON schema (`start`, `end`, `reason`, optional `coherence`) that D-01 tags extend
- `.claude/skills/make-shorts/SKILL.md` step 5 "Refine (pass 2)" — current min/max trim logic; this is the step that today has no path for a moment that can't reach `min_seconds`
- `scripts/config.py::ClipConfig` (`min_seconds`/`max_seconds`, lines 41-44) — the threshold this phase's candidates fall under, and the ceiling D-05 discusses raising for compilations specifically

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `scripts/transitions.py::select_boundary_transitions` / `classify_transition` — already-built signal analysis (motion/audio/similarity) and 6-type transition classification; this phase's stitch points are a new caller of the same engine, not a new engine
- `scripts/naming.py` — filename slugify/indexing; compilation output still needs a filename, likely via the same helper
- `scripts/metadata.py` + Phase 2's LLM title/tag flow — compilation still needs per-platform metadata text, same rendering path as single clips

### Established Patterns
- **Semantic judgment stays in SKILL.md, not Python** (project Anti-Pattern: "Encoding semantic judgment in Python") — tagging (D-01) and similarity matching (D-02) belong in the orchestrator's judgment, same as candidate-finding and `coherence` scoring today. Python modules should only get the mechanical grouping/stitching math once Claude has decided which candidates belong together.
- **Fail-open optional features** (TRANS-03, diarization, audio-energy) — if transition analysis or grouping fails for a compilation, the established pattern is graceful degradation (e.g. fall back to plain-cut stitching) rather than aborting the whole run.
- `runner=subprocess.run` injectable pattern (`render.py::probe_video`) — any new ffmpeg-invoking compilation-render logic should stay unit-testable the same way.

### Integration Points
- New tagging/grouping logic sits in Stage 1/pass-2 territory (SKILL.md steps 3-5, where candidates are found and refined) — same place `coherence` and hype-phrase tagging already live.
- Compilation rendering is a new *caller* of `render.py`'s existing transition-fold machinery, but needs multi-source-candidate stitching (not today's single-clip multi-segment splice) — planner should decide whether this extends `build_jumpcut_command`, adds a new `render.py` function, or introduces a new module (e.g. `scripts/compilation.py`), following the one-module-per-concern convention.

</code_context>

<specifics>
## Specific Ideas

No specific creative-direction examples given beyond D-01–D-06 above — user left tag wording, match precision, and exact length cap to Claude's judgment, same pattern as Phase 4's D-01 conservative-bias discussion.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 5-Sub-Threshold-Highlight-Compilation*
*Context gathered: 2026-07-09*
