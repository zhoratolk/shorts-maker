# Subtitle styling, karaoke highlight & hype-phrase sensitivity — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bigger/higher subtitles, a centered video frame with subtitle position tied to the actual black-bar geometry, always-on karaoke-style word highlighting synced to speech, and pass-1 candidate finding that's explicitly sensitive to streamer/chat hype phrases.

**Architecture:** All changes are additive edits to the existing deterministic modules (`scripts/config.py`, `scripts/render.py`, `scripts/subtitles.py`) plus one prompt-only `SKILL.md` update — no new files, no new dependencies. Karaoke timing reads the per-word JSON that `SKILL.md` step 5.3 already writes to disk, so render-time code needs no new upstream data.

**Tech Stack:** Python 3.11+, PyYAML, pytest (unchanged from the base project).

## Global Constraints

- `subtitles.size` default moves `72 -> 92`; `SUBTITLE_MARGIN_V["bottom"]` in `scripts/render.py` moves `280 -> 380` (spec §1).
- `pad` crop centers the video (`top_pad = round(total_pad / 2)`, same formula `original-16:9` already uses). For `pad`/`original-16:9`, bottom-position subtitle margin becomes `max(SUBTITLE_MARGIN_V["bottom"], bottom_bar_height // 2)` — computed relative to the actual video frame, never below the 380px safe floor. `zoom` and the `top`/`center` positions keep the static per-config margin (spec §2).
- Karaoke word-highlight is **always on**, no config toggle — `PrimaryColour` = configured base subtitle color, `SecondaryColour` = new `subtitles.highlight_color` (default `yellow`), via ASS `\k<centiseconds>` tags (spec §3).
- `.srt` output stays plain text (no ASS tags) — it's still the human/Claude proofreading surface from pipeline step 5.2. Karaoke timing is derived at render time from the sibling `<clip_filename_stem>_words.json` file (already written by `SKILL.md` step 5.3); if that file is missing, render falls back to plain (non-karaoke) cues — never a hard error (spec §3).
- New `analysis.hype_phrases` config field (`list[str]`, user-editable default list) — pass-1 candidate finding treats matches, and similar-register language, as a strong positive signal (spec §4). Prompt-only change, no new deterministic code.
- `TARGET_WIDTH`/`TARGET_HEIGHT` stay fixed at 1080x1920 (unchanged from the base plan).

---

### Task 1: Config schema — `analysis.hype_phrases`, `subtitles.highlight_color`, bigger default subtitle size

**Files:**
- Modify: `scripts/config.py:27-31` (`AnalysisConfig`), `scripts/config.py:53-61` (`SubtitlesConfig`)
- Modify: `config.example.yaml:11-22` (`analysis:` block), `config.example.yaml:62-75` (`subtitles:` block)
- Test: `tests/test_config.py`, `tests/test_config_example.py`

**Interfaces:**
- Produces: `AnalysisConfig.hype_phrases: list[str]` (default 8-phrase Russian streaming-slang list), `SubtitlesConfig.size: int = 92` (was 72), `SubtitlesConfig.highlight_color: str = "yellow"`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_config.py`:

```python
def test_load_config_subtitles_defaults_size_and_highlight_color(tmp_path):
    path = write_config(tmp_path, 'input_dir: "F:/in"\noutput_dir: "F:/out"\n')

    config = load_config(path)

    assert config.subtitles.size == 92
    assert config.subtitles.highlight_color == "yellow"


def test_load_config_analysis_default_hype_phrases(tmp_path):
    path = write_config(tmp_path, 'input_dir: "F:/in"\noutput_dir: "F:/out"\n')

    config = load_config(path)

    assert config.analysis.hype_phrases == [
        "завоз", "ору", "кринж", "база", "это база", "мем вышел", "жиза", "воу-воу",
    ]


def test_load_config_analysis_hype_phrases_overridable(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        analysis:
          hype_phrases: ["кастом"]
        """,
    )

    config = load_config(path)

    assert config.analysis.hype_phrases == ["кастом"]
```

Add to `tests/test_config_example.py` (inside `test_example_config_loads_without_error`):

```python
    assert config.subtitles.size == 92
    assert config.subtitles.highlight_color == "yellow"
    assert config.analysis.hype_phrases == [
        "завоз", "ору", "кринж", "база", "это база", "мем вышел", "жиза", "воу-воу",
    ]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_config.py tests/test_config_example.py -v`
Expected: FAIL — `AttributeError`/`TypeError` on the new fields (they don't exist yet) or `AssertionError` on `size == 72` mismatch.

- [ ] **Step 3: Update the dataclasses**

In `scripts/config.py`, replace:

```python
@dataclasses.dataclass
class AnalysisConfig:
    chunk_minutes: int = 35
    use_subagents: bool = True
    require_approval: bool = True
```

with:

```python
@dataclasses.dataclass
class AnalysisConfig:
    chunk_minutes: int = 35
    use_subagents: bool = True
    require_approval: bool = True
    hype_phrases: list[str] = dataclasses.field(
        default_factory=lambda: [
            "завоз", "ору", "кринж", "база", "это база", "мем вышел", "жиза", "воу-воу",
        ]
    )
```

Replace:

```python
@dataclasses.dataclass
class SubtitlesConfig:
    enabled: bool = False
    font: str = "Arial Black"
    size: int = 72
    color: str = "white"
    outline: str = "black"
    position: str = "bottom"
    words_per_cue: int = 4
```

with:

```python
@dataclasses.dataclass
class SubtitlesConfig:
    enabled: bool = False
    font: str = "Arial Black"
    size: int = 92
    color: str = "white"
    outline: str = "black"
    highlight_color: str = "yellow"
    position: str = "bottom"
    words_per_cue: int = 4
```

- [ ] **Step 4: Update `config.example.yaml`**

Replace the `analysis:` block:

```yaml
analysis:
  # Chunk size for pass-1 candidate search. Recommended range: 20-45 minutes.
  # Smaller = more precise candidates but more subagent calls (slower/pricier).
  # Larger = cheaper but risks missing a short moment inside a big block.
  chunk_minutes: 35
  # Parallel subagents per chunk (recommended). false = one sequential pass
  # over the whole transcript instead - simpler and cheaper, but slower and
  # coarser on very long (multi-hour) recordings.
  use_subagents: true
  # Stop and show CANDIDATES.md for you to pick from before rendering.
  # false = fully automatic, rendering every candidate found.
  require_approval: true
```

with:

```yaml
analysis:
  # Chunk size for pass-1 candidate search. Recommended range: 20-45 minutes.
  # Smaller = more precise candidates but more subagent calls (slower/pricier).
  # Larger = cheaper but risks missing a short moment inside a big block.
  chunk_minutes: 35
  # Parallel subagents per chunk (recommended). false = one sequential pass
  # over the whole transcript instead - simpler and cheaper, but slower and
  # coarser on very long (multi-hour) recordings.
  use_subagents: true
  # Stop and show CANDIDATES.md for you to pick from before rendering.
  # false = fully automatic, rendering every candidate found.
  require_approval: true
  # Phrases that signal a strong candidate moment on their own (streamer/chat
  # hype, meme call-outs) - pass-1 treats these, and similar language, as a
  # positive signal even when the surrounding text looks unremarkable.
  hype_phrases: ["завоз", "ору", "кринж", "база", "это база", "мем вышел", "жиза", "воу-воу"]
```

Replace the `subtitles:` block:

```yaml
subtitles:
  enabled: false
  # Arial Black: bold, full Cyrillic support, ships with Windows - reliable
  # for burned-in captions over busy gameplay footage.
  font: Arial Black
  size: 72
  color: white
  outline: black
  # bottom keeps a safe margin from the true bottom edge (280px of 1920) so
  # captions don't sit under TikTok/Reels/Shorts' own caption/like/comment UI.
  position: bottom       # bottom | top | center
  # How many words appear per subtitle cue - keeps captions short and synced
  # to speech instead of showing a whole sentence at once.
  words_per_cue: 4
```

with:

```yaml
subtitles:
  enabled: false
  # Arial Black: bold, full Cyrillic support, ships with Windows - reliable
  # for burned-in captions over busy gameplay footage.
  font: Arial Black
  size: 92
  color: white
  outline: black
  # Color of the word currently being spoken (karaoke-style highlight,
  # always on). Base subtitle color above is used for words before/after.
  highlight_color: yellow
  # bottom keeps a safe margin from the true bottom edge (380px of 1920) so
  # captions don't sit under TikTok/Reels/Shorts' own caption/like/comment UI.
  # For pad/original-16:9 crops, this is also the floor - captions center in
  # the black bar under the video but never sit closer to the edge than this.
  position: bottom       # bottom | top | center
  # How many words appear per subtitle cue - keeps captions short and synced
  # to speech instead of showing a whole sentence at once.
  words_per_cue: 4
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_config.py tests/test_config_example.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add scripts/config.py config.example.yaml tests/test_config.py tests/test_config_example.py
git commit -m "feat: add analysis.hype_phrases and subtitles.highlight_color config, bump default subtitle size to 92"
```

---

### Task 2: Raise the default subtitle bottom margin (280 -> 380)

**Files:**
- Modify: `scripts/render.py:23`
- Test: `tests/test_render.py`

**Interfaces:**
- Produces: `SUBTITLE_MARGIN_V["bottom"] == 380`.

- [ ] **Step 1: Update the failing assertions**

In `tests/test_render.py`, replace `test_build_subtitle_force_style_bottom_position`:

```python
def test_build_subtitle_force_style_bottom_position():
    style = build_subtitle_force_style(
        font="Arial Black", size=72, color="white", outline_color="black", position="bottom"
    )

    assert style == (
        "FontName=Arial Black,FontSize=72,PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H00000000,BorderStyle=1,Outline=4,Shadow=2,Bold=1,"
        "Alignment=2,MarginV=280"
    )
```

with:

```python
def test_build_subtitle_force_style_bottom_position():
    style = build_subtitle_force_style(
        font="Arial Black", size=72, color="white", outline_color="black", position="bottom"
    )

    assert style == (
        "FontName=Arial Black,FontSize=72,PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H00000000,BorderStyle=1,Outline=4,Shadow=2,Bold=1,"
        "Alignment=2,MarginV=380"
    )
```

Replace `test_build_ffmpeg_command_with_subtitle_style`:

```python
def test_build_ffmpeg_command_with_subtitle_style():
    command = build_ffmpeg_command(
        "in.mp4", "out.mp4", start=10.0, end=40.0,
        crop_filter="scale=1080:608,pad=1080:1920:0:394:black",
        subtitles_path="work/x/subs.srt",
        subtitle_style={"font": "Arial Black", "size": 72, "color": "white", "outline_color": "black", "position": "bottom"},
    )

    assert command[9] == (
        "scale=1080:608,pad=1080:1920:0:394:black,subtitles='work/x/subs.srt':"
        "force_style='FontName=Arial Black,FontSize=72,PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H00000000,BorderStyle=1,Outline=4,Shadow=2,Bold=1,"
        "Alignment=2,MarginV=280'"
    )
```

with:

```python
def test_build_ffmpeg_command_with_subtitle_style():
    command = build_ffmpeg_command(
        "in.mp4", "out.mp4", start=10.0, end=40.0,
        crop_filter="scale=1080:608,pad=1080:1920:0:394:black",
        subtitles_path="work/x/subs.srt",
        subtitle_style={"font": "Arial Black", "size": 72, "color": "white", "outline_color": "black", "position": "bottom"},
    )

    assert command[9] == (
        "scale=1080:608,pad=1080:1920:0:394:black,subtitles='work/x/subs.srt':"
        "force_style='FontName=Arial Black,FontSize=72,PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H00000000,BorderStyle=1,Outline=4,Shadow=2,Bold=1,"
        "Alignment=2,MarginV=380'"
    )
```

(Note: `394` in `crop_filter` is unrelated pre-existing test fixture data for a different task — leave it untouched here.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_render.py -k bottom_position -v`
Expected: FAIL — `MarginV=280` still produced.

- [ ] **Step 3: Update the constant**

In `scripts/render.py`, replace:

```python
SUBTITLE_MARGIN_V = {"bottom": 280, "top": 120, "center": 0}
```

with:

```python
SUBTITLE_MARGIN_V = {"bottom": 380, "top": 120, "center": 0}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_render.py -v`
Expected: PASS (all render tests, including the two updated above)

- [ ] **Step 5: Commit**

```bash
git add scripts/render.py tests/test_render.py
git commit -m "feat: raise default subtitle bottom margin from 280px to 380px"
```

---

### Task 3: Center the `pad` crop style

**Files:**
- Modify: `scripts/render.py:118-122` (`compute_crop_filter`, `pad` branch)
- Test: `tests/test_render.py`

**Interfaces:**
- Produces: `compute_crop_filter("pad", src_width, src_height)` now centers the video vertically (same `top_pad` formula as `original-16:9`), instead of biasing it toward the top.

- [ ] **Step 1: Update the failing assertion**

In `tests/test_render.py`, replace:

```python
def test_compute_crop_filter_pad():
    result = compute_crop_filter("pad", src_width=1920, src_height=1080)
    assert result == "scale=1080:608,pad=1080:1920:0:394:black"
```

with:

```python
def test_compute_crop_filter_pad():
    result = compute_crop_filter("pad", src_width=1920, src_height=1080)
    assert result == "scale=1080:608,pad=1080:1920:0:656:black"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_render.py -k test_compute_crop_filter_pad -v`
Expected: FAIL — got `...0:394:black`, expected `...0:656:black`.

- [ ] **Step 3: Center the video**

In `scripts/render.py`, replace:

```python
    if crop_style == "pad":
        scaled_height = round(src_height * TARGET_WIDTH / src_width)
        total_pad = TARGET_HEIGHT - scaled_height
        top_pad = round(total_pad * 0.3)
        return f"scale={TARGET_WIDTH}:{scaled_height},pad={TARGET_WIDTH}:{TARGET_HEIGHT}:0:{top_pad}:black"
```

with:

```python
    if crop_style == "pad":
        scaled_height = round(src_height * TARGET_WIDTH / src_width)
        total_pad = TARGET_HEIGHT - scaled_height
        top_pad = round(total_pad / 2)
        return f"scale={TARGET_WIDTH}:{scaled_height},pad={TARGET_WIDTH}:{TARGET_HEIGHT}:0:{top_pad}:black"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_render.py -k test_compute_crop_filter_pad -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/render.py tests/test_render.py
git commit -m "fix: center pad crop style vertically instead of biasing toward the top"
```

---

### Task 4: `compute_subtitle_margin_v` — tie caption position to the actual video frame

**Files:**
- Modify: `scripts/render.py` (add function near `compute_crop_filter`, after line 132)
- Test: `tests/test_render.py`

**Interfaces:**
- Consumes: `SUBTITLE_MARGIN_V`, `TARGET_WIDTH`, `TARGET_HEIGHT`, `RenderError` (all already in `scripts/render.py`).
- Produces: `compute_subtitle_margin_v(position: str, crop_style: str, src_width: int, src_height: int) -> int`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_render.py`, update the import line to also pull in `SUBTITLE_MARGIN_V` and `compute_subtitle_margin_v`:

```python
from scripts.render import (
    RenderError,
    ass_color,
    build_ass_content,
    build_ffmpeg_command,
    build_subtitle_force_style,
    clamp_clip_bounds,
    compute_crop_filter,
    compute_subtitle_margin_v,
    probe_video,
    render_clip,
    SUBTITLE_MARGIN_V,
)
```

Add tests (place near the `compute_crop_filter` tests):

```python
def test_compute_subtitle_margin_v_top_and_center_passthrough():
    assert compute_subtitle_margin_v("top", "zoom", src_width=1920, src_height=1080) == SUBTITLE_MARGIN_V["top"]
    assert compute_subtitle_margin_v("center", "pad", src_width=1920, src_height=1080) == SUBTITLE_MARGIN_V["center"]


def test_compute_subtitle_margin_v_zoom_uses_static_bottom_margin():
    assert compute_subtitle_margin_v("bottom", "zoom", src_width=1920, src_height=1080) == SUBTITLE_MARGIN_V["bottom"]


def test_compute_subtitle_margin_v_pad_uses_safe_floor_on_standard_16_9_source():
    # bottom bar is 656px; half of that (328px) is below the 380px safe
    # floor, so the floor wins for a typical 16:9 recording.
    assert compute_subtitle_margin_v("bottom", "pad", src_width=1920, src_height=1080) == 380


def test_compute_subtitle_margin_v_original_16_9_centers_in_large_bottom_bar():
    # an ultra-wide source leaves a big black bar - captions center inside
    # it, well past the 380px safe floor.
    assert compute_subtitle_margin_v("bottom", "original-16:9", src_width=2560, src_height=600) == 416


def test_compute_subtitle_margin_v_rejects_unresolved_auto():
    with pytest.raises(RenderError, match="resolved value"):
        compute_subtitle_margin_v("bottom", "auto", src_width=1920, src_height=1080)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_render.py -k compute_subtitle_margin_v -v`
Expected: FAIL — `ImportError: cannot import name 'compute_subtitle_margin_v'`

- [ ] **Step 3: Implement the function**

In `scripts/render.py`, add immediately after `compute_crop_filter` (after the line ending the function, currently line 132's closing `raise RenderError(...)` block):

```python
def compute_subtitle_margin_v(position: str, crop_style: str, src_width: int, src_height: int) -> int:
    if position != "bottom":
        return SUBTITLE_MARGIN_V[position]

    if crop_style == "zoom":
        return SUBTITLE_MARGIN_V["bottom"]

    if crop_style in ("pad", "original-16:9"):
        scaled_height = round(src_height * TARGET_WIDTH / src_width)
        top_pad = round((TARGET_HEIGHT - scaled_height) / 2)
        bottom_bar_height = TARGET_HEIGHT - top_pad - scaled_height
        return max(SUBTITLE_MARGIN_V["bottom"], bottom_bar_height // 2)

    raise RenderError(
        f"crop_style must be a resolved value (zoom/pad/original-16:9), got {crop_style!r}. "
        "'auto' must be resolved to a concrete style before reaching render.py."
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_render.py -v`
Expected: PASS (full file, no regressions from Tasks 1-3)

- [ ] **Step 5: Commit**

```bash
git add scripts/render.py tests/test_render.py
git commit -m "feat: add compute_subtitle_margin_v to tie caption position to the actual video frame"
```

---

### Task 5: Karaoke word-highlight text builder

**Files:**
- Modify: `scripts/subtitles.py` (add functions after `group_words_into_cues`, currently ending at line 19)
- Test: `tests/test_subtitles.py`

**Interfaces:**
- Consumes: nothing new (pure functions over `{"word", "start", "end"}` dicts, same shape `group_words_into_cues` already uses).
- Produces: `build_karaoke_text(words: list[dict]) -> str`, `group_words_into_karaoke_cues(words: list[dict], max_words: int = 4) -> list[dict]`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_subtitles.py` (update the import line first):

```python
from scripts.subtitles import (
    build_karaoke_text,
    format_srt_timestamp,
    group_words_into_cues,
    group_words_into_karaoke_cues,
    parse_srt,
    render_srt,
)
```

```python
def test_build_karaoke_text_single_word():
    words = [{"word": "hello", "start": 0.0, "end": 0.4}]

    assert build_karaoke_text(words) == "{\\k40}hello"


def test_build_karaoke_text_two_words_with_gap():
    words = [
        {"word": "hello", "start": 0.0, "end": 0.4},
        {"word": "world", "start": 0.5, "end": 1.0},
    ]

    assert build_karaoke_text(words) == "{\\k40}hello{\\k10} {\\k50}world"


def test_build_karaoke_text_clamps_negative_gap_to_zero():
    words = [
        {"word": "hello", "start": 0.0, "end": 0.5},
        {"word": "world", "start": 0.4, "end": 0.9},
    ]

    assert build_karaoke_text(words) == "{\\k50}hello{\\k0} {\\k50}world"


def test_build_karaoke_text_strips_word_whitespace():
    words = [{"word": " hello ", "start": 0.0, "end": 0.3}]

    assert build_karaoke_text(words) == "{\\k30}hello"


def test_group_words_into_karaoke_cues_matches_plain_grouping_boundaries():
    words = [
        {"word": "one", "start": 0.0, "end": 0.3},
        {"word": "two", "start": 0.3, "end": 0.6},
        {"word": "three", "start": 0.6, "end": 0.9},
    ]

    cues = group_words_into_karaoke_cues(words, max_words=2)

    assert [(cue["start"], cue["end"]) for cue in cues] == [(0.0, 0.6), (0.6, 0.9)]
    assert cues[0]["text"] == "{\\k30}one{\\k0} {\\k30}two"
    assert cues[1]["text"] == "{\\k30}three"


def test_group_words_into_karaoke_cues_empty_input():
    assert group_words_into_karaoke_cues([], max_words=4) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_subtitles.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_karaoke_text'`

- [ ] **Step 3: Implement the functions**

In `scripts/subtitles.py`, add immediately after `group_words_into_cues` (after its closing line, currently line 19):

```python
def build_karaoke_text(words: list[dict]) -> str:
    first = words[0]
    parts = [f"{{\\k{round((first['end'] - first['start']) * 100)}}}{first['word'].strip()}"]
    for previous, word in zip(words, words[1:]):
        gap_cs = max(round((word["start"] - previous["end"]) * 100), 0)
        word_cs = round((word["end"] - word["start"]) * 100)
        parts.append(f"{{\\k{gap_cs}}} {{\\k{word_cs}}}{word['word'].strip()}")
    return "".join(parts)


def group_words_into_karaoke_cues(words: list[dict], max_words: int = 4) -> list[dict]:
    cues = []
    for i in range(0, len(words), max_words):
        group = words[i : i + max_words]
        cues.append(
            {
                "start": group[0]["start"],
                "end": group[-1]["end"],
                "text": build_karaoke_text(group),
            }
        )
    return cues
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_subtitles.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/subtitles.py tests/test_subtitles.py
git commit -m "feat: add karaoke-tagged word grouping for synced subtitle highlighting"
```

---

### Task 6: Wire margin + karaoke highlighting into render_clip and the CLI

**Files:**
- Modify: `scripts/render.py:62-97` (`build_ass_content`), `scripts/render.py:223-261` (`render_clip`), `scripts/render.py:264-308` (`main`)
- Test: `tests/test_render.py`

**Interfaces:**
- Consumes: `compute_subtitle_margin_v` (Task 4), `group_words_into_karaoke_cues` (Task 5), `parse_srt` (existing).
- Produces: `build_ass_content(cues, font, size, color, outline_color, highlight_color, position, margin_v, play_res_x, play_res_y) -> str` (signature change — `margin_v` is now an explicit caller-supplied value, not derived internally from `position`); `render_clip(...)` now builds karaoke cues when a sibling `<stem>_words.json` exists next to the subtitles path, else falls back to plain cues; CLI gains `--sub-highlight-color` (default `yellow`) and `--sub-words-per-cue` (default `4`).

- [ ] **Step 1: Update existing `build_ass_content` tests for the new signature**

In `tests/test_render.py`, replace:

```python
def test_build_ass_content_sets_play_res_to_canvas_size():
    cues = [{"start": 0.26, "end": 2.18, "text": "hello world"}]

    ass = build_ass_content(cues, "Arial Black", 72, "white", "black", "bottom", 1080, 1920)

    assert "PlayResX: 1080" in ass
    assert "PlayResY: 1920" in ass
    assert "Alignment=2" not in ass  # baked into the Style line, not a force_style override
    assert "Style: Default,Arial Black,72,&H00FFFFFF,&H000000FF,&H00000000," in ass
    assert "Dialogue: 0,0:00:00.26,0:00:02.18,Default,,0,0,0,,hello world" in ass


def test_build_ass_content_escapes_newlines_as_hard_breaks():
    cues = [{"start": 0.0, "end": 1.0, "text": "line one\nline two"}]

    ass = build_ass_content(cues, "Arial", 48, "white", "black", "top", 1080, 1920)

    assert "line one\\Nline two" in ass
```

with:

```python
def test_build_ass_content_sets_play_res_to_canvas_size():
    cues = [{"start": 0.26, "end": 2.18, "text": "hello world"}]

    ass = build_ass_content(cues, "Arial Black", 92, "white", "black", "yellow", "bottom", 380, 1080, 1920)

    assert "PlayResX: 1080" in ass
    assert "PlayResY: 1920" in ass
    assert "Alignment=2" not in ass  # baked into the Style line, not a force_style override
    assert "Style: Default,Arial Black,92,&H00FFFFFF,&H0000FFFF,&H00000000," in ass
    assert "MarginV=380" in ass
    assert "Dialogue: 0,0:00:00.26,0:00:02.18,Default,,0,0,0,,hello world" in ass


def test_build_ass_content_escapes_newlines_as_hard_breaks():
    cues = [{"start": 0.0, "end": 1.0, "text": "line one\nline two"}]

    ass = build_ass_content(cues, "Arial", 48, "white", "black", "yellow", "top", 120, 1080, 1920)

    assert "line one\\Nline two" in ass
```

Replace the `subtitle_style` dict in `test_render_clip_bakes_subtitles_into_ass_with_canvas_play_res`:

```python
    subtitle_style = {
        "font": "Arial Black", "size": 72, "color": "white",
        "outline_color": "black", "position": "bottom",
    }
```

with:

```python
    subtitle_style = {
        "font": "Arial Black", "size": 92, "color": "white",
        "outline_color": "black", "highlight_color": "yellow",
        "position": "bottom", "words_per_cue": 4,
    }
```

(This test's `tmp_path` fixture writes only `subs.srt`, no sibling `_words.json`, so it now doubles as the fallback-to-plain-cues regression test — its existing assertions are unaffected.)

- [ ] **Step 2: Add a test proving the karaoke path is used when a words.json sibling exists**

Add to `tests/test_render.py`:

```python
def test_render_clip_uses_karaoke_words_json_when_present(tmp_path):
    srt_path = tmp_path / "subs.srt"
    srt_path.write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nhello world\n\n", encoding="utf-8"
    )
    words_path = tmp_path / "subs_words.json"
    words_path.write_text(
        json.dumps([
            {"word": "hello", "start": 0.0, "end": 0.4},
            {"word": "world", "start": 0.5, "end": 1.0},
        ]),
        encoding="utf-8",
    )

    captured = {}

    class FakeResult:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_runner(command, capture_output, text):
        captured["command"] = command
        return FakeResult()

    plan_entry = {
        "start": 10.0, "end": 40.0, "crop_style": "zoom",
        "subtitles_path": str(srt_path),
    }
    subtitle_style = {
        "font": "Arial Black", "size": 92, "color": "white", "outline_color": "black",
        "highlight_color": "yellow", "position": "bottom", "words_per_cue": 4,
    }

    render_clip(
        "in.mp4", "out.mp4", plan_entry,
        video_duration=100.0, src_width=1920, src_height=1080,
        subtitle_style=subtitle_style,
        runner=fake_runner,
    )

    ass_content = srt_path.with_suffix(".ass").read_text(encoding="utf-8")
    assert "\\k" in ass_content
    assert "hello" in ass_content
    assert "world" in ass_content
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_render.py -v`
Expected: FAIL — `TypeError: build_ass_content() takes 8 positional arguments but 10 were given` (or `KeyError: 'highlight_color'` in `render_clip`)

- [ ] **Step 4: Update `build_ass_content`**

In `scripts/render.py`, replace the whole function:

```python
def build_ass_content(
    cues: list[dict], font: str, size: int, color: str, outline_color: str, position: str,
    play_res_x: int, play_res_y: int,
) -> str:
    """Bakes cues into a self-contained .ass with PlayResX/Y matching the render canvas.

    ffmpeg's `subtitles` filter has no header info to go on for a plain .srt, so it
    assumes a 384x288 reference canvas and scales font/margins from there — on a
    1080x1920 canvas that blows FontSize/MarginV up by ~6.7x and the text lands off
    the top of frame. Writing PlayResX/Y equal to the actual output size avoids that
    scaling entirely, so style values apply at face value.
    """
    alignment = SUBTITLE_ALIGNMENT[position]
    margin_v = SUBTITLE_MARGIN_V[position]
    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {play_res_x}\n"
        f"PlayResY: {play_res_y}\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{font},{size},{ass_color(color)},&H000000FF,{ass_color(outline_color)},"
        f"&H00000000,1,0,0,0,100,100,0,0,1,4,2,{alignment},10,10,{margin_v},1\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    events = "".join(
        f"Dialogue: 0,{format_ass_timestamp(cue['start'])},{format_ass_timestamp(cue['end'])},"
        f"Default,,0,0,0,,{cue['text'].replace(chr(10), '\\N')}\n"
        for cue in cues
    )
    return header + events
```

with:

```python
def build_ass_content(
    cues: list[dict], font: str, size: int, color: str, outline_color: str, highlight_color: str,
    position: str, margin_v: int, play_res_x: int, play_res_y: int,
) -> str:
    """Bakes cues into a self-contained .ass with PlayResX/Y matching the render canvas.

    ffmpeg's `subtitles` filter has no header info to go on for a plain .srt, so it
    assumes a 384x288 reference canvas and scales font/margins from there — on a
    1080x1920 canvas that blows FontSize/MarginV up by ~6.7x and the text lands off
    the top of frame. Writing PlayResX/Y equal to the actual output size avoids that
    scaling entirely, so style values apply at face value.

    `highlight_color` becomes the style's SecondaryColour, which ASS `\\k<centiseconds>`
    tags in the cue text use for the karaoke sweep (word highlighted while spoken,
    reverting to `color`/PrimaryColour once done). `margin_v` is caller-supplied rather
    than derived from `position` here, so it can be tied to actual crop geometry —
    see `compute_subtitle_margin_v`.
    """
    alignment = SUBTITLE_ALIGNMENT[position]
    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {play_res_x}\n"
        f"PlayResY: {play_res_y}\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{font},{size},{ass_color(color)},{ass_color(highlight_color)},{ass_color(outline_color)},"
        f"&H00000000,1,0,0,0,100,100,0,0,1,4,2,{alignment},10,10,{margin_v},1\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    events = "".join(
        f"Dialogue: 0,{format_ass_timestamp(cue['start'])},{format_ass_timestamp(cue['end'])},"
        f"Default,,0,0,0,,{cue['text'].replace(chr(10), '\\N')}\n"
        for cue in cues
    )
    return header + events
```

- [ ] **Step 5: Update `render_clip`**

Replace:

```python
def render_clip(
    input_path: str,
    output_path: str,
    plan_entry: dict,
    video_duration: float,
    src_width: int,
    src_height: int,
    fade_seconds: float = 0.0,
    subtitle_style: dict | None = None,
    runner=subprocess.run,
) -> list[str]:
    start, end = clamp_clip_bounds(plan_entry["start"], plan_entry["end"], video_duration)
    crop_filter = compute_crop_filter(plan_entry["crop_style"], src_width, src_height)
    subtitles_path = plan_entry.get("subtitles_path")

    if subtitles_path is not None and subtitle_style is not None:
        import sys

        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from scripts.subtitles import parse_srt

        cues = parse_srt(Path(subtitles_path).read_text(encoding="utf-8"))
        ass_content = build_ass_content(
            cues, subtitle_style["font"], subtitle_style["size"], subtitle_style["color"],
            subtitle_style["outline_color"], subtitle_style["position"], TARGET_WIDTH, TARGET_HEIGHT,
        )
        subtitles_path = str(Path(subtitles_path).with_suffix(".ass"))
        Path(subtitles_path).write_text(ass_content, encoding="utf-8")
        subtitle_style = None  # baked into the .ass style block already; no force_style needed

    command = build_ffmpeg_command(
        input_path, output_path, start, end, crop_filter, subtitles_path,
        fade_seconds, video_duration, subtitle_style,
    )

    result = runner(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise RenderError(f"ffmpeg failed for {output_path}: {result.stderr}")
    return command
```

with:

```python
def render_clip(
    input_path: str,
    output_path: str,
    plan_entry: dict,
    video_duration: float,
    src_width: int,
    src_height: int,
    fade_seconds: float = 0.0,
    subtitle_style: dict | None = None,
    runner=subprocess.run,
) -> list[str]:
    start, end = clamp_clip_bounds(plan_entry["start"], plan_entry["end"], video_duration)
    crop_style = plan_entry["crop_style"]
    crop_filter = compute_crop_filter(crop_style, src_width, src_height)
    subtitles_path = plan_entry.get("subtitles_path")

    if subtitles_path is not None and subtitle_style is not None:
        import sys

        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from scripts.subtitles import group_words_into_karaoke_cues, parse_srt

        words_path = Path(subtitles_path).with_name(Path(subtitles_path).stem + "_words.json")
        if words_path.exists():
            words = json.loads(words_path.read_text(encoding="utf-8"))
            cues = group_words_into_karaoke_cues(words, max_words=subtitle_style["words_per_cue"])
        else:
            cues = parse_srt(Path(subtitles_path).read_text(encoding="utf-8"))

        margin_v = compute_subtitle_margin_v(
            subtitle_style["position"], crop_style, src_width, src_height
        )
        ass_content = build_ass_content(
            cues, subtitle_style["font"], subtitle_style["size"], subtitle_style["color"],
            subtitle_style["outline_color"], subtitle_style["highlight_color"],
            subtitle_style["position"], margin_v, TARGET_WIDTH, TARGET_HEIGHT,
        )
        subtitles_path = str(Path(subtitles_path).with_suffix(".ass"))
        Path(subtitles_path).write_text(ass_content, encoding="utf-8")
        subtitle_style = None  # baked into the .ass style block already; no force_style needed

    command = build_ffmpeg_command(
        input_path, output_path, start, end, crop_filter, subtitles_path,
        fade_seconds, video_duration, subtitle_style,
    )

    result = runner(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise RenderError(f"ffmpeg failed for {output_path}: {result.stderr}")
    return command
```

- [ ] **Step 6: Update the CLI (`main`)**

Replace:

```python
    parser.add_argument("--sub-font", default="Arial Black")
    parser.add_argument("--sub-size", type=int, default=72)
    parser.add_argument("--sub-color", default="white")
    parser.add_argument("--sub-outline-color", default="black")
    parser.add_argument("--sub-position", default="bottom", choices=sorted(SUBTITLE_ALIGNMENT))
    args = parser.parse_args()

    subtitle_style = {
        "font": args.sub_font,
        "size": args.sub_size,
        "color": args.sub_color,
        "outline_color": args.sub_outline_color,
        "position": args.sub_position,
    }
```

with:

```python
    parser.add_argument("--sub-font", default="Arial Black")
    parser.add_argument("--sub-size", type=int, default=92)
    parser.add_argument("--sub-color", default="white")
    parser.add_argument("--sub-outline-color", default="black")
    parser.add_argument("--sub-highlight-color", default="yellow")
    parser.add_argument("--sub-position", default="bottom", choices=sorted(SUBTITLE_ALIGNMENT))
    parser.add_argument("--sub-words-per-cue", type=int, default=4)
    args = parser.parse_args()

    subtitle_style = {
        "font": args.sub_font,
        "size": args.sub_size,
        "color": args.sub_color,
        "outline_color": args.sub_outline_color,
        "highlight_color": args.sub_highlight_color,
        "position": args.sub_position,
        "words_per_cue": args.sub_words_per_cue,
    }
```

- [ ] **Step 7: Run the full test suite to verify everything passes**

Run: `pytest -v`
Expected: PASS — every test in `tests/`, no regressions from Tasks 1-6.

- [ ] **Step 8: Commit**

```bash
git add scripts/render.py tests/test_render.py
git commit -m "feat: wire frame-relative subtitle margin and karaoke word-highlight into render_clip"
```

---

### Task 7: `SKILL.md` — hype-phrase steering and new render CLI flags

**Files:**
- Modify: `SKILL.md:46` (step 3, candidate-finding instructions), `SKILL.md:113` (step 6, render command)

**Interfaces:**
- Consumes: `config.analysis.hype_phrases`, `config.subtitles.highlight_color`, `config.subtitles.words_per_cue` (Task 1 + Task 6 CLI flags).
- No code interfaces — prompt/documentation only.

- [ ] **Step 1: Add the hype-phrase rule to step 3**

In `SKILL.md`, find this line (currently line 46):

```
- If `config.content.allow_mature` is `false`, instruct the search (subagent prompt or your own pass) to skip any moment that is primarily profanity or sexual/adult humor rather than including it — only surface it as a candidate if it stands on its own without that material. If `true` (default), keep such moments as candidates normally; step 5 below flags them in the generated metadata instead of filtering them here.
```

Add immediately after it:

```
- Treat any phrase in `config.analysis.hype_phrases` — and other language in the same register (streamer/audience hype, meme call-outs, exaggerated reactions) — as a strong positive signal for a candidate moment, even when the surrounding content alone wouldn't stand out.
```

- [ ] **Step 2: Add the new flags to the step 6 render command**

In `SKILL.md`, replace the render command (currently line 113):

```
python scripts/render.py "<video>" work/<video_stem>/PLAN.json "<config.output_dir>" --fade-seconds <config.clip.fade_seconds> --sub-font "<config.subtitles.font>" --sub-size <config.subtitles.size> --sub-color <config.subtitles.color> --sub-outline-color <config.subtitles.outline> --sub-position <config.subtitles.position>
```

with:

```
python scripts/render.py "<video>" work/<video_stem>/PLAN.json "<config.output_dir>" --fade-seconds <config.clip.fade_seconds> --sub-font "<config.subtitles.font>" --sub-size <config.subtitles.size> --sub-color <config.subtitles.color> --sub-outline-color <config.subtitles.outline> --sub-highlight-color <config.subtitles.highlight_color> --sub-position <config.subtitles.position> --sub-words-per-cue <config.subtitles.words_per_cue>
```

- [ ] **Step 3: Commit**

```bash
git add SKILL.md
git commit -m "docs: steer pass-1 toward hype phrases and wire highlight/words-per-cue flags into the render step"
```

---

### Task 8: Full regression pass

**Files:** none (verification only)

- [ ] **Step 1: Run the entire test suite**

Run: `pytest -v`
Expected: PASS — every test across `tests/`, confirming Tasks 1-7 compose correctly (config defaults, centered pad crop, frame-relative margin, karaoke highlighting, and the CLI/SKILL.md wiring all agree with each other).

- [ ] **Step 2: Sanity-check `config.example.yaml` still round-trips**

Run: `pytest tests/test_config_example.py -v`
Expected: PASS (already covered in Step 1, called out separately since it's the one file most likely to drift out of sync with `scripts/config.py` defaults if a later edit touches one but not the other).
