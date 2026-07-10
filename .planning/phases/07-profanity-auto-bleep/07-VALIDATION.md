---
phase: 7
slug: profanity-auto-bleep
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-07-11
---

# Phase 7 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest>=7.4.0 (`requirements-dev.txt`) |
| **Config file** | `pyproject.toml` (`[tool.pytest.ini_options]`: `pythonpath=["."]`, `testpaths=["tests"]`, `integration` marker) |
| **Quick run command** | `pytest -m "not integration" tests/test_profanity.py tests/test_render.py -x` |
| **Full suite command** | `pytest tests/ -x` (includes `integration`-marked real-ffmpeg smoke tests, self-skip if ffmpeg/ffprobe not on PATH) |
| **Estimated runtime** | ~5-10s quick, ~30-60s full (faster-whisper self-transcription check adds real model load time — see Sampling Rate) |

---

## Sampling Rate

- **After every task commit:** `pytest -m "not integration" tests/test_profanity.py tests/test_render.py tests/test_config.py -x`
- **After every plan wave:** `pytest tests/ -x` (full suite including `integration`-marked real-ffmpeg tests — the `volumedetect`-based loudness-delta assertion is cheap, sub-second synthetic audio)
- **Before `/gsd-verify-work`:** Full suite must be green. The `faster-whisper` self-transcription check (AUDIO-03's strongest automated proxy for "defeats STT") loads a real Whisper model — run at phase gate, not every wave merge.
- **Max feedback latency:** 60 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 07-01-01 | 07-01 | 1 | AUDIO-01 | V5 | `find_profane_spans` matches RU/EN stems + obfuscated spellings, rejects false-positive substrings (word-boundary regex, `re.escape()` on every wordlist entry) | unit | `pytest tests/test_profanity.py -k detect -x` | ❌ W0 | ⬜ pending |
| 07-01-02 | 07-01 | 1 | AUDIO-01 | — | Detected spans survive `jumpcuts.remap_words` correctly — a word cut by a jump-cut gap is silently absent from the span list | unit | `pytest tests/test_profanity.py -k remap -x` | ❌ W0 | ⬜ pending |
| 07-01-03 | 07-01 | 1 | AUDIO-01 | Malformed-wordlist DoS | `load_wordlist` fail-open: malformed/missing YAML degrades to empty wordlist + warns, never raises | unit | `pytest tests/test_profanity.py -k load_wordlist -x` | ❌ W0 | ⬜ pending |
| 07-02-01 | 07-02 | 2 | AUDIO-02 | — | `build_profanity_mask_filter` produces the expected `enable`-gated clause string (exact-string assertion) | unit | `pytest tests/test_render.py -k profanity_mask_filter -x` | ❌ W0 | ⬜ pending |
| 07-02-02 | 07-02 | 2 | AUDIO-02 | — | `build_audio_filter_chain` inserts the mask clause in correct order (after `loudnorm`, before `afade`) | unit | `pytest tests/test_render.py -k profanity_filter_chain_order -x` | ❌ W0 | ⬜ pending |
| 07-02-03 | 07-02 | 2 | AUDIO-02 | Span-count DoS | `max_masked_spans_per_clip` cap enforced — pathologically many spans triggers fail-open skip+warn, never blocks render | unit | `pytest tests/test_profanity.py -k span_cap -x` | ❌ W0 | ⬜ pending |
| 07-03-01 | 07-03 | 3 | AUDIO-02 | — | A rendered clip with `profanity_spans` set has measurably lower loudness inside the span vs. outside (real ffmpeg, `volumedetect`) | integration | `pytest tests/test_integration_ffmpeg.py -k profanity -m integration -x` | ❌ W0 | ⬜ pending |
| 07-03-02 | 07-03 | 3 | AUDIO-03 | — | Masked span, re-transcribed via faster-whisper, no longer recognizably transcribes to the original word (self-check proxy for "defeats STT") | integration (slow) | `pytest tests/test_integration_ffmpeg.py -k profanity_defeats_transcription -m integration -x` | ❌ W0 | ⬜ pending |
| 07-04-01 | 07-04 | 4 | AUDIO-01/02/03 | — | `ProfanityConfig` dataclass validation (fail-open, mirrors `DiarizationConfig`/`AudioEnergyConfig`) | unit | `pytest tests/test_config.py -k profanity -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

*(Exact task IDs/waves are illustrative — final numbering set by the planner; this table's requirement→test mapping is the binding contract.)*

---

## Wave 0 Requirements

- [ ] `tests/test_profanity.py` — new file, covers AUDIO-01 (mirrors `tests/test_monetization_risk.py`'s structure: `load_wordlist` fail-open behavior, `normalize_word` obfuscation cases, `find_profane_spans` boundary/merge/padding logic, `max_masked_spans_per_clip` cap)
- [ ] `tests/test_render.py` additions — covers AUDIO-02 (`build_profanity_mask_filter` string-assertion tests, `build_audio_filter_chain` ordering test, `render_clip` reading `plan_entry["profanity_spans"]`)
- [ ] `tests/test_integration_ffmpeg.py` additions — covers AUDIO-02/AUDIO-03 (real-ffmpeg loudness-delta assertion via `volumedetect`; optional `faster-whisper` self-transcription check for AUDIO-03, gated `integration`)
- [ ] `tests/test_config.py` additions — `ProfanityConfig` dataclass validation
- [ ] No new test-framework install needed — pytest/PyYAML already present

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|--------------------|
| Final duck/garble parameter values sound acceptable (quiet enough, not an abrupt-sounding cut) on a real rendered clip | AUDIO-03, D-03 | Subjective audio-quality judgment — no automated proxy fully captures "doesn't sound like an obvious edit" | Render one real clip with `profanity.enabled=true` against a source video with known swear words; listen to the output; confirm the mask is audible-but-hard-to-parse and doesn't read as a hard cut. Adjust duck depth / noise level in config if not satisfied. |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
