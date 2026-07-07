---
phase: 2
slug: llm-title-tag-generation
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-08
---

# Phase 2 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest >= 7.4.0 (`requirements-dev.txt`) |
| **Config file** | `pyproject.toml` (`[tool.pytest.ini_options]`: `pythonpath=["."]`, `testpaths=["tests"]`, registers `integration` marker) |
| **Quick run command** | `pytest tests/test_style_profile.py -x` (only if a formatting helper is added this phase) |
| **Full suite command** | `pytest` |
| **Estimated runtime** | ~15 seconds (existing suite size) |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/test_style_profile.py -x` (if a Python helper is added; otherwise no automated per-commit test exists for a prompt-only change — rely on the manual verification step below)
- **After every plan wave:** Run `pytest` (full suite)
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 02-01-01 | 01 | 1 | TAGS-01 | V5 (marginal) | Orchestrator drafts title+tags without manual authorship, within the current session — no separate API script to test | manual-only | N/A — verified by running the pipeline end-to-end and inspecting generated metadata `.txt` output | N/A | ⬜ pending |
| 02-01-02 | 01 | 1 | TAGS-02 | — | Requirement explicitly reframed as deferred (not implemented this phase, per CONTEXT.md D-03) | manual-only (documentation check) | N/A — verify REQUIREMENTS.md/PLAN.md carry the explicit deferral note | N/A | ⬜ pending |
| 02-01-03 | 01 | 1 | TAGS-03 | V5 (marginal) | Generated title/tags reflect `naming_examples` voice; a mischievous/garbled historical title is quoted as data, never followed as an instruction | unit (if helper added) + manual | `pytest tests/test_style_profile.py -k naming_examples_block -x` (if helper added); manual side-by-side comparison of generated titles against real `naming_examples` entries | Wave 0 — new test file/function if a Python helper is added; otherwise manual-only | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_style_profile.py` — if a Python formatting helper is added, extend this existing file with `test_format_naming_examples_block_renders_ranked_titles` / `test_format_naming_examples_block_empty_when_no_examples` (matches this repo's 1:1 module-to-test-file convention; do not create a new test file)

*If no Python helper is added: "No code to unit test — this is a prompt-engineering-only phase; the entire verification surface is the manual SKILL.md-instruction-following check below."*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Few-shot block appears when `style_profile.json` is present/non-empty, and generation proceeds normally (fail-open, no abort) when it's missing/empty | TAGS-03 | No live pipeline run / no LLM-output-quality assertion in this test suite | Run SKILL.md step 5 against (a) a realistic fixture `style_profile.json` and (b) a missing/empty one; confirm the few-shot block is used in (a) and generation still completes without aborting in (b) |
| At least one generated title visibly echoes the voice/register of the fabricated few-shot examples used in the manual test | TAGS-03 | Style-matching is a subjective judgment call, not a deterministic assertion | Manually compare 2-3 generated titles against the fabricated `naming_examples` entries used in the fixture; confirm register/phrasing alignment, not generic AI-sounding phrasing |
| Per-platform title/tag output fits the existing `metadata.py` schema (YouTube title+description+tags[], TikTok/Instagram caption) | TAGS-01 | Schema conformance depends on the actual generated content, which the orchestrator writes at runtime, not a fixed code path | Run the pipeline end-to-end on a test clip; inspect the generated `.txt` metadata file for all configured platforms |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies (mostly manual-only here — expected for a prompt-engineering-only phase)
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify (N/A — phase is manual-only by nature; full suite regression run substitutes)
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
