---
phase: 04-context-driven-transitions
fixed_at: 2026-07-09T20:10:00Z
review_path: .planning/phases/04-context-driven-transitions/04-REVIEW.md
iteration: 1
findings_in_scope: 4
fixed: 4
skipped: 0
status: all_fixed
---

# Phase 04: Code Review Fix Report

**Fixed at:** 2026-07-09T20:10:00Z
**Source review:** .planning/phases/04-context-driven-transitions/04-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 4 (Critical: CR-01, CR-02; Warning: WR-01, WR-02, WR-03 — CR-02 and WR-01 describe the same underlying bug at the same file/lines and were fixed together in one commit)
- Fixed: 4
- Skipped: 0

Info findings IN-01 and IN-02 were intentionally left untouched — out of scope for the `critical_warning` fix pass.

## Fixed Issues

### CR-01: `render.py`'s transition fold can crash the whole clip render on a short kept segment (negative xfade offset)

**Files modified:** `scripts/render.py`
**Commit:** `e2834ef`
**Applied fix:** In `_build_transition_fold`, `d_eff` (the borrowed xfade/acrossfade overlap per boundary) is now capped by `min(gap, seg_a_duration, seg_b_duration)` instead of just `gap` — a short kept segment can no longer be asked to host more overlap than it actually contains. Boundaries where the capped overlap falls below `min_overlap_seconds` now downgrade to a plain 2-input concat (matching the existing TRANS-03 fallback pattern), instead of the crossfade offset going negative and `build_transition_filter` raising `RenderError`. Added a second, last-resort guard immediately before the xfade call (`d_eff > acc_duration`) that also downgrades to concat, covering the edge case where a segment is borrowed into from both adjacent boundaries and the per-boundary cap alone isn't sufficient. Verified against the reviewer's exact repro (`keep_segments=[(10.0, 10.05), (10.4, 40.0)]` with a crossfade boundary) — no longer raises, degrades cleanly to concat. `tests/test_render.py` (80 tests) passes unchanged.

### CR-02 / WR-01: `scripts/transitions.py` cannot run standalone as documented in `SKILL.md`

**Files modified:** `scripts/transitions.py`
**Commit:** `3c8f011`
**Applied fix:** Added `sys.path.insert(0, str(Path(__file__).resolve().parent.parent))` before the top-level `from scripts.frames import extract_frames` / `from scripts.jumpcuts import compute_boundary_gaps` imports, mirroring the exact `sys.path.insert` pattern `render.py` already uses for its own sibling-module imports. Verified with the reviewer's exact live invocation: `python scripts/transitions.py --help` now prints the argparse help text instead of raising `ModuleNotFoundError: No module named 'scripts'`. `tests/test_transitions.py` and `tests/test_jumpcuts.py` (51 passed, 5 skipped — cv2/librosa not installed, fail-open by design) pass unchanged.

Note: CR-02 and WR-01 in `04-REVIEW.md` both describe the identical bug at the identical location (`scripts/transitions.py:22-23`, top-level sibling-module imports breaking standalone execution) with the identical fix — REVIEW.md's frontmatter counts them as separate Critical/Warning findings, but only one finding body (WR-01) documents the fix in the "Warnings" section; the "Extra context" passed to this fixer run supplied the CR-02 details directly. One code change resolves both.

### WR-02: Caption text/words are not escaped for ASS override-block syntax

**Files modified:** `scripts/render.py`
**Commit:** `5ca087d`
**Applied fix:** Added `_escape_ass_text()` helper that escapes `\` (first), then `{` and `}` before any caption text is interpolated into a `Dialogue:` line. Applied to `cue["text"]` (base event, escaped before the `\N` newline substitution so the inserted `\N` isn't itself double-escaped) and to each per-word `token` (karaoke overlay events). Verified with a malicious-input test containing literal `}`, `{`, and `\` in both cue text and a word token: output now shows `\}\{\\r\}weird` and `\}\{bad\\` (escaped) while the deliberately-emitted `{\alpha&H00&\c...}` override tags remain intact and unescaped. `tests/test_render.py` (80 tests) passes unchanged.

### WR-03: Boundary frame-extraction timestamps aren't clamped to `>= 0`

**Files modified:** `scripts/transitions.py`
**Commit:** `0900802`
**Applied fix:** Wrapped the frame-extraction start timestamp in `max(0.0, boundary_time - _BOUNDARY_FRAME_OFFSET)`, matching the same clamp pattern already used three lines below by `extract_audio_window` (`start = max(0.0, center_time - duration / 2)`). A boundary near the start of a clip (e.g. a short first kept segment, per CR-01) can no longer request a negative `-ss` timestamp from ffmpeg. `tests/test_transitions.py` (29 passed, 5 skipped) passes unchanged.

## Skipped Issues

None — all in-scope findings were fixed.

---

_Fixed: 2026-07-09T20:10:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
