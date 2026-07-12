# Phase 8: Hook Title Overlay - Research

**Researched:** 2026-07-12
**Domain:** ffmpeg `drawtext` filter-graph banner (styled text burned over the frame), reusing `render.py`'s existing crop/punch-zoom/subtitles/fade pipeline; Cyrillic TrueType rendering on Windows; PLAN.json/SKILL.md field flow for a pre-sanitized text field
**Confidence:** HIGH - every `drawtext` claim below (Cyrillic rendering, fontfile requirement, escaping rules, multi-line behavior, timeline `enable`/`alpha`) was **live-verified this session** against the real `ffmpeg 8.1.2-full_build` (Gyan.FFmpeg) binary and Windows fonts installed on this machine, via `subprocess.run` with an argv list (the exact invocation shape `render.py` uses - not shell-quoted), including visual inspection of rendered PNG frames.

<phase_requirements>
## Phase Requirements

No formal REQ IDs exist yet (ROADMAP.md: "to be defined at planning"). Assigning `HOOK-01..04` from the roadmap's 4 success criteria, matching the phase's own ID-prefix convention (`AUDIO-*` for Phase 7, `MONET-*` for Phase 1):

| ID | Description | Research Support |
|----|-------------|------------------|
| HOOK-01 | Banner shows the hook: `hook` mode = first ~2-3s then gone (hard cut or fade); `persistent` mode (default) = whole clip + optional CTA/nick line under it | Architecture Patterns > Pattern 1/2; Code Examples |
| HOOK-02 | Banner never overlaps burned-in subtitles or platform UI safe areas | Placement Math section; Pitfall 5 |
| HOOK-03 | Missing/empty title or feature disabled renders byte-identical to today (fail-open, default-off) | Recommended Approach > Config + Integration Points |
| HOOK-04 | Banner text passes the same anti-AI-tone/hashtag-stripping rules as metadata | Recommended Approach > Text Sanitization Pipeline |

</phase_requirements>

## Summary

`drawtext`, not a second ASS/libass track, is the right tool here, and it slots into `render.py` exactly like `build_punch_zoom_filter`/`build_video_effects_chain` already do: a pure string-building function, validated up front, appended into the same `video_filter`/`video_ops` list all three render builders (`build_ffmpeg_command`, `build_jumpcut_command`, `build_compilation_command`) already share. No `filter_complex` restructuring, no second ffmpeg input, no new pip package - `drawtext` is a core `libavfilter` filter already present in the project's existing ffmpeg dependency.

Two non-obvious, live-verified findings drive the concrete design below. **First:** this Windows ffmpeg build's `drawtext` has **no working fontconfig** (`font='Arial Black'` by name fails with `Fontconfig error: Cannot load default config file`) - an explicit `fontfile=` path is mandatory, unlike the ASS `subtitles` filter (libass resolves font names via GDI/Windows font enumeration, a different code path). Windows 11 ships `ariblk.ttf` (true Arial Black) with **full Cyrillic glyph coverage** (visually confirmed), matching `config.subtitles.font: "Arial Black"`'s existing default for visual consistency between banner and captions. **Second:** embedding a literal `\n` inside a single `drawtext text=` value does **not** produce a newline when the command is built as a Python argv list (no shell) - it renders as a literal lowercase `n` character (live-reproduced). The Dunduk-pattern two-line banner (hook line + CTA/nick line) must instead be built as **two chained `drawtext` filters** (comma-joined, one per line, each with its own `y` offset expression and independent box/centering) - this also sidesteps `text_align`'s ffmpeg-version dependency and gives each line its own font size/color for free (title bold+white, CTA smaller+accent color, matching the reference clip's "КАПС-хук + плашка с ником" pattern documented in `work/refs/_analysis/ANALYSIS.md`).

**Primary recommendation:** new `build_hook_banner_filter()` in `scripts/render.py` (pure builder, mirrors `build_punch_zoom_filter`'s validate-then-string shape) + a new `HookBannerConfig` dataclass in `scripts/config.py` (fail-open, default `enabled=false`, default `mode="persistent"` per the roadmap's locked mode decision) + one new optional `banner_text` field on `PLAN.json` clip/compilation entries, populated by a new SKILL.md step-5 bullet that mechanically strips hashtags/emoji from the already anti-AI-tone-filtered `youtube.title` (Claude's semantic drafting happens once, in the existing title-writing bullet; the banner-text derivation is a pure regex strip, safe as either an inline SKILL.md instruction or a tiny new `scripts/banner.py` helper - no new semantic judgment).

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Deciding/wording the hook text (`youtube.title`) | Orchestration (`SKILL.md` step 5, Claude's judgment) | - | Already exists (Phase 2/hook-formula rules); this phase reuses it, never re-derives it |
| Hashtag/emoji stripping from the title for banner display | Mechanical (regex, either inline SKILL.md `python -c` one-liner or new `scripts/banner.py::sanitize_banner_text`) | - | Pure string transform, no semantic judgment - matches TAGS/MONET precedent |
| Line-wrapping, font/box/position/timing math | Mechanical (`scripts/render.py::build_hook_banner_filter`) | - | Pure ffmpeg filter-string construction, no subprocess call itself - matches `build_punch_zoom_filter`/`build_profanity_mask_filter` precedent |
| ffmpeg execution (burning the banner into pixels) | Mechanical (`scripts/render.py::render_clip`, existing `runner=subprocess.run` injectable) | - | No new execution path |
| Collision with subtitle placement / platform safe areas | Mechanical validation (`render_clip`/`_validate`, `RenderError`) | - | Deterministic geometry check, not a judgment call - same style as the existing `punch_zoom_at` + `crop_style` incompatibility check |

## Standard Stack

### Core
| Component | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| ffmpeg `drawtext` filter | already required (project dependency, `ffmpeg 8.1.2-full_build`) | Burns styled text banner into the frame | Core `libavfilter` filter, zero new dependency; live-verified this session on this machine's exact binary |
| `ariblk.ttf` (Windows-shipped Arial Black) | OS-provided | Banner title font (matches `config.subtitles.font` default) | Visually confirmed full Cyrillic coverage this session (see screenshot evidence in session); ships with Windows 11 at `C:\Windows\Fonts\ariblk.ttf` |
| `arialbd.ttf` (Windows-shipped Arial Bold) | OS-provided | CTA/nick line font (smaller, secondary weight) | Same font family as subtitles' fallback path; full Cyrillic support confirmed live |

**No new pip packages.** `drawtext` is compiled into the project's existing ffmpeg binary (`--enable-libfreetype --enable-libfribidi --enable-libharfbuzz` all present in this build's `ffmpeg -version` output). See Package Legitimacy Audit.

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `drawtext` (recommended) | A second ASS/libass track (like `build_ass_content`, burned via a second `subtitles=` filter or merged into the same `.ass`) | libass gives free auto-wrap/rounded-box styling, but duplicates `build_ass_content`'s PlayResX/escaping machinery for a fundamentally different use case (one static multi-line banner vs. a synced caption timeline), and the project's existing ASS style block already has one `[V4+ Styles]` "Default" style tied to captions - a second banner style would need its own `[V4+ Styles]` entry and a second `.ass` file per clip. More moving parts for no capability `drawtext` lacks here (banner never needs word-level karaoke highlighting). |
| Two chained `drawtext` filters, one per line (recommended) | One `drawtext` with `\n` + `text_align=center` | Live-reproduced this session: a literal `\n` two-character sequence inside `text=` renders as a literal `n`, not a newline, when the command is built as a Python argv list (no shell interpreting the escape). Also `text_align` requires a newer ffmpeg (~6.1+) and gives both lines the same font size/color, which the Dunduk CTA-under-title pattern explicitly does not want. |
| `fontfile=` explicit path (recommended) | `font='Arial Black'` name lookup via fontconfig | Live-reproduced this session: `font=` errors with `Fontconfig error: Cannot load default config file: File not found` on this Windows Gyan.FFmpeg build - fontconfig is compiled in but has no config file on Windows. `fontfile=` bypasses fontconfig entirely and always works. |
| `expansion=none` on the drawtext filter (recommended) | Doubling every literal `%` as `%%` | Live-verified both work, but `expansion=none` is simpler (no need to hunt for `%` in the title text at all) and also disables `drawtext`'s `strftime`-style expansion entirely, which is irrelevant here and only a source of surprise if a title ever contains a `%` followed by a letter. |

**Installation:** None - no new packages.

## Package Legitimacy Audit

Zero new external packages. `drawtext` is a filter inside the project's existing `ffmpeg` dependency (already vetted, Phase 1). `ariblk.ttf`/`arialbd.ttf` are OS-shipped font files, not a package dependency.

| Package | Registry | Verdict | Disposition |
|---------|----------|---------|-------------|
| *(none - no new packages)* | - | N/A | N/A |

## Architecture Patterns

### System Architecture Diagram
```text
PLAN.json clip entry: "banner_text": "МУЖИКИ, ВЫ ЧЁ ТВОРИТЕ?"   <-- NEW optional field
   (hashtags/emoji already stripped by SKILL.md step 5;
    omitted entirely when empty/missing - fail-open)
        |
        v
scripts/render.py :: render_clip()
   plan_entry.get("banner_text")
        |
        v
scripts/render.py :: build_hook_banner_filter()        <-- NEW pure builder
   -> wraps text into lines (chars-per-line heuristic)
   -> builds one drawtext=... clause per line (title, optional CTA)
   -> mode="hook": adds enable='between(t,0,dur)' + alpha fade-out
   -> mode="persistent": no enable/alpha (visible whole clip)
   -> RenderError if computed banner zone overlaps subtitle zone
        |
        v
video_filter chain (build_ffmpeg_command/build_jumpcut_command/
build_compilation_command - all three, same insertion point):
  crop_filter -> punch_zoom -> effects_chain (vignette/grain)
      -> HOOK BANNER (new, inserted here)                <-- AFTER punch_zoom
      -> subtitles (existing)                                (banner must not zoom)
      -> fade=t=out (existing, whole-clip fade to black)
        |
        v
  rendered .mp4 with banner burned in, subtitles/UI-safe-area
  clear, byte-identical to today when banner_text is absent
```

### Recommended Project Structure
```
scripts/
├── render.py     # EXTENDED - build_hook_banner_filter (new), video_filter
│                 #             insertion in all 3 command builders, render_clip
│                 #             reads plan_entry["banner_text"]
├── config.py     # EXTENDED - HookBannerConfig dataclass
data/             # no new data file needed (unlike profanity's wordlist -
                  #  banner text is pre-sanitized upstream, not detected here)
```

### Pattern 1: Two-line banner via chained `drawtext`, not `\n` (live-verified)

**What:** Title line + optional CTA line are two separate `drawtext=...` clauses joined by `,` in the filter chain, each independently centered (`x=(w-text_w)/2`) and each with its own `y` (the CTA's `y` expression references the title's own `y + fontsize + gap`, e.g. `y=140+58+18`), rather than one `drawtext` with an embedded `\n`.

**When to use:** Any multi-line `drawtext` banner built from a Python argv list (i.e., always in this codebase - `render.py` never uses `shell=True`).

**Live-verified example** (`subprocess.run(['ffmpeg', ..., '-vf', vf, ...])`, no shell):
```python
# Source: live-verified this session, D:\shorts-maker, ffmpeg 8.1.2-full_build
line1 = (
    r"drawtext=fontfile='C\:/Windows/Fonts/ariblk.ttf':"
    r"text='МУЖИКИ\, ВЫ ЧЁ ТВОРИТЕ?':fontsize=58:fontcolor=white:"
    r"expansion=none:x=(w-text_w)/2:y=140:box=1:boxcolor=black@0.55:boxborderw=24"
)
line2 = (
    r"drawtext=fontfile='C\:/Windows/Fonts/arialbd.ttf':"
    r"text='@channel_nick':fontsize=36:fontcolor=0xffe98a:"
    r"expansion=none:x=(w-text_w)/2:y=140+58+20:box=1:boxcolor=black@0.55:boxborderw=16"
)
vf = line1 + "," + line2
# rc=0, both lines rendered, each independently centered - confirmed via
# rendered PNG frame inspection this session.
```
Both `x`/`y` fields accept arithmetic expressions (`140+58+20` evaluated by ffmpeg's own expression parser), so the CTA line's vertical offset can be computed relative to the title line without Python pre-computing exact pixel sums (though computing them in Python is equally valid and arguably clearer for a `RenderError` bounds check).

**Text escaping (mirrors `render.py`'s existing `subtitles_path` colon-escape and `_escape_ass_text`'s backslash-first ordering):** before interpolating `banner_text`/CTA text into the `text='...'` filter argument, escape in this order: (1) backslash `\` -> `\\`, (2) single quote `'` -> `\'`, (3) colon `:` -> `\:`, (4) comma `,` -> `\,`. Set `expansion=none` on every banner `drawtext` clause instead of doubling `%` - live-verified to suppress ffmpeg's `strftime`-expansion parsing entirely (no "Stray %" warning, rc=0) without needing a 5th escape rule.

### Pattern 2: Insertion point in the filter chain - after punch-zoom, before subtitles

**What:** `build_hook_banner_filter`'s output is appended to `video_filter` (in `build_ffmpeg_command`) / `video_ops` (in `build_jumpcut_command`/`build_compilation_command`) at the same point `build_video_effects_chain`'s docstring already establishes for vignette/grain: **after** `crop_filter` + `build_punch_zoom_filter`, **before** the `subtitles=` clause.

**Why after punch-zoom:** `build_punch_zoom_filter` re-crops and rescales the already-1080x1920 frame around its center as a per-frame zoom ramp. If the banner were drawn before punch-zoom, the zoom crop would clip/shift the banner text off-frame or partially crop it as the clip zooms in - exactly the `RenderError` `render_clip` already raises for `punch_zoom_at` + non-`zoom` crop styles (`scripts/render.py:1095-1104`) is the same class of bug this ordering avoids. Drawing the banner **after** the zoom (on the already-zoomed, fixed 1080x1920 output) guarantees it stays pinned in place regardless of punch-zoom.

**Why before subtitles:** Not strictly required for correctness (the two occupy disjoint y-regions by construction - see Placement Math below), but keeps `build_video_effects_chain`'s established ordering convention ("cinematic touch-ups applied after crop, before subtitles are burned in") intact, and keeps the ASS subtitle burn (which already handles its own force_style/margins) as the final visual layer, matching today's mental model of "subtitles are always the last thing drawn."

### Placement Math (1080x1920 canvas)

- **Subtitle zones (existing, `render.py:23-24`):** `position="bottom"` (default) -> `MarginV=380`, alignment=2 (bottom-anchored, text grows upward from `y=1920-380=1540`). `position="top"` -> `MarginV=120`, alignment=8 (top-anchored, text grows downward from `y=120`). `position="center"` -> vertically centered.
- **Platform UI safe areas** (TikTok/Reels/Shorts, approximate, consistent with the existing subtitle-margin rationale already in `config.example.yaml`'s `subtitles.position` comment): top ~0-120px (username/follow/live-badge UI), bottom ~380-480px (caption/like/comment/share UI + the existing subtitle `MarginV=380` floor), right ~150-160px width (like/comment/share button rail).
- **Recommended banner zone (top, default):** `y=140` for the title line's top edge - clears the ~120px platform top-UI band with a small margin. At `fontsize=58` + `boxborderw=24` the title box spans roughly `y=116` to `y=214`; a CTA line at `fontsize=36` below it (`y=140+58+20=218`) extends the block to roughly `y=280`. This stays clear of a bottom-positioned subtitle block (`MarginV=380`, i.e. subtitle text never renders above `y≈1540`) with over 1200px of clearance regardless of crop style.
- **Collision case: `config.subtitles.position == "top"` and the banner is also top-positioned.** These overlap by construction (both anchor near `y=120-140`). Recommend `render_clip`/a config `_validate` raise `RenderError` for this exact combination (`hook_banner.position == "top" and subtitle_style["position"] == "top"`) rather than attempting dynamic collision-avoidance math - mirrors the existing `punch_zoom_at` + `crop_style` incompatibility check's fail-loud style. `hook_banner.position` should default to `"top"` (independent of `subtitles.position`, which defaults to `"bottom"`) so the common case (both defaults) never collides.
- **Character-width measurement (live-verified via rendered frame, not estimated):** `"МУЖИКИ, ВЫ ЧЁ ТВОРИТЕ?"` (22 chars incl. spaces/punctuation) at `fontsize=58` in `ariblk.ttf` bold caps spans roughly 920px of the 1080px canvas width. That is ~42px/char average for bold Cyrillic caps at this size. With ~60px side margins (960px usable), that is **~22-23 characters per line** at `fontsize=58`. Since hooks are capped at "≤7 words, readable in ≤3 seconds" per `docs/metadata-writing-ru.md`, most hooks will fit on 1-2 wrapped lines at this size; a hook running long should either drop to `fontsize≈48-50` (giving ~26-28 chars/line) or wrap to a 3rd line - `build_hook_banner_filter` should accept a `max_lines` cap (e.g. 2) and raise `RenderError` (or, per D-01 fail-open convention, warn-and-truncate) rather than silently overflowing the frame.

### Anti-Patterns to Avoid
- **Relying on `font=<name>` instead of `fontfile=<path>`:** fails outright on this Windows ffmpeg build (fontconfig has no config file). Always resolve to an explicit `fontfile=` path, with a documented fallback comment for non-Windows machines exactly like `config.subtitles.font`'s existing comment already does.
- **Embedding `\n` in a single `drawtext text=` value for a multi-line banner:** renders as a literal `n` character when the command is built as a Python argv list. Use chained `drawtext` filters, one per line, instead.
- **Drawing the banner before `build_punch_zoom_filter`:** the punch-zoom crop will clip/shift the banner as it zooms.
- **Doubling `%` manually:** works, but `expansion=none` is simpler and closes off the whole class of `strftime`-expansion surprises in one flag.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Multi-line text layout / auto-wrap | A text-shaping/layout library (e.g. Pillow to pre-render a PNG overlay, then `overlay=` filter) | Python-side greedy word-wrap (chars-per-line heuristic above) feeding N chained `drawtext` filters | `drawtext` already handles font rendering, Cyrillic shaping (`--enable-libfribidi --enable-libharfbuzz` present in this build), and box/shadow styling natively - a PNG-overlay approach would need a second heavy dependency (Pillow) and a temp-file-per-clip step this project doesn't otherwise need |
| Emoji stripping | A full grapheme-cluster/ICU-based emoji detector | A stdlib `re` Unicode-range strip (`\U0001F300-\U0001FAFF`, `☀-➿`, etc.) applied once, mechanically, to `banner_text` before rendering | `arialbd.ttf`/`ariblk.ttf` have no color-emoji glyphs; an un-stripped emoji renders as a missing-glyph box (visual noise), and the hook-formula guidance already discourages emoji-heavy titles - a simple regex strip is enough, matches `strip_display_punctuation`'s existing mechanical-regex precedent in `scripts/subtitles.py` |

**Key insight:** every mechanical piece this phase needs (font rendering, Cyrillic shaping, box background, timeline fade) already exists in the project's ffmpeg dependency; the actual net-new work is one builder function + one config section + one PLAN.json field + text sanitization glue, matching Phase 7's "glue-shaped, not infrastructure-shaped" precedent.

## Common Pitfalls

### Pitfall 1: `font=<name>` silently requires fontconfig, which is broken on this Windows build (Severity: HIGH - blocks the feature outright if not caught)
**What goes wrong:** Using `font='Arial Black'` (matching `config.subtitles.font`'s string convention) instead of `fontfile=` causes ffmpeg to exit with `Fontconfig error: Cannot load default config file: File not found`.
**Why it happens:** This Gyan.FFmpeg Windows build has `--enable-fontconfig` compiled in, but no fontconfig config file is installed/configured on Windows (fontconfig is a Linux/macOS-native font-discovery library).
**How to avoid:** Always use `fontfile=<explicit path>`. Recommend a small `HOOK_BANNER_FONT_PATHS` map in `render.py` (mirrors `NAMED_ASS_COLORS`'s shape) resolving a friendly name (`"Arial Black"`) to `C:/Windows/Fonts/ariblk.ttf`, with a documented non-Windows fallback comment identical in spirit to `config.subtitles.font`'s existing one ("not installed by default on macOS/Linux - set a locally available bold font path there").
**Warning signs:** ffmpeg exits non-zero with `Fontconfig error` in stderr; `RenderError` should surface this stderr verbatim (already the pattern in `render_clip`'s existing `result.stderr` propagation).

### Pitfall 2: `\n` inside `text=` does not produce a newline (Severity: HIGH - silently produces a garbled single-line banner, not a crash)
**What goes wrong:** A two-line banner built as one `drawtext` with `text='LINE1\nLINE2'` renders as `LINE1nLINE2` - visually wrong but ffmpeg exits 0, so nothing fails loudly.
**Why it happens:** The two-character sequence `\` + `n` inside a Python string built into an argv list is not converted to an actual newline byte (0x0A) anywhere in the pipeline (no shell interpreting escapes, and `drawtext`'s own parser does not treat literal `\n` specially the way some online examples/shell-built commands imply).
**How to avoid:** Build one `drawtext` filter per line (Pattern 1), never rely on embedded `\n`.
**Warning signs:** A rendered clip's banner shows a stray lowercase `n` mid-sentence where a line break was intended - only catchable by visually inspecting a real render (add this as an explicit `checkpoint:human-verify` step in the plan, mirroring Phase 7's Plan 07-05 masking-quality checkpoint).

### Pitfall 3: Banner colliding with top-positioned subtitles (Severity: MEDIUM)
**What goes wrong:** If `config.subtitles.position == "top"` and the hook banner also defaults/is configured to the top zone, both burn into the same `y≈120-140` region.
**Why it happens:** Both features independently default to reasonable-sounding zones without cross-checking each other.
**How to avoid:** Validate the combination at config-load or render time and raise `RenderError` (or `ConfigError`) rather than attempting collision-avoidance geometry - see Placement Math above.
**Warning signs:** Caught immediately by the validation, not something that should reach a rendered clip.

### Pitfall 4: Long/untruncated hook overflowing the 1080px canvas width (Severity: MEDIUM)
**What goes wrong:** A hook longer than ~22-23 chars/line at the default font size, if not wrapped, renders past the frame edge or gets clipped.
**Why it happens:** `drawtext` has no auto-wrap; `x=(w-text_w)/2` centers the (potentially oversized) text box but does not constrain its width.
**How to avoid:** Pre-wrap in Python using the measured chars-per-line heuristic (Placement Math above), cap at `max_lines` (recommend 2), and either shrink `fontsize` one step or truncate-with-ellipsis on overflow rather than letting `drawtext` draw off-frame.
**Warning signs:** A rendered clip where the banner box visibly runs off the left/right edge of the 1080px frame.

### Pitfall 5: Forgetting to gate the banner behind `punch_zoom_at`'s crop-style check (Severity: LOW)
**What goes wrong:** None directly - the banner is drawn after punch-zoom regardless of crop style, so it is inherently safe. Listed as a pitfall only because it's easy to *assume* the banner needs the same `crop_style == "zoom"` guard `punch_zoom_at` has; it does not.
**Why it happens:** Pattern-matching on `punch_zoom_at`'s existing validation without re-deriving why that guard exists (it's about the zoom crop eating real frame content on `pad`/`original-16:9`, not about drawing order).
**How to avoid:** No new guard needed here - just confirm in review that `build_hook_banner_filter`'s output is appended after `build_punch_zoom_filter`'s output in all three command builders, not conditionally.

## Code Examples

### `render.py` addition (pure builder, mirrors `build_punch_zoom_filter`/`build_profanity_mask_filter` shape)
```python
# Source: this session's design, live-verified filter syntax (see Pattern 1/2 above)
HOOK_BANNER_FONT_PATHS = {
    "Arial Black": "C:/Windows/Fonts/ariblk.ttf",
    "Arial Bold": "C:/Windows/Fonts/arialbd.ttf",
}

def _escape_drawtext_text(text: str) -> str:
    """Mirrors _escape_ass_text's backslash-first ordering, for drawtext's
    own single-quoted text= argument syntax (backslash, quote, colon, comma
    all have filtergraph meaning; % is neutralized via expansion=none
    instead of doubling)."""
    return (
        text.replace("\\", "\\\\").replace("'", "\\'")
        .replace(":", "\\:").replace(",", "\\,")
    )

def build_hook_banner_filter(
    text: str, mode: str, cta_text: str = "", font_path: str = HOOK_BANNER_FONT_PATHS["Arial Black"],
    cta_font_path: str = HOOK_BANNER_FONT_PATHS["Arial Bold"], size: int = 58, cta_size: int = 36,
    color: str = "white", cta_color: str = "0xffe98a", box_color: str = "black@0.55",
    y_top: int = 140, duration_seconds: float = 3.0, fade_seconds: float = 0.4,
) -> str | None:
    """Returns None (fail-open) when text is empty/whitespace - caller omits
    the filter entirely, byte-identical to today's command."""
    if not text or not text.strip():
        return None
    if mode not in ("hook", "persistent"):
        raise RenderError(f"banner mode must be 'hook' or 'persistent', got {mode!r}")

    escaped_title = _escape_drawtext_text(text.strip())
    clauses = [
        f"drawtext=fontfile='{font_path}':text='{escaped_title}':fontsize={size}:"
        f"fontcolor={color}:expansion=none:x=(w-text_w)/2:y={y_top}:"
        f"box=1:boxcolor={box_color}:boxborderw=24"
    ]
    if cta_text and cta_text.strip():
        escaped_cta = _escape_drawtext_text(cta_text.strip())
        clauses.append(
            f"drawtext=fontfile='{cta_font_path}':text='{escaped_cta}':fontsize={cta_size}:"
            f"fontcolor={cta_color}:expansion=none:x=(w-text_w)/2:y={y_top}+{size}+20:"
            f"box=1:boxcolor={box_color}:boxborderw=16"
        )

    if mode == "hook":
        enable_expr = f"between(t,0,{duration_seconds})"
        fade_start = round(duration_seconds - fade_seconds, 3)
        alpha_expr = f"if(lt(t,{fade_start}),1,max(0,1-(t-{fade_start})/{fade_seconds}))"
        clauses = [f"{clause}:enable='{enable_expr}':alpha='{alpha_expr}'" for clause in clauses]

    return ",".join(clauses)
```

### Insertion point (all three command builders, same shape as `build_video_effects_chain`'s existing call site)
```python
# Source: this session's design, matching build_ffmpeg_command's existing
# video_filter accumulation pattern verbatim (scripts/render.py:461-476)
video_filter = crop_filter
if punch_zoom_at is not None:
    video_filter = f"{video_filter},{build_punch_zoom_filter(...)}"
effects_chain = build_video_effects_chain(vignette, grain_strength)
if effects_chain:
    video_filter = f"{video_filter},{effects_chain}"
banner_filter = build_hook_banner_filter(...)   # NEW - after punch-zoom, before subtitles
if banner_filter:
    video_filter = f"{video_filter},{banner_filter}"
if subtitles_path is not None:
    ...  # unchanged
```

### `config.py` addition
```python
@dataclasses.dataclass
class HookBannerConfig:
    # Opt-in, off by default (D-01 fail-open precedent) - new optional
    # feature, same footing as diarization/audio_energy/profanity.
    enabled: bool = False
    # "persistent" is the locked default per ROADMAP.md's 2026-07-12 mode
    # decision - the nick plate stands in for a face until a webcam/PNGTuber
    # layout exists.
    mode: str = "persistent"          # hook | persistent
    cta_text: str = ""                 # e.g. "@channel_nick" - empty = no CTA line
    duration_seconds: float = 3.0      # hook mode only: visible window before fade
    fade_seconds: float = 0.4          # hook mode only: 0 = hard cut, else fade-out
    font: str = "Arial Black"
    size: int = 58
    color: str = "white"
    cta_font: str = "Arial Bold"
    cta_size: int = 36
    cta_color: str = "#ffe98a"
    box_color: str = "black"
    box_opacity: float = 0.55
    position: str = "top"              # top | bottom - validated against subtitles.position
```
`_validate` additions: `mode in {"hook","persistent"}`; `duration_seconds > 0`; `fade_seconds >= 0`; `0 <= box_opacity <= 1`; `position != config.subtitles.position` whenever both are `"top"` (Pitfall 3).

### PLAN.json field (SKILL.md step 5/5b, same optional-field convention as `profanity_spans`)
```json
{
  "banner_text": "МУЖИКИ, ВЫ ЧЁ ТВОРИТЕ?"
}
```
Omitted entirely when `config.hook_banner.enabled` is `false`, the title is empty, or sanitization strips it to nothing (fail-open, HOOK-03). Derived once from the already-drafted `youtube.title` in step 5's existing metadata bullet: strip `#\S+` hashtags, strip emoji (Unicode ranges), collapse whitespace, drop a leading `⚠️ 18+` content-warning prefix if step 5's mature-content bullet added one (that belongs in metadata text, not burned into pixels). No new anti-AI-tone pass needed - the source title already went through that filter when drafted; this is a pure mechanical strip, safe as an inline SKILL.md `python -c` regex one-liner.

### `render.py` CLI flags (step 6, same "pass regardless, harmless no-op when unused" convention as `--profanity-*`)
```
--banner-mode <hook|persistent> --banner-font "<name>" --banner-size <int>
--banner-color <name> --banner-cta-text "<text>" --banner-cta-font "<name>"
--banner-cta-size <int> --banner-cta-color <name> --banner-position <top|bottom>
--banner-duration-seconds <float> --banner-fade-seconds <float>
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| N/A - `render.py`'s video filter chain has never burned static text into the frame before this phase (only synced ASS captions) | First static-banner `drawtext` usage in this codebase | This phase | Establishes the `fontfile=`/`expansion=none`/chained-multi-line pattern any future on-frame text feature (e.g. a watermark, a "Part 2" indicator) can reuse |

**Deprecated/outdated:** Nothing replaced - purely additive.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | ~22-23 chars/line at `fontsize=58` is a safe wrapping threshold for arbitrary Cyrillic/Latin hook titles, not just the one sample string measured | Placement Math | Low-Medium - measured from one real rendered sample (bold caps, widest-case Cyrillic); character width varies by letter mix. Mitigate by keeping a small safety margin (measured 920px of 960px usable = already ~4% headroom) and treating `max_lines`/truncation as a real fallback, not a never-hit edge case |
| A2 | Platform safe-area pixel figures (top ~120px, bottom ~380-480px, right ~150-160px) are reasonable approximations, not measured against live TikTok/Shorts/Reels UI on a real device this session | Placement Math | Low - the bottom figure is already load-bearing precedent (`SUBTITLE_MARGIN_V["bottom"]=380`, an existing, presumably-tuned constant); top/right are `[ASSUMED]` from general platform-UI knowledge, not re-verified this session. If wrong, worst case the banner sits slightly under/over a platform's own UI chrome - cheap to fix by adjusting `y_top` after watching one real upload |
| A3 | `ariblk.ttf`'s Cyrillic coverage on this specific Windows 11 install generalizes to other Windows 10/11 installs | Standard Stack | Low - Arial Black has shipped as a system font with Cyrillic support on Windows since Windows 7-era language-pack updates; a very old/minimal Windows install could differ. Same class of risk `config.subtitles.font`'s existing comment already accepts for the subtitles feature |
| A4 | Chained multi-line `drawtext` (Pattern 1) has no meaningful encode-speed cost vs. a single-filter approach | Architecture Patterns | Low - `drawtext` is a lightweight CPU filter; 1-2 extra filter instances per clip is negligible next to the existing crop/scale/ASS-subtitle/audio-filter cost already paid per clip |

## Open Questions

1. **Exact banner font size / box opacity / CTA color are starting values, not final-tuned.**
   - What we know: the mechanics work end-to-end (live-verified); values are reasoned from the reference clip's visual style (`work/refs/_analysis/ANALYSIS.md`'s Dunduk description) and general legibility practice.
   - What's unclear: whether these specific values read well against real busy gameplay footage (as opposed to the flat-color test background used this session).
   - Recommendation: include a `checkpoint:human-verify` step against a real rendered clip before considering HOOK-01 fully satisfied, mirroring Phase 7's Plan 07-05 precedent.

2. **Should `hook_banner.position` be more than a binary top/bottom choice** (e.g. respecting `crop_style`'s letterbox bars the way `compute_subtitle_margin_v` already does for pad/original-16:9)?
   - What we know: `compute_subtitle_margin_v` extends the bottom subtitle margin into a letterbox bar's own height for `pad`/`original-16:9` crops.
   - What's unclear: whether the top banner zone needs similar crop-style-aware adjustment, or a fixed `y=140` is fine since the top of frame is real video content (not a letterbox bar) in all three crop styles.
   - Recommendation: fixed `y=140` is sufficient for v1 (only the bottom of a `pad`/`original-16:9` crop has a letterbox bar; the top zone this phase uses is unaffected) - defer crop-aware banner placement unless a real render shows otherwise.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| ffmpeg `drawtext` filter | HOOK-01/02 | Yes (verified this session) | Present in `8.1.2-full_build` (`--enable-libfreetype --enable-libfribidi --enable-libharfbuzz`) | N/A - already a hard project dependency |
| `C:\Windows\Fonts\ariblk.ttf` / `arialbd.ttf` | Banner font rendering | Yes (verified this session, visually confirmed Cyrillic) | OS-provided | Non-Windows: document a fallback bold font path, same as `config.subtitles.font`'s existing comment |

**Missing dependencies with no fallback:** none.
**Missing dependencies with fallback:** font path only, on non-Windows platforms (not this project's primary runtime - see `CLAUDE.md`'s Windows-first constraint).

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | `pytest>=7.4.0` |
| Config file | `pyproject.toml` (`pythonpath=["."]`, `testpaths=["tests"]`, `integration` marker) |
| Quick run command | `pytest -m "not integration" tests/test_render.py tests/test_config.py -x` |
| Full suite command | `pytest tests/ -x` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| HOOK-01 | `build_hook_banner_filter` produces expected chained-drawtext string for both modes (exact-string assertion, mirrors `test_build_profanity_mask_filter`'s pattern) | unit | `pytest tests/test_render.py -k banner_filter -x` | Wave 0 |
| HOOK-02 | Config validation rejects `hook_banner.position == subtitles.position == "top"` | unit | `pytest tests/test_config.py -k banner_position_collision -x` | Wave 0 |
| HOOK-03 | `render_clip` with `banner_text` absent produces byte-identical command to today (no banner clause in `video_filter`) | unit | `pytest tests/test_render.py -k banner_absent_byte_identical -x` | Wave 0 |
| HOOK-04 | A rendered clip with `banner_text` set actually shows the text (real ffmpeg, frame-extraction + non-blank-region assertion) | integration | `pytest tests/test_integration_ffmpeg.py -k hook_banner -m integration -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest -m "not integration" tests/test_render.py tests/test_config.py -x`
- **Per wave merge:** Full suite including `integration`-marked real-ffmpeg tests
- **Phase gate:** Full suite green + a manual `checkpoint:human-verify` watching one real rendered clip with the banner on (Open Question 1)

### Wave 0 Gaps
- [ ] `tests/test_render.py` additions - `build_hook_banner_filter` string-assertion tests (both modes, escaping cases, empty-text fail-open), insertion-order test (banner appears after punch-zoom clause, before subtitles clause)
- [ ] `tests/test_config.py` additions - `HookBannerConfig` validation (mirrors `ProfanityConfig`/`DiarizationConfig` test shape)
- [ ] `tests/test_integration_ffmpeg.py` addition - real-ffmpeg render with `banner_text` set, frame-extraction sanity check that pixels changed in the banner region vs. an unbannered render

## Security Domain

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V5 Input Validation | Yes | `_escape_drawtext_text` must escape backslash/quote/colon/comma before any title text reaches the filter string - an unescaped title containing `:` or `,` would corrupt the filtergraph (parse error, not code execution - `drawtext` has no eval/exec surface), but still a correctness bug worth closing per the existing `_escape_ass_text`/subtitles-path-colon-escape precedent |
| V6 Cryptography | No | N/A |

### Known Threat Patterns for this stack
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| A title containing unescaped filtergraph-meaningful characters (`:`, `,`, `'`, `\`) breaking the `-vf` string parse | Tampering (of the render command, not a security boundary - titles are generator-controlled, not attacker-controlled) | `_escape_drawtext_text`, applied before every `text=` interpolation (Pattern 1 above) |

## Sources

### Primary (HIGH confidence - verified this session)
- Live `ffmpeg 8.1.2-full_build` execution on this machine via `subprocess.run` (Python, argv list, no shell) - confirmed `fontfile=` Cyrillic rendering (visual PNG inspection), `font=<name>` fontconfig failure, `\n`-does-not-newline behavior (visual PNG inspection, both bash and Python-subprocess reproductions), chained-multi-line independent centering (visual PNG inspection), `expansion=none` suppressing `%` warnings, colon/comma/apostrophe escaping inside `text=`, `enable`/`alpha` timeline expression acceptance (rc=0)
- `D:\shorts-maker\scripts\render.py` - read directly: `build_ffmpeg_command`/`build_jumpcut_command`/`build_compilation_command`/`build_punch_zoom_filter`/`build_video_effects_chain`/`build_subtitle_force_style`/`SUBTITLE_MARGIN_V`/`compute_subtitle_margin_v`/`render_clip` structure and existing filter-order rationale
- `D:\shorts-maker\scripts\config.py`, `config.example.yaml` - dataclass/fail-open validation conventions
- `D:\shorts-maker\.claude\skills\make-shorts\SKILL.md` (steps 5/5b/6) - PLAN.json field flow, `--profanity-*` CLI-flag "pass regardless, harmless no-op" convention reused for `--banner-*`
- `D:\shorts-maker\.planning\phases\07-profanity-auto-bleep\07-RESEARCH.md` - structural precedent for this document and the fail-open/checkpoint conventions reused here
- `D:\shorts-maker\.planning\ROADMAP.md` (Phase 8 entry) - locked mode decision (`persistent` default), success criteria
- `D:\shorts-maker\work\refs\_analysis\ANALYSIS.md` - real reference example (`twitch.tv/dunduk` persistent CAPS-hook + colored-number + nick plate) grounding the persistent+CTA design
- `D:\shorts-maker\docs\metadata-writing-ru.md` - hook-formula length constraint (<=7 words, <=3s readable, one CAPS word) used for the char-wrap sizing recommendation

### Secondary / Tertiary
- None used for a load-bearing claim - all `drawtext`-mechanics claims were live-verified rather than taken from unverified secondary sources; platform safe-area pixel figures (A2) are `[ASSUMED]`, flagged in the Assumptions Log.

## Metadata

**Confidence breakdown:**
- `drawtext` filter mechanics (fontfile, escaping, multi-line, timeline): HIGH - live-verified against the real binary + visual frame inspection
- Codebase integration points (`render.py` structure, PLAN.json/SKILL.md conventions): HIGH - read directly
- Placement pixel math (subtitle zones): HIGH (reused existing `SUBTITLE_MARGIN_V` constants) / MEDIUM (platform-UI-safe-area figures, `[ASSUMED]`, see A2)
- Font legibility/styling final values: MEDIUM - functionally verified to render correctly; final tuning deferred to a human-verify checkpoint (Open Question 1), same as Phase 7's D-03 precedent

**Research date:** 2026-07-12
**Valid until:** ffmpeg `drawtext` mechanics are stable/long-lived - 90 days reasonable. Platform safe-area figures should be re-checked if TikTok/YouTube/Instagram change their UI layout (directional, not a hard expiry).
