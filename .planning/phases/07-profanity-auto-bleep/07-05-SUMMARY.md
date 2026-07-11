---
phase: 07-profanity-auto-bleep
plan: 05
subsystem: human-checkpoint
tags: [checkpoint, human-verify, audio-quality, profanity]

requires:
  - phase: 07-profanity-auto-bleep (Plans 01-04)
    provides: full profanity auto-bleep feature (detection, duck+garble mask, config, integration tests)
provides:
  - "Human sign-off on masking quality (AUDIO-03 / D-03) — approved with retuned values"
  - "Retuned config.yaml profanity values + two new mask capabilities (quick task 260711-id0)"
affects: []

tech-stack:
  added: []
  patterns: []

key-files:
  created: []
  modified:
    - config.yaml (gitignored, disk-only — retuned values below)

key-decisions:
  - "Shipped default garble parameters (1800/4/18/0.7) empirically FAIL to defeat faster-whisper re-transcription on both EN ('stupid', Plan 07-04) and RU ('пиздец', this checkpoint) test words — the operator's config.yaml now carries the stronger validated set (garble_freq=1200, garble_width_octaves=6, warble_freq=25, warble_depth=1.0). Code defaults left unchanged (07-03 exact-value tests)."
  - "Onset audibility (TV-bleep style, first letters audible) validated: onset <= ~0.12s preserves STT-defeat (whisper heard 'пить'); 0.20s/0.28s leak the full word. Shipped as mask_onset_seconds via quick task 260711-id0."
  - "User requested and approved a second mask mode: custom censor sound (mute word + overlay user-supplied clip, trimmed/looped per span). Validated live (whisper output dropped the word entirely), shipped as mask_mode=sound via quick task 260711-id0."

requirements-completed: [AUDIO-03]

duration: interactive checkpoint (spanned demo generation + quick task 260711-id0)
completed: 2026-07-11
status: complete
---

# Phase 7 Plan 5: Human Listening Checkpoint Summary

**Human sign-off obtained on the profanity mask ("маска принимается" — both modes approved). AUDIO-03's subjective bar is met; final masking parameters locked into the operator's config.yaml.**

## Checkpoint Protocol

F: drive (real stream recordings) was offline during the checkpoint, so listening validation ran on a real-speech SAPI TTS fixture (Russian, Microsoft Irina, sentence containing «пиздец») rendered through the real production pipeline (`scripts/profanity.py` detection → `build_profanity_mask_filter` / sound-overlay ffmpeg graph). Demo artifacts in `work/_profanity_demo/` (gitignored).

## What the Human Heard and Approved

1. `demo_masked_strong.wav` — garble mask with stronger-than-default values; whisper re-transcription drops the word entirely.
2. `demo_masked_onset_120ms.wav` — same strong garble with the word's first ~0.12s audible (TV-bleep style); whisper hears «пить», not the swear.
3. `demo_masked_sound.wav` — word muted, user's own censor clip overlaid (trimmed to span). Whisper drops the word.

Verdict: **approved** («ладно маска принимается, оба варианта что щас есть доделывай»).

## Empirical Findings Recorded

| Variant | Whisper re-transcription of masked span |
|---|---|
| shipped defaults (1800/4/18/0.7) | «пиздец» — **mask defeated** (confirms 07-04's EN finding on RU) |
| strong (1200/6/25/1.0) | word gone |
| strong + onset 0.12s | «пить» (mangled) |
| strong + onset 0.20s / 0.28s | «пиздец» — **leak**; onset must stay ≤ ~0.12s |
| sound mode (mute + overlay) | word gone |

## Final Locked Values (operator's config.yaml, gitignored)

```yaml
profanity:
  enabled: true
  mask_mode: "sound"            # operator's choice; garble остаётся фолбэком
  mask_sound_path: "<local censor clip, user-selected>"
  mask_onset_seconds: 0.12
  garble_freq: 1200.0           # strong set — shipped code defaults unchanged
  garble_width_octaves: 6.0
  warble_freq: 25.0
  warble_depth: 1.0
```

## Follow-on Work Spawned by This Checkpoint

Quick task **260711-id0-garble-onset** (commits `6d5561b`..`025771d`, docs `dfd4424`): `mask_mode` (garble|sound), `mask_sound_path`, `mask_onset_seconds` — config schema + validation, onset-shifted detection, sound-censor render path (mute + amix overlay, aloop for short clips), fail-open sound→garble fallback, 12 new unit tests. Suite: 609 passed / 5 skipped.

## Deviations from Plan

- Checkpoint ran on a TTS fixture instead of a real stream recording (F: drive offline). The mask mechanics, STT-defeat, and subjective quality were still validated on genuine human-like speech through the production code path; a real-clip spot-check remains advisable once the drive is back, but AUDIO-03's gate (human judgment on mask quality) is satisfied.
- The checkpoint produced scope growth (onset + sound mode) — routed through a proper quick task rather than folded into this plan (files_modified: [] preserved).

---
*Phase: 07-profanity-auto-bleep*
*Completed: 2026-07-11*
