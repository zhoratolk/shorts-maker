---
phase: 04-context-driven-transitions
reviewed: 2026-07-09T00:00:00Z
depth: standard
files_reviewed: 11
files_reviewed_list:
  - .claude/skills/make-shorts/SKILL.md
  - scripts/config.py
  - scripts/jumpcuts.py
  - scripts/render.py
  - scripts/transitions.py
  - tests/test_config.py
  - tests/test_integration_ffmpeg.py
  - tests/test_jumpcuts.py
  - tests/test_render.py
  - tests/test_transitions.py
  - config.example.yaml
findings:
  critical: 2
  warning: 3
  info: 2
  total: 7
status: issues_found
---

# Phase 04: Code Review Report

**Reviewed:** 2026-07-09T00:00:00Z
**Depth:** standard
**Files Reviewed:** 11
**Status:** issues_found

## Summary

Reviewed the context-driven-transitions feature: `scripts/transitions.py` (new boundary-analysis/classification module), the restructured `scripts/render.py` (flat-concat → sequential xfade/acrossfade fold), `scripts/jumpcuts.py`'s new `compute_boundary_gaps`, config schema/validation, and the associated tests.

The enum-drift guard (`VALID_TRANSITIONS` vs `TRANSITION_TYPES`) is correctly implemented and tested (`test_valid_transitions_matches_transitions_module_canonical_enum`), and the all-cut/all-match_cut backward-compatibility path is verified byte-identical by tests and matches the code as read.

Two blockers were found and confirmed by actually running the code (not just static reading):

1. `scripts/transitions.py` cannot be invoked the way `SKILL.md` itself documents (`python scripts/transitions.py select-transitions ...`) — it crashes at import time.
2. `render.py`'s new sequential-fold path can crash with an unhandled `RenderError` (negative xfade offset) when a kept segment adjacent to a transition boundary is short — this defeats the TRANS-03 "fall back to a plain cut" guarantee the code's own docstrings claim to provide, and the gap that lets it through is untested.

## Critical Issues

### CR-01: `render.py`'s transition fold can crash the whole clip render on a short kept segment (negative xfade offset)

**File:** `scripts/render.py:417-470` (particularly the `effective_duration` loop at 417-426 and the offset computation at 460)

**Issue:** `_build_transition_fold` caps the borrowed overlap `d_eff` for a boundary only against `transition_duration` and the boundary's pause `gap` (`compute_boundary_gaps`). It never caps `d_eff` against the *duration of the adjacent kept segment itself*. When a kept segment is shorter than the transition overlap it's asked to host (a short spoken snippet wedged between two nearby pauses is a completely ordinary case for `jumpcuts.compute_keep_segments` — nothing in `jumpcuts.py` enforces a minimum segment length, and `select_boundary_transitions` in `transitions.py` never looks at segment duration when picking a transition type), `acc_duration` at that fold step becomes smaller than `d_eff`, so `offset = acc_duration - d_eff` (line 460) goes negative. `build_transition_filter` (render.py:283-284) then raises `RenderError("offset must be >= 0, ...")`, which propagates all the way out of `render_clip` uncaught — the entire clip fails to render instead of the boundary silently degrading to a plain cut, even though the surrounding docstring (render.py:398-402) explicitly claims "non-cut boundaries whose gap is below `min_overlap_seconds` ... join via a plain 2-input concat instead" (TRANS-03) as the safety net. That safety net checks gap size only, not segment size, so the promised guarantee is incomplete.

Confirmed by direct execution:
```python
from scripts.render import build_jumpcut_command
build_jumpcut_command(
    "in.mp4", "out.mp4", clip_start=10.0, clip_end=40.0,
    keep_segments=[(10.0, 10.05), (10.4, 40.0)],   # first kept segment is only 0.05s
    crop_filter="crop=608:1080:656:0,scale=1080:1920",
    boundary_transitions=["crossfade"], boundary_gaps=[0.35],
)
# -> RenderError: offset must be >= 0, got -0.125
```
No existing test in `tests/test_render.py` exercises a short kept segment adjacent to a transition boundary — every fixture uses 10s+/18s+ segments, so this gap is untested.

**Fix:** Cap `d_eff` by the available duration on each side of the boundary too (not just by `gap`/`transition_duration`), and downgrade to a plain concat (matching the existing `min_overlap_seconds` downgrade path) whenever the capped overlap can't be honored:
```python
for boundary in range(segment_count - 1):
    transition_type = boundary_transitions[boundary]
    gap = boundary_gaps[boundary]
    seg_a_duration = ends[boundary] - starts[boundary]
    seg_b_duration = ends[boundary + 1] - starts[boundary + 1]
    max_borrowable = min(gap, seg_a_duration, seg_b_duration)
    if transition_type in ("cut", "match_cut") or max_borrowable < min_overlap_seconds:
        effective_duration.append(None)
        continue
    d_eff = min(transition_duration, max_borrowable)
    effective_duration.append(round(d_eff, 3))
```
Also consider guarding `acc_duration >= d_eff` immediately before calling `build_transition_filter` in the fold loop and downgrading to concat there as a last-resort safety net, so a future change to the capping logic can't reintroduce the crash silently.

## Warnings

### WR-01: `scripts/transitions.py` cannot run standalone as documented in `SKILL.md`

**File:** `scripts/transitions.py:22-23`

**Issue:** `transitions.py` does top-level `from scripts.frames import extract_frames` and `from scripts.jumpcuts import compute_boundary_gaps`. `SKILL.md:142` documents invoking this exact file as `python scripts/transitions.py select-transitions "<video>" ...` (matching every other script in this project, e.g. `python scripts/jumpcuts.py keep-segments ...`, `python scripts/render.py ...`). When Python runs a script directly (`python scripts/transitions.py`), `sys.path[0]` is set to the script's own containing directory (`.../scripts`), not the repo root — so `import scripts.frames` fails because no `scripts` package is reachable from there. Confirmed by direct execution in this repo:
```
$ python scripts/transitions.py --help
Traceback (most recent call last):
  File "D:\shorts-maker\scripts\transitions.py", line 22, in <module>
    from scripts.frames import extract_frames
ModuleNotFoundError: No module named 'scripts'
```
This breaks the entire "Context-driven transitions" pipeline step exactly as documented — `select-transitions` can never be run the way the skill orchestrator is told to run it. It only "works" today because `pytest`'s `pythonpath = ["."]` (`pyproject.toml`) papers over it in the test suite; `tests/test_transitions.py` never invokes `python scripts/transitions.py` as a subprocess (unlike `tests/test_jumpcuts.py`'s `_run_cli` helper), so no test catches this. It also contradicts this project's own documented architectural constraint (`CLAUDE.md`: "Circular imports: None ... none imports another `scripts.*` module") and diverges from the existing workaround `render.py` already uses for the same problem (`render.py:650-652` and `689-691` lazily `sys.path.insert(0, str(Path(__file__).resolve().parent.parent))` before importing sibling `scripts.*` modules inside a function body, specifically so the module still works when run as a standalone script).

**Fix:** Either (a) apply the same `sys.path.insert` workaround `render.py` uses, moved to the top of `transitions.py` before the sibling imports, or (b) move `extract_frames`/`compute_boundary_gaps` calls behind a local import inside `select_boundary_transitions` (mirroring the lazy-import convention this file already uses for `cv2`/`librosa`), e.g.:
```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.frames import extract_frames
from scripts.jumpcuts import compute_boundary_gaps
```
Add a regression test that actually shells out (`subprocess.run([sys.executable, "scripts/transitions.py", "--help"], cwd=repo_root)`) the way `tests/test_jumpcuts.py::_run_cli` does, so this class of bug can't reappear silently.

### WR-02: Caption text/words are not escaped for ASS override-block syntax

**File:** `scripts/render.py:119-137` (`build_ass_content`)

**Issue:** Both the base `Dialogue` text (line 122: `cue['text'].replace(chr(10), '\\N')`) and the per-word karaoke overlay tokens (lines 127-132: `token = w["word"].strip()` inserted verbatim between `{...}` override blocks) only escape newlines. ASS delimits inline style overrides with `{`/`}` and uses `\` for tag syntax. A caption word/text containing a literal `{`, `}`, or `\` (plausible from a transcribed code-reading, chat-quote, or emoticon, and explicitly editable per `SKILL.md`'s "correct obviously mis-transcribed words" step) will corrupt the surrounding override tag — e.g. a word literally `"}{\\r}weird"` would prematurely close the `\alpha`/`\c` override and inject its own arbitrary override tag into the rendered subtitle stream, producing corrupted/unexpected styling in the final video rather than a clean failure.

**Fix:** Escape ASS special characters before interpolating into `Dialogue:` lines (backslash first, then braces):
```python
def _escape_ass_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")
```
and apply it to `cue['text']` and each `token`/`w["word"]` before building the `Dialogue:` lines.

### WR-03: Boundary frame-extraction timestamps aren't clamped to `>= 0`

**File:** `scripts/transitions.py:268-284`

**Issue:** `select_boundary_transitions` extracts a frame pair via `extract_frames(video_path, [boundary_time - _BOUNDARY_FRAME_OFFSET, boundary_time + _BOUNDARY_FRAME_OFFSET], ...)` (lines 270-276) with no lower bound. `scripts/frames.py::extract_frames` passes `str(timestamp)` straight to ffmpeg's `-ss` with no clamping either. For a boundary very close to the start of a clip (a short first kept segment — see CR-01, this is a realistic case), `boundary_time - 0.05` can be negative. This is inconsistent with the same file's own `extract_audio_window` three lines below, which explicitly does `start = max(0.0, center_time - duration / 2)` (line 110) specifically to avoid this exact situation ("clamps the window start at 0.0 so a boundary near the start of the video doesn't request a negative timestamp" — the function's own docstring, line 108-109). The video-frame extraction path was not given the same treatment.

**Fix:** Clamp the same way:
```python
frame_a_path, frame_b_path = extract_frames(
    video_path,
    [max(0.0, boundary_time - _BOUNDARY_FRAME_OFFSET), boundary_time + _BOUNDARY_FRAME_OFFSET],
    tmp_dir,
    prefix=f"boundary_{index}",
    runner=runner,
)
```

## Info

### IN-01: `boundary_transitions` set without `keep_segments` is silently ignored rather than validated

**File:** `scripts/render.py:613-707` (`render_clip`)

**Issue:** `SKILL.md:140` documents that `boundary_transitions` is only ever written to a plan entry when `keep_segments` has more than one `[start, end]` pair. `render_clip`'s `else` branch (line 701, taken when `plan_entry.get("keep_segments")` is `None`) never reads `plan_entry.get("boundary_transitions")` at all, so a malformed `PLAN.json` entry that sets `boundary_transitions` without `keep_segments` (a planner bug, hand-edit, or future regression) is silently dropped instead of raising — unlike the existing `punch_zoom_at`/`crop_style` combination, which *is* actively validated (lines 637-646).

**Fix:** Add a symmetrical guard, e.g. in `render_clip`:
```python
if plan_entry.get("boundary_transitions") is not None and keep_segments_raw is None:
    raise RenderError("boundary_transitions requires keep_segments to be set")
```

### IN-02: Confusing redundant clamp in `_build_transition_fold`'s `effective_duration` computation

**File:** `scripts/render.py:417-426`

**Issue:**
```python
d_eff = min(transition_duration, gap)
d_eff = max(min_overlap_seconds, min(d_eff, transition_duration))
```
The second line's `min(d_eff, transition_duration)` is a no-op (`d_eff` is already `<= transition_duration` from the first line), so this reads as dead code on first pass. It is not actually dead: it's the only thing that keeps the invariant "`d_eff <= gap`" safe when `render.py`'s CLI is invoked directly with `--min-overlap-seconds` greater than `--transition-duration` (a combination `config.py`'s `_validate` forbids, but the two CLI flags on `render.py`'s `main()` have no equivalent cross-check against each other). That's a subtle, easy-to-break invariant with no comment explaining why the second `max()` is required.

**Fix:** Either add a comment explaining the CLI-flags-can-disagree-with-config-validation rationale, or make it self-evidently safe by clamping against `gap` directly instead of relying on the earlier `min()`:
```python
d_eff = min(max(min_overlap_seconds, transition_duration), gap)
```

---

_Reviewed: 2026-07-09T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
