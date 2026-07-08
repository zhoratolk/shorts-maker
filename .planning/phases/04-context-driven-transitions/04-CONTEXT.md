# Phase 4: Context-Driven Transitions - Context

**Gathered:** 2026-07-08
**Status:** Ready for planning

<domain>
## Phase Boundary

At each jumpcut boundary (the splice point between two `keep_segments` pieces within a single rendered clip, currently a hard concat cut), the pipeline analyzes motion (optical flow) and audio (energy/onset) at the end of segment A / start of segment B, and picks a transition type instead of always using a plain cut. Six transition types must be supported: cut, crossfade, whip pan, mask/wipe, glitch, match cut. When analysis is inconclusive, falls back to today's cut/punch-zoom behavior. Scope is the transition *chosen at a boundary*, not stitching together separate top-level clips (that's Phase 5's compilation, which will consume this same transition engine).

</domain>

<decisions>
## Implementation Decisions

### Aggressiveness / trigger threshold
- **D-01:** Conservative bias — a non-cut transition (whip pan/glitch/mask/crossfade/match cut) is only chosen when the motion/audio signal at the boundary is clearly strong; the default/fallback is a plain cut. Prioritizes not making the edit feel noisy or "over-edited" on a long gameplay video with many jumpcuts, over maximizing transition variety.
- **D-02:** Exact numeric threshold(s)/scoring for "strong signal" are Claude's/planner's discretion — no user-specified formula, just the conservative-by-default intent above.

### Visibility / review
- **D-03:** Fully automatic, no review/override step — the chosen transition type is not surfaced in `CANDIDATES.md` for manual approval, same as how punch-zoom/jumpcuts are decided today without a review gate. User can still ask Claude to change a specific render's result after the fact if unhappy with it (no new UI/workflow needed for that — it's an ordinary follow-up request).

### Transition type coverage
- **D-04:** All 6 required types (cut, crossfade, whip pan, mask/wipe, glitch, match cut) are in scope with no exclusions — user has no gameplay-content-fit objection to any of them. Claude/planner decides which signal patterns map to which type.

### Claude's Discretion
- Exact motion/audio signal thresholds and the scoring formula that decides "cut vs. fancy transition" (per D-02).
- Which specific transition type is chosen for a given signal pattern (per D-04).
- ffmpeg filter-graph implementation approach for each of the 6 types (xfade for crossfade/wipe are native; whip pan, glitch, match cut likely need custom filter chains — research's job).
- Whether missing optional deps (opencv for optical flow, librosa for audio onset) trigger fail-open degradation to today's cut/punch-zoom behavior, consistent with the project's existing fail-open pattern (diarization, audio-energy) — not raised as a gray area since it directly follows the project's standing "Fail-open" constraint (see PROJECT.md), no separate user decision needed.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements / roadmap
- `.planning/REQUIREMENTS.md` — TRANS-01, TRANS-02, TRANS-03 (Phase 4 scope); COMP-01/02/03 (Phase 5, consumes this engine, out of scope here)
- `.planning/ROADMAP.md` — Phase 4 detail block (goal, success criteria, depends-on Phase 1)
- `.planning/REQUIREMENTS.md` Out of Scope table — "True CV-based match-cut detection via heavy ML models... cheap proxies (scenedetect + optical flow + librosa) achieve the same practical result" — this is the locked technical direction for match-cut/motion detection, not full ML-based shot matching

### Project-level constraints (apply to this phase)
- `.planning/PROJECT.md` Constraints — "Fail-open" directly shapes how missing opencv/librosa deps should degrade; "Локальность" means no cloud CV service, on-device only

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `scripts/render.py::build_jumpcut_command` (lines ~326-380) — currently concatenates `keep_segments` via ffmpeg's `concat` filter with a hard cut at each boundary; this is the exact site where transition selection needs to plug in.
- `scripts/render.py::build_video_effects_chain` / `build_punch_zoom_filter` — existing pattern for building named ffmpeg filter-graph fragments that compose into the larger filter chain; new transition filters should follow the same shape (pure function → filter string).
- `scripts/jumpcuts.py::compute_keep_segments` — produces the `(start, end)` tuples whose boundaries are the transition insertion points; boundary timestamps (end of segment N / start of segment N+1) are already available here.
- `scripts/audio_energy.py` — existing ffmpeg EBU R128 momentary-loudness spike detection; likely reusable or adjacent to the new audio-onset signal needed for transition selection (currently used for candidate-scoring, not boundary analysis, but the ffmpeg loudness-measurement pattern applies).

### Established Patterns
- Optional/heavy dependencies are imported lazily inside the function that needs them (see `scripts/diarize.py` for pyannote/torch) — any new opencv/librosa import for motion/audio-onset analysis should follow this, keeping the module import-safe without the optional extra installed.
- `runner=subprocess.run` injectable-parameter pattern (`scripts/render.py::probe_video`, `scripts/silence.py::measure_loudness`) — new ffmpeg-invoking analysis functions should be unit-testable the same way.
- Fail-open pattern (log + continue with existing behavior) used throughout Stage 1 signals — the mandated fallback for inconclusive/missing-dependency transition analysis (TRANS-03) is this same philosophy.

### Integration Points
- New analysis functions (motion/optical-flow, audio-onset) sit logically in Stage 1/pre-render, feeding a decision into `PLAN.json` or directly into `render.py`'s jumpcut command builder — planner to decide exact wiring (new `scripts/transitions.py` module vs. extending `jumpcuts.py`/`render.py` in place, following the existing one-module-per-concern convention).

</code_context>

<specifics>
## Specific Ideas

- No specific per-type creative direction given beyond D-01 (conservative bias) — user explicitly OK'd all 6 types with no exclusions and left signal-to-type mapping to Claude's judgment.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope beyond the items above.

</deferred>

---

*Phase: 4-Context-Driven-Transitions*
*Context gathered: 2026-07-08*
