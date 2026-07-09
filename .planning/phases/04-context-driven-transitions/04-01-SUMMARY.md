---
phase: 04-context-driven-transitions
plan: 01
subsystem: infra
tags: [transitions, dependencies, opencv, librosa, pip, checkpoint]

# Dependency graph
requires:
  - phase: 04-context-driven-transitions (04-RESEARCH.md)
    provides: Package Legitimacy Audit (SUS verdicts for opencv-python-headless, librosa) and Security Domain analysis
provides:
  - opencv-python-headless 5.0.0.93 and librosa 0.11.0 installed in .venv and registered as optional dependencies in requirements.txt
affects: [04-02, 04-03, 04-context-driven-transitions]

# Tech tracking
tech-stack:
  added:
    - "opencv-python-headless>=5.0 (optional, transitions boundary analysis - dense optical flow + histogram similarity for match-cut)"
    - "librosa>=0.11 (optional, transitions boundary analysis - audio onset detection)"
  patterns:
    - "Optional-dependency comment block in requirements.txt, mirroring the pyannote.audio convention (comment explaining the gating config flag, then the package lines)"

key-files:
  created: []
  modified:
    - requirements.txt

key-decisions:
  - "Plan halted at Task 1's blocking-human checkpoint per package-legitimacy protocol — checkpoint is never auto-approvable regardless of workflow.auto_advance"
  - "Human approved both packages after verifying pypi.org source repos (github.com/opencv/opencv-python, github.com/librosa/librosa), maintenance activity, and exact-spelling typosquat check — Task 2 proceeded"
  - "pip install pulled numpy down from 2.5.0 to 2.4.6 as a transitive resolution for numba (librosa's dependency) — verified via `pip check` that no installed package is left broken by this downgrade"
  - "No scripts.* module imports cv2/librosa yet; lazy-import is deferred to plan 04-03 (scripts/transitions.py), so the base pipeline is unaffected by this install — Fail-open constraint intact"

patterns-established:
  - "New optional-dependency blocks in requirements.txt use >= version floors and a one-line comment naming the config flag that gates the feature, matching pyannote.audio/google-api-python-client blocks"

requirements-completed: [TRANS-01]

coverage:
  - id: D1
    description: "Human legitimacy checkpoint for opencv-python-headless and librosa presented (pypi.org verification steps, typosquat check)"
    verification: []
    human_judgment: true
    rationale: "This IS the human verification gate itself (threat T-04-SC mitigation) — a human reviewed pypi.org before install proceeded. Cannot be auto-passed by design."
  - id: D2
    description: "cv2 and librosa import successfully from the project's .venv after install"
    verification:
      - "cd D:/shorts-maker && .venv/Scripts/python.exe -c \"import cv2, librosa; print(cv2.__version__, librosa.__version__)\" → 5.0.0 0.11.0"
    human_judgment: false
  - id: D3
    description: "requirements.txt entries for opencv-python-headless and librosa under an optional-dependency comment block, not promoted into the mandatory core"
    verification:
      - "requirements.txt diff shows both packages under a new '# optional, only needed when transitions.enabled is true' comment, appended after the existing google-api-python-client block"
    human_judgment: false

# Metrics
duration: 30min
completed: 2026-07-09
status: complete
---

# Phase 4 Plan 01: Optional Dependency Legitimacy Checkpoint Summary

**Installed opencv-python-headless 5.0.0.93 and librosa 0.11.0 into the project .venv after a human-approved blocking legitimacy checkpoint, and registered both under a new optional-dependency block in requirements.txt.**

## Performance

- **Duration:** 30 min total (5 min to checkpoint + resume/install/commit)
- **Started:** 2026-07-09T15:22:00Z
- **Completed:** 2026-07-09T15:48:00Z
- **Tasks:** 2/2 completed
- **Files modified:** 1 (requirements.txt)

## Accomplishments
- Loaded and cross-checked 04-01-PLAN.md, 04-CONTEXT.md, PROJECT.md, STATE.md, config.json, and requirements.txt against the existing optional-dependency comment convention (pyannote.audio block) this plan mirrors.
- Confirmed the plan's Task 1 is a `checkpoint:human-verify gate="blocking-human"` that STRIDE-maps to threat T-04-SC (supply-chain tampering via new PyPI install) — this gate was not silently approved by the executor.
- Presented the exact pypi.org verification steps from the plan (repo match, maintenance activity, version match, exact-spelling typosquat check) to the user without running any install command; user reviewed and responded "approved" (opencv-python-headless → github.com/opencv/opencv-python; librosa → github.com/librosa/librosa — no typosquat concerns, actively maintained).
- Installed both packages into the project's existing `.venv` using its own interpreter (`.venv/Scripts/python.exe -m pip install opencv-python-headless librosa`) — resolved to prebuilt win_amd64 wheels with no compiler step, per 04-RESEARCH.md's prediction.
- Verified `import cv2, librosa` succeeds and prints versions 5.0.0 / 0.11.0.
- Ran `pip check` post-install to confirm no broken requirements after the transitive numpy downgrade (2.5.0 → 2.4.6, pulled in by numba/librosa).
- Confirmed no `scripts/*.py` module imports cv2 or librosa yet, so the base pipeline's Fail-open guarantee is untouched by this install — lazy-import is deferred to plan 04-03.
- Appended the optional-dependency block to requirements.txt, mirroring the pyannote.audio block's shape exactly (comment above, `>=` floors, no pins).

## Task Commits

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Legitimacy checkpoint for opencv-python-headless and librosa | 65f3c5d | 04-01-SUMMARY.md (partial), STATE.md |
| 2 | Install packages and register them in requirements.txt | 141c685 | requirements.txt |

**Plan metadata:** committed separately (docs commit) after this SUMMARY.md finalization.

## Files Created/Modified

- `requirements.txt` — added optional-dependency block: `# optional, only needed when transitions.enabled is true (Phase 4 boundary analysis)` comment, then `opencv-python-headless>=5.0` and `librosa>=0.11`.

## Decisions Made

- Followed the checkpoint protocol strictly: no auto-approval of the blocking-human gate under any circumstance, including `AUTO_CFG=true` in this project's config (blocking-human package-legitimacy checkpoints are explicitly excluded from auto-approval per the executor's checkpoint protocol).
- Did not add `scenedetect` — 04-RESEARCH.md documents that it pulls plain `opencv-python` alongside `opencv-python-headless`, a known `cv2` module conflict; the match-cut proxy will use `cv2.calcHist`/`compareHist` directly instead (deferred to plan 04-03).
- Accepted the transitive numpy downgrade (2.5.0 → 2.4.6) triggered by numba's pin, after confirming via `pip check` that no other installed package requires numpy>=2.5.

## Deviations from Plan

None — plan executed exactly as written. No auto-fixes were needed or applied.

## Issues Encountered

None. The install completed cleanly with prebuilt wheels; no compiler/CUDA/VC++ dependency was triggered, as predicted by 04-RESEARCH.md.

## User Setup Required

None further — the one-time human legitimacy checkpoint (Task 1) was the only manual step required by this plan, and it has been completed.

## Next Phase Readiness

- Ready. Downstream plans (04-02, 04-03) can now lazy-import `cv2` and `librosa` from the project `.venv` for boundary analysis. The base install still works without them being imported anywhere yet, preserving Fail-open until 04-03 wires them in with its own degrade-on-absence handling.
- No blockers.

---
*Phase: 04-context-driven-transitions*
*Completed: 2026-07-09*

## Self-Check: PASSED

- FOUND: commit 141c685 (Task 2)
- FOUND: commit 65f3c5d (Task 1 checkpoint)
- FOUND: requirements.txt with opencv-python-headless>=5.0 and librosa>=0.11 entries
