# Phase 4: Context-Driven Transitions - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-08
**Phase:** 4-Context-Driven-Transitions
**Areas discussed:** Aggressiveness, Visibility, Transition type coverage

---

## Aggressiveness

| Option | Description | Selected |
|--------|-------------|----------|
| Консервативно | Fancy переход только при сильном/явном сигнале (резкий скачок движения или звука); по умолчанию — обычный cut | ✓ |
| Агрессивно | Пытаться подобрать не-cut переход почти на каждом стыке, если хоть какой-то сигнал есть | |
| Настраиваемый порог в config.yaml | Числовой threshold в конфиге, пользователь сам крутит агрессивность позже | |

**User's choice:** Консервативно (Recommended)
**Notes:** Приоритет — не сделать монтаж шумным/переперегруженным на длинном геймплейном видео с частыми jumpcuts.

---

## Visibility

| Option | Description | Selected |
|--------|-------------|----------|
| Полностью автоматически | Как punch-zoom/jumpcuts сейчас — Claude сам решает, никакого доп. review-шага | ✓ |
| Показывать в PLAN.json, можно вручную поправить | Тип перехода на каждый стык записывается явно в план перед рендером — можно попросить Claude заменить, если не нравится результат | |

**User's choice:** Полностью автоматически (Recommended)
**Notes:** Соответствует текущему flow пайплайна — не добавлять новый review-гейт.

---

## Transition type coverage

| Option | Description | Selected |
|--------|-------------|----------|
| Все 6 ОК, Claude сам решает где что уместно | Никаких исключений — набор из TRANS-02 используется полностью | ✓ |
| Есть конкретные исключения/приоритеты | Назвать конкретный тип(ы), который не хочется видеть, или наоборот — что должно встречаться чаще остальных | |

**User's choice:** Все 6 ОК, Claude сам решает где что уместно (Recommended)
**Notes:** Нет возражений по геймплейному контенту ни к одному из 6 типов.

## Claude's Discretion

- Числовые пороги/scoring-формула для "сильный сигнал vs cut" (D-02).
- Маппинг конкретного паттерна сигнала на конкретный тип перехода (D-04).
- ffmpeg filter-graph реализация каждого из 6 типов.
- Fail-open поведение при отсутствии opencv/librosa — не поднималось как отдельный вопрос, напрямую следует из уже действующего constraint "Fail-open" в PROJECT.md.

## Deferred Ideas

None.
