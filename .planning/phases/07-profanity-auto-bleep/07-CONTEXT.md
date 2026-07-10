# Phase 7: Profanity Auto-Bleep - Context

**Gathered:** 2026-07-11
**Status:** Ready for planning

<domain>
## Phase Boundary

Swear words identified in the existing Whisper word-level transcript get a quiet overlay-tone mask applied at render time (`render.py`'s audio filter chain) — audio keeps flowing under the mask (no dead silence), and the mask is quiet/garbled enough to defeat platform speech-to-text moderation without reading as an abrupt cut. Scope is detection + masking only — no UI, no manual review step, no per-clip opt-out mechanism beyond the existing fail-open config toggle pattern.

</domain>

<decisions>
## Implementation Decisions

### Wordlist source
- **D-01:** RU+EN swear wordlist, stored in a local editable data file (same pattern as `data/monetization_rules.yaml` — no external service, no LLM call, local-first).
- **D-02:** Wordlist must support common obfuscated spellings creators actually use in speech/chat-adjacent contexts (e.g. yo-substitution, partial stems like `бл*`) — not just exact literal forms. Matching should be deterministic (regex/stem-based), not fuzzy-LLM, consistent with MONET-02's precedent ("deterministic rule-tier only — no LLM-nuance tier").

### Overlay tone character
- **D-03:** Masking = duck the original word's volume down + layer a light noise/garble on top (not a pure clean sine beep, not a full silence cut). Goal: audio keeps flowing, word is hard to make out, doesn't read as an obvious hard edit.
- **Claude's discretion:** exact ffmpeg filter combination (e.g. `volume=enable='between(t,...)'` ducking + a noise-burst overlay mixed in via `amix`/`sidechain`), specific duck depth, noise level/frequency shaping — pick values that satisfy Success Criterion 3 (defeats STT, doesn't sound like a jarring cut) and validate empirically against a real clip during implementation.

### Config toggle
- **D-04:** New `config.yaml` section for this feature (e.g. `profanity:`), following the same fail-open, default-off pattern as `diarization`/`audio_energy` — missing/malformed config or wordlist degrades to "no masking applied" rather than failing the pipeline. Default OFF (opt-in), not on-by-default — this is a new optional feature like its predecessors, not a mandatory safety gate.

### Claude's Discretion
- Exact regex/matching implementation for obfuscation handling.
- Precise ffmpeg filter graph for the duck+noise overlay (research/planning phase should validate against `render.py`'s existing `build_audio_filter_chain` structure — per-span time-windowed filters are new to this codebase; existing filters like `afade`/`loudnorm` apply to the whole clip, not a sub-span, so this needs new filter-graph work, not just reuse).
- Whether detection happens as a standalone new script (`scripts/profanity.py`, mirroring `monetization_risk.py`'s shape) vs. folded into an existing module — planner's call based on codebase patterns.
- Word-boundary matching strictness (avoiding false positives like a stem matching inside an unrelated word) — deterministic, not LLM-judged.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & Roadmap
- `.planning/REQUIREMENTS.md` — AUDIO-01/02/03 (swear-word identification from transcript, quiet overlay tone at render time, moderation-scanner-defeating without abrupt-cut sound)
- `.planning/ROADMAP.md` §"Phase 7: Profanity Auto-Bleep" — Goal, Depends-on (Phase 1), Success Criteria

### Closest existing patterns (reuse shape, not code)
- `scripts/monetization_risk.py` — deterministic keyword/category scoring against transcript text, fail-open rules-file loading (`load_rules`), advisory/never-blocking framing. Closest analog for a new profanity-detection module: same rule-tier-only precedent (MONET-02), same YAML-driven wordlist idea, but operates on raw text offsets — profanity detection needs word-level *timestamps*, not just text offsets, so the matching target differs (see `scripts/transcribe.py` below).
- `scripts/transcribe.py` (`transcribe_video`, ~line 47-56) — Whisper `word_timestamps=True`; each segment's `words` list is `[{"word": str, "start": float, "end": float}, ...]`. This is the source of per-word audio spans that masking needs.
- `scripts/render.py` — `build_audio_filter_chain` (~line 315) builds the `-af` chain (`afftdn` → `loudnorm` → `afade`, in that filter order for a reason — comment explains fade must come last). `build_ffmpeg_command` (~line 333) is where filters get assembled per clip. Any new masking filter must slot into this existing chain without breaking the documented ordering rationale. No existing filter in this file operates on a sub-span of the clip (all are whole-clip) — per-span time-windowed audio filtering is new territory here.
- `scripts/config.py` — one `@dataclass` per config section pattern (`DiarizationConfig`, `AudioEnergyConfig`, etc.), each with fail-open validation. New `ProfanityConfig`-shaped section should follow this exact convention.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `scripts/monetization_risk.py::load_rules` — fail-open YAML-loading pattern (missing/malformed file → warn to stderr, degrade to empty/no-op, never raise) directly reusable for loading the swear wordlist.
- Whisper word-level timestamps (`scripts/transcribe.py`) already give exact `start`/`end` per word — no new transcription work needed, this phase is pure downstream consumption of existing transcript JSON.

### Established Patterns
- Fail-open optional feature: config toggle off by default, missing dependency/data degrades silently rather than aborting the pipeline (diarization, audio_energy, YouTube Analytics grounding all follow this — same principle applies here per PROJECT.md Constraints).
- Deterministic rule-tier only, no LLM-nuance tier for keyword/wordlist matching in v1 (MONET-02 precedent, reaffirmed by user for this phase's D-02).
- Mechanical execution belongs in `scripts/*.py`, semantic judgment stays in `SKILL.md`/orchestrator (TAGS-01 precedent) — profanity *detection* (deterministic wordlist match) is mechanical and belongs in a script; no orchestrator/LLM step needed for this phase.

### Integration Points
- New detection step slots in after transcript is available (Phase 1 output), before/alongside `render.py` invocation — likely produces a per-clip list of masked spans (start/end in clip-relative time) that `render.py` consumes the same way it already consumes `keep_segments`/`punch_zoom_at` from `PLAN.json`.
- `render.py`'s `build_audio_filter_chain` needs extending to accept span-scoped filters (new capability, not just appending to the existing whole-clip filter list).

</code_context>

<specifics>
## Specific Ideas

No specific creative reference beyond the three answered questions above (RU+EN wordlist with obfuscation support; duck+noise masking style; fail-open off-by-default config). Open to standard implementation approach for the ffmpeg filter mechanics.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 7-profanity-auto-bleep*
*Context gathered: 2026-07-11*
