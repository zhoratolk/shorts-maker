# Phase 7: Profanity Auto-Bleep - Research

**Researched:** 2026-07-11
**Domain:** ffmpeg time-windowed audio filter graphs (sub-span masking within a single `-af`/`filter_complex` chain), deterministic RU/EN profanity detection over Whisper word-level timestamps, clip-relative timestamp remapping through the existing jumpcut splice pipeline
**Confidence:** HIGH (ffmpeg filter mechanics — live-tested against a real ffmpeg 8.1.2 binary on this machine, not just read from docs; codebase integration points — read directly from `scripts/render.py`/`scripts/jumpcuts.py`/`scripts/subtitles.py`/`SKILL.md`) / MEDIUM (Whisper word-timestamp precision figures — external sources, not this project's own measurement) / MEDIUM (exact duck/garble parameter values — functionally verified to work, but D-03 explicitly defers final tuning to empirical validation against a real clip during implementation)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Wordlist source**
- **D-01:** RU+EN swear wordlist, stored in a local editable data file (same pattern as `data/monetization_rules.yaml` — no external service, no LLM call, local-first).
- **D-02:** Wordlist must support common obfuscated spellings creators actually use in speech/chat-adjacent contexts (e.g. yo-substitution, partial stems like `бл*`) — not just exact literal forms. Matching should be deterministic (regex/stem-based), not fuzzy-LLM, consistent with MONET-02's precedent ("deterministic rule-tier only — no LLM-nuance tier").

**Overlay tone character**
- **D-03:** Masking = duck the original word's volume down + layer a light noise/garble on top (not a pure clean sine beep, not a full silence cut). Goal: audio keeps flowing, word is hard to make out, doesn't read as an obvious hard edit.
- **Claude's discretion:** exact ffmpeg filter combination, specific duck depth, noise level/frequency shaping — pick values that satisfy Success Criterion 3 and validate empirically against a real clip during implementation.

**Config toggle**
- **D-04:** New `config.yaml` section for this feature (e.g. `profanity:`), following the same fail-open, default-off pattern as `diarization`/`audio_energy` — missing/malformed config or wordlist degrades to "no masking applied" rather than failing the pipeline. Default OFF (opt-in).

### Claude's Discretion
- Exact regex/matching implementation for obfuscation handling. **Resolved below** (Standard Stack > Wordlist Format, Code Examples).
- Precise ffmpeg filter graph for the duck+noise overlay — per-span time-windowed filters are new to this codebase. **Resolved below** (Architecture Patterns > Pattern 1, live-verified).
- Whether detection happens as a standalone new script (`scripts/profanity.py`) vs. folded into an existing module. **Resolved below**: standalone `scripts/profanity.py`, mirroring `monetization_risk.py`'s shape.
- Word-boundary matching strictness (avoiding false positives). **Resolved below** (Common Pitfalls > Pitfall 1, live-verified with Python's `re` engine).

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within phase scope.

</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| AUDIO-01 | Swear words are identified from the existing word-level Whisper transcript for every clip before render | Architecture Patterns > Pattern 2 (clip-relative remap reuse); Standard Stack > Wordlist Format + `scripts/profanity.py` design |
| AUDIO-02 | Each identified span gets a quiet overlay tone applied at render time (via `render.py`'s audio filter chain) — audio keeps playing, no dead-silence gap | Architecture Patterns > Pattern 1 (live-verified filter graph); Code Examples |
| AUDIO-03 | Overlay is quiet/garbled enough to defeat platform speech-to-text moderation scanning of the masked word, without sounding like an abrupt cut | Architecture Patterns > Pattern 1 (bandreject+tremolo garble); Validation Architecture (self-check via faster-whisper re-transcription) |

</phase_requirements>

## Summary

The codebase already has everything this phase needs except one new mechanical capability: **time-windowed (sub-span) audio filtering**. Every existing filter in `render.py`'s `build_audio_filter_chain` (`afftdn`, `loudnorm`, `afade`) applies to the whole clip. Masking a specific swear word's audio span, while leaving the rest of the clip untouched, requires ffmpeg's **timeline `enable` option** — a feature several ffmpeg audio filters already support natively, with zero new dependencies (no new pip package, no second ffmpeg input, no `filter_complex`/`amix` restructuring needed).

This was live-verified against the actual `ffmpeg 8.1.2` binary installed on this machine (not just read from docs): a single `-af` chain of the form `volume=enable='between(t,2.0,2.4)+between(t,5.0,5.6)':volume=0.1,bandreject=enable='...':f=1800:width_type=o:w=4,tremolo=enable='...':f=18:d=0.7` applies a duck+garble effect **only** inside the named time windows and leaves everything outside them byte-identical (confirmed via `volumedetect`: -21.1dB baseline unaffected outside the window, -33.3dB inside a ducked window). Because this stays within a single-input, single-output filter chain — no synthetic noise source, no `amix` — it slots into the **exact same chain string** that `build_ffmpeg_command` (plain `-af`) and `build_jumpcut_command`/`build_compilation_command` (embedded as `[acat]<chain>[aout]` inside `filter_complex`) already both consume. No structural change to `render.py`'s command-building is needed — only `build_audio_filter_chain`'s own returned string needs to grow one more optional clause.

Detection reuses the project's own established "clip-relative timestamp" plumbing rather than inventing a second one: `scripts/monetization_risk.py`'s text-offset regex matching is the wrong shape for this phase (it matches against joined text, not per-word spans) — the right precedent is Whisper's own `words` list (`{"word","start","end"}`, already absolute source-file seconds) combined with `scripts/jumpcuts.py::remap_words`, the exact function `SKILL.md` step 5 already uses to convert subtitle word timestamps from absolute to clip-relative (and to correctly drop any word that fell inside a cut jump-cut gap). Profanity detection should run on that same post-remap, clip-relative word list — this makes jumpcut interaction free (a word cut out by a jump cut simply isn't in the list to begin with) and keeps detection granularity at the word level, so no text-offset-to-timestamp reconstruction is ever needed (unlike `monetization_risk.py`).

**Primary recommendation:** New `scripts/profanity.py` (detection, mirrors `monetization_risk.py`'s fail-open YAML-loading shape) + a new `ProfanityConfig` section in `scripts/config.py` + a new `data/profanity_wordlist.yaml` (committed, generic — no channel-specific content, same footing as `data/monetization_rules.yaml`) + two small additive functions in `scripts/render.py` (`build_profanity_mask_filter`, and an extended `build_audio_filter_chain` signature) + a new optional `profanity_spans` field on `PLAN.json` clip entries, populated by a new SKILL.md step-5 bullet that reuses the existing word-collection-and-remap pattern already established for subtitles.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Swear-word detection (text matching against wordlist) | Mechanical script (`scripts/profanity.py`) | — | Deterministic regex/stem matching, no semantic judgment — matches TAGS-01 precedent ("mechanical execution belongs in `scripts/*.py`") and MONET-02's "deterministic rule-tier only" reaffirmation |
| Clip-relative timestamp remap of matched spans | Mechanical script (reuse `scripts/jumpcuts.py::remap_words`) | — | Pure function, already exists, already proven correct for the identical "absolute source time -> spliced clip-relative time" problem subtitles solve |
| Config toggle + wordlist load (fail-open) | Config layer (`scripts/config.py` + `scripts/profanity.py::load_wordlist`) | — | Matches `DiarizationConfig`/`AudioEnergyConfig`/`monetization_risk.load_rules` convention exactly |
| Audio filter-graph construction (duck+garble) | Mechanical script (`scripts/render.py`) | — | Pure ffmpeg command-string building, no subprocess call itself — matches `build_punch_zoom_filter`/`build_video_effects_chain` precedent |
| ffmpeg execution (rendering the masked audio) | Mechanical script (`scripts/render.py::render_clip`, existing `runner=subprocess.run` injectable) | — | No new execution path; reuses the existing render dispatch |
| Deciding *which* transcript region is a "moment worth clipping" vs. profanity policy | N/A (out of scope) | — | This phase never makes a semantic judgment — it is a deterministic post-process applied uniformly to every rendered clip when `config.profanity.enabled` |

## Standard Stack

### Core
| Component | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `ffmpeg` `volume` filter, timeline (`enable`) mode | already required (project dependency) | Time-windowed volume duck | Built-in ffmpeg filter; documented timeline support (`enable` AVOption), live-verified on this machine's `ffmpeg 8.1.2` |
| `ffmpeg` `bandreject` filter, timeline mode | already required | Removes mid-band (speech-formant) frequency energy inside the masked window — directly degrades STT recognizability, not just loudness | Built-in ffmpeg filter, confirmed timeline-capable via `ffmpeg -h filter=bandreject` ("This filter has support for timeline through the 'enable' option") |
| `ffmpeg` `tremolo` filter, timeline mode | already required | Adds a warble/robotic amplitude-modulation texture inside the window so the mask reads as "garbled," not a flat cut | Built-in ffmpeg filter; live-verified to compose in the same chain |
| Python `re` (stdlib) | stdlib | Deterministic regex/stem matching against the wordlist | Matches `monetization_risk.py`'s existing `re.compile`/`re.escape` pattern; zero new dependency |
| `yaml` (`PyYAML>=6.0`, already a dependency) | already required | Wordlist file format | Matches `data/monetization_rules.yaml`'s existing format/loading convention (`scripts/config.py`, `scripts/monetization_risk.py::load_rules`) |

**No new pip packages.** This phase needs zero new external dependencies — pure stdlib (`re`) + the project's existing `ffmpeg` binary + existing `PyYAML`. See Package Legitimacy Audit below.

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `volume`+`bandreject`+`tremolo` single-input `-af` chain (recommended) | Synthetic noise source (`anoisesrc`) mixed in via `filter_complex`+`amix` | Live-tested and works (see Common Pitfalls > Pitfall 4 for the exact gotcha), but requires restructuring `build_ffmpeg_command`'s plain `-af` path into `filter_complex` with a second input, and getting relative gain-staging right (risk of clipping — observed `max_volume` rising from -18.1dB to -11.5dB in testing when noise wasn't level-matched). Not needed: the self-contained filter chain already satisfies D-03's "duck + garble on top" without a second source. |
| Regex `\b<root>\w*\b` stem matching with a normalization pre-pass (recommended) | Full literal-string enumeration of every obfuscated spelling in the wordlist | Unbounded list size, doesn't generalize to spellings not anticipated in advance — violates D-02's actual intent ("common obfuscated spellings," not "every possible spelling") |
| Regex `\b<root>\w*\b` stem matching (recommended) | Fuzzy/edit-distance matching (e.g. Levenshtein against a swear-word list) | Explicitly ruled out by D-02/MONET-02 precedent ("deterministic... not fuzzy-LLM") |
| A pure `volume=0` mute (silence) inside the window | — | Explicitly ruled out by D-03 ("not a full silence cut" — a silence gap reads as an obvious edit and doesn't "keep audio flowing") |
| A clean sine-tone beep (`sine=frequency=1000` gated to the window) | — | Explicitly ruled out by D-03 ("not a pure clean sine beep") |

**Installation:** None — no new packages to install.

## Package Legitimacy Audit

This phase introduces **zero new external packages** — only stdlib `re` (already used project-wide) and the project's existing `ffmpeg` binary/`PyYAML` dependency (already vetted in Phase 1). No legitimacy check is applicable.

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| *(none — no new packages)* | — | — | — | — | — | N/A |

**Packages removed due to [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## Architecture Patterns

### System Architecture Diagram

```text
Whisper transcript (absolute source-file seconds)
        |
        v
[per-clip] words in [clip_start, clip_end) window   <-- same collection SKILL.md step 5
        |                                                already does for subtitles
        v
scripts/jumpcuts.py :: remap_words()                 <-- REUSED, not reimplemented
   (absolute -> clip-relative / spliced timeline;
    drops words inside cut jump-cut gaps)
        |
        v
scripts/profanity.py :: find_profane_spans()          <-- NEW (this phase)
   normalize each clip-relative word -> match against
   data/profanity_wordlist.yaml stems -> pad +/- N ms
   -> merge overlapping spans -> [(start,end), ...]
        |
        v
PLAN.json clip entry: "profanity_spans": [[s,e], ...]  <-- NEW optional field
   (omitted entirely when empty/disabled - existing
    PLAN.json convention)
        |
        v
scripts/render.py :: render_clip()
   plan_entry.get("profanity_spans")
        |
        v
scripts/render.py :: build_profanity_mask_filter()     <-- NEW pure builder
   -> "volume=enable='between(t,s1,e1)+...':volume=0.12,
       bandreject=enable='...':f=1800:width_type=o:w=4,
       tremolo=enable='...':f=18:d=0.7"
        |
        v
scripts/render.py :: build_audio_filter_chain()         <-- EXTENDED (one new
   afftdn -> loudnorm -> [profanity mask] -> afade          optional param,
        |                                                    inserted here)
        v
   -af "<chain>"  (build_ffmpeg_command, no keep_segments)
   or [acat]<chain>[aout]  (build_jumpcut_command /
                             build_compilation_command,
                             inside filter_complex)
        |
        v
  rendered .mp4 with masked span(s) - audio keeps
  flowing, target word ducked+garbled, everything
  else byte-identical
```

### Recommended Project Structure
```
scripts/
├── profanity.py          # NEW - detection: load_wordlist, normalize_word,
│                          #        find_profane_spans, CLI subcommand
├── render.py              # EXTENDED - build_profanity_mask_filter (new),
│                          #             build_audio_filter_chain (extended),
│                          #             render_clip (reads profanity_spans)
├── config.py               # EXTENDED - ProfanityConfig dataclass
data/
├── profanity_wordlist.yaml # NEW - committed, generic RU+EN stems (mirrors
│                          #        data/monetization_rules.yaml)
tests/
├── test_profanity.py       # NEW - mirrors test_monetization_risk.py shape
```

### Pattern 1: Time-windowed duck+garble in a single-input `-af` chain (live-verified)

**What:** A comma-joined ffmpeg filter clause that applies a volume duck plus two "garble" effects (`bandreject`, `tremolo`), each gated by the same `enable` timeline expression, so the effect is active only during the named span(s) and the filter passes audio through completely unmodified everywhere else.

**When to use:** Any time one or more disjoint (non-contiguous) sub-spans of a clip's audio need masking, without touching the rest of the clip's audio and without introducing a second ffmpeg input.

**Composing multiple non-contiguous spans:** ffmpeg's `enable` option takes an arbitrary boolean-valued expression. `between(t,start,end)` returns 1/0; **summing** multiple `between()` terms with `+` produces an OR (any nonzero value is "true" to `enable`), so all spans for one clip are expressed as **one** `enable` expression per filter, not one filter node per span — this keeps the filter graph flat (3 filter nodes total, regardless of how many swear words are in the clip) rather than growing linearly with span count.

**Verified example** (ran against real `ffmpeg 8.1.2` on this machine, `-f lavfi` synthetic 8s sine-tone input, two spans `[2.0,2.4]` and `[5.0,5.6]`):
```bash
# Source: live-verified this session (D:\shorts-maker, ffmpeg 8.1.2-full_build)
ffmpeg -y -f lavfi -i "sine=frequency=440:duration=8" -af \
"afftdn=nr=6.0,loudnorm=I=-16:TP=-1.5:LRA=11,volume=enable='between(t,2.0,2.4)+between(t,5.0,5.6)':volume=0.12,bandreject=enable='between(t,2.0,2.4)+between(t,5.0,5.6)':f=1800:width_type=o:w=4,tremolo=enable='between(t,2.0,2.4)+between(t,5.0,5.6)':f=18:d=0.7,afade=t=out:st=7.5:d=0.5" \
-f null -
# returncode=0, no filter_complex/second input needed
```
Measured with `volumedetect` (`-af "atrim=start=X:end=Y,volumedetect"`, isolating the `volume` clause alone to demonstrate the duck in isolation):
- Baseline (no mask): `mean_volume: -21.1 dB`
- Inside a ducked window (`volume=0.1`, gated): `mean_volume: -33.3 dB` (~12dB quieter)
- Outside the window: `mean_volume: -21.1 dB` (byte-identical to baseline — confirms `enable=false` is a true bypass, not a muted/zeroed state)

**Ordering matters — insert the mask AFTER `loudnorm`, BEFORE `afade`:** `build_audio_filter_chain`'s existing docstring already establishes "denoise the raw signal first, normalize loudness on the cleaned signal, then fade last." The profanity mask must sit **after** `loudnorm`, not before: ffmpeg's single-pass `loudnorm` filter performs live *time-varying gain adjustment* toward its integrated-loudness target, and a duck applied *before* `loudnorm` risks being partially undone (loudnorm boosting the artificially-quiet window back toward the target loudness). Applying the mask after `loudnorm` guarantees the duck is the last word on that span's gain, with `afade` (only relevant at the clip's very tail) applied last exactly as today. Recommended order: `afftdn -> loudnorm -> profanity_mask -> afade`.

**Why `bandreject`+`tremolo`, not silence, not a clean beep (AUDIO-03):** `bandreject` centered in the speech-formant band (~1800Hz, wide Q) removes the frequency content speech-to-text models rely on most heavily for phoneme recognition, directly degrading STT transcribability — this is a stronger STT-defeat mechanism than loudness reduction alone. `tremolo` adds amplitude-modulated warble, which reads perceptually as "garbled"/processed rather than a jump-cut edit, satisfying D-03's "doesn't read as an obvious hard edit" requirement while the underlying duck (`volume=0.12`, ~-18dB) keeps something audible so the audio track never goes silent (AUDIO-02).

### Pattern 2: Clip-relative timestamp remap — reuse, don't reimplement

**What:** Profanity spans must be expressed in the same clip-relative (post-jumpcut-splice, if applicable) seconds that `render.py` already expects for `punch_zoom_at` and subtitle words — not in absolute source-file seconds.

**When to use:** Always — this is not optional. A span computed in absolute source time and fed directly into `build_profanity_mask_filter` would mask the wrong part of the rendered clip (or nothing at all) whenever `-ss` trimming or jump-cut splicing shifts the timeline.

**Existing mechanism to reuse (verified by reading `scripts/jumpcuts.py`):**
```python
# Source: scripts/jumpcuts.py (existing, unmodified)
def remap_timestamp(t: float, keep_segments: list[tuple[float, float]]) -> float | None:
    """Maps an absolute source-file timestamp onto the spliced (concatenated)
    output timeline built from keep_segments... Returns None when t falls
    inside a cut gap."""

def remap_words(words: list[dict], keep_segments: list[tuple[float, float]]) -> list[dict]:
    """... A word is dropped if either endpoint falls inside a cut gap - it
    no longer exists in the rendered output."""
```
`SKILL.md` step 5's subtitle-building bullet already calls this exact function (`python scripts/jumpcuts.py remap-words <words_absolute.json> <keep.json> <words.json>`) to convert absolute Whisper word timestamps into clip-relative ones, dropping any word that fell inside a cut pause. **Profanity detection should run on that identical output** — either the same `_words.json` file (if `config.subtitles.enabled` and this clip already built one) or an independently-built one (if subtitles are off; profanity masking must not depend on subtitles being enabled, since they are separate, independently-toggleable optional features per D-04).

For a clip with no `keep_segments` (no jump cuts), the simpler existing rule applies instead (also already established in `SKILL.md` step 5): `render.py` seeks with `-ss` before `-i`, so word timestamps are clip-relative time = `absolute_time - clip_start`.

For a **compilation** entry (Phase 5's `"type": "compilation"`, `segments` list, D-06 "decided once per compilation"), the same reuse applies at the compilation level: `SKILL.md` step 5b bullet 7 already builds one combined `_words.json` for the whole compilation via `remap-words` against the flattened cross-member segment list. Profanity spans for a compilation are therefore a **top-level** field on the compilation plan entry (sibling to `boundary_transitions`/`punch_zoom_at`), computed once against that same flattened, already-remapped words file — never per-member.

**Consequence for jumpcut interaction (answers the "do swear spans need remapping through jumpcut keep-segments" question directly): yes, identically to subtitles, and for free** — because detection runs on the *already remapped* word list, a swear word whose Whisper timestamp fell inside a cut pause is simply **absent** from the list the detector sees (jumpcuts.py already dropped it). No separate jump-cut-awareness logic is needed inside `scripts/profanity.py` itself.

### Anti-Patterns to Avoid
- **Running detection on absolute source-file timestamps and feeding them straight to `render.py`:** produces spans that mask the wrong audio (or nothing) whenever `-ss` trimming or jump-cut splicing has occurred. Always detect on the clip-relative, post-remap word list.
- **Reimplementing the absolute-to-clip-relative remap inside `scripts/profanity.py`:** duplicates `jumpcuts.py::remap_words` logic and risks drifting out of sync with the jump-cut splice semantics (dropped-word handling, elapsed-time accumulation) that module already gets right.
- **Enumerating every obfuscated spelling as a literal wordlist entry:** unbounded, doesn't generalize. Normalize the token (case-fold, leetspeak-substitute, collapse repeated characters), then match the normalized token against a small set of stems.
- **Using `enable=` to try to silence the *noise* source outside its window:** `enable=false` means "bypass this filter, pass the input through unchanged" — for a filter whose *unmodified* signal is full-volume noise (e.g. `anoisesrc` piped through a `volume` filter), gating with `enable` would leave the noise **audible everywhere**, not muted (see Common Pitfalls > Pitfall 4 for the live-reproduced failure and the fix). Not applicable to the recommended Pattern 1 approach (no separate noise source at all), but critical to know if a future iteration adds a true synthetic-noise layer via `filter_complex`+`amix`.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Absolute-to-clip-relative timestamp conversion | A second, parallel remap function inside `scripts/profanity.py` | `scripts/jumpcuts.py::remap_words`/`remap_timestamp` (existing, unmodified) | Already correctly handles jump-cut-dropped words and elapsed-time accumulation; a second implementation is a maintenance/drift risk for zero benefit |
| Time-windowed audio effects | A custom audio DSP routine in Python (e.g. via `numpy`/`pydub`, decoding and re-encoding PCM manually) | ffmpeg's built-in timeline (`enable`) filter support (`volume`, `bandreject`, `tremolo`, etc.) | ffmpeg already does this natively, in the compiled binary the project already depends on, with zero new Python audio-processing dependencies; hand-rolling PCM manipulation would need a new heavy dependency (`numpy`/`scipy`/`pydub`) this project doesn't currently have |
| Obfuscated-spelling matching | Character-level fuzzy/edit-distance matching (Levenshtein, etc.) against a swear-word dictionary | Deterministic stem regex (`\b<root>\w*`) over a normalized token (lowercase, leetspeak-substituted, repeated-char-collapsed) | Explicitly ruled out per D-02/MONET-02 precedent; fuzzy matching also has unpredictable false-positive behavior that a deterministic feature shouldn't have |

**Key insight:** every piece this phase needs already exists in the codebase or in the ffmpeg binary the project already depends on — the actual net-new work is small and glue-shaped (one new script, one new config section, two new render.py functions, one new PLAN.json field), not infrastructure-shaped.

## Common Pitfalls

### Pitfall 1: Stem matching inside an unrelated word (false positive)
**What goes wrong:** A profanity stem (e.g. Russian `бл`) appears as a substring inside a completely unrelated word (e.g. `облако` — "cloud" — contains `бл`).
**Why it happens:** Naive substring matching (`"бл" in word`) has no concept of word boundaries.
**How to avoid:** Use Python's `re` with `\b` word-boundary anchors: `re.compile(r'\bбл\w*', re.IGNORECASE)`. **Live-verified this session** (Python 3, default `str` pattern — Unicode word-boundary detection works correctly for Cyrillic out of the box, no `re.UNICODE` flag needed, since it's the default for `str` patterns in Python 3):
```python
# Source: live-verified this session
import re
pattern = re.compile(r'\bбля\w*', re.IGNORECASE)
pattern.search("облако")       # None  (не в начале слова)
pattern.search("таблица")      # None  (не в начале слова)
pattern.search("бляха-муха")   # match (word boundary at hyphen)
pattern.search("бля")          # match
```
Since detection runs **per Whisper word token** (not per raw joined text, unlike `monetization_risk.py`), the boundary problem is actually smaller here than it looks: Whisper already segments the transcript into discrete word tokens, so testing `\broot\w*` against one token at a time (after stripping leading/trailing punctuation, matching `scripts/subtitles.py::strip_display_punctuation`'s existing approach) is enough — there's no risk of a stem inside a *different* word being picked up mid-sentence, only inside the *same* token, which `\b` handles correctly as shown above.
**Warning signs:** Unexpectedly high match counts on a clean transcript; spot-check a sample of matched words during Wave 0 test-writing.

### Pitfall 2: Whisper word-timestamp drift/precision
**What goes wrong:** A masked span computed from Whisper's own `start`/`end` word timestamps clips the very onset or tail of the actual spoken word, leaving an audible unmasked fragment (e.g. the first consonant of the swear word plays before the mask engages).
**Why it happens:** [CITED: whisper-timestamped / CrisperWhisper research] Whisper's DTW cross-attention-based word alignment is not sample-accurate — published comparisons show word-boundary drift on the order of **100-400ms** between different Whisper-family alignment approaches, and evaluation studies commonly use a 200ms collar as "correct" for word-segmentation scoring. This is inherent to how word timestamps are derived (cross-attention alignment, not a forced-aligner), not specific to `faster-whisper`.
**How to avoid:** Pad every detected span by a fixed buffer on each side before masking (e.g. `pad_seconds: 0.08`-`0.12`, i.e. 80-120ms) as a config-tunable value on `ProfanityConfig`, clamped to `[0, clip_duration]`. Merge any two padded spans that now overlap/touch into a single span before building the filter (keeps the filter graph flat and avoids a redundant duplicate `between()` term). This is a starting point — D-03 already calls for empirical validation against a real clip during implementation; treat the exact pad value as tunable, not fixed.
**Warning signs:** A masked clip where the very start or end of the target word is still faintly audible/legible on playback.

### Pitfall 3: Whisper mis-transcribes exactly the words this feature needs to catch
**What goes wrong:** `SKILL.md` step 5 already documents (verbatim, existing text): *"Whisper garbles words, especially on fast/profane/slang speech"* — meaning the transcript text this phase pattern-matches against is disproportionately likely to be wrong for the exact words it's trying to detect.
**Why it happens:** Whisper's training data has known biases around profanity (softening/mis-transcribing it), and profanity is also disproportionately represented in fast/slurred/emphatic speech, which is harder to transcribe accurately in general.
**How to avoid:** `SKILL.md`'s existing "Correct obviously mis-transcribed words" proofreading bullet (part of the subtitles-building step) is a semantic, human-in-the-loop-via-Claude correction pass — genuinely useful here, but currently only runs when `config.subtitles.enabled` is `true`. There is **no fully deterministic Python fix** for this within D-02's "no LLM-nuance tier" scope — this is a real, honest recall limitation of the feature, not a solved problem. Document it as an Open Question / known limitation rather than pretending detection is complete. Recommendation for the plan: when both `subtitles.enabled` and `profanity.enabled` are true, run profanity detection on the *corrected* words file (after the proofreading pass) for better recall; when subtitles are off, detection runs on raw (uncorrected) Whisper words — functional, but may under-detect Whisper-garbled instances.
**Warning signs:** A clip known (by the human reviewer) to contain profanity that the pipeline didn't flag — check whether the transcript text for that span actually matches the spoken word before assuming the wordlist itself is incomplete.

### Pitfall 4: Gating a synthetic noise source with `enable=` mutes it backwards (only relevant if a future iteration adds true noise-mixing)
**What goes wrong:** Using `enable='between(t,...)'` on a filter applied to a synthetic noise source (e.g. `anoisesrc` piped through `volume`) to try to make the noise silent *outside* the masked window instead makes it **audible everywhere**, because `enable=false` means "bypass the filter" (pass the noise through unmodified, i.e. at full volume), not "apply the filter's off-state."
**Why it happens:** `enable` controls whether a filter *processes* its input at all for a given timestamp; it is not a per-filter on/off signal value. A filter's "bypassed" state is its **input unchanged**, not silence, and a raw noise source's unmodified state is full-volume noise.
**How to avoid — live-reproduced and fixed this session:**
```bash
# WRONG - noise passes through at full volume OUTSIDE the window too
# (enable=false means "bypass," not "mute")
anoisesrc=d=8:c=pink:a=0.4,volume=enable='between(t,2.0,2.4)':volume=1.0

# RIGHT - always-active filter, time-varying volume EXPRESSION (not enable)
anoisesrc=d=8:c=pink:a=0.4,volume=eval=frame:volume='if(between(t\,2.0\,2.4)\,1\,0)'
```
Measured: with the WRONG form, `mean_volume` *outside* the intended window rose from a -21.1dB baseline to -18.8dB (noise leaking in) with `max_volume` jumping from -18.1dB to -8.1dB (clipping risk). With the RIGHT form (`eval=frame` + an `if()` expression evaluated per-frame instead of `enable`), the outside-window measurement matched the -21.1dB baseline exactly.
**Not applicable to the recommended Pattern 1** (no synthetic noise source at all — `bandreject`+`tremolo` operate directly on the existing signal, both correctly time-gated via `enable` since their *bypassed* state genuinely is "pass the original word through," which is the semantics `enable` provides). Documented here because it's a real, easy-to-hit trap if a future iteration adds a literal noise-burst layer via `filter_complex`+`amix`, and because ffmpeg's own `-h filter=X` output does not make this distinction obvious.
**Warning signs:** A masked clip where the "quiet" parts of the clip (outside any detected profanity span) sound noticeably noisier/hissier than an unmasked render of the same clip.

### Pitfall 5: Filter-graph size scaling with the number of masked spans
**What goes wrong:** A clip with an unusually large number of matched spans (pathological wordlist, normalization bug producing false-positive floods, or a genuinely very sweary clip) could, in principle, produce a very long `enable` expression string.
**Why it happens:** Pattern 1's OR-composition (`between(t,s1,e1)+between(t,s2,e2)+...`) keeps filter *node* count constant (3 filters regardless of span count) but the `enable` expression string itself still grows linearly with span count.
**How to avoid:** In practice this is a non-issue at realistic scale (a 30-60s clip has, at most, a handful of profanity instances) — Windows argv length limits (~32K chars) and ffmpeg's own expression parser are both far larger than any realistic span count would produce. As a cheap defensive measure, add a `max_masked_spans_per_clip` config knob (e.g. default 40) and fail-open (skip masking, warn, continue rendering) if exceeded, consistent with the project's established fail-open discipline — never let an edge case in this optional feature block rendering.
**Warning signs:** Not expected in normal operation; only relevant as a defensive cap, not an anticipated real failure.

## Code Examples

### Wordlist format (`data/profanity_wordlist.yaml`)
```yaml
# Source: this session's design, mirroring data/monetization_rules.yaml's
# existing committed-data-file convention (generic policy/wordlist data,
# zero channel-specific content -> safe to commit, per Plan 01-01 precedent).
updated: "2026-07-11"

# Applied to each Whisper word token BEFORE stem matching (case-fold first,
# then substitute, then collapse repeats) - this is what makes "common
# obfuscated spellings" (D-02) tractable without enumerating every variant.
normalize:
  substitutions:
    "0": "о"
    "3": "е"
    "1": "и"
    "4": "ч"
    "@": "а"
    "$": "с"
  collapse_repeats: true   # "бляяя"/"fuuuuck" -> "бля"/"fuck" (run of 3+ same char -> 1)
  strip_chars: "*_-."      # user-typed censoring chars stripped before matching

ru:
  - root: "бля"
  - root: "хуй"
  - root: "хер"
  - root: "пизд"
  - root: "еба"
  - root: "сук"      # NOTE: broad stem - validate against real transcripts for
                      # false positives (e.g. "сука" true positive vs some
                      # unrelated declension) during Wave 0 test-writing
en:
  - root: "fuck"
  - root: "shit"
  - root: "bitch"
  - root: "asshole"
```

### Detection module shape (`scripts/profanity.py`)
```python
# Source: this session's design, mirroring scripts/monetization_risk.py's
# fail-open load_rules() shape and re.compile/re.escape usage exactly.
from __future__ import annotations

import re
from pathlib import Path

import yaml

_REPEAT_RE_CACHE: dict[str, re.Pattern] = {}


def load_wordlist(path: str) -> dict:
    """Fail-open YAML load - missing/malformed file -> empty wordlist
    (no masking applied), never raises. Mirrors monetization_risk.load_rules."""
    try:
        raw = Path(path).read_text(encoding="utf-8")
        data = yaml.safe_load(raw) or {}
    except Exception as error:
        print(f"[warn] could not load profanity wordlist from {path} ({error}); "
              "continuing with an empty wordlist (no masking will be applied)",
              file=__import__("sys").stderr)
        return {"updated": "unknown", "normalize": {}, "ru": [], "en": []}
    data.setdefault("updated", "unknown")
    return data


def normalize_word(word: str, normalize_cfg: dict) -> str:
    text = word.lower()
    for src, dst in (normalize_cfg.get("substitutions") or {}).items():
        text = text.replace(src, dst)
    strip_chars = normalize_cfg.get("strip_chars", "")
    if strip_chars:
        text = re.sub(f"[{re.escape(strip_chars)}]", "", text)
    if normalize_cfg.get("collapse_repeats", False):
        text = re.sub(r"(.)\1{2,}", r"\1", text)
    return text


def compile_patterns(wordlist: dict) -> list[re.Pattern]:
    roots = [entry["root"] for lang in ("ru", "en") for entry in wordlist.get(lang, [])]
    # re.escape() every root - literal stems only, no raw regex from the
    # data file, so a malformed wordlist entry can never cause catastrophic
    # backtracking (V5 Input Validation / ReDoS guard).
    return [re.compile(rf"\b{re.escape(root)}\w*", re.IGNORECASE) for root in roots]


def find_profane_spans(
    words: list[dict], wordlist: dict, pad_seconds: float = 0.08,
    clip_duration: float | None = None,
) -> list[tuple[float, float]]:
    """words: clip-relative {"word","start","end"} list (already remapped
    through jumpcuts.remap_words if applicable - see 07-RESEARCH.md Pattern 2).
    Returns merged, padded, clip-bound-clamped (start,end) spans."""
    normalize_cfg = wordlist.get("normalize") or {}
    patterns = compile_patterns(wordlist)

    raw_spans: list[tuple[float, float]] = []
    for word in words:
        token = normalize_word(word["word"].strip(".,!?:;\"'()"), normalize_cfg)
        if any(pattern.search(token) for pattern in patterns):
            start = max(0.0, word["start"] - pad_seconds)
            end = word["end"] + pad_seconds
            if clip_duration is not None:
                end = min(end, clip_duration)
            raw_spans.append((round(start, 3), round(end, 3)))

    if not raw_spans:
        return []

    raw_spans.sort()
    merged = [raw_spans[0]]
    for start, end in raw_spans[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged
```

### `render.py` additions (pure builder, no subprocess)
```python
# Source: this session's design, mirroring build_punch_zoom_filter's
# validate-then-build shape exactly (RenderError on bad input, one
# self-contained string returned, no side effects).
def build_profanity_mask_filter(
    spans: list[tuple[float, float]],
    duck_volume: float = 0.12,
    garble_freq: float = 1800.0,
    garble_width_octaves: float = 4.0,
    warble_freq: float = 18.0,
    warble_depth: float = 0.7,
) -> str | None:
    if not spans:
        return None
    if not (0.0 < duck_volume < 1.0):
        raise RenderError(f"duck_volume must be between 0 and 1 (exclusive), got {duck_volume}")
    for start, end in spans:
        if start < 0 or end <= start:
            raise RenderError(f"invalid profanity span ({start}, {end})")

    enable_expr = "+".join(f"between(t,{start},{end})" for start, end in spans)
    return (
        f"volume=enable='{enable_expr}':volume={duck_volume},"
        f"bandreject=enable='{enable_expr}':f={garble_freq}:width_type=o:w={garble_width_octaves},"
        f"tremolo=enable='{enable_expr}':f={warble_freq}:d={warble_depth}"
    )


def build_audio_filter_chain(
    denoise: bool, loudnorm: bool, fade_filter: str | None, denoise_strength: float = 6.0,
    profanity_filter: str | None = None,   # NEW optional param
) -> str | None:
    """Order: denoise -> loudnorm -> profanity mask -> fade (see 07-RESEARCH.md
    Pattern 1 "Ordering matters" - the mask must come after loudnorm so
    loudnorm's own gain-riding can't partially undo the duck)."""
    filters = []
    if denoise:
        filters.append(f"afftdn=nr={denoise_strength}")
    if loudnorm:
        filters.append("loudnorm=I=-16:TP=-1.5:LRA=11")
    if profanity_filter:
        filters.append(profanity_filter)
    if fade_filter:
        filters.append(fade_filter)
    return ",".join(filters) if filters else None
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| N/A - `render.py`'s audio filter chain has never had a sub-span (time-windowed) filter before this phase; every existing filter (`afftdn`/`loudnorm`/`afade`) is whole-clip | This phase introduces the codebase's first timeline (`enable`)-gated filters | This phase | Establishes a reusable pattern (`enable='between(t,...)+...'`) any future phase needing sub-span audio/video effects can reuse — e.g. `build_punch_zoom_filter`/`build_video_effects_chain`'s video-side equivalents don't yet use timeline gating, but could |

**Deprecated/outdated:** Nothing in this codebase is being replaced by this phase — it is purely additive.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Exact duck volume (0.12), `bandreject` center frequency (1800Hz)/width (4 octaves), and `tremolo` frequency (18Hz)/depth (0.7) are reasonable *starting* values | Standard Stack, Code Examples | Low — D-03 already explicitly requires empirical validation against a real rendered clip during implementation; these are documented as tunable starting points, not final values. If wrong, the mask either sounds too audible (fails AUDIO-03) or too aggressive/obviously edited (fails D-03's "doesn't read as an obvious hard edit") — both are cheap to detect by listening to one real render and adjusting the constants |
| A2 | Whisper word-timestamp drift is commonly in the 100-400ms range | Common Pitfalls > Pitfall 2 | Medium — sourced from external research on Whisper-family DTW alignment generally, not measured against this project's own `faster-whisper` model/settings specifically. If this project's actual drift is smaller, the recommended 80-120ms pad is conservative (harmless, slightly wider mask than strictly needed); if larger, some masks may clip the word's onset/tail — mitigated by treating pad_seconds as a tunable config value, not a hardcoded constant |
| A3 | A `bandreject` centered around ~1800Hz with a wide (4-octave) width meaningfully degrades platform STT recognizability of the masked word | Architecture Patterns > Pattern 1 | Medium — reasoned from general knowledge that STT relies heavily on speech-formant frequency content, not verified against an actual platform moderation pass (impossible to test directly - no phase can call a real platform's private STT pipeline). Mitigated by the Validation Architecture section's self-check recommendation: re-run the masked span through this project's own `faster-whisper` model and assert it no longer transcribes to the original word - a real, automatable proxy for "an STT system can't read this cleanly" even though it can't guarantee behavior of any specific platform's proprietary moderation model |
| A4 | Detection on raw (uncorrected) Whisper words, when subtitles are disabled, is an acceptable recall tradeoff rather than a blocking gap | Common Pitfalls > Pitfall 3 | Low-Medium — this is a real, disclosed limitation, not a hidden one; if the user considers under-detection unacceptable, the planner/discuss-phase should surface whether profanity masking should *require* `subtitles.enabled` (forcing the correction pass) rather than being fully independent — CONTEXT.md currently treats them as independent toggles with no stated dependency |

**If this table is empty:** N/A — assumptions listed above.

## Open Questions

1. **Should `config.profanity.enabled` require `config.subtitles.enabled` to get the benefit of the word-correction proofreading pass (Pitfall 3), or stay fully independent as CONTEXT.md's D-04 implies?**
   - What we know: Whisper measurably mis-transcribes exactly the words this feature targets (`SKILL.md`'s own existing text says so). The only existing correction mechanism is coupled to the subtitles-building step.
   - What's unclear: whether the user considers this an acceptable, disclosed limitation (ship independent, document the gap) or wants stronger detection at the cost of coupling two currently-independent optional features.
   - Recommendation: ship independent (matches D-04's framing, keeps blast radius minimal), but the plan should document the recall gap explicitly in code comments/README, not silently.

2. **Exact duck/garble parameter values (A1) — final tuning needs a real clip.**
   - What we know: the filter mechanics work (live-verified); starting values are reasoned from ffmpeg filter semantics (formant-band rejection, warble depth).
   - What's unclear: whether these specific values sound "hard to make out but not silent, garbled but not obviously edited" on a real clip with real speech (as opposed to a synthetic sine-tone test signal).
   - Recommendation: the plan should include an explicit manual-listening checkpoint (`checkpoint:human-verify` or equivalent) against a real rendered masked clip before considering AUDIO-03 satisfied — this mirrors D-03's own explicit instruction.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `ffmpeg`/`ffprobe` on PATH | Filter graph execution (all of AUDIO-01/02/03) | ✓ (verified this session) | 8.1.2-full_build (Gyan.FFmpeg) | N/A — already a hard project dependency (`README.md`, `scripts/setup.py`) |
| `ffmpeg`'s `volume`/`bandreject`/`tremolo` filters with timeline (`enable`) support | Pattern 1 | ✓ (verified this session via `ffmpeg -h filter=X`) | Present in 8.1.2 build (`--enable-*` flags don't gate these — they're core `libavfilter` filters) | None needed |
| Python `re`/`yaml` (stdlib/existing dep) | `scripts/profanity.py` | ✓ | stdlib / `PyYAML>=6.0` (existing) | None needed |

**Missing dependencies with no fallback:** none.
**Missing dependencies with fallback:** none — everything this phase needs is already present and verified working on this development machine.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | `pytest>=7.4.0` (`requirements-dev.txt`) |
| Config file | `pyproject.toml` (`[tool.pytest.ini_options]`: `pythonpath=["."]`, `testpaths=["tests"]`, `integration` marker) |
| Quick run command | `pytest -m "not integration" tests/test_profanity.py tests/test_render.py -x` |
| Full suite command | `pytest tests/ -x` (includes `integration`-marked real-ffmpeg smoke tests, which self-skip if `ffmpeg`/`ffprobe` aren't on PATH) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| AUDIO-01 | `find_profane_spans` correctly matches RU/EN stems, obfuscated spellings, and rejects false-positive substrings (Pitfall 1) | unit | `pytest tests/test_profanity.py -k detect -x` | ❌ Wave 0 |
| AUDIO-01 | Detected spans survive `jumpcuts.remap_words` correctly (a word cut by a jump-cut gap is silently absent, per Pattern 2) | unit | `pytest tests/test_profanity.py -k remap -x` | ❌ Wave 0 |
| AUDIO-02 | `build_profanity_mask_filter` produces the expected `enable`-gated clause string (exact-string assertion, mirrors `test_build_ffmpeg_command_denoise_only`'s pattern) | unit | `pytest tests/test_render.py -k profanity_mask_filter -x` | ❌ Wave 0 |
| AUDIO-02 | `build_audio_filter_chain` inserts the mask clause in the correct order (after `loudnorm`, before `afade`) | unit | `pytest tests/test_render.py -k profanity_filter_chain_order -x` | ❌ Wave 0 |
| AUDIO-02 | A rendered clip with `profanity_spans` set actually has measurably lower loudness inside the span vs. outside (real ffmpeg, `volumedetect`-based) | integration | `pytest tests/test_integration_ffmpeg.py -k profanity -m integration -x` | ❌ Wave 0 |
| AUDIO-03 | The masked span, re-transcribed via this project's own `faster-whisper` model, no longer recognizably transcribes to the original word (self-check proxy for "defeats STT") | integration (slow) | `pytest tests/test_integration_ffmpeg.py -k profanity_defeats_transcription -m integration -x` | ❌ Wave 0 (optional — see Sampling Rate) |

### Sampling Rate
- **Per task commit:** `pytest -m "not integration" tests/test_profanity.py tests/test_render.py tests/test_config.py -x` (fast, mocked/string-assertion tests only — mirrors `test_build_ffmpeg_command_*`'s existing style)
- **Per wave merge:** Full suite including `integration`-marked real-ffmpeg tests: `pytest tests/ -x` — the `volumedetect`-based loudness-difference assertion is cheap (sub-second synthetic audio, same technique live-verified in this research session) and should run every wave merge
- **Phase gate:** Full suite green before `/gsd-verify-work`. The `faster-whisper` self-transcription check (AUDIO-03's strongest available automated proxy) is comparatively slow (loads a real Whisper model) — mark it `integration` and consider running it only at the phase gate, not every wave merge, per the project's existing `integration` marker convention (`test_integration_ffmpeg.py`'s own docstring: "slower, needs ffmpeg on PATH")

### Wave 0 Gaps
- [ ] `tests/test_profanity.py` — covers AUDIO-01 (new file, mirrors `tests/test_monetization_risk.py`'s structure: `load_wordlist` fail-open behavior, `normalize_word` obfuscation cases, `find_profane_spans` boundary/merge/padding logic)
- [ ] `tests/test_render.py` additions — covers AUDIO-02 (`build_profanity_mask_filter` string-assertion tests, `build_audio_filter_chain` ordering test, `render_clip` reading `plan_entry["profanity_spans"]`)
- [ ] `tests/test_integration_ffmpeg.py` additions — covers AUDIO-02/AUDIO-03 (real-ffmpeg loudness-delta assertion via `volumedetect`, using the exact technique live-verified in this research session; optionally a `faster-whisper` self-transcription check for AUDIO-03, gated behind the `integration` marker like the rest of the file)
- [ ] `tests/test_config.py` additions — `ProfanityConfig` dataclass validation (mirrors existing `DiarizationConfig`/`AudioEnergyConfig` test coverage)
- [ ] No framework install needed — `pytest`/`PyYAML` already present

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | N/A — local batch CLI, no auth surface touched by this phase |
| V3 Session Management | No | N/A |
| V4 Access Control | No | N/A |
| V5 Input Validation | Yes | Wordlist `root` entries must always be passed through `re.escape()` before compiling (see Code Examples `compile_patterns`) — never compile a data-file-supplied string as a raw regex fragment. This is a deliberate simplification vs. `monetization_risk.py` (which also only ever calls `re.escape(keyword.lower())`, same precedent) and closes off ReDoS risk from a malformed/malicious `data/profanity_wordlist.yaml` edit entirely, at the cost of not supporting arbitrary regex syntax in the wordlist (acceptable — D-02 only asks for stem/obfuscation support, not full regex) |
| V6 Cryptography | No | N/A — no secrets/crypto touched by this phase |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Malformed/malicious `data/profanity_wordlist.yaml` causing a regex-compile crash or catastrophic backtracking (ReDoS) | Tampering / Denial of Service | Fail-open YAML load (mirrors `monetization_risk.load_rules` — malformed file -> empty wordlist, warn, continue, never raise) **and** always `re.escape()` every `root` value before compiling — no raw-regex escape hatch from the data file (see V5 row above) |
| Pathologically many matched spans in one clip producing an oversized `enable` expression string | Denial of Service (resource exhaustion / render failure) | `max_masked_spans_per_clip` config cap, fail-open skip+warn if exceeded (Pitfall 5) — never let this optional feature block rendering |
| Committing the wordlist itself to a public/shared repo | Information Disclosure (mild — reputational/content-sensitivity, not a security vulnerability) | Same footing as `data/monetization_rules.yaml`'s existing precedent: this is generic, non-channel-specific policy/wordlist data (a list of common swear-word stems, not private user data), so committing it follows the exact same established convention — no new risk class introduced. Worth a one-line note in the PR/commit message given the content is more visually "loud" than the monetization ruleset's neutral category names, but not a reason to deviate from the existing commit-data-files convention |

## Sources

### Primary (HIGH confidence — verified this session)
- `D:\shorts-maker\scripts\render.py` — read directly, `build_audio_filter_chain`/`build_ffmpeg_command`/`build_jumpcut_command`/`build_compilation_command`/`render_clip` structure and existing filter-order rationale
- `D:\shorts-maker\scripts\jumpcuts.py` — read directly, `remap_timestamp`/`remap_words`/`compute_keep_segments` shape
- `D:\shorts-maker\scripts\monetization_risk.py` — read directly, fail-open `load_rules`/`score_transcript` shape
- `D:\shorts-maker\scripts\subtitles.py`, `scripts/config.py`, `scripts/transcribe.py`, `scripts/metadata.py`, `data/monetization_rules.yaml`, `.claude/skills/make-shorts/SKILL.md` (steps 1-6, 5b) — read directly
- Live ffmpeg 8.1.2 execution on this machine — `-h filter=volume`/`bandreject`/`anoisesrc`/`tremolo`/`amix` (confirmed timeline/`enable` support), a full synthetic-audio filter-chain run (`-af "afftdn,loudnorm,volume+bandreject+tremolo(enable=...),afade"`, returncode 0), and `volumedetect`-based before/after loudness measurements proving the time-windowed gating works exactly as specified and leaves the rest of the signal untouched
- Live Python 3 `re` execution on this machine — confirmed `\b` word-boundary matching correctly rejects a stem match inside an unrelated Cyrillic word, and confirmed the normalization pre-pass (leetspeak substitution + repeated-character collapse) design compiles and runs

### Secondary (MEDIUM confidence)
- [CrisperWhisper: Accurate Timestamps on Verbatim Speech Transcriptions](https://arxiv.org/html/2408.16589v1) — word-timestamp drift/precision figures for Whisper-family DTW alignment (100-400ms range, 200ms evaluation collar)
- [linto-ai/whisper-timestamped GitHub](https://github.com/linto-ai/whisper-timestamped) — general Whisper word-timestamp precision characterization

### Tertiary (LOW confidence)
- None used directly in a load-bearing claim — all filter-mechanics claims were live-verified rather than taken from unverified secondary sources.

## Metadata

**Confidence breakdown:**
- Standard stack (no new deps): HIGH — nothing to verify beyond what's already installed and working
- Architecture / ffmpeg filter mechanics: HIGH — live-verified against the real binary, not just documentation
- Timestamp remap / jumpcut interaction: HIGH — read directly from existing, tested code (`jumpcuts.py`, `SKILL.md`)
- Pitfalls (false positives, filter-graph pitfalls): HIGH — live-reproduced
- Pitfalls (Whisper timestamp drift magnitude): MEDIUM — external research, not this project's own measurement
- Exact duck/garble parameter values: MEDIUM — functionally verified to work; final tuning explicitly deferred to empirical validation per D-03

**Research date:** 2026-07-11
**Valid until:** ffmpeg filter mechanics are stable/long-lived (not fast-moving) — 90 days is reasonable for the filter-graph findings; the Whisper-timestamp-precision secondary sources should be treated as directional, not re-verified per-phase
