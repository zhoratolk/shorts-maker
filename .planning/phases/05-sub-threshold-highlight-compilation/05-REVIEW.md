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
  critical: 0
  warning: 2
  info: 1
  total: 3
status: issues_found
---

# Phase 05: Code Review Report (re-review after gap-closure Plan 05-05)

**Reviewed:** 2026-07-10T00:00:00Z
**Depth:** standard
**Files Reviewed:** 10
**Status:** issues_found

## Summary

This is a re-review after Plan 05-05's gap-closure pass. Rather than trusting Plan 05-05's own claims, each prior finding was independently re-verified against the current code:

- **CR-01 (boundary_transitions validated against post-cap fitted list while SKILL.md computes it pre-cap) — confirmed fixed.** `build_compilation_entry` (`scripts/compilation.py:87-103`) now truncates an over-long `boundary_transitions` down to `flattened_segment_count - 1` before the length check, and still raises `CompilationError` when the (possibly-truncated) list is genuinely too short:
  ```python
  if len(boundary_transitions) > expected_length:
      boundary_transitions = boundary_transitions[:expected_length]
  if len(boundary_transitions) != expected_length:
      raise CompilationError(...)
  ```
  Traced the capping loop above it (`fitted` only ever drops a *contiguous trailing run* of `members`, walking strongest-first and never reordering or splitting mid-member) and confirmed truncate-from-the-end is index-correct: the pre-cap list's own prefix is exactly the boundary set that survives capping. `test_build_compilation_entry_caps_and_truncates_boundary_transitions` and `test_build_compilation_entry_still_rejects_too_short_boundary_transitions` (`tests/test_compilation.py:81-111`) both exercise this correctly, including the "must never pad, only shrink" case.
- **WR-01 (groups.json/unmatched.json read before any write instruction) — confirmed fixed.** SKILL.md bullet 9 (`.claude/skills/make-shorts/SKILL.md:236`) now explicitly says to accumulate both files "as bullets 1-8 above are worked through" and to "start each as `[]` before the first append if this run produces zero groups or zero unmatched candidates respectively, since `append_compilation_sections_markdown` below reads both unconditionally."
- **WR-02 (compilation words-file path inferred by convention) — confirmed fixed.** Bullet 7 (`.claude/skills/make-shorts/SKILL.md:224`) now spells out the literal path `work/<video_stem>/compilations/<compilation_stem>_words.json` as the explicit third argument to `remap-words`, matching the `.srt` stem `render_clip` derives its karaoke-words lookup from.
- **WR-03 (unchecked dict access in append_compilation_sections_markdown) — confirmed fixed** for every field that can legitimately be missing: `member.get('id', '?')`, `group.get('title', '(untitled compilation)')`, `candidate.get('reason', '(no reason given)')`, `candidate.get('tag', '(untagged)')` (`scripts/candidates.py:97,111-112`), exercised by `test_append_compilation_sections_markdown_defaults_missing_fields`. `start`/`end` remain required direct-key access by design (the test explicitly documents "`'start'/'end' stay required`"), which is a reasonable contract, not a regression.
- **WR-04 (fold-loop duplication between `_build_compilation_fold`/`_build_transition_fold` in render.py)** — confirmed still present, as expected; this was explicitly deferred by Plan 05-05 and is not re-flagged here as new.

Independent adversarial re-review of the full phase (all 5 plans' combined changes, not just the gap-closure diff) surfaced two new issues, both in `SKILL.md`'s own orchestration text rather than in the Python modules. The Python modules (`compilation.py`, `render.py`, `candidates.py`, `config.py`) held up well under tracing of the capping/truncation/fold-offset arithmetic and the fixed-vs-flattened segment bookkeeping between `compilation.py` and `render.py`'s `build_compilation_command`/`_build_compilation_fold`.

## Warnings

### WR-05: SKILL.md's compilation `PLAN.json` example is internally invalid — would raise both `CompilationError` and `RenderError` if used literally

**File:** `.claude/skills/make-shorts/SKILL.md:258-273`

**Issue:** The illustrative compilation entry shown for step 5b is broken in two independent, provable ways:

1. It sets `"crop_style": "pad"` together with `"punch_zoom_at": 3.1`. `render.py` explicitly rejects this combination:
   ```python
   if punch_zoom_at is not None and crop_style != "zoom":
       raise RenderError(
           f"punch_zoom_at requires crop_style='zoom' (got {crop_style!r}); ..."
       )
   ```
   (`scripts/render.py:895-904`), proven by `test_render_clip_rejects_punch_zoom_at_on_pad_crop_style` (`tests/test_render.py:814-827`).

2. Its `segments` list has 2 members: the first with no `keep_segments` (1 flattened segment) and the second with a 2-entry `keep_segments` (2 flattened segments) — 3 flattened segments total, requiring `boundary_transitions` of length 2 (`3 - 1`). The example's `boundary_transitions` has only 1 entry (`["crossfade"]`). This is the *exact* shape `build_compilation_entry` is unit-tested to reject:
   ```python
   members = [
       make_member("mystream", 0, 20),
       make_member("mystream", 30, 50, keep_segments=[[30, 35], [40, 50]]),
   ]
   with pytest.raises(CompilationError, match="boundary_transitions"):
       build_compilation_entry(members, 150, "zoom", boundary_transitions=["cut"])
   ```
   (`tests/test_compilation.py:68-79`).

Since `SKILL.md` is the literal orchestration script an agent pattern-matches against when constructing `PLAN.json` compilation entries, a broken reference example directly risks the agent reproducing one of these invalid combinations on a real run, failing at `build_compilation_entry` (step 5b bullet 8) or at `render_clip` (step 6) for exactly the "punch-zoom + pad" or "keep_segments + short boundary_transitions" cases the example exists to demonstrate.

**Fix:** Replace the example with an internally consistent one — e.g. keep `crop_style: "zoom"` if `punch_zoom_at` stays in the example (or drop `punch_zoom_at` from the `pad` example), and size `boundary_transitions` to match the flattened segment count implied by the shown `segments` (2 entries for the shown 3-flattened-segment case, or drop the second member's `keep_segments` to keep it a 1-boundary example).

### WR-06: SKILL.md step 5b never instructs writing `<compilation_stem>_members.json` before bullet 8 reads it

**File:** `.claude/skills/make-shorts/SKILL.md:230-234`

**Issue:** Step 5b bullet 8 invokes `scripts/compilation.py` against `work/<video_stem>/compilations/<compilation_stem>_members.json` and describes its required shape inline ("a JSON list of this group's members in strongest-first order, each `{"video_stem": ..., "start": ..., "end": ..., "keep_segments": [...]}`"), but no earlier bullet instructs constructing or writing this file. This is the same class of gap Plan 05-05 just fixed for `groups.json`/`unmatched.json` (WR-01) and mirrors the pattern bullet 4 already gets right for `_segments.json` ("Write it to `work/<video_stem>/compilations/<compilation_stem>_segments.json`") — but `_members.json` has no equivalent instruction anywhere in bullets 1-8. Note `_members.json` is not interchangeable with `_segments.json`: `_segments.json` is a flat `[[start, end], ...]` list consumed by `select-transitions`/`remap-words`, while `_members.json` needs the richer per-member structure (`video_stem`, per-member `keep_segments`) that `compilation.py`'s CLI actually parses via `member["video_stem"]`/`member.get("keep_segments")`. An implementer following the doc literally hits a `FileNotFoundError` at bullet 8, or has to silently infer this whole bookkeeping step.

**Fix:** Add an explicit instruction analogous to bullet 4's — e.g. append to bullet 3 (where crop_style/punch_zoom_at are decided) or make it its own sentence in bullet 8: "Write this group's members, in strongest-first order, as a JSON list of `{"video_stem": ..., "start": ..., "end": ..., "keep_segments": [...]}` (omitting `keep_segments` per member when step 5 didn't set one for it) to `work/<video_stem>/compilations/<compilation_stem>_members.json` before running the command below."

## Info

### IN-01: Duplicate `sys.path.insert` boilerplate within a single `render_clip` call

**File:** `scripts/render.py:907-911` and `scripts/render.py:981-991`

**Issue:** `render_clip` independently does `import sys; sys.path.insert(0, str(Path(__file__).resolve().parent.parent)); from scripts.X import Y` twice in the same function body — once to reach `scripts.subtitles` (for karaoke cue building), once to reach `scripts.jumpcuts.compute_boundary_gaps` (for single-clip boundary transitions). Both branches are reachable in the same call (a clip with both subtitles and jump-cut `boundary_transitions`), so the same path gets inserted into `sys.path` twice per render.
**Fix:** Hoist the `sys.path.insert(...)` call once to the top of `render_clip` (before either conditional import), or factor both lazy imports behind a single small helper. Low priority — harmless (idempotent path insert, no observable bug) but avoidable duplication.

---

_Reviewed: 2026-07-10T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
