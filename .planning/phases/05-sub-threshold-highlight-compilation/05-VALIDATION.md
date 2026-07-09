---
phase: 5
slug: sub-threshold-highlight-compilation
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-07-09
---

# Phase 5 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.1.1 (`python -m pytest --version`) |
| **Config file** | `pyproject.toml` (`[tool.pytest.ini_options]`, `pythonpath=["."]`, `testpaths=["tests"]`, `integration` marker) |
| **Quick run command** | `python -m pytest tests/test_compilation.py tests/test_render.py tests/test_candidates.py -x --basetemp=D:/shorts-maker/.pytest-tmp` |
| **Full suite command** | `python -m pytest --basetemp=D:/shorts-maker/.pytest-tmp` |
| **Estimated runtime** | ~30-60s non-integration; longer with `-m integration` real-ffmpeg compilation render |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/test_compilation.py tests/test_render.py tests/test_candidates.py -x --basetemp=D:/shorts-maker/.pytest-tmp`
- **After every plan wave:** Run `python -m pytest --basetemp=D:/shorts-maker/.pytest-tmp` (full suite)
- **Before `/gsd-verify-work`:** Full suite must be green, including `-m integration`
- **Max feedback latency:** 60 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 05-01-01 | 05-01 | 1 | COMP-01 | V5 | `Candidate` dataclass carries `tag`/`sub_threshold`/`group_id`/`unmatched`; `merge_candidates` unaffected for normal candidates | unit | `pytest tests/test_candidates.py -k tag_or_sub_threshold -x` | ❌ W0 | ⬜ pending |
| 05-01-02 | 05-01 | 1 | COMP-01 | — | New markdown-append renders unmatched candidates distinctly in `CANDIDATES.md` | unit | `pytest tests/test_candidates.py -k compilation_sections -x` | ❌ W0 | ⬜ pending |
| 05-02-01 | 05-02 | 2 | COMP-02 | — | `scripts/compilation.py` builds a valid compilation `PLAN.json` entry from mock grouped candidates, min group size 2+ enforced | unit | `pytest tests/test_compilation.py -x` | ❌ W0 | ⬜ pending |
| 05-02-02 | 05-02 | 2 | COMP-03 | — | Grouping validation rejects candidates from a different `video_stem` | unit | `pytest tests/test_compilation.py -k same_video_stem -x` | ❌ W0 | ⬜ pending |
| 05-03-01 | 05-03 | 3 | COMP-02 | V5 | `render.py::build_compilation_command` produces a valid multi-input `filter_complex`; rejects empty/single-member `segments` with `RenderError` before building any ffmpeg command | unit | `pytest tests/test_render.py -k compilation -x` | ❌ W0 | ⬜ pending |
| 05-03-02 | 05-03 | 3 | COMP-02 | — | End-to-end real-ffmpeg compilation render (3 short candidates from a real tiny fixture video, far apart in timestamp) produces a playable, correctly-dimensioned output | integration | `pytest tests/test_integration_ffmpeg.py -k compilation -m integration -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

*(Exact task IDs/waves are illustrative — final numbering set by the planner; this table's requirement→test mapping is the binding contract.)*

---

## Wave 0 Requirements

- [ ] `tests/test_compilation.py` — new file, covers COMP-02/COMP-03 mechanical validation and PLAN.json entry construction
- [ ] `tests/test_candidates.py` — extend with new tests for tag/sub_threshold fields and the new markdown-append function (COMP-01)
- [ ] `tests/test_render.py` — extend with `build_compilation_command` unit tests (mocked `runner`, mirroring existing `build_jumpcut_command` test style)
- [ ] `tests/test_integration_ffmpeg.py` — extend with one real-ffmpeg compilation smoke test (3 short segments from a synthetic fixture video far apart in timestamp), same `integration` marker/skip-if-no-ffmpeg pattern already established
- [ ] No new test-framework install needed — pytest and its `integration` marker are already configured

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Compilation "reads as one coherent short" (not a jarring patchwork) despite uniform-crop-style constraint (D-06) | COMP-02 | Subjective creative judgment | Render a real compilation from 2-3 sub-threshold moments, review by eye whether the stitched result feels coherent |
| Strongest-moment-first ordering (D-04) actually leads with the strongest hook | COMP-02 | Requires human judgment of "which moment is strongest" | Compare the compilation's member order against the candidates' original `reason`/`coherence` — confirm the lead moment is the intended strongest one |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
