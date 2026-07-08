---
phase: 4
slug: context-driven-transitions
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-08
---

# Phase 4 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest >=7.4.0 (`requirements-dev.txt`, already installed) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` — `pythonpath=["."]`, `testpaths=["tests"]`, registers `integration` marker |
| **Quick run command** | `pytest tests/test_transitions.py -x` |
| **Full suite command** | `pytest -x` (real-ffmpeg `integration`-marked tests run too since ffmpeg is on PATH; `pytest -m "not integration" -x` for a faster non-integration pass) |
| **Estimated runtime** | ~30-60s non-integration, longer with integration render tests |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/test_transitions.py -x` (plus `tests/test_render.py`/`tests/test_jumpcuts.py` for touched functions)
- **After every plan wave:** Run `pytest -x` (full suite, including integration since ffmpeg is present)
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 60 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 04-01-01 | 04-01 | 1 | TRANS-01 | V5 | Motion/audio boundary analysis returns sane scores on known fixtures; degrades to `None` when `cv2`/`librosa` unimportable | unit | `pytest tests/test_transitions.py -x -k analyze` | ❌ W0 | ⬜ pending |
| 04-01-02 | 04-01 | 1 | TRANS-02 | V5 | `classify_transition` returns each of the 6 valid type strings for constructed signal inputs; transition-type value validated against fixed enum before use in filter dispatch | unit | `pytest tests/test_transitions.py -x -k classify` | ❌ W0 | ⬜ pending |
| 04-01-03 | 04-01 | 1 | TRANS-02 | V5 | Filter-graph builder produces valid ffmpeg syntax per transition type, built from argument lists / enum-constrained strings, never raw string interpolation | unit | `pytest tests/test_render.py -x -k transition` | ❌ W0 | ⬜ pending |
| 04-02-01 | 04-02 | 2 | TRANS-03 | — | Inconclusive/missing-signal boundary falls back to plain cut/punch-zoom; insufficient pause-gap overlap falls back to cut | unit | `pytest tests/test_transitions.py -x -k fallback` | ❌ W0 | ⬜ pending |
| 04-02-02 | 04-02 | 2 | TRANS-01/02 | — | Full jumpcut render with a forced non-cut boundary produces a playable, correctly-dimensioned output | integration | `pytest tests/test_integration_ffmpeg.py -x -m integration -k transition` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

*(Exact task IDs/waves are illustrative — final numbering set by the planner; this table's requirement→test mapping is the binding contract.)*

---

## Wave 0 Requirements

- [ ] `tests/test_transitions.py` — new file, covers TRANS-01/02/03 unit-level behavior (motion/audio/similarity scoring, `classify_transition`, fail-open on missing `cv2`/`librosa`)
- [ ] New integration test in `tests/test_integration_ffmpeg.py` mirroring `test_jumpcut_splices_out_silence_gap`'s fixture-video pattern, covering a real xfade-based transition render
- [ ] Extend `tests/test_jumpcuts.py` if `compute_keep_segments` (or a sibling) gains pause-gap-size exposure for the overlap-borrowing logic
- [ ] No new test-framework install needed — pytest and its `integration` marker are already configured

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Perceived "conservative bias" feel (fancy transitions rare, not noisy on a long render) | TRANS-01 (D-01 in 04-CONTEXT.md) | Subjective creative judgment, not mechanically testable | Render a real multi-jumpcut clip, review by eye whether non-cut transitions feel rare/appropriate rather than gimmicky |
| Match-cut visual result (research flagged this as likely rendering identical to a plain cut, distinction living only in selection metadata) | TRANS-02 | Open question from research — needs a human look at actual output to confirm it reads as intentional, not a missing feature | Render a boundary classified as `match_cut`, visually confirm it looks like a deliberate cut on action, not an arbitrary hard cut |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
