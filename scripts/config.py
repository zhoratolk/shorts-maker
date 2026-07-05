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
METADATA_PLATFORMS = {"youtube", "tiktok", "instagram"}


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
    hype_phrases: list[str] = dataclasses.field(
        default_factory=lambda: [
            "завоз", "ору", "кринж", "база", "это база", "мем вышел", "жиза", "воу-воу",
            "рофл", "дичь", "жесть", "разрыв", "го клип", "клипани", "красава", "топчик", "агонь",
        ]
    )


@dataclasses.dataclass
class ClipConfig:
    min_seconds: int = 30
    max_seconds: int = 60
    fade_seconds: float = 0.5


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
    font: str = "Arial Black"
    size: int = 92
    color: str = "white"
    outline: str = "black"
    highlight_color: str = "yellow"
    position: str = "bottom"
    words_per_cue: int = 4
    strip_punctuation: bool = True


@dataclasses.dataclass
class ContentConfig:
    allow_mature: bool = True


@dataclasses.dataclass
class AudioConfig:
    denoise: bool = True
    # FFmpeg afftdn's own default (12) treats the whole mixed track as noise
    # to subtract - fine for an isolated mic, but on a mixed game+voice track
    # it introduces a "musical noise"/wind-like artifact on non-stationary
    # game audio (SFX, music) while voice survives. Gentler default here;
    # raise it back up for a genuinely hissy/noisy mic, lower or disable
    # denoise entirely if game audio still sounds smeared.
    denoise_strength: float = 6.0
    loudnorm: bool = True


@dataclasses.dataclass
class VisualConfig:
    enabled: bool = False
    frame_interval_seconds: float = 120.0
    detect_game_context: bool = True
    detect_visual_candidates: bool = True


@dataclasses.dataclass
class JumpcutsConfig:
    enabled: bool = False
    detect_min_seconds: float = 0.15
    cut_threshold_seconds: float = 0.4


@dataclasses.dataclass
class EffectsConfig:
    vignette: bool = False
    grain_strength: int = 0
    punch_zoom_amount: float = 1.15
    punch_zoom_ramp: float = 0.25


@dataclasses.dataclass
class MetadataConfig:
    enabled: bool = True
    platforms: list[str] = dataclasses.field(
        default_factory=lambda: ["youtube", "tiktok", "instagram"]
    )
    language: str = "auto"


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
    content: ContentConfig = dataclasses.field(default_factory=ContentConfig)
    metadata: MetadataConfig = dataclasses.field(default_factory=MetadataConfig)
    audio: AudioConfig = dataclasses.field(default_factory=AudioConfig)
    effects: EffectsConfig = dataclasses.field(default_factory=EffectsConfig)
    jumpcuts: JumpcutsConfig = dataclasses.field(default_factory=JumpcutsConfig)
    visual: VisualConfig = dataclasses.field(default_factory=VisualConfig)


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
        content=_build(ContentConfig, data.get("content", {}), "content"),
        metadata=_build(MetadataConfig, data.get("metadata", {}), "metadata"),
        audio=_build(AudioConfig, data.get("audio", {}), "audio"),
        effects=_build(EffectsConfig, data.get("effects", {}), "effects"),
        jumpcuts=_build(JumpcutsConfig, data.get("jumpcuts", {}), "jumpcuts"),
        visual=_build(VisualConfig, data.get("visual", {}), "visual"),
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
    if config.clip.fade_seconds < 0:
        raise ConfigError("clip.fade_seconds must be >= 0")
    if config.subtitles.words_per_cue <= 0:
        raise ConfigError("subtitles.words_per_cue must be > 0")
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
    if config.effects.grain_strength < 0 or config.effects.grain_strength > 100:
        raise ConfigError(
            f"effects.grain_strength must be between 0 and 100, got {config.effects.grain_strength}"
        )
    if config.effects.punch_zoom_amount <= 1.0:
        raise ConfigError(
            f"effects.punch_zoom_amount must be > 1.0, got {config.effects.punch_zoom_amount}"
        )
    if config.effects.punch_zoom_ramp <= 0:
        raise ConfigError(f"effects.punch_zoom_ramp must be > 0, got {config.effects.punch_zoom_ramp}")
    if config.jumpcuts.detect_min_seconds <= 0:
        raise ConfigError(
            f"jumpcuts.detect_min_seconds must be > 0, got {config.jumpcuts.detect_min_seconds}"
        )
    if config.jumpcuts.cut_threshold_seconds <= 0:
        raise ConfigError(
            f"jumpcuts.cut_threshold_seconds must be > 0, got {config.jumpcuts.cut_threshold_seconds}"
        )
    if config.jumpcuts.cut_threshold_seconds < config.jumpcuts.detect_min_seconds:
        raise ConfigError(
            "jumpcuts.cut_threshold_seconds must be >= jumpcuts.detect_min_seconds"
        )
    if config.audio.denoise_strength <= 0 or config.audio.denoise_strength > 97:
        raise ConfigError(
            f"audio.denoise_strength must be between 0 and 97, got {config.audio.denoise_strength}"
        )
    if config.visual.frame_interval_seconds <= 0:
        raise ConfigError(
            f"visual.frame_interval_seconds must be > 0, got {config.visual.frame_interval_seconds}"
        )
    if config.metadata.enabled:
        if not config.metadata.platforms:
            raise ConfigError("metadata.platforms must be non-empty when metadata.enabled is true")
        unknown = set(config.metadata.platforms) - METADATA_PLATFORMS
        if unknown:
            raise ConfigError(
                f"metadata.platforms contains unknown values {sorted(unknown)}; "
                f"must be a subset of {sorted(METADATA_PLATFORMS)}"
            )
