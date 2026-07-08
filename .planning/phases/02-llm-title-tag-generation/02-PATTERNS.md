# Phase 2: LLM Title/Tag Generation - Pattern Map

**Mapped:** 2026-07-07
**Files analyzed:** 3 (1 Markdown orchestration edit, 1 optional Python helper + its test, 1 optional docs edit)
**Analogs found:** 3 / 3

<domain_note>
This phase is **prompt-engineering / Markdown authoring**, not conventional software engineering (confirmed by CONTEXT.md D-01/D-02 and RESEARCH.md Summary). There is no controller/component/service in the usual sense — the "files to modify" are `SKILL.md` (orchestrator instructions), optionally `scripts/style_profile.py` (a tiny pure-function helper), and `docs/metadata-writing-ru.md`. Pattern-matching below is calibrated to that reality: the "closest analog" for a Markdown instruction change is the *existing* instruction section it extends, not a random code file.
</domain_note>

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `SKILL.md` (step 5, "Per-platform metadata" section, ~lines 165-181) | orchestrator-instruction (Markdown prompt) | transform (read local JSON → inject into drafting instructions → write JSON) | `SKILL.md` "Real channel performance (optional)" section (~lines 212-214) | exact — same shape: read an optional local JSON cache, fail-open if absent, use as a grounding "lens" for a judgment call the orchestrator already makes |
| `scripts/style_profile.py::format_naming_examples_block` (optional new function) | utility (pure transform) | transform (dict → formatted text block) | `scripts/style_profile.py::derive_profile` (same file, lines 40-66) | exact — same file, same fail-open pure-function convention, same docstring style |
| `tests/test_style_profile.py` (new test functions, if helper added) | test | transform | `tests/test_style_profile.py::test_derive_profile_empty_input_fails_open` (lines 82-87) | exact — same file, same fail-open assertion pattern |
| `docs/metadata-writing-ru.md` (optional addition: few-shot injection guidance) | config/docs (guidance consumed by orchestrator) | transform (reference doc read by SKILL.md step 5) | `docs/metadata-writing-ru.md` itself, "Hook (first line...)" section (lines 17-38) | exact — same file, same "table/example then apply-instruction" structure |

## Pattern Assignments

### `SKILL.md` step 5 edit (orchestrator-instruction, transform)

**Analog:** `SKILL.md` "Real channel performance (optional)" section, lines 212-214, and step 5's own existing per-platform metadata block, lines 165-181.

**Fail-open read pattern to copy** (lines 212-214):
```text
If `<config.output_dir>/analytics/channel_performance.json` exists (produced by
`python scripts/youtube_analytics.py`, see README — requires one-time OAuth
setup, not run automatically as part of this skill), read it before step 3
when it's present and treat it the same way as [docs/viral-clips-ru.md]
(docs/viral-clips-ru.md): a lens, not a hard filter. ... Don't fetch or
refresh this file yourself as part of the pipeline — it's a manually-run,
occasional snapshot; just read it if it's already there.
```
**What to copy:** the "if `<path>` exists, read it and use it as grounding; if not, proceed exactly as today" phrasing — this is the exact fail-open shape needed for `work/_profile/style_profile.json` + `naming_examples`. Note the existing precedent explicitly frames the optional file as advisory ("a lens, not a hard filter"), matching CONTEXT.md's Pattern 2 (fail-open) requirement precisely.

**Existing per-platform metadata block to extend in place** (lines 165-181):
```text
- **Per-platform metadata** — if `config.metadata.enabled` is `true`, for each
  platform in `config.metadata.platforms` produce:
  - `youtube`: `{"title": ..., "description": ..., "tags": [...]}` ...
  - `tiktok` / `instagram`: `{"caption": "..."}` ...
  ...
  Write the metadata text in `config.metadata.language` ... load
  [docs/metadata-writing-ru.md](docs/metadata-writing-ru.md) and
  [docs/register-ru.md](docs/register-ru.md) and apply both: pick a hook
  formula ... then run the drafted title/description/captions through the
  anti-AI-tone filter and the register rules ...
  **Hook rotation** — track which hook formula ... each clip in this run used.
```
**What to copy/extend:** insert the new few-shot instruction as its own bullet/paragraph immediately before or alongside the existing "load docs/metadata-writing-ru.md ... apply both" instruction — same imperative, second-person-implicit "load X and apply Y" phrasing already used for the anti-AI-tone/register load. Per RESEARCH.md Pitfall 5, place it prominently (not buried after hook-rotation text).

**Suggested insertion point:** directly after the `tiktok`/`instagram` shape bullets (line 167) and before the "If `config.visual.enabled`..." sentence (line 169), so the few-shot grounding is established before game-context/hook-formula/anti-AI-tone instructions layer on top — matches RESEARCH.md's "prominent placement" pitfall avoidance.

---

### `scripts/style_profile.py::format_naming_examples_block` (optional helper) (utility, transform)

**Analog:** same file, `derive_profile` (lines 40-66) and `load_analytics_cache` (lines 13-25) — both establish this file's fail-open, no-exception, docstring-explains-why convention.

**Imports pattern** (lines 1-6, file top — copy verbatim style):
```python
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
```

**Fail-open pure-function pattern to copy** (`derive_profile`, lines 40-66 — docstring + empty-input handling):
```python
def derive_profile(records: list[dict]) -> dict:
    """Derives a structured, concrete few-shot style profile from real
    per-video performance records (STYLE-02). Every example carries an
    actual title string plus its real performance signal - never a prose
    description of "the creator's style" (PITFALL 5). Fails open to a
    valid, empty, correctly-shaped profile when given no records."""
    ranked = sorted(
        (record for record in records if record.get("title")),
        key=_performance_signal,
        reverse=True,
    )
    naming_examples = [
        {"title": record["title"], "signal": _performance_signal(record)}
        for record in ranked[:TOP_N]
    ]
    ...
```
**What to copy:** the docstring convention (state the "why" — cross-reference a PITFALL/requirement ID in a parenthetical), the "returns a valid empty/degenerate shape rather than raising" fail-open convention, and the list-comprehension-over-ranked-records style. RESEARCH.md's own design sketch for `format_naming_examples_block` (lines 259-271 of 02-RESEARCH.md) already follows this shape — use it directly:
```python
def format_naming_examples_block(profile: dict, limit: int = 10) -> str:
    """Renders style_profile.json's naming_examples as a fixed few-shot
    text block for prompt injection. Returns "" when there are no
    examples (fail-open - caller checks for empty string, not exceptions)."""
    examples = profile.get("naming_examples") or []
    if not examples:
        return ""
    lines = [
        f'{i}. "{example["title"]}" (signal: {example["signal"]})'
        for i, example in enumerate(examples[:limit], start=1)
    ]
    return "\n".join(lines)
```

**Error handling pattern to copy** (`load_analytics_cache`, lines 13-25 — warn-and-degrade, never raise):
```python
def load_analytics_cache(cache_path: str) -> list[dict]:
    path = Path(cache_path)
    if not path.exists():
        print(f"[warn] analytics cache not found at {cache_path}; deriving an empty style profile", file=sys.stderr)
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as error:
        print(f"[warn] could not read analytics cache ({error}); deriving an empty style profile", file=sys.stderr)
        return []
```
Apply the same `[warn] ...` to stderr + safe-default-return convention if the helper (or the orchestrator's own Read step) needs to handle a missing/corrupt `style_profile.json`.

---

### `tests/test_style_profile.py` (new tests, if helper added) (test, transform)

**Analog:** same file — `test_derive_profile_empty_input_fails_open` (lines 82-87) and `test_derive_profile_naming_examples_are_concrete_not_prose` (lines 21-40).

**Fail-open test pattern to copy** (lines 82-87):
```python
def test_derive_profile_empty_input_fails_open():
    profile = derive_profile([])

    assert profile["schema_version"] >= 1
    assert profile["naming_examples"] == []
    assert profile["moment_examples"] == []
```
**What to copy:** name new tests `test_format_naming_examples_block_empty_when_no_examples` / `test_format_naming_examples_block_renders_ranked_titles` (matches RESEARCH.md Wave 0 Gaps naming), assert on the exact return value (`""` for empty, not an exception), and reuse the existing `_record(...)` fixture helper (lines 6-18) rather than inventing new fixture data — extend this file, do not create a new one (1:1 module-to-test-file convention per CLAUDE.md Naming Patterns).

**Concrete-not-prose test pattern to copy** (lines 21-40) — if testing that the formatted block contains the literal title string, not a paraphrase:
```python
top = profile["naming_examples"][0]
assert top["title"] in {"Boss Rage Quit Moment", "Clutch 1v5 Ace"}
assert isinstance(top["signal"], (int, float))
```
Use only fabricated titles (`"Boss Rage Quit Moment"`, `"Clutch 1v5 Ace"`) in any new fixture — never a real channel title (RESEARCH.md Pitfall 4 / PROJECT.md privacy incident).

---

### `docs/metadata-writing-ru.md` (optional guidance addition) (docs, transform)

**Analog:** same file, "Hook (first line of the caption / the title itself)" section (lines 17-38).

**Structure to copy** (table + short imperative instruction, lines 17-21):
```text
## Hook (first line of the caption / the title itself)

A hook is ≤7 words, readable in ≤3 seconds. Pick the formula that fits what
actually happened in the clip — don't force one that doesn't match.

| Formula | Fits when the clip has... | Example |
| --- | --- | --- |
...
```
**What to copy:** if adding a "Few-shot grounding from style profile" subsection, mirror this exact structure — short imperative rule, then a compact table/example, then a one-line negative-instruction ("Not a hook: ..." style) warning against the failure mode (here: generic-sounding titles despite grounding, or verbatim copying). Use fabricated example titles only (matches this file's own convention — its examples are Russian phrases invented for illustration, never real channel data).

## Shared Patterns

### Fail-Open (applies to SKILL.md edit + optional helper + optional helper's tests)
**Source:** `SKILL.md` lines 212-214 (Markdown level) + `scripts/style_profile.py::load_analytics_cache` lines 13-25 (Python level) + `tests/test_style_profile.py::test_derive_profile_empty_input_fails_open` lines 82-87 (test level)
**Apply to:** every file this phase touches — the missing/empty `naming_examples` case must degrade to "draft exactly as today," never abort, never raise, never block.
```text
# Markdown level (SKILL.md convention)
If `<optional-cache-path>` exists ... read it ... treat it as a lens, not a
hard filter. [If missing:] proceed exactly as today.

# Python level (style_profile.py convention)
if not path.exists():
    print(f"[warn] ... not found ...; deriving an empty ...", file=sys.stderr)
    return []
```

### Concrete-not-prose grounding (applies to SKILL.md edit + docs edit)
**Source:** `scripts/style_profile.py::derive_profile` docstring (lines 41-45) — "Every example carries an actual title string plus its real performance signal — never a prose description of 'the creator's style'"
**Apply to:** the exact wording of the new SKILL.md instruction and any docs addition — must instruct the orchestrator to quote real `naming_examples` entries verbatim (as delimited example data, per RESEARCH.md's V5 prompt-hygiene note), not to summarize them into a style description.

### Privacy / no-real-data-in-committed-files (applies to SKILL.md edit, docs edit, and any test fixtures)
**Source:** `tests/test_style_profile.py::test_privacy_write_profile_default_target_is_under_gitignored_work_dir` (lines 90-115) — verifies `style_profile.json` lands under gitignored `work/` and `git check-ignore` passes.
**Apply to:** any illustrative example added to `SKILL.md`, `docs/metadata-writing-ru.md`, or test fixtures must use fabricated titles only (e.g. `"Boss Rage Quit Moment"`, `"Clutch 1v5 Ace"` — the vocabulary already established in `tests/test_style_profile.py`). Never paste a real title from an actual `work/_profile/style_profile.json` run into any committed file.

## No Analog Found

None — this phase's file set is narrow (one Markdown instruction edit, one optional pure-function helper + its test, one optional docs edit) and every file has a strong same-file or same-pattern analog already in the repo.

## Metadata

**Analog search scope:** `SKILL.md`, `scripts/style_profile.py`, `scripts/metadata.py`, `scripts/config.py`, `tests/test_style_profile.py`, `docs/metadata-writing-ru.md`
**Files scanned:** 6
**Pattern extraction date:** 2026-07-07
</content>
