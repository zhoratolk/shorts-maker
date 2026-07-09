---
phase: 6
slug: tiktok-instagram-auto-publish
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-07-09
---

# Phase 6 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.1.1 (`python -m pytest --version`) |
| **Config file** | `pyproject.toml` (`[tool.pytest.ini_options]`, `pythonpath=["."]`, `testpaths=["tests"]`, `integration` marker) |
| **Quick run command** | `python -m pytest tests/test_tiktok_publish.py tests/test_instagram_publish.py -x --basetemp=D:/shorts-maker/.pytest-tmp` |
| **Full suite command** | `python -m pytest --basetemp=D:/shorts-maker/.pytest-tmp` |
| **Estimated runtime** | ~30-60s non-integration; no real-network integration tests planned (both platforms' live APIs require real OAuth consent, unsuitable for CI/local automated runs) |

---

## Sampling Rate

- **After every task commit:** `python -m pytest tests/test_tiktok_publish.py tests/test_instagram_publish.py -x --basetemp=D:/shorts-maker/.pytest-tmp`
- **After every plan wave:** `python -m pytest --basetemp=D:/shorts-maker/.pytest-tmp` (full suite)
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 60 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 06-01-01 | 06-01 | 1 | PUB-06 | V5 | `video/init` request body built with `FILE_UPLOAD` source, correct `post_info`/`source_info` shape | unit | `pytest tests/test_tiktok_publish.py::test_init_direct_post_body -x` | ❌ W0 | ⬜ pending |
| 06-01-02 | 06-01 | 1 | PUB-06 | — | Chunked PUT loop sends correct `Content-Range` headers, covers whole file (fake HTTP layer) | unit | `pytest tests/test_tiktok_publish.py::test_upload_video_chunks -x` | ❌ W0 | ⬜ pending |
| 06-01-03 | 06-01 | 1 | PUB-06 | — | `creator_info/query` gating check (D-05): `is_still_gated=True` when `PUBLIC_TO_EVERYONE` absent from `privacy_level_options` | unit | `pytest tests/test_tiktok_publish.py::test_check_tiktok_publish_gate_self_only -x` | ❌ W0 | ⬜ pending |
| 06-01-04 | 06-01 | 1 | PUB-06 | — | Dry-run default: `publish.tiktok_enabled=false` makes no HTTP call | unit | `pytest tests/test_tiktok_publish.py::test_dry_run_default_no_upload -x` | ❌ W0 | ⬜ pending |
| 06-01-05 | 06-01 | 1 | PUB-06 | V5 | Queue idempotency — write-ahead status before `video/init`, no re-upload on retry | unit | `pytest tests/test_tiktok_publish.py::test_idempotent_retry_no_duplicate -x` | ❌ W0 | ⬜ pending |
| 06-02-01 | 06-02 | 2 | PUB-07 | V5 | Resumable-container creation body (`media_type=REELS`, `upload_type=resumable`) | unit | `pytest tests/test_instagram_publish.py::test_create_resumable_container -x` | ❌ W0 | ⬜ pending |
| 06-02-02 | 06-02 | 2 | PUB-07 | — | Local-file upload POSTs to `rupload.facebook.com`, correct `offset`/`file_size` headers | unit | `pytest tests/test_instagram_publish.py::test_upload_local_video -x` | ❌ W0 | ⬜ pending |
| 06-02-03 | 06-02 | 2 | PUB-07 | — | Publish only fires after `status_code == FINISHED`, never before | unit | `pytest tests/test_instagram_publish.py::test_poll_then_publish_sequencing -x` | ❌ W0 | ⬜ pending |
| 06-02-04 | 06-02 | 2 | PUB-07 | — | Dry-run default: `publish.instagram_enabled=false` makes no HTTP call | unit | `pytest tests/test_instagram_publish.py::test_dry_run_default_no_upload -x` | ❌ W0 | ⬜ pending |
| 06-03-01 | 06-03 | 3 | PUB-06, PUB-07 | — | Isolation: killing/pausing a TikTok entry never touches `queue.json` (YouTube) or `instagram_queue.json`, and vice versa (Success Criterion 3) | unit | `pytest tests/test_tiktok_publish.py tests/test_instagram_publish.py -k isolation -x` | ❌ W0 | ⬜ pending |
| 06-03-02 | 06-03 | 3 | V4 | V4 | Scope-minimization: authorize-URL construction sites request only the documented minimal scopes per platform, not broader | unit | `pytest tests/test_tiktok_publish.py tests/test_instagram_publish.py -k scope -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

*(Exact task IDs/waves are illustrative — final numbering set by the planner; this table's requirement→test mapping is the binding contract.)*

---

## Wave 0 Requirements

- [ ] `tests/test_tiktok_publish.py` — new file, covers PUB-06 (all rows above), following `tests/test_publish_queue.py`'s hand-written-fake HTTP-layer convention (no `unittest.mock`/`pytest-mock`)
- [ ] `tests/test_instagram_publish.py` — new file, covers PUB-07 (all rows above), same fake-HTTP-layer convention
- [ ] Consider a shared `conftest.py`-level fake-`requests`-session fixture given three modules now need HTTP test doubles (`publish_queue.py`, `tiktok_publish.py`, `instagram_publish.py`) — planner's discretion, not a hard requirement
- [ ] No new test-framework install needed — pytest and its `integration` marker are already configured

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Real OAuth consent flow completes and issues a working token for each platform | PUB-06, PUB-07 | Requires live browser interaction + real developer app credentials, not mockable | Run the one-time interactive consent helper for each platform, confirm a token file is written and a subsequent dry-run queue check succeeds |
| TikTok `SELF_ONLY` gating reflects the account's actual real-world audit status | PUB-06 | Depends on TikTok's live audit approval state for this specific developer app, not something a test double can simulate meaningfully | After filing/completing the TikTok audit, run `check_tiktok_publish_gate` against the real account and confirm it matches the Content Posting API dashboard's stated status |
| Instagram Standard-vs-Advanced-Access applicability (Open Question 1) | PUB-07 | Requires reading this project's actual Meta app dashboard, which only the user can access | User confirms in the Meta App Dashboard whether App Review is actually required for publishing to their own linked Instagram Business account before the planner locks the review-gated design |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
