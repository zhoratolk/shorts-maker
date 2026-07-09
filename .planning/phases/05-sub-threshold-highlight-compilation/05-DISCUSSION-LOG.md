# Phase 5: Sub-Threshold Highlight Compilation - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-09
**Phase:** 5-Sub-Threshold Highlight Compilation
**Areas discussed:** Tagging & matching, Unmatched leftovers, Ordering & length, Visual treatment

---

## Tagging & matching

| Option | Description | Selected |
|--------|-------------|----------|
| Free-form tags + semantic match | Claude assigns a short tag per sub-threshold moment (like `reason` today) and groups by semantic similarity, not exact string match | ✓ |
| Fixed category list | Predefined tag vocabulary (death/clutch/fail/joke/rage); grouping = exact category match | |

**User's choice:** Free-form tags + semantic match.
**Notes:** Matches how `reason` is already written today; grouping is a Claude judgment call, not a Python string-equality function.

---

## Unmatched leftovers

| Option | Description | Selected |
|--------|-------------|----------|
| Silently drop (current behavior) | If no match found, moment disappears like today | |
| Show as unmatched in CANDIDATES.md | Surfaced in the review doc marked unmatched — visible but doesn't render | ✓ |

**User's choice:** Show as unmatched in CANDIDATES.md.
**Notes:** No cross-run persistence — a moment unmatched this run isn't held over to combine with a future session's candidates (consistent with COMP-03's same-session-only scope).

---

## Ordering & length inside a compilation

| Option | Description | Selected |
|--------|-------------|----------|
| Chronological + strict max_seconds | Source-video order; grouping stops at the normal clip length ceiling | |
| Strongest moment first + own limit | Best hook leads; compilation gets its own (longer) length ceiling since it's a different output shape | ✓ |

**User's choice:** Strongest moment first + own limit.
**Notes:** No exact cap number given — left to Claude's discretion (see CONTEXT.md Claude's Discretion: recommend ~2-3x `config.clip.max_seconds`).

---

## Visual treatment across sub-clips

| Option | Description | Selected |
|--------|-------------|----------|
| Independent per sub-clip | Each stitched moment keeps its own crop_style/punch-zoom choice, like single clips today | |
| Uniform style for whole compilation | One crop_style (and other visual choices) for the entire compilation | ✓ |

**User's choice:** Uniform style for whole compilation.
**Notes:** Chosen for visual consistency — reads as one roll, not a patchwork of differently-framed moments.

---

## Claude's Discretion

- Exact compilation length cap (no number specified by user)
- Exact mechanics/wiring of the semantic-match pass (dedicated step vs. folded into existing step)
- Whether compilation title/metadata generation runs once for the whole group vs. per sub-clip (defaulted to once-per-compilation)
- Minimum group size (implied 2+, per D-03's "unmatched = leftover" framing)

## Deferred Ideas

None — discussion stayed within phase scope.
