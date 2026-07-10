---
phase: 05-sub-threshold-highlight-compilation
reviewed: 2026-07-10T00:00:00Z
depth: standard
files_reviewed: 10
files_reviewed_list:
  - .claude/skills/make-shorts/SKILL.md
  - scripts/candidates.py
  - scripts/compilation.py
  - scripts/config.py
  - scripts/render.py
  - tests/test_candidates.py
  - tests/test_compilation.py
  - tests/test_config.py
  - tests/test_integration_ffmpeg.py
  - tests/test_render.py
findings:
  critical: 1
  warning: 4
  info: 0
  total: 5
status: issues_found
---

# Phase 05: Code Review Report

**Reviewed:** 2026-07-10T00:00:00Z
**Depth:** standard
**Files Reviewed:** 10
**Status:** issues_found

## Summary

Reviewed the full Phase 05 changeset: sub-threshold candidate tagging fields (`candidates.py`), the mechanical compilation-entry validator/builder (`compilation.py`), the multi-input compilation ffmpeg command builder (`render.py`), the new `compilation_max_seconds` config knob, and the `SKILL.md` orchestration wiring that ties all of it together. Ran the full unit suite (181 tests, excluding the environment-broken `test_config.py`/`integration` runs caused by a non-ASCII Windows username in the default pytest tempdir, which is unrelated to this code and reproduced cleanly once `--basetemp` was pinned to an ASCII path).

The unit-level logic in `compilation.py` and `render.py` is well-tested and correct in isolation. The main defect found is a genuine contract break **between** `compilation.py`'s validation and the exact sequence `SKILL.md` instructs the orchestrator to follow: when a compilation's length-ceiling capping actually drops trailing (weakest) members — a supported, tested code path — and `config.transitions.enabled` is also on, building the compilation entry will always raise and abort, because the `boundary_transitions` array SKILL.md tells the orchestrator to compute is sized for the *pre-cap* segment list while `build_compilation_entry` validates it against the *post-cap* one. Verified this empirically (see finding CR-01). Three further findings cover documentation gaps in `SKILL.md`'s new compilation section and a couple of small robustness/duplication issues in the new code.

## Critical Issues

### CR-01: `build_compilation_entry` validates `boundary_transitions` against the post-cap segment list, but SKILL.md computes it pre-cap — length-ceiling capping + transitions always fails together

**File:** `scripts/compilation.py:62-94` (also `.claude/skills/make-shorts/SKILL.md:204-230`)

**Issue:** `build_compilation_entry`'s length-ceiling capping (D-04/D-05) walks `members` in strongest-first order and drops the weakest trailing members that would push the running total over `compilation_max_seconds`, producing a `fitted` list that can be shorter than `members` (this is a real, tested path — see `test_build_compilation_entry_caps_at_compilation_max_seconds_dropping_weakest`). The `boundary_transitions` length check that follows is computed from `flattened_segment_count` of the **fitted (post-cap)** list:

```python
flattened_segment_count = sum(
    len(member["keep_segments"]) if member.get("keep_segments") else 1 for member in fitted
)
if boundary_transitions is not None:
    expected_length = flattened_segment_count - 1
    if len(boundary_transitions) != expected_length:
        raise CompilationError(...)
```

But `SKILL.md` step 5b instructs building `boundary_transitions` *before* any capping ever happens: bullet 4 builds the flattened segment list from **all** group members, bullet 5 runs `select-transitions` against that full (uncapped) list, and only then does bullet 8 call `compilation.py`'s CLI — which is the very first place capping occurs. So whenever capping actually drops members, the `boundary_transitions` array handed to `build_compilation_entry` is longer than `expected_length`, and the call always raises `CompilationError`, blocking the whole compilation from being built. Reproduced directly:

```python
from scripts.compilation import build_compilation_entry
members = [
    {"video_stem": "mystream", "start": 0, "end": 60},
    {"video_stem": "mystream", "start": 100, "end": 160},
    {"video_stem": "mystream", "start": 200, "end": 260},
]
build_compilation_entry(members, 150, "zoom", boundary_transitions=["crossfade", "crossfade"])
# -> CompilationError: boundary_transitions must have length 1 (flattened segment count 2 - 1), got 2
```

Nothing in `compilation.py` or `SKILL.md` reconciles the two lists (e.g. truncating `boundary_transitions` to the fitted prefix — which would be valid, since capping only ever drops a contiguous trailing run of members, so the pre-cap boundary list's prefix is exactly the boundaries that survive). As written, any run that both enables `config.transitions.enabled` and produces a compilation group whose full uncapped duration exceeds `config.clip.compilation_max_seconds` will fail to build that compilation.

**Fix:** Either truncate the caller-supplied `boundary_transitions` to the fitted prefix inside `build_compilation_entry` (safe because capping only drops a trailing run):
```python
if boundary_transitions is not None:
    expected_length = flattened_segment_count - 1
    boundary_transitions = boundary_transitions[:expected_length]  # capping only drops the trailing run
```
or update `SKILL.md` step 5b to compute/recompute `select-transitions` *after* the orchestrator has determined which members will actually fit under `compilation_max_seconds` (duplicating `build_compilation_entry`'s own capping logic client-side, which is worse). The former is simpler and keeps the "no semantic judgment in Python" boundary intact.

## Warnings

### WR-01: SKILL.md step 9 references `groups.json`/`unmatched.json` that no earlier step instructs writing

**File:** `.claude/skills/make-shorts/SKILL.md:234` (and steps 1-8, lines 202-230)

**Issue:** Step 9's one-liner reads `work/<video_stem>/compilations/groups.json` and `work/<video_stem>/compilations/unmatched.json` as pre-existing inputs:
```
python -c "import json, scripts.candidates as c; c.append_compilation_sections_markdown('work/<video_stem>/CANDIDATES.md', json.load(open('work/<video_stem>/compilations/groups.json', ...)), json.load(open('work/<video_stem>/compilations/unmatched.json', ...)))"
```
Every other artifact this subsection touches (`<compilation_stem>_segments.json`, `<compilation_stem>_boundary.json`, `<compilation_stem>_members.json`, `<compilation_stem>_entry.json`) has an explicit "write it to `<path>`" instruction earlier in the same subsection. `groups.json`/`unmatched.json` do not — bullet 1 ("One-shot grouping pass") only describes the semantic judgment of forming groups and leaving some candidates unmatched, never says to persist that decision to these two file paths as the run progresses through the per-group loop (bullets 2-8). An orchestrating agent has to infer this bookkeeping step itself; if it doesn't (or picks different paths/shapes), step 9 fails with `FileNotFoundError` or silently reads stale data from a previous run.

**Fix:** Add an explicit instruction (e.g. at the end of bullet 1, or as its own bullet before bullet 9) telling the orchestrator to accumulate every group formed and every candidate left unmatched into `work/<video_stem>/compilations/groups.json` (list of `{"members": [...], "title": ...}`) and `work/<video_stem>/compilations/unmatched.json` (list of `{"start", "end", "reason", "tag"}`) as it works through the grouping pass, so step 9 has a concrete, always-present input.

### WR-02: Compilation karaoke-subtitle words file path is inferred by convention but never explicitly specified for compilations, risking silent feature loss

**File:** `scripts/render.py:905-921`, `.claude/skills/make-shorts/SKILL.md:224` (step 5b bullet 7)

**Issue:** `render_clip` derives the per-word karaoke JSON path purely from the `subtitles_path` stem:
```python
words_path = Path(subtitles_path).with_name(Path(subtitles_path).stem + "_words.json")
...
if words_path.exists():
    words = json.loads(words_path.read_text(encoding="utf-8"))
    cues = group_words_into_cues(...)
else:
    cues = parse_srt(Path(subtitles_path).read_text(encoding="utf-8"))
```
For a single clip, `SKILL.md` step 5 spells out the exact `remap-words` output path (`work/<video_stem>/subtitles/<clip_filename_stem>_words.json`) as a literal CLI argument, so the naming convention `render_clip` relies on is guaranteed. For a compilation, step 5b bullet 7 only says to "produce one clip-relative words file for the whole compilation" and "render the `.srt` via the existing `scripts/subtitles.py` call — the same invocation shape as a single clip" — it never gives the literal output path for the remapped words file the way the single-clip bullet does. If the orchestrator doesn't independently infer that the file must be named `<compilation_stem>_words.json` (matching the `.srt`'s own stem), `words_path.exists()` is `False` and `render_clip` silently falls back to the plain `.srt` parse — no error, no warning, just quietly losing the per-word highlight effect for every compilation.

**Fix:** Make the compilation bullet as explicit as the single-clip one, e.g. spell out `work/<video_stem>/compilations/<compilation_stem>_words.json` as the literal third argument to the `jumpcuts.py remap-words` call, matching the stem `naming.py`/`subtitles.py` will use for the `.srt`.

### WR-03: `append_compilation_sections_markdown` uses unchecked dict indexing instead of `.get()`, unlike the rest of the module

**File:** `scripts/candidates.py:97,107`

**Issue:**
```python
member_ids = ", ".join(f"#{member['id']}" for member in group["members"])
...
lines.append(f"- `{start_tc}` - `{end_tc}` — {candidate['reason']} (tag: {candidate['tag']})")
```
Every other dict-based field access in this module (`merge_candidates`) uses `.get(...)` with a sensible default, but this new function indexes `member['id']` and `candidate['tag']`/`['reason']` directly. This function's only caller is a hand-assembled `python -c` one-liner in `SKILL.md` (see WR-01) run by an LLM orchestrator, not a validated internal call site — a slightly malformed `groups.json`/`unmatched.json` (e.g. a group member dict missing `id`, or an unmatched candidate that somehow lacks `tag`) raises a bare, unhelpful `KeyError` instead of a clear error.

**Fix:** Use `.get("id", "?")` / `.get("tag", "?")` or raise a clear `ValueError` naming the missing field, consistent with `merge_candidates`'s defensive style elsewhere in the same file.

### WR-04: `_build_compilation_fold` duplicates `_build_transition_fold`'s accumulate loop almost verbatim

**File:** `scripts/render.py:626-704` (vs. `scripts/render.py:397-501`)

**Issue:** `_build_compilation_fold`'s own docstring states it "mirrors `_build_transition_fold`'s accumulate loop almost verbatim (same acc_v/acc_a accumulation, same `build_transition_filter` call, same `concat=n=2` downgrade line, same `acc_duration` formula, same last-resort d_eff-vs-acc_duration safety net)." Comparing the two loops (`scripts/render.py:470-501` and `scripts/render.py:679-704`) confirms this: roughly 25 lines of xfade-offset/safety-net arithmetic are duplicated with only the pre-computation of `effective_duration` differing between the two callers. Any future fix to this fold math (e.g. a rounding edge case in the offset calculation) has to be applied in two places by hand, and nothing enforces that they stay in sync.

**Fix:** Extract the shared accumulate loop (from `fold_stages = []` through the `return`) into one helper parameterized by `(durations, effective_duration, boundary_transitions)`, called by both `_build_transition_fold` and `_build_compilation_fold` after each computes its own `effective_duration` list.

---

_Reviewed: 2026-07-10T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
