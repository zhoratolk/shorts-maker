# shorts-maker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Claude Code skill + Python toolkit that turns long (3-15+ hour) gameplay/stream recordings into vertical (9:16) short clips using cached local Whisper transcription, Claude-driven semantic moment-finding, and ffmpeg rendering — distributable as an open-source Claude Code skill.

**Architecture:** Deterministic, independently-testable Python modules (`scripts/config.py`, `scripts/chunker.py`, `scripts/candidates.py`, `scripts/render.py`, `scripts/transcribe.py`, `scripts/setup.py`) each expose both a plain-Python API and a thin CLI wrapper. `SKILL.md` orchestrates them plus Claude Code subagents (for the semantic analysis passes that plain code cannot do) into the full pipeline described in the design spec.

**Tech Stack:** Python 3.11+ (see version risk note below), PyYAML, faster-whisper, ffmpeg (via winget), pytest.

## Global Constraints

- Target platform: Windows, with ffmpeg installed via `winget` (`Gyan.FFmpeg`).
- Python 3.13 may lack prebuilt `faster-whisper`/`ctranslate2` wheels at time of writing — `scripts/setup.py` must surface this, not fail silently (see spec, Error Handling).
- No hardcoded paths, language, or content assumptions anywhere in `scripts/` — everything environment/content-specific lives in `config.yaml` (spec, Components).
- `crop_style` values reaching `scripts/render.py` must always be a resolved concrete value (`zoom`/`pad`/`original-16:9`) — `auto` is a config-level default that must be resolved to a concrete style before it reaches `render.py`.
- Subtitles and facecam handling are opt-in and default `false`/`disabled` in `config.example.yaml`.
- Vertical output target is fixed at 1080x1920 for this version (not user-configurable — YAGNI, no requirement for other target resolutions in the spec).

---

### Task 1: Project scaffolding + config loader

**Files:**
- Create: `scripts/__init__.py`
- Create: `tests/__init__.py`
- Create: `pyproject.toml`
- Create: `requirements.txt`
- Create: `requirements-dev.txt`
- Create: `scripts/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `ConfigError(ValueError)`; dataclasses `WhisperConfig`, `AnalysisConfig`, `ClipConfig`, `CropConfig`, `FacecamConfig`, `SubtitlesConfig`, `Config`; function `load_config(path: str) -> Config`.

- [ ] **Step 1: Create empty package markers**

Create `scripts/__init__.py` with content:
```python
```

Create `tests/__init__.py` with content:
```python
```

- [ ] **Step 2: Create pytest config**

Create `pyproject.toml`:
```toml
[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
```

- [ ] **Step 3: Create dependency files**

Create `requirements.txt`:
```
faster-whisper>=1.0.0
PyYAML>=6.0
```

Create `requirements-dev.txt`:
```
pytest>=7.4.0
```

- [ ] **Step 4: Write the failing tests**

Create `tests/test_config.py`:
```python
import pytest

from scripts.config import ConfigError, load_config


def write_config(tmp_path, content):
    path = tmp_path / "config.yaml"
    path.write_text(content, encoding="utf-8")
    return str(path)


def test_load_config_applies_defaults(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/Запись"
        output_dir: "F:/Готовое/Шортс"
        """,
    )

    config = load_config(path)

    assert config.input_dir == "F:/Запись"
    assert config.output_dir == "F:/Готовое/Шортс"
    assert config.whisper.model == "medium"
    assert config.whisper.device == "auto"
    assert config.whisper.language == "auto"
    assert config.analysis.chunk_minutes == 35
    assert config.analysis.use_subagents is True
    assert config.analysis.require_approval is True
    assert config.clip.min_seconds == 30
    assert config.clip.max_seconds == 60
    assert config.crop.mode == "auto"
    assert config.facecam.enabled is False
    assert config.facecam.mode == "manual_region"
    assert config.subtitles.enabled is False


def test_load_config_missing_input_dir_raises(tmp_path):
    path = write_config(tmp_path, "output_dir: \"F:/out\"\n")

    with pytest.raises(ConfigError, match="input_dir"):
        load_config(path)


def test_load_config_missing_output_dir_raises(tmp_path):
    path = write_config(tmp_path, "input_dir: \"F:/in\"\n")

    with pytest.raises(ConfigError, match="output_dir"):
        load_config(path)


def test_load_config_invalid_crop_mode_raises(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        crop:
          mode: sideways
        """,
    )

    with pytest.raises(ConfigError, match="crop.mode"):
        load_config(path)


def test_load_config_invalid_whisper_device_raises(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        whisper:
          device: potato
        """,
    )

    with pytest.raises(ConfigError, match="whisper.device"):
        load_config(path)


def test_load_config_chunk_minutes_must_be_positive(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        analysis:
          chunk_minutes: 0
        """,
    )

    with pytest.raises(ConfigError, match="chunk_minutes"):
        load_config(path)


def test_load_config_min_seconds_must_be_less_than_max(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        clip:
          min_seconds: 60
          max_seconds: 30
        """,
    )

    with pytest.raises(ConfigError, match="min_seconds"):
        load_config(path)


def test_load_config_facecam_manual_region_requires_region_when_enabled(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        facecam:
          enabled: true
          mode: manual_region
        """,
    )

    with pytest.raises(ConfigError, match="facecam.region"):
        load_config(path)


def test_load_config_facecam_auto_detect_does_not_require_region(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        facecam:
          enabled: true
          mode: auto_detect
        """,
    )

    config = load_config(path)

    assert config.facecam.enabled is True
    assert config.facecam.region is None


def test_load_config_unknown_field_in_section_raises(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        whisper:
          not_a_real_field: 1
        """,
    )

    with pytest.raises(ConfigError, match="whisper"):
        load_config(path)
```

- [ ] **Step 5: Run tests to verify they fail**

Run: `pip install -r requirements.txt -r requirements-dev.txt`
Run: `pytest tests/test_config.py -v`
Expected: FAIL (collection error) with `ModuleNotFoundError: No module named 'scripts.config'`

- [ ] **Step 6: Write the implementation**

Create `scripts/config.py`:
```python
from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import yaml


class ConfigError(ValueError):
    pass


CROP_MODES = {"auto", "zoom", "pad", "original-16:9"}
FACECAM_MODES = {"manual_region", "auto_detect"}
WHISPER_DEVICES = {"auto", "cuda", "cpu"}


@dataclasses.dataclass
class WhisperConfig:
    model: str = "medium"
    device: str = "auto"
    language: str = "auto"


@dataclasses.dataclass
class AnalysisConfig:
    chunk_minutes: int = 35
    use_subagents: bool = True
    require_approval: bool = True


@dataclasses.dataclass
class ClipConfig:
    min_seconds: int = 30
    max_seconds: int = 60


@dataclasses.dataclass
class CropConfig:
    mode: str = "auto"


@dataclasses.dataclass
class FacecamConfig:
    enabled: bool = False
    mode: str = "manual_region"
    region: list[float] | None = None


@dataclasses.dataclass
class SubtitlesConfig:
    enabled: bool = False
    font: str = "Arial"
    size: int = 48
    color: str = "white"
    outline: str = "black"
    position: str = "bottom"


@dataclasses.dataclass
class Config:
    input_dir: str
    output_dir: str
    whisper: WhisperConfig = dataclasses.field(default_factory=WhisperConfig)
    analysis: AnalysisConfig = dataclasses.field(default_factory=AnalysisConfig)
    clip: ClipConfig = dataclasses.field(default_factory=ClipConfig)
    crop: CropConfig = dataclasses.field(default_factory=CropConfig)
    facecam: FacecamConfig = dataclasses.field(default_factory=FacecamConfig)
    subtitles: SubtitlesConfig = dataclasses.field(default_factory=SubtitlesConfig)


def _build(section_cls, data: dict, section_name: str):
    try:
        return section_cls(**data)
    except TypeError as error:
        raise ConfigError(f"invalid fields in '{section_name}' section: {error}") from error


def load_config(path: str) -> Config:
    raw_text = Path(path).read_text(encoding="utf-8")
    data: dict[str, Any] = yaml.safe_load(raw_text) or {}

    if "input_dir" not in data:
        raise ConfigError("config is missing required field: input_dir")
    if "output_dir" not in data:
        raise ConfigError("config is missing required field: output_dir")

    config = Config(
        input_dir=data["input_dir"],
        output_dir=data["output_dir"],
        whisper=_build(WhisperConfig, data.get("whisper", {}), "whisper"),
        analysis=_build(AnalysisConfig, data.get("analysis", {}), "analysis"),
        clip=_build(ClipConfig, data.get("clip", {}), "clip"),
        crop=_build(CropConfig, data.get("crop", {}), "crop"),
        facecam=_build(FacecamConfig, data.get("facecam", {}), "facecam"),
        subtitles=_build(SubtitlesConfig, data.get("subtitles", {}), "subtitles"),
    )
    _validate(config)
    return config


def _validate(config: Config) -> None:
    if config.whisper.device not in WHISPER_DEVICES:
        raise ConfigError(
            f"whisper.device must be one of {sorted(WHISPER_DEVICES)}, got {config.whisper.device!r}"
        )
    if config.analysis.chunk_minutes <= 0:
        raise ConfigError("analysis.chunk_minutes must be > 0")
    if config.clip.min_seconds <= 0 or config.clip.max_seconds <= 0:
        raise ConfigError("clip.min_seconds and clip.max_seconds must be > 0")
    if config.clip.min_seconds >= config.clip.max_seconds:
        raise ConfigError("clip.min_seconds must be less than clip.max_seconds")
    if config.crop.mode not in CROP_MODES:
        raise ConfigError(f"crop.mode must be one of {sorted(CROP_MODES)}, got {config.crop.mode!r}")
    if config.facecam.mode not in FACECAM_MODES:
        raise ConfigError(
            f"facecam.mode must be one of {sorted(FACECAM_MODES)}, got {config.facecam.mode!r}"
        )
    if config.facecam.enabled and config.facecam.mode == "manual_region" and config.facecam.region is None:
        raise ConfigError(
            "facecam.region is required when facecam.enabled is true and facecam.mode is manual_region"
        )
    if config.facecam.region is not None and len(config.facecam.region) != 4:
        raise ConfigError("facecam.region must have exactly 4 values: [x, y, w, h]")
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/test_config.py -v`
Expected: PASS (10 passed)

- [ ] **Step 8: Commit**

```bash
git add scripts/__init__.py tests/__init__.py pyproject.toml requirements.txt requirements-dev.txt scripts/config.py tests/test_config.py
git commit -m "feat: add config loader with validation"
```

---

### Task 2: Transcript chunker

**Files:**
- Create: `scripts/chunker.py`
- Test: `tests/test_chunker.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: dataclass `Chunk(index: int, start: float, end: float, segments: list[dict])`; functions `split_into_chunks(segments: list[dict], chunk_minutes: int) -> list[Chunk]` and `write_chunks(chunks: list[Chunk], output_dir: str) -> list[str]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_chunker.py`:
```python
import json
from pathlib import Path

import pytest

from scripts.chunker import Chunk, split_into_chunks, write_chunks


def test_split_into_chunks_empty_segments_returns_empty_list():
    assert split_into_chunks([], chunk_minutes=35) == []


def test_split_into_chunks_zero_or_negative_chunk_minutes_raises():
    with pytest.raises(ValueError, match="chunk_minutes"):
        split_into_chunks([{"start": 0.0, "end": 1.0, "text": "hi"}], chunk_minutes=0)


def test_split_into_chunks_groups_segments_by_window():
    segments = [
        {"start": 0.0, "end": 5.0, "text": "a"},
        {"start": 30.0, "end": 35.0, "text": "b"},
        {"start": 90.0, "end": 95.0, "text": "c"},
        {"start": 120.0, "end": 125.0, "text": "d"},
    ]

    chunks = split_into_chunks(segments, chunk_minutes=1)

    assert chunks == [
        Chunk(index=0, start=0.0, end=35.0, segments=[segments[0], segments[1]]),
        Chunk(index=1, start=90.0, end=95.0, segments=[segments[2]]),
        Chunk(index=2, start=120.0, end=125.0, segments=[segments[3]]),
    ]


def test_split_into_chunks_single_segment():
    segments = [{"start": 0.0, "end": 2.0, "text": "hello"}]

    chunks = split_into_chunks(segments, chunk_minutes=35)

    assert chunks == [Chunk(index=0, start=0.0, end=2.0, segments=segments)]


def test_write_chunks_creates_one_file_per_chunk(tmp_path):
    chunks = [
        Chunk(index=0, start=0.0, end=5.0, segments=[{"start": 0.0, "end": 5.0, "text": "a"}]),
        Chunk(index=1, start=90.0, end=95.0, segments=[{"start": 90.0, "end": 95.0, "text": "c"}]),
    ]

    output_dir = str(tmp_path / "chunks")
    paths = write_chunks(chunks, output_dir)

    assert paths == [
        str(Path(output_dir) / "chunk_0000.json"),
        str(Path(output_dir) / "chunk_0001.json"),
    ]
    written = json.loads(Path(paths[0]).read_text(encoding="utf-8"))
    assert written == {
        "index": 0,
        "start": 0.0,
        "end": 5.0,
        "segments": [{"start": 0.0, "end": 5.0, "text": "a"}],
    }
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_chunker.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.chunker'`

- [ ] **Step 3: Write the implementation**

Create `scripts/chunker.py`:
```python
from __future__ import annotations

import argparse
import dataclasses
import json
from pathlib import Path


@dataclasses.dataclass
class Chunk:
    index: int
    start: float
    end: float
    segments: list[dict]


def split_into_chunks(segments: list[dict], chunk_minutes: int) -> list[Chunk]:
    if chunk_minutes <= 0:
        raise ValueError("chunk_minutes must be > 0")
    if not segments:
        return []

    window_seconds = chunk_minutes * 60
    chunks: list[Chunk] = []
    current_segments: list[dict] = []
    current_window_start = 0.0
    window_index = 0

    for segment in segments:
        while segment["start"] >= current_window_start + window_seconds:
            if current_segments:
                chunks.append(
                    Chunk(
                        index=window_index,
                        start=current_segments[0]["start"],
                        end=current_segments[-1]["end"],
                        segments=current_segments,
                    )
                )
                window_index += 1
                current_segments = []
            current_window_start += window_seconds
        current_segments.append(segment)

    if current_segments:
        chunks.append(
            Chunk(
                index=window_index,
                start=current_segments[0]["start"],
                end=current_segments[-1]["end"],
                segments=current_segments,
            )
        )

    return chunks


def write_chunks(chunks: list[Chunk], output_dir: str) -> list[str]:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    written_paths = []
    for chunk in chunks:
        file_path = output_path / f"chunk_{chunk.index:04d}.json"
        file_path.write_text(
            json.dumps(dataclasses.asdict(chunk), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        written_paths.append(str(file_path))
    return written_paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Split a cached transcript into analysis chunks")
    parser.add_argument("transcript_json", help="Path to a transcript JSON produced by transcribe.py")
    parser.add_argument("output_dir", help="Directory to write chunk_NNNN.json files into")
    parser.add_argument("--chunk-minutes", type=int, default=35)
    args = parser.parse_args()

    transcript = json.loads(Path(args.transcript_json).read_text(encoding="utf-8"))
    chunks = split_into_chunks(transcript["segments"], args.chunk_minutes)
    paths = write_chunks(chunks, args.output_dir)
    for path in paths:
        print(path)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_chunker.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add scripts/chunker.py tests/test_chunker.py
git commit -m "feat: add transcript chunker for pass-1 analysis"
```

---

### Task 3: Candidate merging and markdown rendering

**Files:**
- Create: `scripts/candidates.py`
- Test: `tests/test_candidates.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: dataclass `Candidate(id: int, start: float, end: float, reason: str)`; functions `format_timecode(total_seconds: float) -> str`, `merge_candidates(chunks_candidates: list[list[dict]]) -> list[Candidate]`, `merge_candidate_files(candidates_dir: str) -> list[Candidate]`, `render_candidates_markdown(candidates: list[Candidate]) -> str`, `write_candidates_json(candidates: list[Candidate], path: str) -> None`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_candidates.py`:
```python
import json
from pathlib import Path

import pytest

from scripts.candidates import (
    Candidate,
    format_timecode,
    merge_candidate_files,
    merge_candidates,
    render_candidates_markdown,
    write_candidates_json,
)


def test_format_timecode_zero():
    assert format_timecode(0) == "00:00:00"


def test_format_timecode_over_an_hour():
    assert format_timecode(3661) == "01:01:01"


def test_format_timecode_negative_raises():
    with pytest.raises(ValueError, match="total_seconds"):
        format_timecode(-1)


def test_merge_candidates_sorts_by_start_and_assigns_sequential_ids():
    chunk_a = [{"start": 120.0, "end": 130.0, "reason": "second joke"}]
    chunk_b = [{"start": 10.0, "end": 20.0, "reason": "first joke"}]

    merged = merge_candidates([chunk_a, chunk_b])

    assert merged == [
        Candidate(id=1, start=10.0, end=20.0, reason="first joke"),
        Candidate(id=2, start=120.0, end=130.0, reason="second joke"),
    ]


def test_merge_candidate_files_reads_directory_in_sorted_order(tmp_path):
    (tmp_path / "candidates_chunk_0001.json").write_text(
        json.dumps([{"start": 120.0, "end": 130.0, "reason": "second joke"}]), encoding="utf-8"
    )
    (tmp_path / "candidates_chunk_0000.json").write_text(
        json.dumps([{"start": 10.0, "end": 20.0, "reason": "first joke"}]), encoding="utf-8"
    )

    merged = merge_candidate_files(str(tmp_path))

    assert merged == [
        Candidate(id=1, start=10.0, end=20.0, reason="first joke"),
        Candidate(id=2, start=120.0, end=130.0, reason="second joke"),
    ]


def test_render_candidates_markdown_empty():
    assert render_candidates_markdown([]) == "# Candidates\n\nNo candidates found.\n"


def test_render_candidates_markdown_lists_entries():
    candidates = [
        Candidate(id=1, start=10.0, end=20.0, reason="first joke"),
        Candidate(id=2, start=3661.0, end=3665.0, reason="second joke"),
    ]

    markdown = render_candidates_markdown(candidates)

    assert markdown == (
        "# Candidates\n\n"
        "1. `00:00:10` - `00:00:20` — first joke\n"
        "2. `01:01:01` - `01:01:05` — second joke\n"
    )


def test_write_candidates_json_round_trips(tmp_path):
    candidates = [Candidate(id=1, start=10.0, end=20.0, reason="first joke")]
    path = str(tmp_path / "candidates.json")

    write_candidates_json(candidates, path)

    assert json.loads(Path(path).read_text(encoding="utf-8")) == [
        {"id": 1, "start": 10.0, "end": 20.0, "reason": "first joke"}
    ]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_candidates.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.candidates'`

- [ ] **Step 3: Write the implementation**

Create `scripts/candidates.py`:
```python
from __future__ import annotations

import argparse
import dataclasses
import json
from pathlib import Path


@dataclasses.dataclass
class Candidate:
    id: int
    start: float
    end: float
    reason: str


def format_timecode(total_seconds: float) -> str:
    if total_seconds < 0:
        raise ValueError("total_seconds must be >= 0")
    total_seconds = int(total_seconds)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def merge_candidates(chunks_candidates: list[list[dict]]) -> list[Candidate]:
    flattened: list[dict] = []
    for chunk_candidates in chunks_candidates:
        flattened.extend(chunk_candidates)

    flattened.sort(key=lambda item: item["start"])

    return [
        Candidate(id=index + 1, start=item["start"], end=item["end"], reason=item["reason"])
        for index, item in enumerate(flattened)
    ]


def merge_candidate_files(candidates_dir: str) -> list[Candidate]:
    files = sorted(Path(candidates_dir).glob("*.json"))
    chunks_candidates = [json.loads(file.read_text(encoding="utf-8")) for file in files]
    return merge_candidates(chunks_candidates)


def render_candidates_markdown(candidates: list[Candidate]) -> str:
    if not candidates:
        return "# Candidates\n\nNo candidates found.\n"

    lines = ["# Candidates", ""]
    for candidate in candidates:
        start_tc = format_timecode(candidate.start)
        end_tc = format_timecode(candidate.end)
        lines.append(f"{candidate.id}. `{start_tc}` - `{end_tc}` — {candidate.reason}")
    return "\n".join(lines) + "\n"


def write_candidates_json(candidates: list[Candidate], path: str) -> None:
    Path(path).write_text(
        json.dumps([dataclasses.asdict(candidate) for candidate in candidates], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge per-chunk candidate files into CANDIDATES.md")
    parser.add_argument("candidates_dir", help="Directory containing candidates_chunk_NNNN.json files")
    parser.add_argument("output_markdown", help="Path to write CANDIDATES.md to")
    parser.add_argument("output_json", help="Path to write the machine-readable candidates.json to")
    args = parser.parse_args()

    candidates = merge_candidate_files(args.candidates_dir)
    Path(args.output_markdown).write_text(render_candidates_markdown(candidates), encoding="utf-8")
    write_candidates_json(candidates, args.output_json)
    print(f"{len(candidates)} candidates written to {args.output_markdown}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_candidates.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add scripts/candidates.py tests/test_candidates.py
git commit -m "feat: add candidate merging and CANDIDATES.md rendering"
```

---

### Task 4: Render — crop math and clip bounds clamping

**Files:**
- Create: `scripts/render.py`
- Test: `tests/test_render.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `RenderError(ValueError)`, constants `TARGET_WIDTH = 1080`, `TARGET_HEIGHT = 1920`, functions `clamp_clip_bounds(start: float, end: float, video_duration: float) -> tuple[float, float]` and `compute_crop_filter(crop_style: str, src_width: int, src_height: int) -> str`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_render.py`:
```python
import pytest

from scripts.render import RenderError, clamp_clip_bounds, compute_crop_filter


def test_clamp_clip_bounds_passthrough_when_within_range():
    assert clamp_clip_bounds(10.0, 40.0, video_duration=100.0) == (10.0, 40.0)


def test_clamp_clip_bounds_clamps_end_to_duration():
    assert clamp_clip_bounds(90.0, 120.0, video_duration=100.0) == (90.0, 100.0)


def test_clamp_clip_bounds_clamps_negative_start_to_zero():
    assert clamp_clip_bounds(-5.0, 10.0, video_duration=100.0) == (0.0, 10.0)


def test_clamp_clip_bounds_raises_when_start_after_clamped_end():
    with pytest.raises(RenderError, match="clip bounds invalid"):
        clamp_clip_bounds(150.0, 200.0, video_duration=100.0)


def test_clamp_clip_bounds_raises_on_non_positive_duration():
    with pytest.raises(RenderError, match="video_duration"):
        clamp_clip_bounds(0.0, 10.0, video_duration=0.0)


def test_compute_crop_filter_zoom():
    result = compute_crop_filter("zoom", src_width=1920, src_height=1080)
    assert result == "crop=608:1080:656:0,scale=1080:1920"


def test_compute_crop_filter_pad():
    result = compute_crop_filter("pad", src_width=1920, src_height=1080)
    assert result == "scale=1080:608,pad=1080:1920:0:394:black"


def test_compute_crop_filter_original_16_9():
    result = compute_crop_filter("original-16:9", src_width=1920, src_height=1080)
    assert result == "scale=1080:608,pad=1080:1920:0:656:black"


def test_compute_crop_filter_rejects_unresolved_auto():
    with pytest.raises(RenderError, match="resolved value"):
        compute_crop_filter("auto", src_width=1920, src_height=1080)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_render.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.render'`

- [ ] **Step 3: Write the implementation**

Create `scripts/render.py`:
```python
from __future__ import annotations

TARGET_WIDTH = 1080
TARGET_HEIGHT = 1920


class RenderError(ValueError):
    pass


def clamp_clip_bounds(start: float, end: float, video_duration: float) -> tuple[float, float]:
    if video_duration <= 0:
        raise RenderError("video_duration must be > 0")
    clamped_start = max(0.0, start)
    clamped_end = min(end, video_duration)
    if clamped_start >= clamped_end:
        raise RenderError(
            f"clip bounds invalid after clamping: start={clamped_start}, end={clamped_end}"
        )
    return clamped_start, clamped_end


def compute_crop_filter(crop_style: str, src_width: int, src_height: int) -> str:
    if crop_style == "zoom":
        crop_width = min(round(src_height * TARGET_WIDTH / TARGET_HEIGHT), src_width)
        x_offset = round((src_width - crop_width) / 2)
        return f"crop={crop_width}:{src_height}:{x_offset}:0,scale={TARGET_WIDTH}:{TARGET_HEIGHT}"

    if crop_style == "pad":
        scaled_height = round(src_height * TARGET_WIDTH / src_width)
        total_pad = TARGET_HEIGHT - scaled_height
        top_pad = round(total_pad * 0.3)
        return f"scale={TARGET_WIDTH}:{scaled_height},pad={TARGET_WIDTH}:{TARGET_HEIGHT}:0:{top_pad}:black"

    if crop_style == "original-16:9":
        scaled_height = round(src_height * TARGET_WIDTH / src_width)
        top_pad = round((TARGET_HEIGHT - scaled_height) / 2)
        return f"scale={TARGET_WIDTH}:{scaled_height},pad={TARGET_WIDTH}:{TARGET_HEIGHT}:0:{top_pad}:black"

    raise RenderError(
        f"crop_style must be a resolved value (zoom/pad/original-16:9), got {crop_style!r}. "
        "'auto' must be resolved to a concrete style before reaching render.py."
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_render.py -v`
Expected: PASS (9 passed)

- [ ] **Step 5: Commit**

```bash
git add scripts/render.py tests/test_render.py
git commit -m "feat: add render crop math and clip bounds clamping"
```

---

### Task 5: Render — ffmpeg command building, clip rendering, and video probing

**Files:**
- Modify: `scripts/render.py`
- Modify: `tests/test_render.py`

**Interfaces:**
- Consumes: `RenderError`, `clamp_clip_bounds`, `compute_crop_filter` from Task 4 (same file).
- Produces: functions `build_ffmpeg_command(input_path: str, output_path: str, start: float, end: float, crop_filter: str, subtitles_path: str | None = None) -> list[str]`, `probe_video(video_path: str, runner=subprocess.run) -> dict` (returns `{"duration": float, "width": int, "height": int}`), `render_clip(input_path: str, output_path: str, plan_entry: dict, video_duration: float, src_width: int, src_height: int, runner=subprocess.run) -> list[str]`. `plan_entry` is a dict with keys `start`, `end`, `crop_style`, and optional `subtitles_path`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_render.py`:
```python
import json

from scripts.render import build_ffmpeg_command, probe_video, render_clip


def test_build_ffmpeg_command_without_subtitles():
    command = build_ffmpeg_command(
        "in.mp4", "out.mp4", start=10.0, end=40.0, crop_filter="crop=608:1080:656:0,scale=1080:1920"
    )

    assert command == [
        "ffmpeg", "-y",
        "-ss", "10.0",
        "-i", "in.mp4",
        "-t", "30.0",
        "-vf", "crop=608:1080:656:0,scale=1080:1920",
        "-c:v", "libx264",
        "-c:a", "aac",
        "out.mp4",
    ]


def test_build_ffmpeg_command_with_subtitles():
    command = build_ffmpeg_command(
        "in.mp4", "out.mp4", start=10.0, end=40.0,
        crop_filter="scale=1080:608,pad=1080:1920:0:394:black",
        subtitles_path="work/x/subs.srt",
    )

    assert command[7] == "scale=1080:608,pad=1080:1920:0:394:black,subtitles='work/x/subs.srt'"


def test_probe_video_parses_ffprobe_json():
    fake_stdout = json.dumps(
        {
            "format": {"duration": "125.5"},
            "streams": [{"width": 1920, "height": 1080, "codec_type": "video"}],
        }
    )

    class FakeResult:
        returncode = 0
        stdout = fake_stdout
        stderr = ""

    def fake_runner(command, capture_output, text):
        return FakeResult()

    info = probe_video("in.mp4", runner=fake_runner)

    assert info == {"duration": 125.5, "width": 1920, "height": 1080}


def test_render_clip_builds_and_runs_command():
    captured = {}

    class FakeResult:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_runner(command, capture_output, text):
        captured["command"] = command
        return FakeResult()

    plan_entry = {"start": 10.0, "end": 40.0, "crop_style": "zoom"}

    command = render_clip(
        "in.mp4", "out.mp4", plan_entry,
        video_duration=100.0, src_width=1920, src_height=1080,
        runner=fake_runner,
    )

    assert command == captured["command"]
    assert command[-1] == "out.mp4"
    assert "crop=608:1080:656:0,scale=1080:1920" in command


def test_render_clip_raises_on_ffmpeg_failure():
    class FakeResult:
        returncode = 1
        stdout = ""
        stderr = "boom"

    def fake_runner(command, capture_output, text):
        return FakeResult()

    plan_entry = {"start": 10.0, "end": 40.0, "crop_style": "zoom"}

    with pytest.raises(RenderError, match="boom"):
        render_clip(
            "in.mp4", "out.mp4", plan_entry,
            video_duration=100.0, src_width=1920, src_height=1080,
            runner=fake_runner,
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_render.py -v`
Expected: FAIL with `ImportError: cannot import name 'build_ffmpeg_command'`

- [ ] **Step 3: Write the implementation**

Append to `scripts/render.py`:
```python
import argparse
import json
import subprocess
from pathlib import Path


def build_ffmpeg_command(
    input_path: str,
    output_path: str,
    start: float,
    end: float,
    crop_filter: str,
    subtitles_path: str | None = None,
) -> list[str]:
    duration = end - start
    video_filter = crop_filter
    if subtitles_path is not None:
        escaped_path = subtitles_path.replace("\\", "/").replace(":", "\\:")
        video_filter = f"{video_filter},subtitles='{escaped_path}'"

    return [
        "ffmpeg", "-y",
        "-ss", str(start),
        "-i", input_path,
        "-t", str(duration),
        "-vf", video_filter,
        "-c:v", "libx264",
        "-c:a", "aac",
        output_path,
    ]


def probe_video(video_path: str, runner=subprocess.run) -> dict:
    command = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", video_path,
    ]
    result = runner(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise RenderError(f"ffprobe failed for {video_path}: {result.stderr}")

    data = json.loads(result.stdout)
    video_stream = next(stream for stream in data["streams"] if stream["codec_type"] == "video")
    return {
        "duration": float(data["format"]["duration"]),
        "width": int(video_stream["width"]),
        "height": int(video_stream["height"]),
    }


def render_clip(
    input_path: str,
    output_path: str,
    plan_entry: dict,
    video_duration: float,
    src_width: int,
    src_height: int,
    runner=subprocess.run,
) -> list[str]:
    start, end = clamp_clip_bounds(plan_entry["start"], plan_entry["end"], video_duration)
    crop_filter = compute_crop_filter(plan_entry["crop_style"], src_width, src_height)
    subtitles_path = plan_entry.get("subtitles_path")
    command = build_ffmpeg_command(input_path, output_path, start, end, crop_filter, subtitles_path)

    result = runner(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise RenderError(f"ffmpeg failed for {output_path}: {result.stderr}")
    return command


def main() -> None:
    parser = argparse.ArgumentParser(description="Render approved clips from a PLAN.json")
    parser.add_argument("input_video", help="Path to the source recording")
    parser.add_argument("plan_json", help="Path to PLAN.json: a list of clip plan entries")
    parser.add_argument("output_dir", help="Directory to write rendered clips into")
    args = parser.parse_args()

    video_info = probe_video(args.input_video)
    plan = json.loads(Path(args.plan_json).read_text(encoding="utf-8"))

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    for index, entry in enumerate(plan):
        output_path = str(output_dir / entry.get("output_filename", f"clip_{index:04d}.mp4"))
        render_clip(
            args.input_video, output_path, entry,
            video_duration=video_info["duration"],
            src_width=video_info["width"],
            src_height=video_info["height"],
        )
        print(output_path)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_render.py -v`
Expected: PASS (14 passed)

- [ ] **Step 5: Commit**

```bash
git add scripts/render.py tests/test_render.py
git commit -m "feat: add ffmpeg command building, video probing, and clip rendering"
```

---

### Task 6: Dependency and GPU checks (setup)

**Files:**
- Create: `scripts/setup.py`
- Test: `tests/test_setup.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: functions `check_ffmpeg() -> bool`, `check_gpu(runner=subprocess.run) -> str` (returns `"cuda"` or `"cpu"`), `check_python_deps(module_names: tuple[str, ...] = ("yaml", "faster_whisper")) -> list[str]`, `install_ffmpeg(runner=subprocess.run) -> None`, `install_python_deps(missing: list[str], runner=subprocess.run) -> None`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_setup.py`:
```python
import subprocess

from scripts.setup import (
    check_ffmpeg,
    check_gpu,
    check_python_deps,
    install_ffmpeg,
    install_python_deps,
)


def test_check_ffmpeg_found(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "C:/ffmpeg/ffmpeg.exe")
    assert check_ffmpeg() is True


def test_check_ffmpeg_missing(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    assert check_ffmpeg() is False


def test_check_gpu_returns_cuda_when_nvidia_smi_succeeds():
    class FakeResult:
        returncode = 0

    def fake_runner(command, capture_output, check):
        return FakeResult()

    assert check_gpu(runner=fake_runner) == "cuda"


def test_check_gpu_returns_cpu_when_nvidia_smi_missing():
    def fake_runner(command, capture_output, check):
        raise FileNotFoundError()

    assert check_gpu(runner=fake_runner) == "cpu"


def test_check_gpu_returns_cpu_when_nvidia_smi_errors():
    def fake_runner(command, capture_output, check):
        raise subprocess.CalledProcessError(1, command)

    assert check_gpu(runner=fake_runner) == "cpu"


def test_check_python_deps_reports_missing_module():
    missing = check_python_deps(module_names=("os", "definitely_not_a_real_module_xyz"))
    assert missing == ["definitely_not_a_real_module_xyz"]


def test_check_python_deps_empty_when_all_present():
    missing = check_python_deps(module_names=("os", "sys"))
    assert missing == []


def test_install_ffmpeg_calls_winget():
    captured = {}

    def fake_runner(command, check):
        captured["command"] = command

    install_ffmpeg(runner=fake_runner)

    assert captured["command"] == ["winget", "install", "-e", "--id", "Gyan.FFmpeg"]


def test_install_python_deps_maps_module_names_to_packages():
    captured = {}

    def fake_runner(command, check):
        captured["command"] = command

    install_python_deps(["yaml", "faster_whisper"], runner=fake_runner)

    assert captured["command"][-2:] == ["pyyaml", "faster-whisper"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_setup.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.setup'`

- [ ] **Step 3: Write the implementation**

Create `scripts/setup.py`:
```python
from __future__ import annotations

import shutil
import subprocess
import sys

PACKAGE_NAMES = {"yaml": "pyyaml", "faster_whisper": "faster-whisper"}


def check_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def check_gpu(runner=subprocess.run) -> str:
    try:
        runner(["nvidia-smi"], capture_output=True, check=True)
        return "cuda"
    except (FileNotFoundError, subprocess.CalledProcessError):
        return "cpu"


def check_python_deps(module_names: tuple[str, ...] = ("yaml", "faster_whisper")) -> list[str]:
    missing = []
    for module_name in module_names:
        try:
            __import__(module_name)
        except ImportError:
            missing.append(module_name)
    return missing


def install_ffmpeg(runner=subprocess.run) -> None:
    runner(["winget", "install", "-e", "--id", "Gyan.FFmpeg"], check=True)


def install_python_deps(missing: list[str], runner=subprocess.run) -> None:
    packages = [PACKAGE_NAMES[name] for name in missing]
    runner([sys.executable, "-m", "pip", "install", *packages], check=True)


def main() -> None:
    print("Checking dependencies...")

    if check_ffmpeg():
        print("[ok] ffmpeg found")
    else:
        answer = input("ffmpeg not found. Install via winget now? [y/N] ")
        if answer.strip().lower() == "y":
            install_ffmpeg()
        else:
            print("[skip] ffmpeg not installed — rendering will fail until it is")

    missing_deps = check_python_deps()
    if not missing_deps:
        print("[ok] python dependencies found")
    else:
        print(f"Missing python packages: {', '.join(missing_deps)}")
        answer = input("Install them now? [y/N] ")
        if answer.strip().lower() == "y":
            install_python_deps(missing_deps)
        else:
            print("[skip] missing packages not installed — the pipeline will fail until they are")

    if sys.version_info[:2] >= (3, 13):
        print(
            "[warn] Python 3.13+ detected — faster-whisper/ctranslate2 may not have prebuilt "
            "wheels yet on this platform. If installation fails, create a venv with Python 3.11 or "
            "3.12 instead."
        )

    print(f"[info] GPU detected: {check_gpu()}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_setup.py -v`
Expected: PASS (9 passed)

- [ ] **Step 5: Commit**

```bash
git add scripts/setup.py tests/test_setup.py
git commit -m "feat: add dependency, ffmpeg, and GPU setup checks"
```

---

### Task 7: Transcription wrapper with caching

**Files:**
- Create: `scripts/transcribe.py`
- Test: `tests/test_transcribe.py`

**Interfaces:**
- Consumes: `check_gpu` from `scripts/setup.py` (Task 6).
- Produces: functions `transcript_cache_path(video_path: str, transcripts_dir: str) -> str`, `is_cached(video_path: str, transcripts_dir: str) -> bool`, `transcribe_video(video_path: str, transcripts_dir: str, model, language: str = "auto") -> dict` (returns `{"video_path", "language", "duration", "segments"}` where each segment is `{"start", "end", "text"}`), `load_whisper_model(model_size: str, device: str)`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_transcribe.py`:
```python
import json
import sys
import types
from pathlib import Path

from scripts.transcribe import (
    is_cached,
    load_whisper_model,
    transcribe_video,
    transcript_cache_path,
)


def test_transcript_cache_path_uses_video_stem():
    path = transcript_cache_path("F:/Запись/2025-11-02 17-32-40.mp4", "transcripts")
    assert path == str(Path("transcripts") / "2025-11-02 17-32-40.json")


def test_is_cached_false_when_missing(tmp_path):
    assert is_cached(str(tmp_path / "video.mp4"), str(tmp_path / "transcripts")) is False


def test_is_cached_true_when_present(tmp_path):
    transcripts_dir = tmp_path / "transcripts"
    transcripts_dir.mkdir()
    (transcripts_dir / "video.json").write_text("{}", encoding="utf-8")

    assert is_cached(str(tmp_path / "video.mp4"), str(transcripts_dir)) is True


class FakeSegment:
    def __init__(self, start, end, text):
        self.start = start
        self.end = end
        self.text = text


class FakeInfo:
    def __init__(self, language, duration):
        self.language = language
        self.duration = duration


class FakeModel:
    def transcribe(self, video_path, language, word_timestamps):
        segments = [FakeSegment(0.0, 2.0, "hello"), FakeSegment(2.0, 4.0, "world")]
        return iter(segments), FakeInfo("en", 4.0)


def test_transcribe_video_writes_cache(tmp_path):
    video_path = str(tmp_path / "video.mp4")
    transcripts_dir = str(tmp_path / "transcripts")

    result = transcribe_video(video_path, transcripts_dir, FakeModel())

    assert result == {
        "video_path": video_path,
        "language": "en",
        "duration": 4.0,
        "segments": [
            {"start": 0.0, "end": 2.0, "text": "hello"},
            {"start": 2.0, "end": 4.0, "text": "world"},
        ],
    }
    cache_file = Path(transcripts_dir) / "video.json"
    assert json.loads(cache_file.read_text(encoding="utf-8")) == result


def test_transcribe_video_uses_cache_when_present(tmp_path):
    video_path = str(tmp_path / "video.mp4")
    transcripts_dir = tmp_path / "transcripts"
    transcripts_dir.mkdir()
    cached_content = {"video_path": video_path, "language": "ru", "duration": 1.0, "segments": []}
    (transcripts_dir / "video.json").write_text(json.dumps(cached_content), encoding="utf-8")

    class ExplodingModel:
        def transcribe(self, *args, **kwargs):
            raise AssertionError("should not be called when cache exists")

    result = transcribe_video(video_path, str(transcripts_dir), ExplodingModel())

    assert result == cached_content


def test_load_whisper_model_resolves_auto_device(monkeypatch):
    captured = {}

    class FakeWhisperModel:
        def __init__(self, model_size, device, compute_type):
            captured["model_size"] = model_size
            captured["device"] = device
            captured["compute_type"] = compute_type

    fake_module = types.ModuleType("faster_whisper")
    fake_module.WhisperModel = FakeWhisperModel
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_module)
    monkeypatch.setattr("scripts.setup.check_gpu", lambda: "cuda")

    load_whisper_model("medium", "auto")

    assert captured == {"model_size": "medium", "device": "cuda", "compute_type": "float16"}


def test_load_whisper_model_respects_explicit_device(monkeypatch):
    captured = {}

    class FakeWhisperModel:
        def __init__(self, model_size, device, compute_type):
            captured["device"] = device
            captured["compute_type"] = compute_type

    fake_module = types.ModuleType("faster_whisper")
    fake_module.WhisperModel = FakeWhisperModel
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_module)

    load_whisper_model("small", "cpu")

    assert captured == {"device": "cpu", "compute_type": "int8"}


def test_load_whisper_model_falls_back_to_cpu_on_gpu_failure(monkeypatch, capsys):
    calls = []

    class FakeWhisperModel:
        def __init__(self, model_size, device, compute_type):
            calls.append({"model_size": model_size, "device": device, "compute_type": compute_type})
            if device == "cuda":
                raise RuntimeError("CUDA out of memory")

    fake_module = types.ModuleType("faster_whisper")
    fake_module.WhisperModel = FakeWhisperModel
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_module)
    monkeypatch.setattr("scripts.setup.check_gpu", lambda: "cuda")

    load_whisper_model("medium", "auto")

    assert calls == [
        {"model_size": "medium", "device": "cuda", "compute_type": "float16"},
        {"model_size": "medium", "device": "cpu", "compute_type": "int8"},
    ]
    assert "falling back to CPU" in capsys.readouterr().out


def test_load_whisper_model_reraises_when_already_on_cpu(monkeypatch):
    class FakeWhisperModel:
        def __init__(self, model_size, device, compute_type):
            raise RuntimeError("out of memory")

    fake_module = types.ModuleType("faster_whisper")
    fake_module.WhisperModel = FakeWhisperModel
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_module)

    try:
        load_whisper_model("medium", "cpu")
        raise AssertionError("expected RuntimeError to propagate")
    except RuntimeError as error:
        assert "out of memory" in str(error)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_transcribe.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.transcribe'`

- [ ] **Step 3: Write the implementation**

Create `scripts/transcribe.py`:
```python
from __future__ import annotations

import argparse
import json
from pathlib import Path


def transcript_cache_path(video_path: str, transcripts_dir: str) -> str:
    stem = Path(video_path).stem
    return str(Path(transcripts_dir) / f"{stem}.json")


def is_cached(video_path: str, transcripts_dir: str) -> bool:
    return Path(transcript_cache_path(video_path, transcripts_dir)).exists()


def transcribe_video(
    video_path: str,
    transcripts_dir: str,
    model,
    language: str = "auto",
) -> dict:
    cache_path = Path(transcript_cache_path(video_path, transcripts_dir))
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))

    cache_path.parent.mkdir(parents=True, exist_ok=True)

    whisper_language = None if language == "auto" else language
    segments_iter, info = model.transcribe(video_path, language=whisper_language, word_timestamps=True)

    segments = [
        {"start": segment.start, "end": segment.end, "text": segment.text}
        for segment in segments_iter
    ]
    result = {
        "video_path": video_path,
        "language": info.language,
        "duration": info.duration,
        "segments": segments,
    }
    cache_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def load_whisper_model(model_size: str, device: str):
    from faster_whisper import WhisperModel

    from scripts.setup import check_gpu

    resolved_device = check_gpu() if device == "auto" else device
    compute_type = "float16" if resolved_device == "cuda" else "int8"

    try:
        return WhisperModel(model_size, device=resolved_device, compute_type=compute_type)
    except Exception as error:
        # ctranslate2/CUDA can fail with several different exception types on OOM;
        # catch broadly here since this is a best-effort fallback, not error handling
        # for a known failure mode.
        if resolved_device != "cuda":
            raise
        print(f"[warn] failed to load Whisper model on GPU ({error}); falling back to CPU")
        return WhisperModel(model_size, device="cpu", compute_type="int8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Transcribe a video with faster-whisper (cached)")
    parser.add_argument("video_path")
    parser.add_argument("transcripts_dir")
    parser.add_argument("--model", default="medium")
    parser.add_argument("--device", default="auto")
    parser.add_argument("--language", default="auto")
    args = parser.parse_args()

    if is_cached(args.video_path, args.transcripts_dir):
        print(transcript_cache_path(args.video_path, args.transcripts_dir))
        return

    model = load_whisper_model(args.model, args.device)
    transcribe_video(args.video_path, args.transcripts_dir, model, args.language)
    print(transcript_cache_path(args.video_path, args.transcripts_dir))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_transcribe.py -v`
Expected: PASS (9 passed)

- [ ] **Step 5: Commit**

```bash
git add scripts/transcribe.py tests/test_transcribe.py
git commit -m "feat: add faster-whisper transcription wrapper with caching"
```

---

### Task 8: Example config, gitignore, and config validation test

**Files:**
- Create: `config.example.yaml`
- Create: `.gitignore`
- Test: `tests/test_config_example.py`

**Interfaces:**
- Consumes: `load_config` from `scripts/config.py` (Task 1).

- [ ] **Step 1: Write the failing test**

Create `tests/test_config_example.py`:
```python
from pathlib import Path

from scripts.config import load_config

EXAMPLE_CONFIG_PATH = str(Path(__file__).resolve().parent.parent / "config.example.yaml")


def test_example_config_loads_without_error():
    config = load_config(EXAMPLE_CONFIG_PATH)

    assert config.whisper.model == "medium"
    assert config.analysis.chunk_minutes == 35
    assert config.analysis.use_subagents is True
    assert config.analysis.require_approval is True
    assert config.facecam.enabled is False
    assert config.subtitles.enabled is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config_example.py -v`
Expected: FAIL with `FileNotFoundError` (config.example.yaml does not exist yet)

- [ ] **Step 3: Create the example config**

Create `config.example.yaml`:
```yaml
# Copy this file to config.yaml and fill in your paths.

input_dir: "F:/Запись"
output_dir: "F:/Готовое/Шортс"

whisper:
  model: medium        # tiny | base | small | medium | large-v3
  device: auto          # auto | cuda | cpu
  language: auto        # auto, or a fixed language code like "ru"

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

clip:
  min_seconds: 30
  max_seconds: 60

crop:
  mode: auto             # auto | zoom | pad | original-16:9

facecam:
  # Set true if the recording has a webcam or VTuber avatar overlay.
  enabled: false
  # manual_region: cheap, fixed coordinates for a static overlay.
  # auto_detect: visual detection per video/scene - costs meaningfully more
  # compute and tokens; useful for VTubers with multiple models/scenes or a
  # moving camera.
  mode: manual_region
  region: null           # [x, y, w, h] as % of frame, only used in manual_region mode

subtitles:
  enabled: false
  font: Arial
  size: 48
  color: white
  outline: black
  position: bottom       # bottom | top | center
```

- [ ] **Step 4: Create the gitignore**

Create `.gitignore`:
```
transcripts/
work/
__pycache__/
*.pyc
.venv/
config.yaml
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_config_example.py -v`
Expected: PASS (1 passed)

- [ ] **Step 6: Commit**

```bash
git add config.example.yaml .gitignore tests/test_config_example.py
git commit -m "feat: add example config and gitignore"
```

---

### Task 9: SKILL.md — Claude Code skill orchestration

**Files:**
- Create: `SKILL.md`

**Interfaces:**
- Consumes: all CLIs from Tasks 2, 3, 5, 6, 7 (`scripts/chunker.py`, `scripts/candidates.py`, `scripts/render.py`, `scripts/setup.py`, `scripts/transcribe.py`) and `config.yaml` schema from Task 1/8.

- [ ] **Step 1: Write SKILL.md**

Create `SKILL.md`:
```markdown
---
name: make-shorts
description: Turn a long gameplay/stream recording into vertical (9:16) short clips using local Whisper transcription and semantic moment-finding. No watermarks, no time limits. Invoke as /make-shorts <path-to-video>.
---

# make-shorts

## Prerequisites

Before the first run, make sure the environment is ready:

```bash
python scripts/setup.py
```

This checks/installs ffmpeg (via winget) and the Python dependencies, and reports whether a CUDA GPU was detected.

Make sure `config.yaml` exists (copy `config.example.yaml` if not) and read it before starting — every step below is governed by it.

## Pipeline

Given a video path `<video>` and the loaded `config.yaml`:

### 1. Transcribe (cached)

```bash
python scripts/transcribe.py "<video>" transcripts --model <whisper.model> --device <whisper.device> --language <whisper.language>
```

This prints the path to the cached transcript JSON (`transcripts/<video_stem>.json`). If the file already existed, transcription is skipped — do not re-run Whisper on a video that already has a cached transcript.

### 2. Split into chunks

```bash
python scripts/chunker.py transcripts/<video_stem>.json work/<video_stem>/chunks --chunk-minutes <analysis.chunk_minutes>
```

This writes one `chunk_NNNN.json` file per window into `work/<video_stem>/chunks/`.

### 3. Find candidates (pass 1)

For each `chunk_NNNN.json` file, produce a `work/<video_stem>/candidates/candidates_chunk_NNNN.json` file containing a JSON list of objects `{"start": <seconds>, "end": <seconds>, "reason": "<short reason>"}` for every strong moment found in that chunk's segments (jokes, reactions, stories — judged from the text itself, not audio energy).

- If `config.analysis.use_subagents` is `true` (default): dispatch one Agent (subagent_type: general-purpose) per chunk file, **in parallel in a single message**, each instructed to read its assigned chunk JSON and write its own `candidates_chunk_NNNN.json` file with that format. Do not have subagents talk to each other — they work independently on disjoint time windows.
- If `config.analysis.use_subagents` is `false`: read every chunk file yourself, sequentially, and write the candidate files directly without dispatching agents.

Once every chunk has a candidates file, merge them:

```bash
python scripts/candidates.py work/<video_stem>/candidates work/<video_stem>/CANDIDATES.md work/<video_stem>/candidates.json
```

### 4. User approval

- If `config.analysis.require_approval` is `true` (default): show the user `work/<video_stem>/CANDIDATES.md` and ask which candidate IDs to proceed with. Only the approved subset continues to step 5.
- If `config.analysis.require_approval` is `false`: proceed with every candidate in `work/<video_stem>/candidates.json`.

### 5. Refine (pass 2)

For each approved candidate, re-read that moment's transcript window (from the chunk file(s) covering its time range) and decide:

- **Exact trim points** — adjust `start`/`end` to fall on natural speech pauses, not mid-word/mid-phrase, and keep the final duration within `config.clip.min_seconds`–`config.clip.max_seconds`.
- **Crop style** — one of `zoom` (visually dynamic moment, crop in tight) or `pad` (dialogue/joke-driven moment where the visual matters less, leave room for captions). Never write `auto` here — it must be a concrete resolved value.
- If `config.facecam.enabled` is `true`, factor the camera/avatar overlay into the crop decision (e.g. prefer `pad` so the full frame including the overlay stays visible, or `zoom` centered on the overlay region if `config.facecam.mode` is `manual_region` and a `region` is set).
- If `config.subtitles.enabled` is `true`, generate an `.srt` file for the clip's exact window under `work/<video_stem>/subtitles/` from the transcript segments, and reference it in the plan entry.

Write the merged results to `work/<video_stem>/PLAN.json`: a JSON list of objects:
```json
{
  "start": 123.4,
  "end": 156.2,
  "crop_style": "zoom",
  "subtitles_path": "work/<video_stem>/subtitles/clip_0001.srt",
  "output_filename": "<video_stem>_clip01.mp4"
}
```
(`subtitles_path` is omitted entirely when subtitles are disabled.)

### 6. Render

```bash
python scripts/render.py "<video>" work/<video_stem>/PLAN.json "<config.output_dir>"
```

This probes the source video once, then renders every entry in `PLAN.json` into `config.output_dir`, printing each output path.

## Library-wide search

Because every transcript is cached under `transcripts/`, steps 2-5 can be re-run against any subset of already-transcribed videos to search for moments across the whole archive, not just the video just processed — skip step 1 for videos that are already cached.
```

- [ ] **Step 2: Commit**

```bash
git add SKILL.md
git commit -m "feat: add make-shorts Claude Code skill orchestration"
```

---

### Task 10: README

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write README.md**

Create `README.md`:
```markdown
# shorts-maker

Turn long gameplay/stream recordings into vertical (9:16) short clips — fully local, free, no watermarks, no time limits. Runs as a Claude Code skill: local Whisper transcription + ffmpeg rendering do the mechanical work, Claude Code reads the transcript to find and trim the good moments.

## Requirements

- Windows with [winget](https://learn.microsoft.com/windows/package-manager/winget/) available
- Python 3.11 or 3.12 (faster-whisper/ctranslate2 may not yet have prebuilt wheels for 3.13 on all platforms)
- [Claude Code](https://claude.com/claude-code)
- Optional: an NVIDIA GPU for faster transcription

## Setup

```bash
git clone <this-repo>
cd shorts-maker
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt
python scripts/setup.py
```

`scripts/setup.py` checks for ffmpeg and Python dependencies, offers to install anything missing, and reports whether it detected a CUDA GPU.

Copy the example config and fill in your paths:

```bash
copy config.example.yaml config.yaml
```

Edit `config.yaml` — see the comments in `config.example.yaml` for what each field does (recommended chunk size ranges, facecam mode cost tradeoffs, etc).

## Usage

In Claude Code, from this project directory:

```
/make-shorts F:\Recordings\my-stream.mp4
```

Claude Code will transcribe (cached — only happens once per video ever), search the transcript for candidate moments, show you a list to approve, then render the approved clips into `config.output_dir`.

## Running the tests

```bash
pytest
```

## Project layout

- `scripts/` — the deterministic building blocks (config loading, transcript chunking, candidate merging, ffmpeg rendering, dependency setup) — each has a Python API and a CLI wrapper.
- `SKILL.md` — the Claude Code skill that orchestrates the above plus the semantic analysis passes.
- `transcripts/` — cached Whisper output per video (gitignored).
- `work/<video>/` — per-video working files: chunked transcript, candidate list, render plan (gitignored).
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add project README"
```

---

### Task 11: End-to-end integration test and manual verification guide

**Files:**
- Create: `tests/test_integration.py`
- Create: `docs/MANUAL_TESTING.md`

**Interfaces:**
- Consumes: `split_into_chunks`, `write_chunks` (Task 2); `merge_candidate_files`, `render_candidates_markdown` (Task 3); `render_clip` (Task 5).

- [ ] **Step 1: Write the integration test**

Create `tests/test_integration.py`:
```python
import json
from pathlib import Path

from scripts.candidates import merge_candidate_files, render_candidates_markdown, write_candidates_json
from scripts.chunker import split_into_chunks, write_chunks
from scripts.render import render_clip


def test_full_pipeline_on_synthetic_transcript(tmp_path):
    segments = [
        {"start": 0.0, "end": 3.0, "text": "intro"},
        {"start": 65.0, "end": 70.0, "text": "a really funny joke about the boss fight"},
        {"start": 130.0, "end": 134.0, "text": "another great reaction moment"},
    ]

    # Step 1: chunk the synthetic transcript (1-minute windows)
    chunks = split_into_chunks(segments, chunk_minutes=1)
    chunk_paths = write_chunks(chunks, str(tmp_path / "chunks"))
    assert len(chunk_paths) == 3

    # Step 2: simulate per-chunk subagent output — one candidate for chunks 1 and 2, none for chunk 0
    candidates_dir = tmp_path / "candidates"
    candidates_dir.mkdir()
    (candidates_dir / "candidates_chunk_0000.json").write_text(json.dumps([]), encoding="utf-8")
    (candidates_dir / "candidates_chunk_0001.json").write_text(
        json.dumps([{"start": 65.0, "end": 70.0, "reason": "funny joke about the boss fight"}]),
        encoding="utf-8",
    )
    (candidates_dir / "candidates_chunk_0002.json").write_text(
        json.dumps([{"start": 130.0, "end": 134.0, "reason": "great reaction moment"}]),
        encoding="utf-8",
    )

    # Step 3: merge into CANDIDATES.md + candidates.json
    candidates = merge_candidate_files(str(candidates_dir))
    assert len(candidates) == 2
    markdown = render_candidates_markdown(candidates)
    assert "funny joke about the boss fight" in markdown
    assert "great reaction moment" in markdown

    candidates_json_path = tmp_path / "candidates.json"
    write_candidates_json(candidates, str(candidates_json_path))

    # Step 4: simulate approval of both, and a refine pass producing PLAN.json
    plan = [
        {"start": 64.5, "end": 71.0, "crop_style": "zoom", "output_filename": "clip_0001.mp4"},
        {"start": 129.5, "end": 135.0, "crop_style": "pad", "output_filename": "clip_0002.mp4"},
    ]

    # Step 5: render each plan entry against a fake ffmpeg runner
    rendered_commands = []

    class FakeResult:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_runner(command, capture_output, text):
        rendered_commands.append(command)
        return FakeResult()

    for entry in plan:
        render_clip(
            "video.mp4", entry["output_filename"], entry,
            video_duration=200.0, src_width=1920, src_height=1080,
            runner=fake_runner,
        )

    assert len(rendered_commands) == 2
    assert rendered_commands[0][-1] == "clip_0001.mp4"
    assert rendered_commands[1][-1] == "clip_0002.mp4"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_integration.py -v`
Expected: FAIL only if any prior task's code is missing/broken — since Tasks 1-8 are already complete at this point, this should actually run and expose any integration mismatch between modules.

- [ ] **Step 3: Run test to verify it passes**

Run: `pytest tests/test_integration.py -v`
Expected: PASS (1 passed). If it fails, the failure points at a real interface mismatch between the modules built in Tasks 2, 3, and 5 — fix the mismatch (not the test) before continuing.

- [ ] **Step 4: Write the manual verification guide**

Create `docs/MANUAL_TESTING.md`:
```markdown
# Manual verification

The automated test suite covers the deterministic building blocks (config, chunking, candidate merging, crop math, command building). It does not cover the LLM-driven analysis passes or actual ffmpeg/Whisper execution — verify those by hand before trusting the pipeline on a real multi-hour recording:

1. Get a short (2-3 minute) sample video with a couple of clearly funny/interesting moments in it. Place it somewhere convenient, e.g. `test_video.mp4`.
2. Run `python scripts/setup.py` and confirm ffmpeg is found and the reported GPU/CPU device is correct.
3. Copy `config.example.yaml` to `config.yaml`, point `input_dir`/`output_dir` at test folders, and set `whisper.model: small` (faster for a quick manual check).
4. In Claude Code, run `/make-shorts test_video.mp4` with `analysis.use_subagents: true` and `analysis.require_approval: true`. Confirm:
   - The transcript is cached under `transcripts/test_video.json`.
   - `work/test_video/CANDIDATES.md` lists timecodes that land on genuinely interesting moments.
   - Re-running `/make-shorts test_video.mp4` skips transcription (no re-run of Whisper).
5. Approve one candidate and confirm `work/test_video/PLAN.json` has plausible trim points and a resolved (non-`auto`) `crop_style`.
6. Confirm the rendered clip in `config.output_dir` is 1080x1920, plays back correctly, and (if `subtitles.enabled: true`) has readable, correctly-synced burned-in subtitles.
7. Re-run once with `analysis.use_subagents: false` and once with `analysis.require_approval: false` to confirm both toggles change behavior as expected.
```

- [ ] **Step 5: Commit**

```bash
git add tests/test_integration.py docs/MANUAL_TESTING.md
git commit -m "test: add end-to-end integration test and manual verification guide"
```
