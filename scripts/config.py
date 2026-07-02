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
