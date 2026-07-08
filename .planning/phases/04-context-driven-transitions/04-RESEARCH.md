# Phase 4: Context-Driven Transitions - Research

**Researched:** 2026-07-08
**Domain:** ffmpeg filter-graph transitions + lightweight local CV/audio signal analysis (optical flow, onset detection, scene-similarity proxy)
**Confidence:** MEDIUM-HIGH (ffmpeg filter capabilities and local dependency-install behavior were directly verified against this machine's actual toolchain; signal-to-type mapping and numeric thresholds are inherently judgment calls, flagged as such)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Aggressiveness / trigger threshold**
- **D-01:** Conservative bias — a non-cut transition (whip pan/glitch/mask/crossfade/match cut) is only chosen when the motion/audio signal at the boundary is clearly strong; the default/fallback is a plain cut. Prioritizes not making the edit feel noisy or "over-edited" on a long gameplay video with many jumpcuts, over maximizing transition variety.
- **D-02:** Exact numeric threshold(s)/scoring for "strong signal" are Claude's/planner's discretion — no user-specified formula, just the conservative-by-default intent above.

**Visibility / review**
- **D-03:** Fully automatic, no review/override step — the chosen transition type is not surfaced in `CANDIDATES.md` for manual approval, same as how punch-zoom/jumpcuts are decided today without a review gate. User can still ask Claude to change a specific render's result after the fact if unhappy with it (no new UI/workflow needed for that — it's an ordinary follow-up request).

**Transition type coverage**
- **D-04:** All 6 required types (cut, crossfade, whip pan, mask/wipe, glitch, match cut) are in scope with no exclusions — user has no gameplay-content-fit objection to any of them. Claude/planner decides which signal patterns map to which type.

### Claude's Discretion
- Exact motion/audio signal thresholds and the scoring formula that decides "cut vs. fancy transition" (per D-02).
- Which specific transition type is chosen for a given signal pattern (per D-04).
- ffmpeg filter-graph implementation approach for each of the 6 types (xfade for crossfade/wipe are native; whip pan, glitch, match cut likely need custom filter chains — research's job).
- Whether missing optional deps (opencv for optical flow, librosa for audio onset) trigger fail-open degradation to today's cut/punch-zoom behavior, consistent with the project's existing fail-open pattern (diarization, audio-energy) — not raised as a gray area since it directly follows the project's standing "Fail-open" constraint (see PROJECT.md), no separate user decision needed.

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within phase scope beyond the items above.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| TRANS-01 | Pipeline analyzes clip-boundary motion (optical flow) and audio (energy/onset via librosa) to choose a transition type at each clip boundary | Standard Stack (opencv-python-headless + librosa, both verified installable in this project's `.venv` with zero source builds); Architecture Patterns 1-2 (lazy-import + ffmpeg frame-extraction reuse); Code Examples (Farneback optical flow, librosa onset_strength) |
| TRANS-02 | Supports at least: cut, crossfade, whip pan, mask/wipe, glitch, match cut | Architecture Patterns 3-5 (native `xfade` transitions for crossfade/wipe/whip-pan via `hblur`; custom filter chain for glitch; metadata-only distinction for match-cut); all 6 confirmed renderable with this machine's installed ffmpeg 8.1.2 |
| TRANS-03 | Falls back to existing cut/punch-zoom behavior if boundary analysis is inconclusive | Common Pitfalls 1 & 4 (insufficient pause-gap overlap or unclear signal → fall back to cut); Environment Availability (missing opencv/librosa → fail-open, no analysis attempted); Pattern 1 (lazy-import returns `None` on missing dependency) |
</phase_requirements>

## Summary

This phase adds a new analysis+decision step at each jump-cut boundary inside `build_jumpcut_command`, plus new filter-graph plumbing to render 6 transition types instead of always concatenating with a hard cut. Two genuinely new points of complexity, both fully resolved by this research:

1. **New optional dependencies** (`opencv-python-headless` for optical flow, `librosa` for audio onset — the latter is explicitly named in `TRANS-01`'s own requirement text, not just a research suggestion) are safe, prebuilt-wheel-only installs on this machine's actual `.venv` (Python 3.13.14) — confirmed via `pip install --dry-run` against the real project venv, not just PyPI existence. No compiler, no CUDA, no Visual C++ build step needed for either.
2. **The real architectural gotcha** is not filter syntax — ffmpeg 8.1.2 (already installed, confirmed via `ffmpeg -filters`) natively supports `xfade` with 58 named transitions (crossfade, all wipe/slide/circle variants, `hblur` — usable for whip-pan — are all built in, zero custom code). The gotcha is that `xfade` needs **overlapping footage** on both sides of a boundary, while `compute_keep_segments` trims to a **zero-overlap hard splice** by design (that's literally what a jump cut is). The fix specific to this codebase: the dead-air pause that `jumpcuts.py` already cuts out sits right at every boundary as unused source footage — borrow a slice of it as the overlap window for the transition, instead of eating into either segment's real (kept) content. Detailed in Common Pitfalls below.

**Primary recommendation:** Build `scripts/transitions.py` with three independent, unit-testable analysis functions (motion score via lazy-imported `cv2` + ffmpeg-extracted frame pairs, audio-onset score via lazy-imported `librosa`, and a same-`cv2` histogram-similarity proxy for match-cut — no `scenedetect` dependency needed, avoiding an opencv-python/opencv-python-headless conflict), one pure decision function mapping `(motion_score, audio_score, similarity_score)` → transition type with conservative, config-exposed thresholds, and rework `build_jumpcut_command`'s concat stage into a sequential fold that borrows pause-gap overlap for `xfade`-based boundaries and falls through to today's plain `concat` for `cut`/inconclusive boundaries.

## Architectural Responsibility Map

This project has no web tiers (browser/SSR/API/CDN/DB) — it's a local, single-process CLI pipeline. Mapped onto this project's actual layers instead:

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Boundary motion analysis (optical flow) | Stage 1 analysis script (new `scripts/transitions.py`) | — | Pure signal extraction over already-decoded frames, same shape as `audio_energy.py`/`silence.py` |
| Boundary audio-onset analysis (librosa) | Stage 1 analysis script (`scripts/transitions.py`) | — | Same as above; independent of video decode |
| Match-cut similarity proxy | Stage 1 analysis script (`scripts/transitions.py`) | — | Reuses the `cv2` import already required for optical flow — no new dependency |
| Signal → transition-type decision | Pure function in `scripts/transitions.py` | — | No I/O, fully unit-testable, mirrors `jumpcuts.compute_keep_segments`'s pure-function style |
| Transition filter-graph construction | `scripts/render.py` (new `build_transition_filter`-style helpers) | `scripts/transitions.py` (if planner splits it out) | Same pattern as existing `build_video_effects_chain`/`build_punch_zoom_filter` — pure function returning a filter-graph string fragment |
| Boundary overlap/gap bookkeeping (borrowing pause slice for xfade) | `scripts/jumpcuts.py` (extend `compute_keep_segments` or add a sibling function) | `scripts/render.py` (consumes the adjusted segments) | The pause-gap timing data already lives in `jumpcuts.py`; render.py should stay a consumer, not recompute pause locations |
| Fail-open degradation (missing opencv/librosa) | `scripts/transitions.py` (analysis functions) | `SKILL.md` orchestration (decides whether to call the new analysis at all) | Matches `diarize.py`'s established lazy-import-and-degrade pattern |

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `opencv-python-headless` | 5.0.0.93 (latest, PyPI, confirmed via `pip index versions` [VERIFIED: PyPI registry, dry-run install against project .venv]) | `cv2.calcOpticalFlowFarneback` dense optical flow between two boundary frames; `cv2.calcHist`/`cv2.compareHist` for match-cut proxy | De facto standard CV library; `-headless` variant avoids pulling GUI/Qt bindings this CLI-only project never uses [ASSUMED: standard community recommendation for headless/server use, not verified via an authoritative doc source this session] |
| `librosa` | 0.11.0 (latest, PyPI [VERIFIED: PyPI registry, dry-run install against project .venv]) | `librosa.onset.onset_strength` + `librosa.onset.onset_detect` for boundary audio-onset scoring | **Named explicitly in `TRANS-01`'s own requirement text** ("audio (energy/onset via librosa)") — this is a requirement-level lock, not a discretionary research pick |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `soundfile` | 0.14.0 (pulled transitively by librosa; not yet in project `.venv` — confirmed via dry-run) | librosa's default audio decode backend | Always, transitive — no direct import needed in `scripts/transitions.py` |
| `numba` + `llvmlite` | 0.66.0 / 0.48.0 (pulled transitively by librosa; prebuilt `win_amd64` wheels confirmed available — no source build) | JIT acceleration for some librosa internals | Transitive only; do not import directly |
| `numpy` | 2.5.0 (**already installed** in this project's `.venv` via `ctranslate2`/`onnxruntime` [VERIFIED: `pip show numpy` against `.venv\Scripts\python.exe`]) | Array backend for both opencv and librosa | Already present — zero incremental footprint |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Hand-rolled `cv2` histogram comparison for match-cut | `scenedetect` (`PySceneDetect`) `HistogramDetector`/`ContentDetector` | `scenedetect` pulls in plain `opencv-python` (GUI-enabled) as its own dependency [VERIFIED: `pip install scenedetect --dry-run` against project `.venv` shows `Collecting opencv-python`] — installing that alongside `opencv-python-headless` (needed for the optical-flow half of this same phase) is a documented source of `cv2` import conflicts, since both packages ship the same `cv2` module name. Since `cv2.calcHist`/`compareHist` (~10 lines) covers the "cheap proxy" match-cut need already using the `cv2` import this phase needs anyway, **recommend skipping `scenedetect` entirely** rather than resolving the dependency clash. |
| librosa `onset_strength` | Reuse `scripts/audio_energy.py`'s existing ffmpeg `ebur128` momentary-loudness spike detector | `audio_energy.py`'s rolling-baseline spike detector answers "is this moment louder than its own recent baseline" — useful as a *cheap pre-filter* or a secondary corroborating signal, but it does not distinguish a sudden transient attack (a hit, a slam, a laugh onset) from a sustained loud passage the way spectral-flux onset detection does. Since `TRANS-01` names librosa explicitly, use librosa for the actual onset score; `audio_energy.py`'s adaptive-relative-threshold *pattern* (not its code) is still worth mirroring for the transitions decision logic (see Common Pitfalls / thresholds below). |
| `xfade`-native `hblur` transition for whip pan | Custom `dblur`/`gblur` + `zoompan` filter chain | ffmpeg 8.1.2 already ships `hblur` as xfade transition #35 [VERIFIED: `ffmpeg -h filter=xfade` on this machine, local binary] — a horizontal-blur cross-dissolve that reads as a whip-pan-style transition with zero custom filter-graph code. A hand-built directional-blur+zoompan chain is a real fallback only if `hblur`'s visual read turns out too subtle in practice (empirical/creative call, not a technical blocker). |

**Installation:**
```bash
pip install opencv-python-headless librosa
```
(No `scenedetect` — see Alternatives Considered above.)

**Version verification:** Ran directly against this project's actual `.venv\Scripts\python.exe` (Python 3.13.14):
```
pip install librosa --dry-run                  # Would install librosa-0.11.0 + 21 transitive deps, all prebuilt win_amd64/py3-none wheels, zero "Building wheel" steps
pip install opencv-python-headless --dry-run    # Would install opencv-python-headless-5.0.0.93 only (numpy already present)
```
Both dry-runs completed with **zero source builds** — every dependency in the resolved graph ships a prebuilt Windows wheel for this Python version. This is meaningfully different from the project's existing `ctranslate2`/CUDA DLL pain (`transcribe.py`'s `README.md` troubleshooting section) — that pain is specific to GPU runtime DLL loading, which neither new dependency touches.

## Package Legitimacy Audit

| Package | Registry | Age (latest release) | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| `opencv-python-headless` | PyPI | latest release 2026-07-02 | unknown (tool has no download-count API access) | `github.com/opencv/opencv-python` | SUS (reasons: `too-new`, `unknown-downloads`) | **Approved with note** — see below |
| `librosa` | PyPI | latest release 2025-03-11 | unknown | `github.com/librosa/librosa` | SUS (reason: `unknown-downloads`) | **Approved with note** |
| `scenedetect` | PyPI | latest release 2026-05-03 | unknown | `github.com/Breakthrough/PySceneDetect` | SUS (reasons: `unknown-downloads`) | **Removed from recommendation** — not because of the verdict, but because of the real `opencv-python`/`opencv-python-headless` conflict documented above |
| `numpy` (transitive, already installed) | PyPI | latest release 2026-07-04 | unknown | none listed by tool | SUS (reasons: `too-new`, `unknown-downloads`, `no-repository`) | **No action** — already installed in this project's `.venv`, pulled in transitively by `ctranslate2`/`onnxruntime` long before this phase; not a new install |

**Reading the `SUS` verdicts:** the legitimacy-check tool has no download-count API in this environment (`unknown-downloads` fires on every package checked, including `numpy`), and its `too-new` signal appears to key off the **latest release date**, not the package's original publish date — which is why even `numpy` (first published 2006, one of the most depended-on packages in the Python ecosystem) shows `too-new`. This is a tool-signal limitation, not a real risk finding. All four packages above are extremely well-known, actively-maintained, mainstream libraries with legitimate GitHub source repos matching their PyPI listing (`opencv/opencv-python`, `librosa/librosa`), verified directly by this research session. None were discovered via an unfamiliar or single-source recommendation.

**Packages removed due to `[SLOP]` verdict:** none.
**Packages flagged as suspicious `[SUS]`:** `opencv-python-headless`, `librosa` — flagged only due to the tool's download-count/age-signal limitation described above, not a substantive legitimacy concern. Per protocol, the planner should still gate the actual `pip install` step behind a `checkpoint:human-verify` task (cheap, and consistent with the stated protocol regardless of this research session's own confidence in these two names).

## Architecture Patterns

### System Architecture Diagram

```text
compute_keep_segments()                 (existing, scripts/jumpcuts.py)
        │
        ▼
[boundary N: end of segment N / start of segment N+1]  (N-1 boundaries for N segments)
        │
        ├──► extract 2-3 frames around boundary (ffmpeg -ss, reuse frames.py's still-extraction pattern)
        │           │
        │           ▼
        │     cv2.calcOpticalFlowFarneback  ──►  motion_score
        │
        ├──► extract short audio window around boundary (ffmpeg -ss -t, or slice already-decoded audio)
        │           │
        │           ▼
        │     librosa.onset.onset_strength / onset_detect  ──►  audio_score
        │
        ├──► cv2.calcHist + cv2.compareHist on boundary frame pair  ──►  similarity_score
        │
        ▼
classify_transition(motion_score, audio_score, similarity_score, thresholds)  (pure function, new scripts/transitions.py)
        │
        ▼
   one of: cut | crossfade | whip_pan | mask_wipe | glitch | match_cut
        │
        ▼
build_jumpcut_command()  (existing, scripts/render.py — reworked from flat concat to sequential fold)
        │
        ├─ boundary = cut/match_cut          ──► plain trim+concat (today's behavior, zero overlap)
        └─ boundary = crossfade/whip_pan/    ──► borrow overlap window from the cut pause gap (see Pitfall 1),
           mask_wipe/glitch                       run pairwise xfade (+ acrossfade for audio) instead of concat
        │
        ▼
   [vout][aout]  ──►  ffmpeg encode (unchanged: libx264/aac)
```

### Recommended Project Structure
```
scripts/
├── transitions.py        # NEW — motion/audio/similarity analysis + classify_transition() pure function
├── jumpcuts.py            # EXTEND — compute_keep_segments (or a sibling) needs to expose the pause-gap size
│                          #   at each boundary so transitions.py/render.py can check overlap availability
├── render.py              # EXTEND — build_jumpcut_command's concat stage becomes a sequential fold;
│                          #   new build_transition_filter-style pure function(s) alongside
│                          #   build_video_effects_chain/build_punch_zoom_filter
tests/
├── test_transitions.py    # NEW — mirrors module-per-test-file convention
```

### Pattern 1: Lazy-imported optional analysis, fail-open on missing dependency
**What:** `scripts/transitions.py`'s `analyze_motion_at_boundary`/`analyze_audio_onset_at_boundary` import `cv2`/`librosa` inside the function body, not at module top level — exactly `diarize.py`'s `load_diarization_pipeline` pattern (`from pyannote.audio import Pipeline` inside the function).
**When to use:** Both new analysis functions, always — the module must remain importable (and the whole phase optional/disable-able) without either dependency installed.
**Example:**
```python
# Source: existing project pattern, scripts/diarize.py:72-78 (verified by reading this file directly)
def analyze_motion_at_boundary(frame_a_path: str, frame_b_path: str) -> float | None:
    try:
        import cv2
    except ImportError:
        return None  # fail-open: caller treats None as "inconclusive" -> TRANS-03 fallback

    frame_a = cv2.imread(frame_a_path, cv2.IMREAD_GRAYSCALE)
    frame_b = cv2.imread(frame_b_path, cv2.IMREAD_GRAYSCALE)
    flow = cv2.calcOpticalFlowFarneback(frame_a, frame_b, None, 0.5, 3, 15, 3, 5, 1.2, 0)
    magnitude, _ = cv2.cartToPolar(flow[..., 0], flow[..., 1])
    return float(magnitude.mean())
```

### Pattern 2: Extracting boundary frames via ffmpeg still-extraction (reuse `frames.py`'s shape)
**What:** `scripts/frames.py::extract_frames` already extracts JPEG stills at arbitrary timestamps via `-ss` fast-seek + `-frames:v 1`, injectable `runner=subprocess.run`. The same call shape extracts the 2 (or a handful of) frames needed around a boundary — no new ffmpeg technique required.
**When to use:** For both the optical-flow input frames and the match-cut histogram-comparison frames.
**Example:**
```python
# Source: scripts/frames.py:31-53 (verified by reading this file directly), adapted call site
boundary_frames = extract_frames(
    video_path, [boundary_time - 0.05, boundary_time + 0.05], tmp_dir, prefix="boundary"
)
```

### Pattern 3: `xfade` for the 4 transitions that map to native transitions
**What:** `crossfade` → `xfade=transition=fade`, `mask/wipe` → `xfade=transition=wipeleft` (or `circleopen`/`rectcrop` for a "mask" read), `whip pan` → `xfade=transition=hblur` (all 58 built-in names confirmed present via `ffmpeg -h filter=xfade` on this machine's ffmpeg 8.1.2, so any of these can be used with zero custom filter code).
**When to use:** Whenever `classify_transition` picks one of these types and the boundary has enough borrowed overlap (see Pitfall 1).
**Example:**
```text
# Source: ffmpeg -h filter=xfade output, this machine's ffmpeg 8.1.2 [VERIFIED: local binary]
[vA][vB]xfade=transition=fade:duration=0.35:offset=<A_len - 0.35>[vout]
[aA][aB]acrossfade=d=0.35[aout]
```

### Pattern 4: Custom filter chain for glitch (no native xfade transition fits)
**What:** No single `xfade` transition name reads as "glitch." Recommended recipe: base the blend on `xfade=transition=pixelize` (blocky, chaotic-looking dissolve) or `distance`, then layer `rgbashift` (RGB channel split) and `noise` on top for the transition's duration only.
**When to use:** `classify_transition` picks `glitch` (per this research's suggested mapping: sudden strong audio onset + at least moderate motion — an "impact" moment).
**Example:**
```text
# Source: ffmpeg filter docs (rgbashift/noise options) [CITED: ffmpeg.org/ffmpeg-filters.html] +
# xfade transition list [VERIFIED: local ffmpeg -h filter=xfade] — combination is this research's synthesis, not a copied recipe
[vA][vB]xfade=transition=pixelize:duration=0.2:offset=<A_len-0.2>,
  rgbashift=rh=8:bh=-8:edge=smear,
  noise=alls=25:allf=t+u[vout]
```

### Pattern 5: Match cut — likely no distinct render, distinct *reason*
**What:** In real film editing, a match cut is specifically a **hard cut** (no dissolve) between two shots chosen for visual/compositional continuity — the "specialness" is entirely in why the cut point was chosen (via the histogram-similarity proxy), not in a different filter graph. [ASSUMED: standard film-editing convention/training knowledge, not verified via a citation this session]
**When to use:** `classify_transition` picks `match_cut` when boundary-frame histogram similarity is high (visually continuous) regardless of motion/audio score.
**Recommendation:** Render identically to `cut` (plain trim+concat, zero overlap needed) but record `"transition_type": "match_cut"` in whatever plan/metadata the planner threads through, so it's distinguishable in logs/`PLAN.json` even though the ffmpeg command is the same. This sidesteps the overlap-borrowing complexity (Pitfall 1) entirely for this one type. Flag this as an open design question for the planner to confirm — if the desired look is closer to a very brief blend, `xfade=transition=fade:duration=0.08` is the minimal-blend fallback.

### Anti-Patterns to Avoid
- **Reaching for `scenedetect` for the match-cut proxy:** pulls in plain `opencv-python` alongside the `opencv-python-headless` this phase already needs for optical flow — a documented `cv2`-module conflict source. Use `cv2.compareHist` directly instead (same import, no extra package).
- **Treating `xfade` like `concat`:** `concat` is a zero-overlap splice; `xfade` requires real overlapping footage and shrinks total output duration by the transition's duration. Do not attempt to bolt `xfade` onto the existing flat `concat=n=N` call without restructuring the graph — see Pitfall 1.
- **Hardcoding one fixed numeric threshold "because it felt right in one test video":** this pipeline runs on arbitrarily different gameplay footage session-to-session; an adaptive/relative threshold (mirroring `silence.py`'s own-file-loudness-baseline precedent) degrades far more gracefully than an absolute magic number tuned on a single clip.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Dense optical flow between two frames | A custom pixel-diff motion estimator | `cv2.calcOpticalFlowFarneback` | Well-tested, well-understood parameters, already the de-facto standard for exactly this task |
| Spectral-flux audio onset detection | A custom FFT-based transient detector | `librosa.onset.onset_strength`/`onset_detect` | Explicitly named in `TRANS-01`'s own requirement text; reinventing spectral flux is real signal-processing work with well-known pitfalls (windowing, log-compression, peak-picking) librosa already handles |
| Cross-fade / wipe transition rendering | A custom per-pixel blend filter_complex expression | ffmpeg's native `xfade` filter (58 built-in transitions) | Already installed, already covers 4 of the 6 required types natively, zero new code |
| Scene-similarity histogram comparison | A hand-rolled pixel-diff or perceptual-hash comparator | `cv2.calcHist` + `cv2.compareHist(method=cv2.HISTCMP_CORREL)` | Standard, cheap, already available once `cv2` is imported for optical flow — a ~10-line function, not a new dependency |

**Key insight:** Every piece of this phase's "hard" CV/audio work already has a standard, already-available (either already-installed or one prebuilt-wheel `pip install` away) library solution. The actual engineering risk in this phase is entirely in the ffmpeg filter-graph restructuring (concat → conditional xfade fold) and in choosing conservative, adaptive thresholds — not in the signal analysis itself.

## Common Pitfalls

### Pitfall 1: `xfade` needs overlap; `keep_segments` boundaries have none — borrow it from the pause gap that was cut
**What goes wrong:** `compute_keep_segments` trims exactly at the pause boundary with zero overlap — that's the entire point of a jump cut (no dead air survives). If you naively try to `xfade` segment N's trimmed end against segment N+1's trimmed start, there is no shared footage to blend; you'd either need to shrink kept content on both sides (eating into real speech/action) or the transition would visually just repeat/freeze a frame.
**Why it happens:** Generic ffmpeg tutorials assume you're crossfading two already-full, independently-trimmed clips with footage to spare on each side. This pipeline's segments are trimmed to the *exact* edge of kept content by design.
**How to avoid:** The pause that was cut between segment N and N+1 (`gap = next_segment_start - this_segment_end`, using the same absolute-source-seconds values `compute_keep_segments` already computes internally) is real, unused source footage sitting right at the boundary. When a non-cut transition is selected and `gap >= transition_duration`, extend segment N's trim end and/or segment N+1's trim start into that gap (symmetrically, `transition_duration / 2` each side is simplest) so both sides have genuinely overlapping frames for `xfade`/`acrossfade` to blend — instead of ever touching the kept segments' own real content. If `gap < transition_duration` (a short pause just over `cut_threshold_seconds`), either clamp the transition duration down to what's available (with a sensible floor, e.g. 0.12s, below which visual difference is negligible) or fall back to a plain cut per `TRANS-03`.
**Warning signs:** A crossfade/wipe/whip-pan/glitch boundary that looks like it "eats" the last word of a sentence or the first frame of the next action — sign that the transition ate into real kept content instead of the pause gap.

### Pitfall 2: A flat `concat=n=N` filter can't express "some boundaries are cuts, some are transitions" in one call
**What goes wrong:** `build_jumpcut_command` today builds one N-ary `concat` node covering every segment at once. Mixing `xfade` (a 2-input filter) into that graph for only *some* boundaries requires restructuring, not appending.
**Why it happens:** `concat`'s N-ary shape and `xfade`'s pairwise shape are architecturally different filter-graph patterns; you can't partially "upgrade" one concat node.
**How to avoid:** Restructure the graph construction into a sequential fold: start with segment 0's trimmed `[v0][a0]`, then for each subsequent segment either (a) append via a 2-input `concat=n=2` (cut/match-cut boundary — equivalent to today's behavior applied pairwise) or (b) blend via `xfade`+`acrossfade` (fancy-transition boundary, using the borrowed overlap from Pitfall 1), accumulating into a running `[vacc][aacc]` pair until all segments are folded in.
**Warning signs:** Attempting to pass a mix of transition types into a single `concat` filter_complex string and getting either a syntax error or a graph that silently ignores the requested transition.

### Pitfall 3: `opencv-python` and `opencv-python-headless` installed together
**What goes wrong:** Both packages provide the same `cv2` module; having both installed in the same environment is a known source of import/DLL conflicts in the opencv-python community.
**Why it happens:** Easy to hit if a match-cut library like `scenedetect` (which depends on plain `opencv-python`) is added alongside this phase's own `opencv-python-headless` choice for optical flow.
**How to avoid:** Don't add `scenedetect`; use `cv2.calcHist`/`compareHist` directly for the match-cut proxy, reusing the single `opencv-python-headless` install this phase already needs.
**Warning signs:** `ImportError`/`AttributeError` on `cv2` symbols that "should" exist, or two different `cv2` versions reported by `pip list`.

### Pitfall 4: Conservative-bias threshold tuned as a single fixed number generalizes poorly
**What goes wrong:** Gameplay footage varies wildly in ambient loudness and camera-motion baseline stream to stream; a fixed absolute optical-flow-magnitude or onset-strength cutoff that "looked right" on one test clip will over- or under-trigger on a louder/quieter or more/less static stream.
**Why it happens:** No universal published threshold exists for "how much optical flow magnitude means a whip pan is warranted" — this is inherently empirical and content-dependent, which is exactly why `D-02` explicitly leaves it to Claude's/planner's discretion.
**How to avoid:** Follow the adaptive-baseline precedent already established in this codebase (`silence.py::measure_loudness` uses the file's own EBU R128 threshold, not a guessed fixed dB; `audio_energy.py::compute_rolling_baseline` compares each point to its own local rolling median). Recommend the same idea for transitions: compute motion/audio scores across all boundaries in the clip/video first, then trigger a non-cut transition only when a boundary's score is clearly above the *distribution* of that video's own other boundaries (e.g., a high percentile or several standard deviations above the median) — not an absolute magic number. Expose the percentile/threshold as a config default with a comment stating it is empirical/tunable, per `D-02`.
**Warning signs:** Every boundary in a test render gets the same transition type, or transitions feel "random"/uncorrelated with what's happening on screen — sign the threshold is miscalibrated for that video's actual signal range.

## Code Examples

### Detecting optical flow magnitude between two boundary frames
```python
# Source: OpenCV official Farneback tutorial pattern (docs.opencv.org/3.4/d4/dee/tutorial_optical_flow.html)
# [CITED: docs.opencv.org] — parameter values are OpenCV's own commonly-cited defaults
import cv2

flow = cv2.calcOpticalFlowFarneback(prev_gray, next_gray, None, 0.5, 3, 15, 3, 5, 1.2, 0)
magnitude, angle = cv2.cartToPolar(flow[..., 0], flow[..., 1])
motion_score = float(magnitude.mean())
```

### Audio onset strength around a boundary
```python
# Source: librosa official docs (librosa.org/doc/main/generated/librosa.onset.onset_strength.html)
# [CITED: librosa.org]
import librosa

y, sr = librosa.load(audio_window_path, sr=None)
onset_env = librosa.onset.onset_strength(y=y, sr=sr)
audio_score = float(onset_env.max())
```

### `xfade` cascaded between two trimmed, overlap-extended segments
```text
# Source: ffmpeg -h filter=xfade [VERIFIED: local ffmpeg 8.1.2] + trim/setpts pattern already used in
# scripts/render.py::build_jumpcut_command (verified by reading this file directly)
[0:v]trim=start=<segA_start>:end=<segA_end_extended>,setpts=PTS-STARTPTS[vA];
[0:v]trim=start=<segB_start_extended>:end=<segB_end>,setpts=PTS-STARTPTS[vB];
[vA][vB]xfade=transition=fade:duration=<d>:offset=<segA_len-d>[vout]
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| This project's current behavior: always hard-cut/punch-zoom at every jump-cut boundary | Context-aware transition selection per boundary (this phase) | This phase (2026-07) | Boundaries that warrant it get visual/audio treatment; conservative default (`D-01`) means most boundaries remain unchanged |

**Deprecated/outdated:** Nothing in the ffmpeg/opencv/librosa stack itself is deprecated for this use — `xfade` (added ffmpeg 4.3, 2020) and `calcOpticalFlowFarneback`/librosa onset detection are all current, actively maintained APIs as of the versions verified above.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `opencv-python-headless` is the right "no-GUI" variant name/convention (vs. always using plain `opencv-python`) | Standard Stack | Low — both provide identical `cv2` API; wrong choice only affects install size/GUI-dependency footprint, not functionality |
| A2 | A "match cut" should render identically to a plain hard cut, differentiated only by selection reason/metadata | Architecture Patterns, Pattern 5 | Medium — if the desired creative effect is a visible brief blend rather than an invisible-but-intentional hard cut, the planner needs to instead treat match_cut like crossfade with a very short duration; low implementation risk either way since it's a duration-parameter choice, not a new filter |
| A3 | Suggested signal-to-type decision mapping (motion→whip-pan, audio-onset→glitch, similarity→match-cut, moderate-both→crossfade, else→mask/wipe or cut) is a reasonable default | Architecture Patterns | Low-Medium — `D-04` explicitly leaves this to discretion; a materially different mapping is still "correct" as long as conservative bias (`D-01`) is honored — this is a starting point for the planner/implementer to refine, not a locked spec |
| A4 | No universal/published numeric threshold exists for "motion/audio strong enough to justify a transition" — this must be adaptive/empirical | Common Pitfalls, Pitfall 4 | Low — confirmed by absence of any such convention in official opencv/librosa docs found this session; recommending adaptive relative thresholding is the safe default regardless |

**If this table is empty:** N/A — see entries above; all are low-to-medium risk and do not block planning, only implementation-detail refinement.

## Open Questions

1. **Should `match_cut` get any visual distinction from `cut` at all, or purely a metadata tag?**
   - What we know: standard editing theory treats match cut as "just a cut, chosen well" — no dissolve.
   - What's unclear: whether the user/planner wants some minimal visual signal (e.g. a very brief `fade`, ~0.08s) to make the 6th type perceptible in the output, given `TRANS-02` requires 6 *selectable* types.
   - Recommendation: default to metadata-only (Pattern 5) since it satisfies `TRANS-02`'s "selectable" requirement (it's a distinct decision-tree outcome, logged and traceable) without adding render complexity; leave a code comment noting the near-zero-duration-fade alternative if a future pass wants a perceptible distinction.

2. **Exact numeric thresholds for the conservative-bias decision tree.**
   - What we know: `D-01`/`D-02` mandate conservative-by-default with thresholds at Claude's/planner's discretion; no external convention exists (Pitfall 4/Assumption A4).
   - What's unclear: the actual percentile/relative-threshold values to start with.
   - Recommendation: expose as `config.yaml` `transitions:` section defaults (mirroring `jumpcuts:`/`audio_energy:` conventions already in `config.example.yaml`), commented as empirical starting points intended to be tuned after watching real renders — do not treat any specific number as authoritative.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| ffmpeg (with `xfade`, `rgbashift`, `gblur`, `dblur`, `noise`, `tblend` filters) | All 6 transition types' rendering | ✓ [VERIFIED: `ffmpeg -filters`/`ffmpeg -h filter=xfade` run directly on this machine] | 8.1.2-full_build (gyan.dev) | — (already required by the whole existing pipeline) |
| `opencv-python-headless` | Motion analysis + match-cut proxy (`TRANS-01`) | ✗ (not yet installed in project `.venv`) | 5.0.0.93 latest on PyPI, prebuilt `win_amd64` wheel confirmed | Fail-open per `TRANS-03`: missing import → treat boundary as inconclusive → today's cut/punch-zoom |
| `librosa` | Audio onset analysis (`TRANS-01`) | ✗ (not yet installed) | 0.11.0 latest on PyPI, all transitive deps prebuilt wheels | Fail-open per `TRANS-03`, same as above |
| Python | Runtime | ✓ | 3.13.14 (this project's actual `.venv`, confirmed via `python --version`) | — |

**Missing dependencies with no fallback:** none — both new dependencies have an explicit, requirement-mandated fail-open fallback (`TRANS-03`).
**Missing dependencies with fallback:** `opencv-python-headless`, `librosa` — both degrade to today's cut/punch-zoom behavior per `TRANS-03` and the project's standing Fail-open constraint.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest >=7.4.0 (`requirements-dev.txt`, already installed) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` — `pythonpath=["."]`, `testpaths=["tests"]`, registers `integration` marker |
| Quick run command | `pytest tests/test_transitions.py -x` |
| Full suite command | `pytest -x` (real-ffmpeg `integration`-marked tests run too since ffmpeg is on PATH on this machine; `pytest -m "not integration" -x` for a faster non-integration pass) |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| TRANS-01 | Motion/audio boundary analysis functions return sane scores on known fixtures; degrade to `None` when `cv2`/`librosa` unimportable | unit | `pytest tests/test_transitions.py -x -k analyze` | ❌ Wave 0 |
| TRANS-02 | `classify_transition` returns each of the 6 valid type strings for constructed signal inputs; filter-graph builder produces valid ffmpeg syntax per type | unit | `pytest tests/test_transitions.py -x -k classify` / `pytest tests/test_render.py -x -k transition` | ❌ Wave 0 |
| TRANS-03 | Inconclusive/missing-signal boundary falls back to plain cut/punch-zoom; insufficient pause-gap overlap falls back to cut | unit | `pytest tests/test_transitions.py -x -k fallback` | ❌ Wave 0 |
| TRANS-01/02 (real render) | A full jumpcut render with a forced non-cut boundary actually produces a playable, correctly-dimensioned output | integration | `pytest tests/test_integration_ffmpeg.py -x -m integration -k transition` (new test, following `test_jumpcut_splices_out_silence_gap`'s existing pattern) | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/test_transitions.py -x` (and `tests/test_render.py`/`tests/test_jumpcuts.py` for touched functions)
- **Per wave merge:** `pytest -x` (full suite, including integration since ffmpeg is present)
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/test_transitions.py` — new file, covers TRANS-01/02/03 unit-level behavior (motion/audio/similarity scoring, classify_transition, fail-open on missing deps)
- [ ] New integration test in `tests/test_integration_ffmpeg.py` mirroring `test_jumpcut_splices_out_silence_gap`'s fixture-video pattern, covering a real xfade-based transition render
- [ ] Extend `tests/test_jumpcuts.py` if `compute_keep_segments` (or a sibling) gains pause-gap-size exposure for the overlap-borrowing logic (Pitfall 1)
- [ ] No new framework install needed — pytest and its `integration` marker are already configured

## Security Domain

### Applicable ASVS Categories

This phase has no network-facing surface, no auth/session, and no user-supplied untrusted input beyond config values already validated by `scripts/config.py::_validate` and internal pipeline data (video files the operator supplies). Most ASVS categories are not applicable to a local, single-operator CLI batch tool with no multi-tenant/auth surface.

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | N/A — no auth surface in this phase |
| V3 Session Management | No | N/A |
| V4 Access Control | No | N/A — single local operator |
| V5 Input Validation | Yes | New `transitions:` config fields (thresholds, enabled flags) validated in `scripts/config.py::_validate` following the existing `raise ConfigError(...)` pattern (verified: `_validate` already validates `effects.punch_zoom_ramp`, `jumpcuts.*`, etc. the same way); transition-type strings from the decision function should be validated against a fixed enum/set before being used to key into a filter-string dispatch table, so an unexpected value fails loudly instead of building a malformed `filter_complex` string |
| V6 Cryptography | No | N/A — no secrets/crypto touched by this phase |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| ffmpeg command/filter-string injection via unsanitized values interpolated into `filter_complex` | Tampering | Already mitigated by existing convention: all subprocess calls in this codebase build an argument **list** (never `shell=True`/string interpolation into a shell), and filter-graph fragments are built from internally-computed floats/enum-constrained strings, not raw external text. New transition filter-string builders must follow the same pattern — never interpolate a transition-type value that wasn't first validated against the fixed 6-item enum |
| Dependency supply-chain risk from new PyPI installs | Tampering / Elevation of Privilege | Covered by the Package Legitimacy Audit above; `checkpoint:human-verify` recommended before the actual `pip install` per the `SUS` verdicts noted (tool-signal limitation, not a substantive concern, but the protocol still applies) |

## Sources

### Primary (HIGH confidence)
- Direct read of this repo's own source: `scripts/render.py`, `scripts/jumpcuts.py`, `scripts/audio_energy.py`, `scripts/silence.py`, `scripts/frames.py`, `scripts/diarize.py`, `scripts/config.py`, `tests/test_render.py`, `tests/test_integration_ffmpeg.py`, `pyproject.toml`, `config.example.yaml`
- Direct execution on this machine: `ffmpeg -filters`, `ffmpeg -h filter=xfade` (ffmpeg 8.1.2-full_build, gyan.dev) [VERIFIED]
- Direct execution on this machine: `pip install librosa/opencv-python-headless/scenedetect --dry-run` against the project's actual `.venv\Scripts\python.exe` (Python 3.13.14) [VERIFIED]
- `pip show numpy` / `pip show llvmlite` etc. against the project's actual `.venv` [VERIFIED]

### Secondary (MEDIUM confidence)
- librosa official docs — `librosa.onset.onset_detect`/`onset_strength` (librosa.org) [CITED]
- OpenCV official docs/tutorial — Farneback dense optical flow (docs.opencv.org) [CITED]
- ffmpeg filters documentation — `rgbashift`, `noise`, `xfade` options (ffmpeg.org/ffmpeg-filters.html) [CITED]
- PySceneDetect official docs — `ContentDetector`/`HistogramDetector` (scenedetect.com) [CITED, but recommendation is to NOT use this library — see Alternatives Considered]

### Tertiary (LOW confidence)
- General WebSearch results on "ffmpeg glitch effect"/"whip pan transition" community tutorials (Medium articles, blog posts) — used only to corroborate that no single canonical glitch/whip-pan ffmpeg recipe exists industry-wide, confirming the custom-combination approach in Pattern 4 is reasonable synthesis rather than a known best practice being missed [ASSUMED]

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — package existence, versions, and Windows-wheel install behavior all directly verified against this project's real environment, not just training knowledge
- Architecture (xfade/concat restructuring): HIGH for the *problem* (verified: `keep_segments` truly has zero overlap by reading `jumpcuts.py`/`render.py` directly), MEDIUM for the *exact* recommended fold implementation shape (a reasonable design, but the planner should treat it as a strong recommendation, not the only valid approach)
- Pitfalls: HIGH for Pitfalls 1-3 (all directly grounded in this repo's actual code + directly-verified package behavior), LOW-MEDIUM for Pitfall 4 (thresholds are inherently empirical, explicitly flagged as such)

**Research date:** 2026-07-08
**Valid until:** ~30 days for the ffmpeg/library-version specifics (stable, slow-moving ecosystem); the signal-to-type mapping and thresholds should be revisited empirically after the first real renders regardless of any "valid until" date
