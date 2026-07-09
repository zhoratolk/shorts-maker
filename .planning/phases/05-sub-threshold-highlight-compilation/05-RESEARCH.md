# Phase 5: Sub-Threshold Highlight Compilation - Research

**Researched:** 2026-07-09
**Domain:** ffmpeg multi-input filter_complex compilation rendering; semantic grouping wiring in a Python-mechanics/Claude-judgment split pipeline
**Confidence:** HIGH (render mechanics, grounded directly in `scripts/render.py`/`scripts/transitions.py`/`scripts/jumpcuts.py` source) / MEDIUM (exact pipeline wiring point, since CONTEXT.md explicitly deferred this to research/planning)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Tagging & matching**
- D-01: Tags are free-form, Claude-assigned short descriptions of the gameplay situation or theme (e.g. "died to same boss", "chat spam reaction"), not a fixed enum/category list — consistent with how `reason` is already written today in step 3 candidate-finding.
- D-02: Matching sub-threshold candidates into a group is a semantic-similarity judgment (does this read as the same situation/theme), not exact string equality on the tag text. This is a Claude judgment call at compilation-grouping time, the same kind of call already made for `coherence` scoring — not a Python string-matching function.

**Unmatched leftovers**
- D-03: A sub-threshold candidate that finds no same-session match this run is not silently dropped — it is surfaced in `CANDIDATES.md` marked as unmatched/ungrouped, so the creator can see it existed even though nothing renders from it. No cross-run persistence of unmatched candidates in v1 — consistent with COMP-03's same-session-only scope and the existing per-run ephemeral `work/<video_stem>/` architecture.

**Ordering & length inside a compilation**
- D-04: Sub-clips within a compilation are ordered strongest-moment-first (the best hook leads), not source-video chronological order — consistent with `docs/viral-clips-ru.md`'s hook-window-near-the-front guidance already applied to single clips in step 5.
- D-05: A compilation is allowed its own length ceiling above the normal `config.clip.max_seconds` — it is explicitly a different output shape ("full-length short" per ROADMAP goal, not a normal single-moment clip). Claude's discretion on the exact cap since the user did not specify a number.

**Visual treatment across sub-clips**
- D-06: One uniform `crop_style` (and other per-clip visual choices normally made per-moment in step 5) applies to the whole compilation, not chosen independently per stitched sub-clip. Punch-zoom, subtitles, and other per-clip settings follow the same "whole compilation, not per-sub-clip" rule for the same consistency reason.

### Claude's Discretion
- Exact compilation length cap (D-05) — recommend a generous multiple of `config.clip.max_seconds` (e.g. ~2-3x) rather than no cap at all; planner should pick and document a concrete default. **Resolved by this research below** (see Standard Stack / Architecture Patterns).
- Exact mechanics of the semantic-match pass (D-02) — whether it's a dedicated Claude pass over all sub-threshold candidates from a session, or folded into an existing step. **Resolved by this research below** (see Architecture Patterns > Recommended Pipeline Placement).
- Whether a compilation's title/metadata generation runs once over the whole compilation's combined theme vs. per sub-clip — default to once-per-compilation unless research surfaces a reason otherwise. **Confirmed**: once-per-compilation is correct and requires no new metadata.py logic (see Don't Hand-Roll).
- Minimum group size (implied 2+ — a "group" of one sub-threshold candidate is just an unmatched leftover per D-03, not a compilation). **Confirmed as 2+**, enforced as a mechanical validation in the new module.

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within phase scope.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| COMP-01 | Candidates shorter than `config.clip.min_seconds` are not discarded — tagged with gameplay/theme tags instead | See Architecture Patterns > Recommended Pipeline Placement (step 5 refine-pass extension); `Candidate` dataclass extension in Don't Hand-Roll / Code Examples |
| COMP-02 | Similar-tagged sub-threshold candidates are grouped and stitched via the TRANS engine into one full-length short | See Key Finding (multi-input filter_complex render path), new `scripts/compilation.py`, new `render.py::build_compilation_command` |
| COMP-03 | Compilation only groups candidates from the same source video/session by default | See Architecture Patterns > grouping scope guard (single-video-stem partition, mechanical, enforced in the new module) |
</phase_requirements>

## Summary

Phase 5 has one real engineering unknown and one real pipeline-wiring unknown; both are resolved below with high confidence because they were verified directly against this repo's actual `scripts/render.py`, `scripts/transitions.py`, and `scripts/jumpcuts.py` source rather than assumed from general ffmpeg knowledge.

**The engineering unknown (the phase's stated "key open technical question"):** `build_jumpcut_command`'s existing splice trick — a single `-ss <clip_start> -i <video>` seek, decoding only `clip_end - clip_start` seconds, then `trim`/`atrim`-ing sub-ranges out of that one decoded window — cannot be reused for compilation stitching. It only works because a single candidate's internal jump-cut segments are all close together in source time (the candidate's own `start`..`end` span, typically 15-60s). A compilation's member candidates are separately-approved moments that can sit anywhere in the source video, potentially minutes or hours apart. Reusing the single-seek trick would force ffmpeg to decode the *entire span* between the earliest and latest candidate just to throw away everything except a few short kept windows — for a multi-hour stream recording this is a correctness-preserving but performance-catastrophic misuse of the technique. **This requires a genuinely new render path**: one independent `-ss`/`-i` input pair per compilation member (cheap, fast, keyframe-seeked, each decoding only its own short window), each candidate's own internal jump-cut segments (if any) trimmed/concatenated within its own input index, and the resulting per-candidate `[vN]/[aN]` streams strung together with the *same pairwise fold algorithm shape* `_build_transition_fold` already uses (sequential concat/xfade accumulation) — just re-keyed to multi-input labels instead of same-input trim labels. This is confirmed as the standard, ffmpeg-documented technique for concatenating non-contiguous segments of the same source file [CITED: ffmpeg concat filter documentation, via WebSearch].

**The pipeline-wiring unknown:** COMP-01's tagging must happen after step 5's trim decision (a candidate is only provably "sub-threshold" once its tightest reasonable trim is known), but D-03 requires unmatched leftovers to surface in `CANDIDATES.md`, which today is a step-3/4 artifact generated *before* step 5 runs. This research recommends appending a new section to `CANDIDATES.md` at the *end* of step 5 (once every approved candidate's tag and trim status is known and the one grouping pass has run), rather than inventing a second document — see Architecture Patterns.

**Primary recommendation:** Add one new sibling module `scripts/compilation.py` (mechanical grouping-application + validation only, no semantic matching) and one new `render.py` function `build_compilation_command` (parallel in shape to `build_jumpcut_command`, but iterating `-ss`/`-i` pairs per member candidate). Reuse `scripts/transitions.py::select_boundary_transitions`/`classify_transition` unchanged for stitch-point signal analysis (it is already documented as generic over any `keep_segments`-shaped list). Reuse `scripts/jumpcuts.py::remap_timestamp`/`remap_words` unchanged for subtitle timing, by having the orchestrator build one flattened, render-order `keep_segments`-shaped list spanning all member candidates before calling them — no new remap math needed. Do **not** reuse `compute_boundary_gaps`' "borrow the cut pause" concept at compilation stitch points: there is no natural pause between two separately-approved candidates, so any non-cut transition there trims real kept content on both sides instead of free dead air — document this as a deliberate, different tradeoff, and default conservatively.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Sub-threshold detection (is this candidate's tightest trim still < min_seconds?) | Orchestrator (SKILL.md step 5, Claude judgment) | Python (mechanical duration math already exists in step 5) | Judging "tightest reasonable trim" is the same judgment step 5 already makes for normal clips; only the comparison against `min_seconds` is new and purely mechanical |
| Tag assignment (D-01) | Orchestrator (Claude judgment) | — | Free-form semantic description — explicitly not a Python enum/classifier per project Anti-Pattern |
| Similarity matching / grouping decision (D-02) | Orchestrator (Claude judgment) | — | Same class of judgment as `coherence` scoring; project Anti-Pattern forbids encoding this in Python |
| Group validation (min size 2+, same-video-stem-only, length ceiling) | Python (new `scripts/compilation.py`) | — | Purely mechanical checks once Claude has already decided membership |
| Stitch-point transition classification (motion/audio/similarity) | Python (`scripts/transitions.py`, reused as-is) | — | Already a signal-classification function, generic over any boundary list; no source-adjacency assumption |
| Multi-input ffmpeg render (fold/xfade/concat across candidates) | Python (new `render.py::build_compilation_command`) | — | Purely mechanical ffmpeg filter-graph construction, same shape as existing `build_jumpcut_command`/`_build_transition_fold` |
| CANDIDATES.md unmatched/compilation surfacing | Python (`scripts/candidates.py`, extended) | Orchestrator (decides *when* to call it — end of step 5) | Rendering a markdown section from already-decided data is mechanical; the timing/wiring decision belongs to SKILL.md orchestration |
| Compilation title/metadata | Orchestrator (Claude, once per compilation) + Python (`scripts/metadata.py`, unchanged) | — | Same split as existing single-clip metadata generation; metadata.py needs zero changes |

## Standard Stack

### Core

No new external packages are required for this phase. Everything needed already ships in this repo from Phases 1-4:

| Library | Version (installed, verified) | Purpose | Why Standard |
|---------|------|---------|--------------|
| ffmpeg / ffprobe | 8.1.2 (`ffmpeg -version`, verified on this machine) [VERIFIED: local `ffmpeg -version` output] | Multi-input `-ss`/`-i` seeking, `filter_complex` concat/xfade/acrossfade fold | Already the project's only rendering engine (`scripts/render.py`); this phase adds a new call pattern (multiple `-i` of the same file), not a new tool |
| opencv-python-headless | 5.0.0 (`.venv` verified: `import cv2; cv2.__version__`) [VERIFIED: local venv import] | Boundary motion/similarity analysis, reused via `scripts/transitions.py` | Already installed and legitimacy-approved in Phase 4 (04-01) |
| librosa | 0.11.0 (`.venv` verified) [VERIFIED: local venv import] | Boundary audio-onset analysis, reused via `scripts/transitions.py` | Same — already installed and approved in Phase 4 |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| stdlib `json`/`dataclasses`/`pathlib` | builtin | New `scripts/compilation.py` module, matching every other pipeline module's style | Always — project convention (no formatter/linter, plain stdlib data modules) |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Multiple `-ss`/`-i` input pairs, one per candidate | `ffmpeg concat demuxer` (`-f concat -i list.txt`) on pre-cut intermediate files | Demuxer concat is "instant" (stream copy) but requires writing N intermediate `.mp4` files to disk first and loses the ability to apply xfade transitions between them (demuxer concat is a hard splice only) [CITED: ffmpeg concat filter documentation via WebSearch] — rejected because D-06/COMP-02 require the transition engine at each stitch |
| Reusing `build_jumpcut_command`'s single-seek trick across the whole compilation span | Decode `[earliest_candidate_start, latest_candidate_end]` in one `-i` and trim within it | Technically correct but can require decoding an entire multi-hour recording to extract a few short clips — rejected on performance grounds, not correctness |
| New `render.py` function vs. extending `build_jumpcut_command` in place | Add an `input_index` parameter to every trim label in `build_jumpcut_command` | Would silently change the meaning of every existing single-clip call site (today's function assumes exactly one input, `[0:v]`/`[0:a]`); a parallel sibling function is safer and matches the project's "no script imports another script's logic destructively" discipline — extract only the shared pairwise-fold *algorithm* if duplication becomes painful, not the whole function |

**Installation:** None — no `requirements.txt` changes needed for this phase.

## Package Legitimacy Audit

**Not applicable.** This phase introduces zero new external packages/dependencies. All required libraries (ffmpeg, opencv-python-headless, librosa) were already installed, legitimacy-reviewed, and approved in Phase 4 (see `.planning/phases/04-context-driven-transitions/04-01-SUMMARY.md`; STATE.md: "Human approved opencv-python-headless + librosa after pypi.org legitimacy review"). No re-audit is required.

## Architecture Patterns

### System Architecture Diagram

```text
Step 3 (unchanged)              Step 4 (unchanged)            Step 5 (extended)                         Step 6 (extended)
candidate-finding  ──────▶  user approval  ──────▶  refine pass, PER approved candidate:        ┌──▶ render.py::render_clip
(chunk subagents,               (CANDIDATES.md,          - compute tightest trim as today             (existing path, unchanged,
 candidates.json)                candidates.json)        - if trimmed duration < clip.min_seconds:      normal single clips)
                                                             mark SUB_THRESHOLD, assign D-01 tag
                                                           - else: proceed as a normal single clip  ──┤
                                                                                                       │
                                            after ALL approved candidates refined:                    │
                                            ┌─────────────────────────────────────────────┐           │
                                            │ ONE Claude grouping pass (D-02) over the     │           │
                                            │ session's SUB_THRESHOLD pool:                │           │
                                            │  - same source video/session only (COMP-03) │           │
                                            │  - semantic tag-similarity judgment          │           │
                                            │  - order group members strongest-first (D-04)│          │
                                            │  - groups of 1 -> "unmatched", not a group    │           │
                                            └─────────────────────────────────────────────┘           │
                                                           │                                            │
                          ┌────────────────────────────────┴─────────────────────────────┐             │
                          ▼                                                              ▼             │
              scripts/compilation.py                                     scripts/candidates.py         │
              (mechanical): validate group                                (mechanical): append          │
              size>=2, same video_stem,                                   "Sub-Threshold Compilations"  │
              length ceiling; build the                                   + "Unmatched Sub-Threshold"   │
              compilation PLAN.json entry                                 sections to CANDIDATES.md     │
              (segments[], crop_style, etc.)                              (D-03)                        │
                          │                                                                              │
                          ▼                                                                              │
              PLAN.json entry with "type": "compilation"  ─────────────────────────────────────────────▶│
                                                                                                          ▼
                                                                                     render.py::render_clip dispatches on
                                                                                     entry["type"] == "compilation" to the
                                                                                     NEW build_compilation_command:
                                                                                       one -ss/-i pair per member candidate
                                                                                       (each internally trimmed/concatenated
                                                                                       if it has its own keep_segments),
                                                                                       select_boundary_transitions reused
                                                                                       for each inter-candidate stitch,
                                                                                       sequential fold (concat/xfade) same
                                                                                       shape as _build_transition_fold,
                                                                                       then punch-zoom/subtitles/fade applied
                                                                                       ONCE on the folded [vcat]/[acat]
                                                                                       output (D-06)
```

### Recommended Project Structure

```
scripts/
├── compilation.py        # NEW — mechanical grouping-application + validation
│                          #   (group size, same-video-stem guard, length ceiling,
│                          #   PLAN.json compilation-entry builder). No semantic
│                          #   matching logic lives here (Anti-Pattern guard).
├── candidates.py          # EXTENDED — Candidate dataclass gains `tag` (D-01,
│                          #   optional) and `sub_threshold`/`group_id`/`unmatched`
│                          #   fields; new render_compilation_sections_markdown()
│                          #   appended to CANDIDATES.md at end of step 5
├── render.py              # EXTENDED — new build_compilation_command(); render_clip
│                          #   dispatches on entry["type"] == "compilation"
├── transitions.py          # UNCHANGED — select_boundary_transitions/classify_transition
│                          #   reused verbatim for compilation stitch points
├── jumpcuts.py             # UNCHANGED — remap_timestamp/remap_words reused verbatim
│                          #   against a flattened, render-order segment list
├── naming.py               # UNCHANGED — build_clip_filename reused for compilation output filename
└── metadata.py             # UNCHANGED — render_metadata_text reused, called once per compilation
```

### Pattern 1: Multi-input filter_complex for non-contiguous source segments

**What:** Instead of one `-ss`/`-i` pair decoding a single contiguous window, open the *same* source file once per compilation member with its own `-ss` offset and `-t` duration, then reference each input's streams by index (`[0:v]`, `[1:v]`, ... `[N:v]`) in `filter_complex`.

**When to use:** Whenever the segments to concatenate are far apart in source time — exactly the compilation case, and structurally different from Phase 4's within-one-candidate jump cuts.

**Example (illustrative shape, adapted from ffmpeg's own documented pattern for concatenating separated segments of one file):**
```bash
# Source: ffmpeg concat filter documentation (via WebSearch); shape adapted to
# this project's crop-then-fold convention.
ffmpeg -y -loglevel error \
  -ss 120.5 -i input.mp4 -t 17.7 \
  -ss 900.0 -i input.mp4 -t 15.0 \
  -ss 3400.2 -i input.mp4 -t 12.0 \
  -filter_complex "
    [0:v]crop=...,scale=1080:1920[v0]; [0:a]anull[a0];
    [1:v]crop=...,scale=1080:1920[v1]; [1:a]anull[a1];
    [2:v]crop=...,scale=1080:1920[v2]; [2:a]anull[a2];
    [v0][v1]xfade=transition=fade:duration=0.35:offset=17.35[vfold1];
    [a0][a1]acrossfade=d=0.35[afold1];
    [vfold1][v2]concat=n=2:v=1:a=0[vcat]; [afold1][a2]concat=n=2:v=0:a=1[acat]
  " -map "[vcat]" -map "[acat]" -c:v libx264 -c:a aac output.mp4
```
Each `-i` is a cheap, independent keyframe seek — this is the standard technique, not a workaround [CITED: ffmpeg concat filter docs via WebSearch].

**Critical difference from Phase 4's fold:** in `_build_transition_fold`, `boundary_gaps` (the literal cut-out pause between two sub-segments of the *same original candidate window*) gives xfade "free" overlap to borrow — no real kept content is lost, because that footage was already being discarded. Between two *different* compilation candidates there is no such natural gap; any non-cut transition duration must be trimmed from the tail of candidate A and the head of candidate B — i.e. from real, already-approved content. Recommend treating `max_borrowable = min(transition_duration, seg_a_duration / 2, seg_b_duration / 2)` (no `boundary_gaps` input at all — pass `None`/omit it) and keep the existing conservative default-to-cut behavior (D-01 from Phase 4) so this trimming only happens when the stitch-point signal is genuinely strong.

### Pattern 2: Flattening candidate segments for subtitle/punch-zoom timeline remap (fully reusable, no new math)

**What:** `scripts/jumpcuts.py::remap_timestamp`/`remap_words` walk a `keep_segments`-shaped `list[tuple[start, end]]` *in order*, accumulating elapsed duration — the function has no assumption that segments are close together in source time; it only cares about presentation order. Build one flattened list spanning the *whole compilation, in final render order* (strongest-first per D-04): for each member candidate in order, append either its own `keep_segments` (if it had internal jump cuts) or its single `(start, end)` pair.

**When to use:** Subtitle word-remap and `punch_zoom_at` placement for a compilation — both must be expressed on the *final compiled output timeline* (D-06: whole-compilation, not per-sub-clip).

```python
# Source: derived directly from scripts/jumpcuts.py (read this session) —
# remap_timestamp/remap_words require no modification, only a differently-
# constructed input list.
flattened_segments = []
for member in ordered_group_members:  # already strongest-first per D-04
    flattened_segments.extend(member.get("keep_segments") or [(member["start"], member["end"])])

# scripts/jumpcuts.py, unchanged:
from scripts.jumpcuts import remap_words
remapped_words = remap_words(all_candidates_absolute_words, flattened_segments)
```

**Caveat (see Pitfall 1):** this flattened-list remap does not account for the small time compression introduced by real (non-cut) transitions at stitch points inside `_build_transition_fold`-style folding (the overlap window plays once, not twice) — this is an *existing*, already-accepted approximation from Phase 4 (SKILL.md step 5 already remaps words before `select-transitions` even runs), not a new problem introduced here. Flag as a known, small, accumulating drift, not a blocker.

### Pattern 3: New `render.py` compilation entry point, reusing the fold algorithm shape

**What:** `_build_transition_fold`'s pairwise accumulate-then-fold algorithm (trim into borrowed gap → build `xfade`/`acrossfade` or downgrade to `concat` when the borrowable amount is too small → accumulate `acc_duration`) is directly reusable *in shape*. A new `build_compilation_command` should mirror it, but:
- Trim/atrim stages reference `[i:v]`/`[i:a]` for each member's own input index (post-crop, since D-06 crop is uniform — apply crop identically to every member's `-i` before folding, or fold first then crop once on `[vcat]` — either is filter-graph-valid since all inputs share resolution; folding-first is simpler and matches `build_jumpcut_command`'s existing "crop only once, at the very end, on the folded output" ordering).
- No `boundary_gaps` parameter — see Pattern 1's caveat; overlap for compilation stitches, when used, borrows from real content within a capped fraction of each side's own duration, not free pause footage.
- Subtitles/punch-zoom/fade are applied exactly once, on `[vcat]`/`[acat]`, identical to how `build_jumpcut_command` already applies them post-fold today — **zero new code needed for this part**, it is the same `video_ops`/`audio_stage` tail already in `build_jumpcut_command`.

### Anti-Patterns to Avoid
- **Encoding tag-similarity matching as a Python string/fuzzy-match function** — explicitly forbidden by this project's own Anti-Pattern ("Encoding semantic judgment in Python") and by D-02. Python only validates and mechanically assembles a grouping decision Claude has already made.
- **Reusing `compute_boundary_gaps` at compilation stitch points as if it computed a real pause** — there is no pause between two separately-approved candidates; doing this would silently make the fold's "free overlap" assumption compute against zero or garbage, or (worse) borrow the wrong footage.
- **Decoding the full span between the earliest and latest candidate in one `-i`** — technically works, catastrophically slow on a real multi-hour recording; always use one `-i` per candidate.
- **Rebuilding `remap_timestamp`/`remap_words` for the compilation case** — unnecessary; the existing functions already handle this correctly given the right input list (Pattern 2).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|--------------|-----|
| Boundary transition type selection at a compilation stitch point | A new classifier for "how similar are these two disparate moments visually/audibly" | `scripts/transitions.py::select_boundary_transitions`/`classify_transition`, called with the compilation's own stitch-boundary timestamps | Already generic over any `keep_segments`-shaped boundary list — the module's own docstring states it was written with this exact reuse in mind: "Generic over any keep_segments list ... so Phase 5's cross-clip compilation can reuse it" [VERIFIED: `scripts/transitions.py` read this session, line ~248] |
| Subtitle/word timing after compiling multiple candidates | A new "multi-source timeline remap" function | `scripts/jumpcuts.py::remap_timestamp`/`remap_words`, fed a flattened segment list (Pattern 2) | Already handles arbitrary elapsed-time accumulation across an ordered segment list; no source-adjacency assumption exists in the code |
| Compilation output filename | A new naming scheme | `scripts/naming.py::build_clip_filename` (same call, just once per compilation instead of once per clip) | Slugify + index + title logic is identical regardless of what the "title" describes |
| Compilation per-platform metadata text | A new metadata renderer for multi-segment content | `scripts/metadata.py::render_metadata_text`/`write_metadata_file` unchanged | Takes an opaque `platforms_data` dict; has no concept of "how many source segments" went into the clip it's describing |

**Key insight:** Every mechanical piece this phase needs (transition classification, timeline remap, filenames, metadata rendering) was either already built generically in Phase 4 or is agnostic to "how many original candidates" a clip came from. The only genuinely new mechanical code is the multi-input ffmpeg command builder and the grouping-validation module — everything else is composition, not invention.

## Common Pitfalls

### Pitfall 1: Subtitle/punch-zoom drift compounds across multiple compilation stitch points
**What goes wrong:** Each real (non-cut) transition inside a fold slightly compresses the output timeline relative to a naive sum of segment durations (the overlap window plays once, not twice). `build_jumpcut_command` already has this property for jump cuts within one candidate; a compilation has one stitch per *group member*, so a 4-5 member compilation accumulates several such small compressions.
**Why it happens:** `_build_transition_fold`'s `acc_duration = acc_duration + seg_duration - d_eff` formula is exact for the render itself, but any word-timestamp remap built from the *pre-fold* segment list (Pattern 2) does not know about the `d_eff` compression at each real-transition boundary.
**How to avoid:** This is an accepted, already-shipped Phase 4 approximation (SKILL.md step 5 remaps words before `select-transitions` even decides which boundaries get a real transition) — document it as inherited behavior rather than solving it net-new. If it becomes visible in real renders (captions drifting out of sync by the end of a long compilation), the fix is to remap using the *actual* extended/compressed segment boundaries `_build_transition_fold` computes internally, not the original ones — flag as a possible follow-up, not a Phase 5 blocker.
**Warning signs:** Captions land slightly early/late toward the end of a compilation with several non-cut transitions; worse with `transition_duration` set higher than the 0.35s default.

### Pitfall 2: Treating "sub-threshold" as knowable at step 3 (candidate-finding) time
**What goes wrong:** A raw candidate window found in step 3 is not yet trimmed to natural speech-pause boundaries — its raw `end - start` may already look short, but step 5's trim logic could still legitimately widen it (e.g. widening for `coherence`, per step 3's own documented behavior) or the tightest natural trim could still land above `min_seconds`. Deciding "sub-threshold" too early risks wrongly routing a candidate into compilation grouping when it could have stood alone.
**Why it happens:** COMP-01's wording ("candidates shorter than `config.clip.min_seconds`") is easy to misread as a step-3/4 concern since that's where `CANDIDATES.md` is first generated.
**How to avoid:** Gate sub-threshold determination on step 5's *already-existing* trim decision (the same min/max trim logic that exists today), not on the raw step-3 window. Only mark `sub_threshold: true` once the tightest reasonable trim is still below `min_seconds`.
**Warning signs:** A candidate that could have been a perfectly good 32-second standalone clip instead gets folded into a compilation because its untrimmed raw window looked shorter than it needed to be.

### Pitfall 3: Compilation length ceiling that quietly exceeds YouTube Shorts eligibility
**What goes wrong:** As of 2026, YouTube's own Shorts classification caps at 3 minutes (180s) for a vertical video to be treated as a Short (expanded from 60s in October 2024); beyond that it's just an ordinary upload, not distributed via the Shorts feed/algorithm [CITED: WebSearch, multiple 2026 sources, e.g. adcreate.com/likefy.com Shorts-length guides]. This project's own PROJECT.md explicitly states "без... лимитов по времени" (no time limit) as a design philosophy, but an *uncapped* compilation could silently produce a 4+ minute file that no longer qualifies as a Short on the platform Phase 3's publish pipeline targets.
**Why it happens:** D-05 leaves the exact number to research/planning; without a concrete number a compilation could grow unboundedly if many sub-threshold candidates share a theme.
**How to avoid:** Add `clip.compilation_max_seconds` to `ClipConfig` (new field, following the existing dataclass-per-section convention). **Recommended default: 150 seconds** (2.5x the default `clip.max_seconds=60`, comfortably inside the 180s YouTube Shorts ceiling with margin) — enforced as a mechanical cap in `scripts/compilation.py` (stop adding group members once the running total would exceed it; a group that hits the cap before all matched candidates are included still renders with the members that fit, ordered strongest-first per D-04, and the rest fall back to unmatched/ungrouped for this run).
**Warning signs:** A compilation renders successfully but the creator finds it no longer appears in the YouTube Shorts shelf after upload.

### Pitfall 4: `-ss`/`-i` reopening the same file N times looks wasteful but isn't
**What goes wrong:** A reviewer might assume opening the same source file 3-6 times (once per compilation member) is inefficient compared to one shared decode pass, and try to "optimize" it into a single `-i` with internal `trim`/`atrim` (Phase 4's existing single-input trick).
**Why it happens:** Not obvious without having read `build_jumpcut_command`'s comment about why `-ss` before `-i` is used (fast keyframe seek + timeline reset to 0) — that same property is exactly what makes reopening the file cheap per-segment, whereas a single `-i` spanning the whole compilation's time range would force ffmpeg to decode everything in between.
**How to avoid:** Document this explicitly in the new `build_compilation_command` docstring (following this project's existing convention of explaining *why*, not *what*, in comments) — this is the intended, standard approach, not a compromise.
**Warning signs:** A future contributor "fixes" this into a single-seek version and render times balloon on long recordings.

## Code Examples

### Extending `Candidate` for tagging/grouping (mechanical fields only)
```python
# Source: derived from scripts/candidates.py (read this session) — adds fields
# without touching merge_candidates' existing sort/id-assignment behavior.
@dataclasses.dataclass
class Candidate:
    id: int
    start: float
    end: float
    reason: str
    coherence: int | None = None
    tag: str | None = None            # D-01, set only once sub-threshold (step 5)
    sub_threshold: bool = False        # set once step 5's trim decision is known
    group_id: int | None = None        # set by the grouping pass, None = ungrouped
    unmatched: bool = False            # True only if sub_threshold and no group formed (D-03)
```
All four new fields are optional/default-`None`/`False` so every existing single-clip candidate is unaffected — matches the project's "optional fields omitted/defaulted, never a breaking schema change" pattern already used in `PLAN.json` entries.

### Compilation `PLAN.json` entry shape (new, alongside the existing single-clip shape)
```json
{
  "type": "compilation",
  "segments": [
    {"start": 120.5, "end": 138.2, "keep_segments": [[120.5, 130.0], [131.0, 138.2]]},
    {"start": 900.0, "end": 915.3},
    {"start": 3400.2, "end": 3412.9}
  ],
  "boundary_transitions": ["crossfade", "cut"],
  "crop_style": "zoom",
  "punch_zoom_at": 42.1,
  "subtitles_path": "work/<video_stem>/subtitles/mystream-0004-boss-rage-compilation.srt",
  "output_filename": "mystream-0004-boss-rage-compilation.mp4",
  "metadata_path": "<config.output_dir>/mystream-0004-boss-rage-compilation.txt"
}
```
`entry["type"] == "compilation"` (a field that never appears on today's entries) is the render.py dispatch discriminator — `render_clip`/CLI `main()` loop checks this before falling into the existing `keep_segments`-present / plain `start`-`end` branches, so no existing behavior changes for non-compilation entries.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| Sub-threshold candidates silently discarded (never reach `min_seconds`, never rendered) | Tagged, grouped, and stitched into one compilation short (this phase) | Phase 5 | No creative material is wasted; every approved candidate produces either a standalone clip or contributes to a compilation |
| Single `-ss`/`-i` decode window per rendered clip (all of Phases 1-4) | Multiple `-ss`/`-i` pairs, one per compilation member, folded via the same xfade/concat pattern | Phase 5 (new) | Enables stitching moments arbitrarily far apart in source time without the performance cost of decoding the whole span |

**Deprecated/outdated:** None — this phase is additive; nothing from Phases 1-4 is replaced, only extended with a new entry `type`.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Recommended `compilation_max_seconds` default of 150s (2.5x `clip.max_seconds`) is the right generosity/safety balance | Pitfall 3 | If too low, legitimately strong compilation groups get truncated; if too high, output silently loses YouTube Shorts feed eligibility. Low risk — it's a config default, easily changed by the user, and the planner is instructed to document the exact number chosen |
| A2 | Folding crop before the transition fold (apply crop identically to every `-i` input first, then fold) is simpler/equivalent to folding first and cropping once on `[vcat]` | Pattern 3 | Low risk — both are filter-graph-valid since all inputs share the same source resolution/fps; this is an implementation detail for the planner to pick, not a correctness question |
| A3 | Pitfall 1's subtitle/punch-zoom drift from real transitions is small enough in practice not to need a fix in this phase (max `transition_duration` default 0.35s × number of stitches) | Pitfall 1 | If wrong (visibly desynced captions on longer compilations), remediation is a follow-up fix to remap against the fold's actual post-extension boundaries, not a Phase 5 blocker |

**Note:** No claims in this research are LOW-confidence/`[ASSUMED]` in the "unverified package/API" sense — all package-existence and API-shape claims were verified directly by reading this repository's own source in this session. The three items above are judgment-call defaults (config numbers, ordering of operations), not unverified facts, and are flagged for the planner to confirm/document rather than requiring user reconfirmation of a fact.

## Open Questions

1. **Should `CANDIDATES.md`'s new sections be appended in-place, or should compilation results live in a separate file (e.g. `COMPILATIONS.md`)?**
   - What we know: D-03 says "surfaced in `CANDIDATES.md`" explicitly; the existing `scripts/candidates.py::render_candidates_markdown` writes the whole file in one pass from step 3/4 data, before step 5 (and therefore before grouping) has run.
   - What's unclear: whether appending a second write to the same file (from step 5, after grouping) fits the existing "one function, one write" shape of `candidates.py`, or whether a small dedicated append function is cleaner.
   - Recommendation: add `append_compilation_sections_markdown(path, groups, unmatched)` in `scripts/candidates.py` that reads the existing file, appends two new `##` sections, and rewrites it — mechanical, testable, and satisfies D-03's literal wording without inventing a second review artifact the user has to know to check.

2. **Does a compilation get its own row in `CANDIDATES.md`'s original numbered list, or only in the new appended sections?**
   - What we know: the original numbered candidate list (`1. `00:02:00` - `00:02:18` — ...`) is generated before grouping is known; member candidates already have their own numbered entries from step 3/4.
   - What's unclear: whether re-approval is expected for the *compilation as a whole* (i.e., does the user see and confirm "these 3 already-approved candidates will become one compilation") before step 6 renders it, or is this fully automatic like jump cuts/transitions today (D-03's own precedent in Phase 4: no separate approval gate for automatic decisions).
   - Recommendation: follow the same automatic/no-second-approval-gate philosophy as Phase 4's transitions (already-approved candidates were approved once in step 4; grouping them is a downstream mechanical/judgment step, not a new user-facing decision) — but flag this explicitly in the appended CANDIDATES.md section text ("Candidates #4, #7, #12 grouped into compilation: <title>") so the user sees it happened, consistent with D-03's transparency intent, without requiring a second approval round-trip.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.1.1 (verified: `python -m pytest --version`) |
| Config file | `pyproject.toml` (`[tool.pytest.ini_options]`, `pythonpath=["."]`, `testpaths=["tests"]`, `integration` marker) |
| Quick run command | `python -m pytest tests/test_compilation.py tests/test_render.py tests/test_candidates.py -x` |
| Full suite command | `python -m pytest` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| COMP-01 | `Candidate` dataclass carries `tag`/`sub_threshold`/`group_id`/`unmatched`; `merge_candidates` unaffected for normal candidates | unit | `pytest tests/test_candidates.py -k tag_or_sub_threshold -x` | ❌ Wave 0 (new tests in existing file) |
| COMP-01 | New `append_compilation_sections_markdown` renders unmatched candidates distinctly | unit | `pytest tests/test_candidates.py -k compilation_sections -x` | ❌ Wave 0 |
| COMP-02 | `scripts/compilation.py` builds a valid compilation `PLAN.json` entry from mock grouped candidates, min group size 2+ enforced | unit | `pytest tests/test_compilation.py -x` | ❌ Wave 0 (new file) |
| COMP-02 | `render.py::build_compilation_command` produces a valid multi-input `filter_complex` (mocked `runner`, same pattern as `test_render.py`) | unit | `pytest tests/test_render.py -k compilation -x` | ❌ Wave 0 (new tests in existing file) |
| COMP-02 | End-to-end real-ffmpeg compilation render (3 short candidates from a real tiny fixture video, far apart in timestamp) | integration | `pytest tests/test_integration_ffmpeg.py -k compilation -m integration -x` | ❌ Wave 0 (extend existing integration file, same skip-if-no-ffmpeg pattern) |
| COMP-03 | Grouping validation rejects candidates from a different `video_stem` | unit | `pytest tests/test_compilation.py -k same_video_stem -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/test_compilation.py tests/test_render.py tests/test_candidates.py -x`
- **Per wave merge:** `python -m pytest` (full suite, excluding `integration` marker unless ffmpeg confirmed on PATH)
- **Phase gate:** Full suite (including `-m integration`) green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/test_compilation.py` — new file, covers COMP-02/COMP-03 mechanical validation and PLAN.json entry construction
- [ ] `tests/test_candidates.py` — extend with new tests for tag/sub_threshold fields and the new markdown-append function (COMP-01)
- [ ] `tests/test_render.py` — extend with `build_compilation_command` unit tests (mocked `runner`, mirroring existing `build_jumpcut_command` test style)
- [ ] `tests/test_integration_ffmpeg.py` — extend with one real-ffmpeg compilation smoke test (3 short segments from a synthetic fixture video far apart in timestamp), same `integration` marker/skip-if-no-ffmpeg pattern already established

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-------------------|
| V2 Authentication | No | No new auth surface — local CLI/subprocess pipeline only |
| V3 Session Management | No | N/A |
| V4 Access Control | No | N/A |
| V5 Input Validation | Yes | `transition_type` values must be validated against `VALID_TRANSITIONS`/`TRANSITION_TYPES` before being interpolated into an ffmpeg filter string — **already enforced** by `build_transition_filter`'s existing `RenderError` guard (reused verbatim); the new `build_compilation_command` must apply the same guard to every boundary in `boundary_transitions`, exactly as `build_jumpcut_command` already does |
| V6 Cryptography | No | N/A |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|----------------------|
| ffmpeg filter-graph string injection via an unvalidated transition-type or path value | Tampering | Never interpolate raw external strings into `filter_complex`; validate `transition_type` against the frozen `VALID_TRANSITIONS` enum before dispatch (already the pattern in `build_transition_filter`), and continue escaping subtitle paths the same way `build_ffmpeg_command`/`build_jumpcut_command` already do (`.replace("\\", "/").replace(":", "\\:")`) |
| A malformed/adversarial `PLAN.json` compilation entry (e.g. `segments` empty, single member, or referencing a `video_stem` that doesn't match the video being rendered) causing an ffmpeg command with a negative/zero duration | Tampering / Denial of Service (self-inflicted, local) | Mirror `build_jumpcut_command`'s existing `if not keep_segments: raise RenderError(...)` guard — the new compilation builder must raise `RenderError` on empty/single-member `segments` before constructing any ffmpeg command, and `scripts/compilation.py` must enforce min-group-size 2+ at construction time so a malformed entry can never reach render.py in the first place |

## Sources

### Primary (HIGH confidence — verified by direct source read this session)
- `scripts/render.py` — `build_jumpcut_command`, `_build_transition_fold`, `build_ffmpeg_command`, `build_transition_filter`, `probe_video`, `render_clip`, `main()` — full read, this session
- `scripts/transitions.py` — `select_boundary_transitions`, `classify_transition`, `TRANSITION_TYPES`, `compute_signal_threshold` — full read, this session; docstring explicitly confirms Phase 5 reuse intent
- `scripts/jumpcuts.py` — `compute_keep_segments`, `compute_boundary_gaps`, `remap_timestamp`, `remap_words` — full read, this session
- `scripts/config.py` — `ClipConfig`, `TransitionsConfig`, `_validate` — full read, this session
- `scripts/candidates.py`, `scripts/naming.py`, `scripts/metadata.py` — full read, this session
- `.claude/skills/make-shorts/SKILL.md` — steps 3, 5, 6 — full read, this session
- Local environment probes this session: `ffmpeg -version` (8.1.2), `.venv` `cv2.__version__` (5.0.0), `.venv` `librosa.__version__` (0.11.0), `pytest --version` (9.1.1), `pyproject.toml`, `requirements.txt`

### Secondary (MEDIUM confidence — WebSearch, cross-checked against multiple sources)
- ffmpeg concat filter documentation (multi-input segment concatenation pattern, demuxer-vs-filter tradeoff) — [herongyang.com](https://www.herongyang.com/Flash/Video-Stream-FFmpeg-Concatenate-Video-Files.html), [underpop.online.fr ffmpeg concat filter docs](http://underpop.online.fr/f/ffmpeg/help/concat-3.htm.gz), [dev.to concat guide](https://dev.to/dak425/concatenate-videos-together-using-ffmpeg-2gg1), [wavespeed.ai 2026 guide](https://wavespeed.ai/blog/posts/blog-how-to-merge-concatenate-videos-ffmpeg/)
- YouTube Shorts 2026 maximum duration (180s, expanded from 60s in Oct 2024) — [adcreate.com 2026 length guide](https://adcreate.com/blog/youtube-shorts-length-guide-2026), [likefy.com 2026 guide](https://likefy.com/en/how-long-can-a-youtube-short-be/), [flowshorts.app 2026 guide](https://flowshorts.app/blog/maximum-length-of-youtube-shorts)

### Tertiary (LOW confidence)
- None — this phase's engineering questions were fully resolvable against the actual codebase; no unverified/training-only claims were needed for the core render-path decision.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new dependencies, everything already installed/approved in Phase 4
- Architecture (multi-input render path): HIGH — derived directly from reading `build_jumpcut_command`/`_build_transition_fold` and confirmed against ffmpeg's own documented concat-filter pattern for non-contiguous segments
- Pipeline wiring (where tagging/grouping happens, CANDIDATES.md timing): MEDIUM — CONTEXT.md explicitly left this to research/planning discretion; the recommendation here is well-grounded in existing step ordering but is a design choice, not a verified fact, and the planner should confirm it fits their preferred task breakdown
- Pitfalls: HIGH for Pitfalls 2/4 (directly derived from code); MEDIUM for Pitfall 1 (drift is a real property of the fold math but its practical visibility wasn't measured); MEDIUM for Pitfall 3 (platform limit verified via WebSearch, but the exact recommended default number is a judgment call)

**Research date:** 2026-07-09
**Valid until:** 30 days for the render-mechanics findings (stable, grounded in this repo's own code); 7 days for the YouTube Shorts platform-limit citation (platform policies change without notice) — re-verify the 180s figure if this phase's implementation is delayed past a few weeks
