---
phase: 07-profanity-auto-bleep
verified: 2026-07-11T10:45:57Z
status: passed
score: 3/3 must-haves verified
behavior_unverified: 0
overrides_applied: 0
---

# Phase 7: Profanity Auto-Bleep Verification Report

**Phase Goal:** Swear words detected in the Whisper transcript are masked with a quiet overlay tone at render time — audio keeps flowing (no dead silence gap) but the profanity itself is hard to hear and hard for platform speech-to-text moderation/demonetization scanners to pick up.

**Verified:** 2026-07-11T10:45:57Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth (ROADMAP Success Criterion) | Status | Evidence |
|---|---|---|---|
| 1 | Swear words present in the Whisper word-level transcript are identified for every clip going into `render.py` | ✓ VERIFIED | `scripts/profanity.py::find_profane_spans` (RU/EN stems + obfuscation normalization via `normalize_word`, word-boundary regex via `compile_patterns`), fail-open on load/cap. Wired into `.claude/skills/make-shorts/SKILL.md` step 5 (single clip) and step 5b bullet 7 (compilation), gated on `config.profanity.enabled` independent of `config.subtitles.enabled` (D-04). 19 unit tests in `tests/test_profanity.py`, all green. |
| 2 | Each identified swear word's audio span gets a quiet overlay tone applied instead of being cut to silence or left untouched — audio keeps playing underneath | ✓ VERIFIED | `scripts/render.py::build_profanity_mask_filter` (duck+bandreject+tremolo, `enable`-gated timeline expression, never silence) and `build_profanity_sound_filter` (mute span + overlay custom censor clip, quick-task 260711-id0's `mask_mode="sound"`) — both keep audio flowing, neither is a hard cut. `build_audio_filter_chain` inserts the mask after `loudnorm`/before `afade`; `profanity_filter=None` (default/disabled) leaves the chain byte-identical (confirmed by reading the conditional-append logic at scripts/render.py:404-425). Real-ffmpeg integration test `test_profanity_mask_measurably_ducks_loudness_inside_span` re-run live in this verification — **PASSED** (measured loudness delta, audio still present inside span). |
| 3 | The masked span is quiet/garbled enough that a platform's STT moderation pass would not transcribe the word cleanly, without being so loud/abrupt that it reads as an obvious edit | ✓ VERIFIED | Automated proxy: real-ffmpeg + real faster-whisper integration test `test_profanity_defeats_transcription` re-run live in this verification — **PASSED** (masked word no longer cleanly re-transcribes). Subjective "doesn't sound like an obvious edit" half is a human-judgment gate — **already signed off** in `07-05-SUMMARY.md` ("маска принимается", both garble and sound modes approved, config.yaml retuned to validated stronger values). Not re-flagged per task instructions. |

**Score:** 3/3 truths verified (0 present-but-behavior-unverified)

### Required Artifacts

| Artifact | Expected | Status | Details |
|---|---|---|---|
| `scripts/profanity.py` | `load_wordlist`, `normalize_word`, `compile_patterns`, `find_profane_spans`, CLI `main()` | ✓ VERIFIED | All functions present, substantive (not stubs), fail-open on malformed wordlist and span-count cap. `--onset-seconds`/`--max-spans` CLI flags present (quick-task addition). |
| `data/profanity_wordlist.yaml` | Committed RU+EN stem wordlist + obfuscation-normalization block | ✓ VERIFIED | 6 RU + 4 EN stems, `normalize:` block (substitutions/collapse_repeats/strip_chars), `updated:` stamp. No placeholder content. |
| `scripts/render.py` | `build_profanity_mask_filter`, extended `build_audio_filter_chain`, `render_clip` reading `profanity_spans`, 7 `--profanity-*` CLI flags | ✓ VERIFIED | Confirmed present and threaded through plain/jumpcut/compilation branches (grep at scripts/render.py:316-1375). Plus `build_profanity_sound_filter` (quick-task addition), fully wired with fail-open fallback to garble on missing sound file. |
| `scripts/config.py` | `ProfanityConfig` dataclass, default-off, fail-open, range-validated | ✓ VERIFIED | `enabled: bool = False` (scripts/config.py:226), 10 fields total (9 original + quick-task's `mask_mode`/`mask_sound_path`/`mask_onset_seconds` split across 2 new — actually 9 base + 3 new = matches SUMMARY), 10 `_validate` invariants including `mask_mode` enum check and `mask_mode=="sound"` requires non-empty `mask_sound_path`. |
| `tests/test_profanity.py`, `tests/test_render.py`, `tests/test_config.py`, `tests/test_integration_ffmpeg.py` | Unit + integration coverage per Per-Task Verification Map | ✓ VERIFIED | All present, substantive, exercised (see Behavioral Spot-Checks below). |

### Key Link Verification

| From | To | Via | Status | Details |
|---|---|---|---|---|
| `scripts/profanity.py::find_profane_spans` output | `SKILL.md` step 5/5b `profanity_spans` field | CLI stdout JSON, recorded verbatim into `PLAN.json` | ✓ WIRED | SKILL.md lines 173-179 (single clip), 245-249 (compilation) — both fail-open, both independent of `config.subtitles.enabled`. |
| `PLAN.json`'s `profanity_spans` | `scripts/render.py::render_clip` | `plan_entry.get("profanity_spans")` | ✓ WIRED | scripts/render.py:1096 reads the field; threaded into plain/jumpcut/compilation branches (5 render_clip masking tests in tests/test_render.py all green). |
| `build_profanity_mask_filter`/`build_profanity_sound_filter` | `build_audio_filter_chain` | Ordering: after `loudnorm`, before `afade` | ✓ WIRED | scripts/render.py:404-425; ordering explicitly load-bearing per comment (loudnorm's gain-riding must not undo the duck) — 2 ordering tests green. |
| `config.profanity.*` | `SKILL.md` step 6 `render.py` CLI invocation | `--profanity-duck-volume`/`--profanity-garble-*`/`--profanity-mask-mode`/`--profanity-mask-sound-path` flags | ✓ WIRED | SKILL.md:303 passes all 7 flags regardless of `enabled` (harmless no-op convention, matches transitions pattern). |
| `config.profanity.mask_mode="sound"` + missing `mask_sound_path` file | Fail-open to garble mask | `render_clip` existence check | ✓ WIRED | scripts/render.py:1105-1113, proven by `test_render_clip_sound_mode_missing_file_falls_back_to_garble`. |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|---|---|---|---|
| Full non-integration suite green (regression check, includes quick-task additions) | `python -m pytest tests/ -m "not integration" --basetemp=work/_pytest -q` | 614 passed, 11 deselected, 0 failed | ✓ PASS |
| Real-ffmpeg loudness ducking (AUDIO-02) | `pytest tests/test_integration_ffmpeg.py::test_profanity_mask_measurably_ducks_loudness_inside_span -m integration` | 1 passed | ✓ PASS |
| Real-ffmpeg + real faster-whisper STT-defeat (AUDIO-03 automated proxy) | `pytest tests/test_integration_ffmpeg.py::test_profanity_defeats_transcription -m integration` | 1 passed | ✓ PASS |
| No debt markers in phase files | `grep -nE "TBD|FIXME|XXX|TODO|HACK|PLACEHOLDER|not.{0,4}implemented" scripts/profanity.py scripts/render.py scripts/config.py data/profanity_wordlist.yaml` | no matches | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan(s) | Description | Status | Evidence |
|---|---|---|---|---|
| AUDIO-01 | 07-01, 07-03, 07-04 | Detect profane spans in transcript | ✓ SATISFIED | `find_profane_spans` + SKILL.md wiring, 19 unit tests |
| AUDIO-02 | 07-02, 07-03, 07-04 | Mask with duck (audio keeps flowing, no silence cut) | ✓ SATISFIED | `build_profanity_mask_filter`/`build_profanity_sound_filter` + real-ffmpeg loudness-delta proof |
| AUDIO-03 | 07-02, 07-04, 07-05 | Garbled enough to defeat STT, not an obvious edit | ✓ SATISFIED | Automated STT-defeat proxy passed + human checkpoint sign-off (07-05-SUMMARY.md) |

No orphaned requirements found in REQUIREMENTS.md mapped to Phase 7 beyond AUDIO-01/02/03.

### Anti-Patterns Found

None blocking. One data-quality self-documented caveat in `data/profanity_wordlist.yaml` line 36 ("NOTE: broad stem — validate against real transcripts for false positives") is an intentional in-data annotation about wordlist tuning, not a code debt marker (no TBD/FIXME/XXX), and does not block masking — false positives only cause extra (harmless) masking, never a missed render.

### Fail-Open / Default-Off Regression Check (quick task 260711-id0 scope growth)

Verified the quick task's additions (`mask_mode`, `mask_sound_path`, `mask_onset_seconds`) did not regress the phase's core must-haves:
- `ProfanityConfig.enabled` still defaults to `False` (scripts/config.py:226) — feature remains opt-in.
- `mask_mode` defaults to `"garble"` and `mask_onset_seconds` defaults to `0.0` — both reproduce the original pre-quick-task behavior byte-for-byte when left at defaults (confirmed in code comments and `test_load_config_profanity_defaults_when_section_missing`).
- Sound-mode fail-open path (missing/empty `mask_sound_path` at render time) falls back to the garble mask rather than raising — `test_render_clip_sound_mode_missing_file_falls_back_to_garble` passes.
- Full regression suite (614 tests) green after the quick task's changes.

### Human Verification Required

None. AUDIO-03's subjective mask-quality gate was already completed and signed off in `07-05-SUMMARY.md` (human listened to garble and sound-overlay variants, approved both — "маска принимается"). Not re-flagged per task instructions.

### Gaps Summary

No gaps found. All three ROADMAP success criteria are verified against actual code (not just SUMMARY claims), backed by live-rerun integration tests against real ffmpeg and real faster-whisper, plus a full green regression suite (614 non-integration tests). The phase goal — profane spans detected, masked with a non-silent duck+garble or custom-sound overlay, defeats an automated STT proxy, and is gated behind a fail-open default-off config — is achieved in the codebase.

**Minor documentation note (non-blocking):** `.planning/ROADMAP.md`'s Phase 7 table still shows "4/5" plans complete / "In Progress" and the `07-05-PLAN.md` checkbox is unchecked, even though `07-05-SUMMARY.md` documents the checkpoint as `status: complete` with human sign-off obtained. This is a roadmap bookkeeping lag, not a functional gap — recommend updating ROADMAP.md's phase-7 row/checkbox to reflect 5/5 complete.

---

_Verified: 2026-07-11T10:45:57Z_
_Verifier: Claude (gsd-verifier)_
