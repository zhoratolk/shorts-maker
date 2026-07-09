# Phase 5: Sub-Threshold Highlight Compilation - Pattern Map

**Mapped:** 2026-07-09
**Files analyzed:** 8 (2 new modules, 2 extended modules, 4 test files)
**Analogs found:** 8 / 8

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|--------------------|------|-----------|-----------------|---------------|
| `scripts/compilation.py` (new) | service/utility (mechanical validation + PLAN.json entry builder) | transform/batch | `scripts/transitions.py` (module shape: docstring, stdlib-only import discipline, CLI wrapper) + `scripts/jumpcuts.py` (mechanical-math-only-once-Claude-decided pattern) | role-match (closest single-concern sibling module) |
| `scripts/candidates.py` (extended) | model + service (dataclass + markdown/JSON render) | CRUD (add fields) / transform (markdown append) | itself, existing `Candidate`, `merge_candidates`, `render_candidates_markdown` | exact (same file, additive fields + new function following existing shape) |
| `scripts/render.py::build_compilation_command` (new fn in existing file) | service (ffmpeg command builder) | transform (filter-graph construction) | `scripts/render.py::build_jumpcut_command` / `_build_transition_fold` / `build_transition_filter` | exact (same file, sibling function, explicitly parallel in shape) |
| `tests/test_compilation.py` (new) | test | unit | `tests/test_transitions.py` (or `tests/test_jumpcuts.py`, same repo test-per-module convention) | role-match |
| `tests/test_candidates.py` (extended) | test | unit | itself, existing tests for `Candidate`/`merge_candidates`/`render_candidates_markdown` | exact |
| `tests/test_render.py` (extended) | test | unit (mocked `runner`) | itself, existing `build_jumpcut_command` tests | exact |
| `tests/test_integration_ffmpeg.py` (extended) | test | integration (real ffmpeg, `integration` marker) | itself, existing jumpcut/transition integration smoke tests | exact |
| `.claude/skills/make-shorts/SKILL.md` (wiring edits, step 5) | orchestration doc | request-response (Claude judgment steps) | itself, existing step 5 refine-pass / step 3 candidate-finding schema docs | exact |

## Pattern Assignments

### `scripts/compilation.py` (new module — service/utility, batch/transform)

**Analog:** `scripts/transitions.py` (module-level shape) — no direct prior analog exists for "mechanical grouping/validation module consuming a Claude-made decision", so pattern comes from this project's own module-shape conventions rather than one single closest file.

**Module docstring pattern** (mirror `scripts/transitions.py` lines 1-12): explain *why* the module exists and what stays out of it (semantic judgment) — e.g.:
```python
"""Mechanical grouping-validation and PLAN.json compilation-entry builder for
sub-threshold highlight compilations (COMP-01/02/03). Claude has already
decided WHICH sub-threshold candidates belong in a group (D-02, semantic
similarity judgment) and their strongest-first order (D-04) before anything
in this module runs — this module only validates the mechanical constraints
(group size >= 2, same video_stem, length ceiling) and assembles the
PLAN.json "compilation" entry shape. No tag-similarity matching, no
string/fuzzy comparison of tag text lives here — see project Anti-Pattern
"Encoding semantic judgment in Python".
"""
```

**sys.path bootstrap for direct invocation** (copy verbatim from `scripts/transitions.py` lines 23-28):
```python
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
```
(only needed if `compilation.py` imports sibling `scripts.*` modules, e.g. `scripts.candidates.Candidate`)

**Custom exception pattern** (mirror `scripts/render.py:43` `class RenderError(ValueError): pass` / `scripts/transitions.py:41-42` `class TransitionError(ValueError): pass`):
```python
class CompilationError(ValueError):
    pass
```

**Validation-then-build pattern** (mirror `build_jumpcut_command`'s up-front guard style, `scripts/render.py:546-555`):
```python
if len(group_candidates) < 2:
    raise CompilationError(f"a compilation group needs >= 2 members, got {len(group_candidates)}")
video_stems = {c.video_stem for c in group_candidates}
if len(video_stems) > 1:
    raise CompilationError(f"all group members must share one video_stem, got {sorted(video_stems)}")
```

**CLI wrapper pattern** (mirror `scripts/transitions.py::main()` lines 339-377 and `_cmd_select_transitions` lines 325-336): one `argparse` subcommand, reads JSON in, writes JSON/PLAN entry out, prints the output path as the last line (matches `scripts/diarize.py main()` convention noted in CLAUDE.md).

**Fail-open / conservative-cap pattern** (mirror Pitfall 3's recommendation — stop adding members once running total exceeds `compilation_max_seconds`, keep the ones that fit, ordered strongest-first per D-04; never raise on a group that has to shrink, only raise on `< 2` remaining members).

---

### `scripts/candidates.py` (extended — model + service, CRUD/transform)

**Analog:** itself (existing file, additive only)

**Dataclass extension pattern** (exact current shape, `scripts/candidates.py` lines 9-17 — extend, do not restructure):
```python
@dataclasses.dataclass
class Candidate:
    id: int
    start: float
    end: float
    reason: str
    coherence: int | None = None
    tag: str | None = None            # D-01
    sub_threshold: bool = False
    group_id: int | None = None
    unmatched: bool = False
```
All new fields optional/defaulted — matches the file's existing convention (`coherence: int | None = None`) and the project-wide "optional fields default, never a breaking schema change" pattern (`PLAN.json` entries per CLAUDE.md Key Abstractions).

**`merge_candidates` extension pattern** (exact current shape, lines 29-45 — add `.get()` calls the same way `coherence` is already read, do not touch sort/id-assignment logic):
```python
Candidate(
    id=index + 1,
    start=item["start"],
    end=item["end"],
    reason=item["reason"],
    coherence=item.get("coherence"),
    tag=item.get("tag"),
    sub_threshold=item.get("sub_threshold", False),
    group_id=item.get("group_id"),
    unmatched=item.get("unmatched", False),
)
```

**Markdown-render style to copy for the new append function** (mirror `render_candidates_markdown`, lines 54-66 — same guard-on-empty, same `lines.append`/`"\n".join` shape, same em-dash/backtick timecode format):
```python
def format_timecode(total_seconds: float) -> str: ...  # reuse verbatim, don't duplicate

def append_compilation_sections_markdown(path: str, groups: list[dict], unmatched: list[Candidate]) -> None:
    existing = Path(path).read_text(encoding="utf-8")
    lines = ["", "## Sub-Threshold Compilations", ""]
    for group in groups:
        member_ids = ", ".join(f"#{m.id}" for m in group["members"])
        lines.append(f"- Candidates {member_ids} grouped into compilation: {group['title']}")
    lines += ["", "## Unmatched Sub-Threshold", ""]
    for candidate in unmatched:
        start_tc = format_timecode(candidate.start)
        end_tc = format_timecode(candidate.end)
        lines.append(f"- `{start_tc}` - `{end_tc}` — {candidate.reason} (tag: {candidate.tag})")
    Path(path).write_text(existing + "\n".join(lines) + "\n", encoding="utf-8")
```
Follows Open Question #1's recommendation in RESEARCH.md — read-append-rewrite, not a second document.

**JSON write pattern** (reuse verbatim, `write_candidates_json`, lines 69-73 — `dataclasses.asdict` already picks up new fields automatically, zero changes needed there).

**CLI `main()` pattern** (lines 76-87 — same `argparse` two-positional-args-plus-print-count shape if a new subcommand is added for the append function; otherwise this stays an internally-called function, no CLI needed).

---

### `scripts/render.py::build_compilation_command` (new function — service, transform)

**Analog:** `scripts/render.py::build_jumpcut_command` (lines 504-625) + `_build_transition_fold` (lines 397-501) + `build_transition_filter` (lines 274-312)

**Function signature shape to mirror** (parallel to `build_jumpcut_command`'s parameter list, lines 504-525 — same crop/subtitle/denoise/loudnorm/vignette/grain/punch-zoom/fade kwargs applied once at the end per D-06, replacing `keep_segments: list[tuple[float,float]]` with a `members: list[dict]` shape where each member carries its own `start`/`end`/optional `keep_segments`):
```python
def build_compilation_command(
    input_path: str,
    output_path: str,
    members: list[dict],  # each: {"start": float, "end": float, "keep_segments": [...] | None}
    crop_filter: str,
    boundary_transitions: list[str] | None = None,
    transition_duration: float = 0.35,
    min_overlap_seconds: float = 0.12,
    subtitles_path: str | None = None,
    fade_seconds: float = 0.0,
    subtitle_style: dict | None = None,
    denoise: bool = False,
    loudnorm: bool = False,
    vignette: bool = False,
    grain_strength: int = 0,
    punch_zoom_at: float | None = None,
    punch_zoom_amount: float = 1.15,
    punch_zoom_ramp: float = 0.25,
    denoise_strength: float = 6.0,
) -> list[str]:
```

**Up-front validation guard** (exact pattern, `scripts/render.py` lines 546-555):
```python
if not members:
    raise RenderError("members must not be empty")
if len(members) < 2:
    raise RenderError("a compilation needs >= 2 members")
if boundary_transitions is not None:
    for transition_type in boundary_transitions:
        if transition_type not in VALID_TRANSITIONS:
            raise RenderError(
                f"boundary_transitions entries must be one of {sorted(VALID_TRANSITIONS)}, got {transition_type!r}"
            )
```

**Multi-input `-ss`/`-i` construction** (new pattern per RESEARCH.md Pattern 1/3 — one input pair per member, NOT the single `-ss`/`-i` trick `build_jumpcut_command` uses):
```python
input_args = []
for index, member in enumerate(members):
    input_args += ["-ss", str(member["start"]), "-i", input_path, "-t", str(member["end"] - member["start"])]
```
Each member's own internal jump cuts (if `keep_segments` present) are trimmed/concatenated within that member's own `[i:v]`/`[i:a]` input index BEFORE the fold — reuse the exact per-segment `trim`/`atrim`+`setpts` stage shape from `_build_transition_fold` lines 465-468, just re-keyed from `[0:v]`/`[0:a]` to `[{index}:v]`/`[{index}:a]`.

**Fold-stage reuse — same pairwise algorithm shape as `_build_transition_fold`** (lines 397-501): reuse `build_transition_filter` (lines 274-312) verbatim for the xfade/acrossfade node per stitch boundary; reuse the `concat=n=2:v=1:a=1` downgrade path verbatim (line 486) when `d_eff is None`. Per RESEARCH.md Pattern 1's "Critical difference": **do not pass `boundary_gaps`** — cap borrowable overlap as `min(transition_duration, seg_a_duration/2, seg_b_duration/2)` instead of using `compute_boundary_gaps`, since there is no free pause between two separately-approved candidates (RESEARCH.md Pattern 1, Anti-Patterns).

**Post-fold tail (crop/punch-zoom/subtitles/fade applied ONCE per D-06)** — reuse verbatim, `scripts/render.py` lines 583-603 (`video_ops` list construction: crop_filter → punch_zoom → effects_chain → subtitles_clause → fade), applied to `[vcat]`/`[acat]` exactly as `build_jumpcut_command` already does. **Zero new code needed for this part** per RESEARCH.md Pattern 3.

**Path-escaping pattern for subtitles** (copy exactly, line 590, and also the same convention in `build_ffmpeg_command` line 364): `subtitles_path.replace("\\", "/").replace(":", "\\:")` — never interpolate a raw external path string (Security Domain V5).

---

## Shared Patterns

### Fail-open optional features
**Source:** `scripts/transitions.py::select_boundary_transitions` (full fail-open behavior, lines 250-253) and CLAUDE.md's documented Anti-Pattern/Error-Handling convention.
**Apply to:** `scripts/compilation.py`'s grouping-validation call site if it ever touches `select_boundary_transitions` for compilation stitch points — if cv2/librosa are unavailable, every boundary resolves to `"cut"`, never a crash. `build_compilation_command` must accept `boundary_transitions=None` and behave as a plain concat fold (mirrors `build_jumpcut_command`'s existing `uses_fold` check, `scripts/render.py` lines 561-563).

### Input validation against a frozen enum before ffmpeg interpolation
**Source:** `scripts/render.py::build_transition_filter` lines 290-293, `build_jumpcut_command` lines 549-555.
**Apply to:** `build_compilation_command` — validate every `boundary_transitions` entry against `VALID_TRANSITIONS`/`TRANSITION_TYPES` before it reaches any filter-string construction (Security Domain V5, ASVS).

### Custom exception subclassing a builtin
**Source:** `class RenderError(ValueError): pass` (`scripts/render.py:43`), `class TransitionError(ValueError): pass` (`scripts/transitions.py:41-42`).
**Apply to:** new `class CompilationError(ValueError): pass` in `scripts/compilation.py`.

### Optional-field, non-breaking dataclass extension
**Source:** `scripts/candidates.py::Candidate` — `coherence: int | None = None` (line 17), already-established precedent for adding an optional field without touching `merge_candidates`' sort/id logic.
**Apply to:** the four new `Candidate` fields (`tag`, `sub_threshold`, `group_id`, `unmatched`) — all default `None`/`False`.

### `runner=subprocess.run` injectable pattern
**Source:** `scripts/render.py::probe_video`, `scripts/transitions.py::extract_audio_window` (line 110), CLAUDE.md Key Abstractions.
**Apply to:** any new ffmpeg-invoking function in `scripts/compilation.py` or the render-dispatch path for compilation entries — keep it unit-testable without a real ffmpeg binary; tests mock `runner`, only `tests/test_integration_ffmpeg.py` (marked `integration`) uses the real binary.

### One-module-per-concern / no script imports another script's logic destructively
**Source:** CLAUDE.md Architectural Constraints ("Circular imports: None — scripts are siblings... none imports another `scripts.*` module").
**Apply to:** `scripts/compilation.py` should import `scripts.candidates.Candidate`/`scripts.jumpcuts.remap_words` as needed (read-only reuse, matching how `scripts/transitions.py` already imports `scripts.jumpcuts.compute_boundary_gaps` and `scripts.frames.extract_frames`, lines 30-31) but must not fold its own logic back into those modules.

## No Analog Found

None — every file in scope has a strong same-repo analog (either itself being extended, or a structurally parallel sibling module/function). The two genuinely new pieces of logic (`scripts/compilation.py`'s grouping validation, `render.py::build_compilation_command`'s multi-input fold) are explicitly documented in RESEARCH.md as compositions of existing verified building blocks (`select_boundary_transitions`, `build_transition_filter`, `_build_transition_fold`'s algorithm shape, `remap_words`), not novel unverified code.

## Metadata

**Analog search scope:** `scripts/` (all `.py` modules), `tests/` (module-mirroring test files), `.claude/skills/make-shorts/SKILL.md`
**Files scanned:** `scripts/transitions.py` (full read), `scripts/candidates.py` (full read), `scripts/render.py` (targeted reads: `build_transition_filter`, `build_audio_filter_chain`, `build_ffmpeg_command`, `_build_transition_fold`, `build_jumpcut_command` — lines 274-625), `scripts/jumpcuts.py` (function signatures via grep)
**Pattern extraction date:** 2026-07-09
