---
phase: 08-hook-title-overlay
plan: 01
status: complete
completed: 2026-07-12
mode: inline (user-requested token-lean execution — no executor subagents; this one summary covers the whole phase)
commits:
  - 2c32732 feat(08): hook title banner — chained-drawtext plate, hook/persistent modes, CTA line
---

# Phase 8: Hook Title Overlay — Summary

Implemented inline in the main session per 08-RESEARCH.md (live-verified drawtext mechanics) and 08-01-PLAN.md, extended with the config/SKILL/integration work the cut-off planner never got to write as 08-02.

## What shipped

- `scripts/render.py`: `HOOK_BANNER_FONT_PATHS` + `resolve_banner_font` (fontfile= mandatory — fontconfig broken on this Windows ffmpeg build), `_escape_drawtext_text` (backslash-first: `\` `'` `:` `,`; `%` neutralized via `expansion=none`), `_wrap_banner_lines` (greedy wrap, fail-open ellipsis truncation + `[warn]`), `build_hook_banner_filter` (chained drawtext — one clause per wrapped line + optional CTA line; hook mode gates every clause with `enable=` + alpha fade-out, `fade_seconds=0` = hard cut; persistent mode = no gating). Threaded as `banner_filter` keyword param through all three command builders (after punch-zoom/effects, before subtitles — 08-RESEARCH Pattern 2), `render_clip` reads `plan_entry["banner_text"]` with a fail-loud RenderError when banner and burned subtitles share a position, 13 `--banner-*` CLI flags.
- `scripts/config.py`: `HookBannerConfig` (default-off, `mode="persistent"` per the locked 2026-07-12 ROADMAP decision) + `_validate` rules incl. the banner/subtitles same-position ConfigError.
- `config.example.yaml`: documented `hook_banner` section.
- SKILL.md: step-5 "Hook banner text" bullet (mechanical hashtag/emoji/18+-prefix strip of the final `youtube.title` — no new semantic judgment), `banner_text` in both PLAN.json schema examples, step-6 `--banner-*` flags.
- Tests: 22 render unit tests (exact-string shapes, escaping order, wrap/truncate, ordering assertion zoom<banner<subtitles, byte-identical without banner_text across all three branches, collision guard), 7 config tests, 1 real-ffmpeg integration test (banner-region pixel signature differs). Full suite: 656 passed, 5 skipped.

## Success criteria

1. Banner renders legibly in both modes (persistent default, CTA line) — verified on a real clip frame (НАУШНИКИ НЕ ТОЙ СТОРОНОЙ? + @zhorekp, two wrapped Cyrillic lines, top zone) ✓
2. No overlap with burned subtitles (position collision fails loud at config load AND at render) or platform top UI (y=140 anchor) ✓
3. Fail-open default-off: no banner_text / disabled → byte-identical command (unit-tested) ✓
4. Hashtags/emoji never reach pixels (SKILL step-5 mechanical strip; title already passed anti-AI-tone when drafted) ✓

## Deviations from 08-01-PLAN.md

- Executed inline (no subagents, single commit instead of three per-task commits) at user request.
- The unwritten 08-02 scope (HookBannerConfig, example config, SKILL wiring, integration test) was folded into the same commit.
