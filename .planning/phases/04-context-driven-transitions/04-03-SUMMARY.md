---
phase: 04-context-driven-transitions
plan: 03
subsystem: infra
tags: [transitions, opencv, librosa, optical-flow, onset-detection, histogram-similarity, fail-open]

# Dependency graph
requires:
  - phase: 04-context-driven-transitions
    provides: opencv-python-headless + librosa installed and registered (04-01); TransitionsConfig + compute_boundary_gaps (04-02)
provides:
  - "scripts/transitions.py: TRANSITION_TYPES canonical 6-item enum, TransitionError, and three lazy-import fail-open signal-analysis functions (analyze_motion_at_boundary, analyze_similarity_at_boundary, analyze_audio_onset_at_boundary) plus extract_audio_window helper"
  - "tests/test_transitions.py: green Wave-0 scaffold (14 tests) covering enum membership, fail-open None paths, and real-score paths"
affects: [04-04-classifier, 04-05-render-fold]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "analyze_motion_at_boundary/analyze_similarity_at_boundary/analyze_audio_onset_at_boundary follow the diarize.py:72-78 lazy-import fail-open shape exactly - try/except ImportError inside the function body, return None, never a module-top-level import"
    - "extract_audio_window takes runner=subprocess.run (project injectable-runner convention: render.py::probe_video, frames.py::extract_frames, diarize.py::extract_audio_wav) and builds the ffmpeg call as an argument list, never shell=True"
    - "Deterministic fail-open test technique: monkeypatch builtins.__import__ to raise ImportError for a named module, rather than relying on the dependency actually being absent from the venv"

key-files:
  created:
    - scripts/transitions.py
    - tests/test_transitions.py
  modified:
    - .gitignore

key-decisions:
  - "TDD RED/GREEN per task (3 test-then-feat commit pairs), matching the 04-02 precedent, rather than one combined commit per task"
  - "Motion test fixtures use a shifted white-square-on-black frame pair (real optical-flow displacement) rather than two differently-colored solid frames, since Farneback flow has no texture/gradient to correlate on uniform color blocks - solid-color pairs are reserved for the similarity/histogram test instead, where color distribution (not position) is what's being compared"
  - "Added .gitignore entries for .pytest_cache/ and .pytest-tmp/ (this machine's --basetemp override, per STATE.md Blockers/Concerns) - runtime output was showing as untracked after every test run"

patterns-established:
  - "Composite-analog module (scripts/transitions.py): diarize.py's lazy-import shape for the two cv2 functions and the one librosa function, frames.py's ffmpeg-argument-list + injectable-runner shape for extract_audio_window"

requirements-completed: [TRANS-01]

coverage:
  - id: D1
    description: "TRANSITION_TYPES is a frozenset of exactly the 6 required type strings; TransitionError subclasses ValueError"
    requirement: "TRANS-01"
    verification:
      - kind: unit
        ref: "tests/test_transitions.py#test_transition_types_has_exactly_six_members"
        status: pass
      - kind: unit
        ref: "tests/test_transitions.py#test_transition_types_contains_expected_values"
        status: pass
      - kind: unit
        ref: "tests/test_transitions.py#test_transition_error_subclasses_value_error"
        status: pass
    human_judgment: false
  - id: D2
    description: "scripts/transitions.py imports cleanly with neither cv2 nor librosa installed (top-level is stdlib-only)"
    requirement: "TRANS-01"
    verification:
      - kind: other
        ref: "manual __import__ monkeypatch blocking cv2+librosa at process level, then `import scripts.transitions` -> succeeds, all three analysis functions return None"
        status: pass
    human_judgment: false
  - id: D3
    description: "analyze_motion_at_boundary / analyze_similarity_at_boundary / analyze_audio_onset_at_boundary each return None (not raise) when their optional dependency is unimportable"
    requirement: "TRANS-01"
    verification:
      - kind: unit
        ref: "tests/test_transitions.py#test_analyze_motion_returns_none_when_cv2_missing"
        status: pass
      - kind: unit
        ref: "tests/test_transitions.py#test_analyze_similarity_returns_none_when_cv2_missing"
        status: pass
      - kind: unit
        ref: "tests/test_transitions.py#test_analyze_audio_onset_returns_none_when_librosa_missing"
        status: pass
      - kind: unit
        ref: "tests/test_transitions.py#test_analyze_motion_returns_none_when_frame_unreadable"
        status: pass
      - kind: unit
        ref: "tests/test_transitions.py#test_analyze_similarity_returns_none_when_frame_unreadable"
        status: pass
    human_judgment: false
  - id: D4
    description: "With cv2/librosa present, each analysis function returns a finite float score on real fixture inputs"
    requirement: "TRANS-01"
    verification:
      - kind: unit
        ref: "tests/test_transitions.py#test_analyze_motion_identical_frames_near_zero_shifted_frames_higher"
        status: pass
      - kind: unit
        ref: "tests/test_transitions.py#test_analyze_similarity_identical_frames_high_differing_colors_lower"
        status: pass
      - kind: unit
        ref: "tests/test_transitions.py#test_analyze_audio_onset_real_score_on_transient"
        status: pass
    human_judgment: false
  - id: D5
    description: "extract_audio_window builds a shell-free ffmpeg argument list, clamps window start at 0.0 near the video start, and raises TransitionError on nonzero ffmpeg returncode"
    requirement: "TRANS-01"
    verification:
      - kind: unit
        ref: "tests/test_transitions.py#test_extract_audio_window_builds_shell_free_command_list"
        status: pass
      - kind: unit
        ref: "tests/test_transitions.py#test_extract_audio_window_clamps_start_at_zero_near_video_start"
        status: pass
      - kind: unit
        ref: "tests/test_transitions.py#test_extract_audio_window_raises_transition_error_on_ffmpeg_failure"
        status: pass
    human_judgment: false

# Metrics
duration: 5min
completed: 2026-07-09
status: complete
---

# Phase 4 Plan 03: Transitions Boundary-Analysis Signal Layer Summary

**scripts/transitions.py delivers the three lazy-import, fail-open TRANS-01 signal functions (Farneback optical-flow motion, histogram-correlation match-cut similarity, librosa spectral-flux audio onset) plus the canonical TRANSITION_TYPES enum and an ffmpeg-argument-list audio-window extractor, backed by a 14-test green scaffold.**

## Performance

- **Duration:** ~5 min (from first commit to last)
- **Started:** 2026-07-09T18:59:09+03:00
- **Completed:** 2026-07-09T19:02:52+03:00
- **Tasks:** 3/3 completed
- **Files modified:** 3 (scripts/transitions.py, tests/test_transitions.py, .gitignore) + 1 new phase note (deferred-items.md)

## Accomplishments
- `scripts/transitions.py` created: stdlib-only top-level imports (`argparse`, `json`, `subprocess`, `pathlib.Path`), a module docstring explaining the lazy-import fail-open contract, `TRANSITION_TYPES` (canonical 6-item frozenset), and `TransitionError(ValueError)`
- `analyze_motion_at_boundary` — Farneback dense optical flow between two grayscale boundary frames, returns mean flow magnitude; `None` on missing cv2 or an unreadable frame
- `analyze_similarity_at_boundary` — `cv2.calcHist` + `compareHist(HISTCMP_CORREL)` match-cut proxy, reusing the same cv2 import (no `scenedetect`, per 04-RESEARCH.md Anti-Patterns); `None` on missing cv2 or an unreadable frame
- `analyze_audio_onset_at_boundary` — librosa spectral-flux onset-strength peak over a short audio window; `None` on missing librosa
- `extract_audio_window` — ffmpeg argument-list wrapper (never `shell=True`), `-ss` before `-i` for fast seek, window start clamped at `0.0` near the video start, injectable `runner=subprocess.run`, raises `TransitionError` on nonzero returncode
- `tests/test_transitions.py` — 14 tests: enum/error shape (3), fail-open deterministic `__import__`-monkeypatch tests for cv2/librosa (3), fail-open unreadable-frame tests (2), real-score tests gated by `pytest.importorskip` (3), and `extract_audio_window` command-shape/clamp/error tests (3)
- Verified module import-safety end-to-end by monkeypatching `builtins.__import__` to block both `cv2` and `librosa` at process level and confirming `import scripts.transitions` succeeds with every analysis function returning `None`
- Full project test suite run (`pytest -m "not integration"`): 343 passed, 0 new failures introduced by this plan; 3 pre-existing unrelated failures in `test_publish_queue.py` logged to `deferred-items.md` (out of scope, missing `googleapiclient` dependency)

## Task Commits

TDD RED→GREEN per task, mirroring the 04-02 precedent:

1. **Task 1: Module skeleton, TRANSITION_TYPES enum, TransitionError, Wave-0 scaffold**
   - `fa74395` test(04-03): add failing test for transitions module skeleton
   - `9c853ab` feat(04-03): add transitions module skeleton, TRANSITION_TYPES, TransitionError
2. **Task 2: Motion + match-cut analysis over boundary frames**
   - `d9683cc` test(04-03): add failing tests for motion/similarity analysis functions
   - `fa06dd9` feat(04-03): implement optical-flow motion and histogram-similarity analysis
3. **Task 3: Audio-onset analysis + boundary audio-window extraction**
   - `b541475` test(04-03): add failing tests for audio onset analysis and window extraction
   - `7e4f993` feat(04-03): implement audio onset analysis and boundary audio-window extraction

**Housekeeping (not a plan task, discovered via untracked-file check):** `c873f64` chore(04-03): gitignore pytest scratch dirs, log pre-existing publish_queue failure

**Plan metadata:** committed separately (docs commit) after this SUMMARY.md finalization.

## Files Created/Modified
- `scripts/transitions.py` — new module: `TRANSITION_TYPES`, `TransitionError`, `analyze_motion_at_boundary`, `analyze_similarity_at_boundary`, `analyze_audio_onset_at_boundary`, `extract_audio_window`, `main()` CLI wrapper
- `tests/test_transitions.py` — new file, 14 tests covering enum, fail-open, and real-score paths
- `.gitignore` — added `.pytest_cache/` and `.pytest-tmp/` (this machine's `--basetemp` scratch dir, see STATE.md Blockers/Concerns)
- `.planning/phases/04-context-driven-transitions/deferred-items.md` — new note logging the pre-existing `test_publish_queue.py` failures found while running the full suite

## Decisions Made
- TDD RED/GREEN commit pairs per task (test commit fails at collection, feat commit turns it green) — matches 04-02's established pattern for this phase
- Motion-test fixtures use a shifted white-square-on-black-background frame pair (genuine pixel displacement) rather than two differently-colored solid frames, since Farneback optical flow needs texture/gradient to correlate — a uniform color-only difference has nothing for the algorithm to track. Solid-color pairs were instead used for the similarity/histogram test, where color distribution (not spatial position) is exactly what's being measured
- Fail-open tests for cv2/librosa use a deterministic `builtins.__import__` monkeypatch rather than relying on the dependency actually being uninstalled — this machine's venv has both installed (04-01), so the monkeypatch is the only way to exercise the `ImportError` branch reliably in CI/local runs alike

## Deviations from Plan

None — plan executed exactly as written. All three analysis functions and `extract_audio_window` match the plan's `<action>` blocks precisely (Farneback parameter defaults, `HISTCMP_CORREL`, `librosa.onset.onset_strength(...).max()`, ffmpeg argument-list shape).

**Out-of-scope discovery (not fixed, logged per SCOPE BOUNDARY):** Running the full test suite surfaced 3 pre-existing failures in `tests/test_publish_queue.py` (`ModuleNotFoundError: No module named 'googleapiclient'`), entirely inside `scripts/publish_queue.py` — a file this plan never touched. Documented in `.planning/phases/04-context-driven-transitions/deferred-items.md`; not auto-fixed since it's a Phase 3 concern, out of this plan's scope.

## Issues Encountered
- Environment quirk (pre-existing, documented in STATE.md Blockers): default pytest temp dir is permission-locked on this machine. Ran every test with `--basetemp=D:/shorts-maker/.pytest-tmp`; also noticed `.pytest_cache/` and `.pytest-tmp/` were showing as untracked after test runs, so both were added to `.gitignore` (housekeeping commit `c873f64`). Unrelated to any code change in this plan.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness
- `scripts/transitions.py`'s three analysis functions + `TRANSITION_TYPES` enum give 04-04 (classifier) everything it needs to build `classify_transition()`: motion score, similarity score, audio-onset score, and the fixed type vocabulary to select from
- `extract_audio_window` gives 04-04/04-05 the audio-window extraction step needed before calling `analyze_audio_onset_at_boundary` on a real video
- No blockers. The module is fully import-safe without cv2/librosa (Fail-open constraint verified), consistent with every other optional feature in this codebase

---
*Phase: 04-context-driven-transitions*
*Completed: 2026-07-09*

## Self-Check: PASSED

- FOUND: scripts/transitions.py, tests/test_transitions.py, .planning/phases/04-context-driven-transitions/deferred-items.md, .planning/phases/04-context-driven-transitions/04-03-SUMMARY.md
- FOUND: commits fa74395, 9c853ab, d9683cc, fa06dd9, b541475, 7e4f993, c873f64 (`git log --oneline --all`)
