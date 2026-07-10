# Phase 7: Profanity Auto-Bleep - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-11
**Phase:** 7-profanity-auto-bleep
**Areas discussed:** Wordlist source, Overlay tone character, Config toggle

---

## Wordlist source

| Option | Description | Selected |
|--------|-------------|----------|
| Hardcoded RU+EN list in code/data-file | data/monetization_rules.yaml-style, redactable, no external services | |
| Только RU | Only Russian obscenities, no English needed | |
| RU+EN with obfuscation support (ё*, бл*) | Base list plus typical creator obfuscations/stem patterns | ✓ |

**User's choice:** RU+EN with obfuscation support.
**Notes:** Matching stays deterministic (regex/stem), no LLM-nuance tier — mirrors MONET-02 precedent.

---

## Overlay tone character

| Option | Description | Selected |
|--------|-------------|----------|
| Тихий синус-бип | Fixed-frequency classic censor beep, quiet, defeats STT | |
| Приглушение громкости слова + лёгкий шум | Duck word volume + light noise/garble overlay instead of clean beep | ✓ |
| Дай сам выбрать / опиши свой вариант | User to specify exact sound | |

**User's choice:** Duck volume + light noise.
**Notes:** Exact ffmpeg filter values (duck depth, noise level) left to Claude's discretion, to be validated empirically during implementation.

---

## Config toggle

| Option | Description | Selected |
|--------|-------------|----------|
| New config.yaml section, fail-open, default off | Same pattern as diarization/audio_energy | ✓ |
| Всегда включено по умолчанию | Mandatory pre-publish step, always on | |

**User's choice:** New fail-open config section, default off.
**Notes:** Consistent with PROJECT.md's fail-open constraint for optional features.

---

## Claude's Discretion

- Exact regex/matching implementation for obfuscation handling.
- Precise ffmpeg filter graph for duck+noise masking (new per-span filter capability in `render.py`).
- Whether detection is a new standalone script (`scripts/profanity.py`) or folded elsewhere.
- Word-boundary matching strictness to avoid false positives.

## Deferred Ideas

None — discussion stayed within phase scope.
