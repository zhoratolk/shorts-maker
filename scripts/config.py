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
PROFANITY_MASK_MODES = {"garble", "sound"}


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
    # Retention analysis 2026-07 (work/_analytics/retention_insights.json): 14/17
    # published clips read "too_long" (end retention <35%) and the recurring
    # drop-off zone is the first 0-20%. A 30s floor forced short meme moments to
    # be padded past their natural length, which is exactly what bleeds viewers -
    # so the floor was lowered to let the pipeline end on the punchline.
    min_seconds: int = 20
    max_seconds: int = 45
    fade_seconds: float = 0.5
    # Length ceiling for a Phase 5 sub-threshold compilation (D-05) - its own,
    # higher cap than max_seconds since it stitches multiple sub-threshold
    # moments into one clip. 2.5x the default max_seconds=60, comfortably
    # inside YouTube's 180s Shorts eligibility ceiling (05-RESEARCH.md
    # Pitfall 3).
    compilation_max_seconds: int = 150


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
    # A pause longer than this closes the current cue early, so a caption
    # never spans a silence and shows words the speaker hasn't said yet.
    max_gap_seconds: float = 1.2
    # Partially mask profane words in burned-in captions (keep a prefix,
    # replace the rest with '*'). Off by default; shares the audio mask's
    # wordlist so a bleeped word is also masked on screen. Fail-open.
    censor_profanity: bool = False
    censor_keep_ratio: float = 0.4
    censor_wordlist: str = "data/profanity_wordlist.yaml"


@dataclasses.dataclass
class ContentConfig:
    allow_mature: bool = True


@dataclasses.dataclass
class DiarizationConfig:
    enabled: bool = False
    # Fixed speaker count takes priority over min/max when set - use it when
    # the cast is stable (e.g. always exactly 2 mics). Leave num_speakers
    # unset and use min/max to let pyannote infer count within a range.
    num_speakers: int | None = None
    min_speakers: int | None = None
    max_speakers: int | None = None


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
class AudioEnergyConfig:
    enabled: bool = False
    # A momentary-loudness jump at least this many dB above its own local
    # rolling baseline counts as a spike (scream/laugh/hype yell).
    threshold_db: float = 6.0
    # Below this absolute LUFS, a "spike" is just noise floor moving inside
    # near-silence - ignored regardless of the relative jump.
    floor_lufs: float = -35.0
    baseline_window_seconds: float = 20.0
    min_duration: float = 0.3
    merge_gap_seconds: float = 1.0


@dataclasses.dataclass
class JumpcutsConfig:
    enabled: bool = False
    detect_min_seconds: float = 0.15
    cut_threshold_seconds: float = 0.4


@dataclasses.dataclass
class TransitionsConfig:
    # Context-driven transitions (crossfade/whip pan/mask-wipe/glitch/match cut)
    # at jumpcut boundaries. Off by default - conservative/opt-in like every
    # other optional feature (D-01, Fail-open).
    enabled: bool = False
    # xfade/borrowed-overlap window length. Short so a transition reads
    # snappy, not drawn-out - empirical starting point, tune after watching
    # real renders (D-02).
    transition_duration: float = 0.35
    # Below this much borrowed overlap at a boundary, a transition would be
    # imperceptible, so the boundary falls back to a plain cut (TRANS-03).
    # Empirical starting point, tune after watching real renders (D-02).
    min_overlap_seconds: float = 0.12
    # A boundary's motion/audio score must exceed this percentile of THIS
    # video's own boundary-score distribution before a non-cut transition is
    # chosen - adaptive, not a fixed magic number (RESEARCH.md Pitfall 4,
    # D-01/D-02). Empirical starting point, tune after watching real renders.
    strong_signal_percentile: float = 85.0
    # Histogram correlation at/above this reads as visually continuous,
    # selecting match_cut over another transition type. Empirical starting
    # point, tune after watching real renders (D-02).
    match_cut_similarity: float = 0.90


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
    # Also generate an English duplicate of the YouTube title (title_en) for
    # international feed reach when the primary metadata language isn't
    # English. Text generation happens in SKILL.md step 5; metadata.py just
    # renders the extra line when the field is present.
    english_title: bool = False


@dataclasses.dataclass
class MonetizationConfig:
    enabled: bool = True
    rules_path: str = "data/monetization_rules.yaml"
    # Audio fingerprinting needs the external fpcalc/Chromaprint binary, so it
    # is opt-in (disabled by default) like diarization/audio_energy - the
    # base install must work without it (fail-open).
    audio_fingerprint_enabled: bool = False
    # AcoustID network lookup is the only network egress this feature can
    # add; off by default to preserve the project's local-first default.
    enable_lookup: bool = False


@dataclasses.dataclass
class PublishConfig:
    # Dry-run is the default - going live requires an explicit opt-in
    # (PUB-03). A missing `publish` section in config.yaml also resolves to
    # this default via load_config's data.get("publish", {}) below.
    enabled: bool = False
    daily_slots_utc: list[str] = dataclasses.field(
        default_factory=lambda: ["09:00", "15:00", "20:00"]
    )
    queue_path: str = "work/_publish/queue.json"
    notifications_path: str = "work/_publish/notifications.log"
    client_secret_path: str = "client_secret.json"
    upload_token_path: str = "upload_token.json"
    # TikTok (PUB-06) and Instagram (PUB-07) per-platform fields - each with
    # its own independent enabled flag (D-01), never a shared/repurposed
    # `enabled`, so toggling one platform live can never accidentally flip
    # another.
    tiktok_enabled: bool = False
    tiktok_queue_path: str = "work/_publish/tiktok_queue.json"
    tiktok_client_key_path: str = "tiktok_client_key.json"
    tiktok_token_path: str = "tiktok_token.json"
    instagram_enabled: bool = False
    instagram_queue_path: str = "work/_publish/instagram_queue.json"
    instagram_client_secret_path: str = "instagram_client_secret.json"
    instagram_token_path: str = "instagram_token.json"


@dataclasses.dataclass
class ProfanityConfig:
    # Opt-in, off by default (D-04) - this is a new optional feature (like
    # diarization/audio_energy), not a mandatory safety gate.
    enabled: bool = False
    # Path to the RU+EN swear-stem wordlist YAML. Fail-open at load time
    # (scripts/profanity.py::load_wordlist): missing/malformed file degrades
    # to "no masking applied", never raises.
    wordlist_path: str = "data/profanity_wordlist.yaml"
    # Pads every detected word span by this many seconds on each side before
    # masking, to absorb Whisper's inherent word-boundary alignment drift
    # (measured ~100-400ms in published Whisper-family comparisons) so the
    # mask doesn't clip the onset/tail of the actual spoken word
    # (07-RESEARCH.md Pitfall 2).
    pad_seconds: float = 0.08
    # Fail-open defensive cap on spans masked per clip - an unrealistically
    # large match count (pathological wordlist, normalization bug, or a
    # genuinely very sweary clip) skips masking (warn + continue) instead of
    # growing the ffmpeg `enable` expression unbounded (07-RESEARCH.md
    # Pitfall 5).
    max_masked_spans_per_clip: int = 40
    # How far the masked word's own volume is ducked (0-1 exclusive, D-03) -
    # audio keeps flowing under the mask rather than a hard silence cut.
    duck_volume: float = 0.12
    # Center frequency (Hz) of the bandreject formant-removal filter applied
    # only inside masked spans - targets speech-intelligibility frequencies
    # to defeat STT without reading as a jarring cut (D-03/AUDIO-03).
    garble_freq: float = 1800.0
    # Width (in octaves) of the bandreject filter around garble_freq.
    garble_width_octaves: float = 4.0
    # Tremolo (amplitude warble) rate in Hz layered onto the masked span -
    # further garbles the word without silencing it.
    warble_freq: float = 18.0
    # Tremolo modulation depth (0-1] - how pronounced the warble effect is.
    warble_depth: float = 0.7
    # Which mask to apply inside a detected profane span: "garble" (the
    # duck+bandreject+tremolo mask above) or "sound" (mute the span and
    # overlay mask_sound_path instead).
    mask_mode: str = "garble"
    # Path to a custom censor audio clip, used only when mask_mode == "sound".
    # Existence is NOT checked at config load time - render.py fail-opens to
    # the garble mask at runtime if the file is missing (never crashes).
    mask_sound_path: str = ""
    # Delay a mask's onset by this many seconds into the word, so its leading
    # transient plays clean and the rest is masked. Empirically validated to
    # stay <= ~0.12s to keep STT-defeat intact (0.20/0.28 let faster-whisper
    # recover the word from its onset + context); 0 = mask from the word's
    # start (current behavior, byte-identical).
    mask_onset_seconds: float = 0.0


@dataclasses.dataclass
class HookBannerConfig:
    # Opt-in, off by default (HOOK-03 fail-open) - same footing as
    # diarization/audio_energy/profanity.
    enabled: bool = False
    # "persistent" is the locked default per ROADMAP.md's 2026-07-12 mode
    # decision: the nick plate stands in for a face (personality-first
    # content strategy) until a webcam/PNGTuber layout exists.
    # "hook" shows the banner only for the first duration_seconds.
    mode: str = "persistent"
    # Optional CTA/nick line drawn under the title (the Dunduk pattern),
    # e.g. "youtube.com/@channel". Empty = no CTA line.
    cta_text: str = ""
    # hook mode only: how long the banner stays before disappearing.
    duration_seconds: float = 3.0
    # hook mode only: fade-out length; 0 = hard cut.
    fade_seconds: float = 0.4
    # Friendly names resolve via render.py's HOOK_BANNER_FONT_PATHS
    # (Windows-shipped ariblk.ttf/arialbd.ttf, full Cyrillic). On
    # macOS/Linux set an explicit .ttf/.otf file path instead.
    font: str = "Arial Black"
    size: int = 58
    color: str = "white"
    cta_font: str = "Arial Bold"
    cta_size: int = 36
    cta_color: str = "#ffe98a"
    box_color: str = "black"
    box_opacity: float = 0.55
    # top | bottom. Must differ from subtitles.position (validated) so the
    # banner never overlaps burned-in captions (HOOK-02).
    position: str = "top"


@dataclasses.dataclass
class EmphasisConfig:
    # Mid-clip editor-style emphasis moves (Phase 9): transient soft zoom/cut-in
    # inserts placed *inside* a continuous clip (not only at splice boundaries),
    # the way a human editor punches in on a reaction or a hot gameplay beat.
    # Opt-in, off by default - same footing as diarization/audio_energy/
    # profanity/hook_banner. When off, PLAN.json's emphasis_moves is ignored and
    # rendering is byte-identical to today.
    enabled: bool = False
    # Hard cap on emphasis moves per clip. A dense stutter of zooms reads as a
    # jittery bad edit (anti-viral), so keep this low. 0 disables emphasis
    # entirely even when enabled.
    max_moves: int = 2
    # Peak zoom multiplier for each move. Deliberately milder than punch_zoom's
    # 1.15 default: emphasis pulses in *and back out*, so it should be gentle.
    zoom_amount: float = 1.12
    # Ease-in / ease-out ramp length (seconds) on each side of a move. The move
    # spends this long ramping up, holds at peak, then this long ramping back
    # down to 1x - a transient pulse, unlike punch_zoom which stays zoomed.
    ramp_seconds: float = 0.18
    # Minimum flat hold at peak zoom (seconds); a move's duration is clamped up
    # so it can always fit 2*ramp + this hold.
    min_hold_seconds: float = 0.25
    # target='face' aims the zoom at the facecam region. Off by default because
    # there is no webcam yet (personality-first strategy uses the nick plate) -
    # the code path exists so enabling a facecam later is a one-flag change.
    # When false, a move with target='face' falls back to 'action' (center).
    face_enabled: bool = False


@dataclasses.dataclass
class SocialOverlayConfig:
    # Phase 10 social popups: a small capsule (glyph + link text) that slides in
    # from the left, holds, and slides back out once per platform per clip.
    # Opt-in, off by default; runs as a fail-open finalize pass so a missing
    # icon or an old FFmpeg never breaks the render. Twitch is live now; Kick is
    # a stub (empty icon => text-only capsule) until a Kick glyph asset exists.
    enabled: bool = False
    # Ordered platforms; a platform is drawn only if it has a label or an icon,
    # so the Kick stub is silent until configured. Both draw once, spread apart.
    platforms: list = dataclasses.field(default_factory=lambda: ["twitch"])
    # {platform: glyph PNG path}. e.g. {"twitch": "assets/overlays/twitch_glyph.png"}
    icon_paths: dict = dataclasses.field(default_factory=dict)
    # {platform: link text}. e.g. {"twitch": "twitch.tv/zhorikp"}
    labels: dict = dataclasses.field(default_factory=dict)
    duration_seconds: float = 3.0
    slide_seconds: float = 0.4
    size: int = 44
    box_color: str = "#9146ff"  # Twitch purple
    box_opacity: float = 0.92
    font: str = "Arial Bold"
    # Capsule top Y in px; None => ~52% of frame height (clear of the top banner
    # and the bottom caption zone).
    y: int | None = None


@dataclasses.dataclass
class OutroCardConfig:
    # Phase 10 end card: an animated full-screen plate appended to each clip -
    # nick + platform glyph + link, over a self-animating gradient. The gradient
    # preset rotates by clip index (pattern_count) so consecutive shorts differ.
    # Opt-in, off by default; part of the same fail-open finalize pass.
    enabled: bool = False
    duration_seconds: float = 2.5
    nick: str = ""            # e.g. "ZhorikP"
    cta_text: str = ""        # e.g. "twitch.tv/zhorikp"
    icon_path: str = ""       # glyph shown above the nick
    font: str = "Arial Black"
    nick_size: int = 120
    cta_size: int = 56
    # How many built-in gradient presets to cycle through (capped at the number
    # that actually exist in render.OUTRO_PATTERNS).
    pattern_count: int = 5
    # Output fps for the appended card; the base clip is resampled to this so
    # the concat is always valid regardless of the source frame rate.
    fps: int = 30


@dataclasses.dataclass
class TopMomentsConfig:
    # Phase 10 auto-select cap. Applies ONLY in auto-select mode ("сделай топ
    # моменты по твоему выбору") - when the user hand-picks moments this is
    # ignored. rate_per_hour * source_hours is the GLOBAL budget of standalone
    # shorts for the whole recording (a 3h stream at rate 3 => 9 total, drawn
    # from anywhere across the 3h, not 3 per each hour). Configurable so a
    # business tier can dial it up.
    rate_per_hour: float = 3.0
    # Floor so a short recording still yields at least one short.
    minimum: int = 1


@dataclasses.dataclass
class ThumbnailConfig:
    # Poster/thumbnail generation: pick a strong frame from the finished clip
    # and burn a short caption over it. Off by default; fail-open (a failure
    # to build the poster never fails the clip render).
    enabled: bool = False
    # Poster size. Defaults to the clip's own 9:16 (Shorts show a custom
    # thumbnail on the channel grid / when shared). Set 1280x720 for regular
    # 16:9 videos.
    width: int = 1080
    height: int = 1920
    font: str = "Arial Black"
    font_size: int = 96
    text_color: str = "white"
    box_color: str = "black"
    box_opacity: float = 0.55
    position: str = "bottom"  # top | center | bottom
    max_lines: int = 3
    # How to choose the poster frame: "energy" uses audio-energy spikes when
    # available (falling back to the midpoint), "midpoint" always the middle.
    timestamp_strategy: str = "energy"
    # When True (and publish is enabled), the publish step sets this poster as
    # the video's custom thumbnail via thumbnails.set after upload. Fail-open:
    # a thumbnail error is logged and never fails an already-uploaded video.
    upload: bool = False


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
    diarization: DiarizationConfig = dataclasses.field(default_factory=DiarizationConfig)
    audio_energy: AudioEnergyConfig = dataclasses.field(default_factory=AudioEnergyConfig)
    metadata: MetadataConfig = dataclasses.field(default_factory=MetadataConfig)
    monetization: MonetizationConfig = dataclasses.field(default_factory=MonetizationConfig)
    audio: AudioConfig = dataclasses.field(default_factory=AudioConfig)
    effects: EffectsConfig = dataclasses.field(default_factory=EffectsConfig)
    jumpcuts: JumpcutsConfig = dataclasses.field(default_factory=JumpcutsConfig)
    visual: VisualConfig = dataclasses.field(default_factory=VisualConfig)
    publish: PublishConfig = dataclasses.field(default_factory=PublishConfig)
    transitions: TransitionsConfig = dataclasses.field(default_factory=TransitionsConfig)
    profanity: ProfanityConfig = dataclasses.field(default_factory=ProfanityConfig)
    hook_banner: HookBannerConfig = dataclasses.field(default_factory=HookBannerConfig)
    emphasis: EmphasisConfig = dataclasses.field(default_factory=EmphasisConfig)
    social_overlay: SocialOverlayConfig = dataclasses.field(default_factory=SocialOverlayConfig)
    outro_card: OutroCardConfig = dataclasses.field(default_factory=OutroCardConfig)
    top_moments: TopMomentsConfig = dataclasses.field(default_factory=TopMomentsConfig)
    thumbnail: ThumbnailConfig = dataclasses.field(default_factory=ThumbnailConfig)


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
        diarization=_build(DiarizationConfig, data.get("diarization", {}), "diarization"),
        audio_energy=_build(AudioEnergyConfig, data.get("audio_energy", {}), "audio_energy"),
        metadata=_build(MetadataConfig, data.get("metadata", {}), "metadata"),
        monetization=_build(MonetizationConfig, data.get("monetization", {}), "monetization"),
        audio=_build(AudioConfig, data.get("audio", {}), "audio"),
        effects=_build(EffectsConfig, data.get("effects", {}), "effects"),
        jumpcuts=_build(JumpcutsConfig, data.get("jumpcuts", {}), "jumpcuts"),
        visual=_build(VisualConfig, data.get("visual", {}), "visual"),
        publish=_build(PublishConfig, data.get("publish", {}), "publish"),
        transitions=_build(TransitionsConfig, data.get("transitions", {}), "transitions"),
        profanity=_build(ProfanityConfig, data.get("profanity", {}), "profanity"),
        hook_banner=_build(HookBannerConfig, data.get("hook_banner", {}), "hook_banner"),
        emphasis=_build(EmphasisConfig, data.get("emphasis", {}), "emphasis"),
        social_overlay=_build(SocialOverlayConfig, data.get("social_overlay", {}), "social_overlay"),
        outro_card=_build(OutroCardConfig, data.get("outro_card", {}), "outro_card"),
        top_moments=_build(TopMomentsConfig, data.get("top_moments", {}), "top_moments"),
        thumbnail=_build(ThumbnailConfig, data.get("thumbnail", {}), "thumbnail"),
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
    if config.clip.compilation_max_seconds <= config.clip.max_seconds:
        raise ConfigError(
            f"clip.compilation_max_seconds ({config.clip.compilation_max_seconds}) must be greater "
            f"than clip.max_seconds ({config.clip.max_seconds})"
        )
    if config.subtitles.words_per_cue <= 0:
        raise ConfigError("subtitles.words_per_cue must be > 0")
    if config.subtitles.max_gap_seconds <= 0:
        raise ConfigError("subtitles.max_gap_seconds must be > 0")
    if not 0 <= config.subtitles.censor_keep_ratio <= 1:
        raise ConfigError("subtitles.censor_keep_ratio must be between 0 and 1")
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
    if config.diarization.num_speakers is not None and config.diarization.num_speakers <= 0:
        raise ConfigError(
            f"diarization.num_speakers must be > 0, got {config.diarization.num_speakers}"
        )
    if config.diarization.min_speakers is not None and config.diarization.min_speakers <= 0:
        raise ConfigError(
            f"diarization.min_speakers must be > 0, got {config.diarization.min_speakers}"
        )
    if config.diarization.max_speakers is not None and config.diarization.max_speakers <= 0:
        raise ConfigError(
            f"diarization.max_speakers must be > 0, got {config.diarization.max_speakers}"
        )
    if (
        config.diarization.min_speakers is not None
        and config.diarization.max_speakers is not None
        and config.diarization.min_speakers > config.diarization.max_speakers
    ):
        raise ConfigError("diarization.min_speakers must be <= diarization.max_speakers")
    if config.audio_energy.threshold_db <= 0:
        raise ConfigError(
            f"audio_energy.threshold_db must be > 0, got {config.audio_energy.threshold_db}"
        )
    if config.audio_energy.baseline_window_seconds <= 0:
        raise ConfigError(
            f"audio_energy.baseline_window_seconds must be > 0, got "
            f"{config.audio_energy.baseline_window_seconds}"
        )
    if config.audio_energy.min_duration <= 0:
        raise ConfigError(f"audio_energy.min_duration must be > 0, got {config.audio_energy.min_duration}")
    if config.audio_energy.merge_gap_seconds < 0:
        raise ConfigError(
            f"audio_energy.merge_gap_seconds must be >= 0, got {config.audio_energy.merge_gap_seconds}"
        )
    for slot in config.publish.daily_slots_utc:
        parts = slot.split(":")
        valid = False
        if len(parts) == 2:
            try:
                hour, minute = int(parts[0]), int(parts[1])
                valid = 0 <= hour <= 23 and 0 <= minute <= 59
            except ValueError:
                valid = False
        if not valid:
            raise ConfigError(
                f"publish.daily_slots_utc contains an invalid HH:MM 24-hour entry: {slot!r}"
            )
    if config.publish.enabled and not config.publish.daily_slots_utc:
        raise ConfigError(
            "publish.daily_slots_utc must be non-empty when publish.enabled is true"
        )
    if config.transitions.transition_duration <= 0:
        raise ConfigError(
            f"transitions.transition_duration must be > 0, got {config.transitions.transition_duration}"
        )
    if config.transitions.min_overlap_seconds <= 0:
        raise ConfigError(
            f"transitions.min_overlap_seconds must be > 0, got {config.transitions.min_overlap_seconds}"
        )
    if config.transitions.min_overlap_seconds > config.transitions.transition_duration:
        raise ConfigError(
            "transitions.min_overlap_seconds must be <= transitions.transition_duration"
        )
    if not (0 < config.transitions.strong_signal_percentile < 100):
        raise ConfigError(
            f"transitions.strong_signal_percentile must be between 0 and 100 (exclusive), "
            f"got {config.transitions.strong_signal_percentile}"
        )
    if not (0 <= config.transitions.match_cut_similarity <= 1):
        raise ConfigError(
            f"transitions.match_cut_similarity must be between 0 and 1, "
            f"got {config.transitions.match_cut_similarity}"
        )
    if config.profanity.pad_seconds < 0:
        raise ConfigError(
            f"profanity.pad_seconds must be >= 0, got {config.profanity.pad_seconds}"
        )
    if config.profanity.max_masked_spans_per_clip <= 0:
        raise ConfigError(
            f"profanity.max_masked_spans_per_clip must be > 0, got "
            f"{config.profanity.max_masked_spans_per_clip}"
        )
    if not (0 < config.profanity.duck_volume < 1):
        raise ConfigError(
            f"profanity.duck_volume must be between 0 and 1 (exclusive), got {config.profanity.duck_volume}"
        )
    if config.profanity.garble_freq <= 0:
        raise ConfigError(
            f"profanity.garble_freq must be > 0, got {config.profanity.garble_freq}"
        )
    if config.profanity.garble_width_octaves <= 0:
        raise ConfigError(
            f"profanity.garble_width_octaves must be > 0, got {config.profanity.garble_width_octaves}"
        )
    if config.profanity.warble_freq <= 0:
        raise ConfigError(
            f"profanity.warble_freq must be > 0, got {config.profanity.warble_freq}"
        )
    if not (0 < config.profanity.warble_depth <= 1):
        raise ConfigError(
            f"profanity.warble_depth must be between 0 (exclusive) and 1 (inclusive), got "
            f"{config.profanity.warble_depth}"
        )
    if config.profanity.mask_mode not in PROFANITY_MASK_MODES:
        raise ConfigError(
            f"profanity.mask_mode must be one of {sorted(PROFANITY_MASK_MODES)}, "
            f"got {config.profanity.mask_mode!r}"
        )
    if config.profanity.mask_onset_seconds < 0:
        raise ConfigError(
            f"profanity.mask_onset_seconds must be >= 0, got "
            f"{config.profanity.mask_onset_seconds}"
        )
    if config.profanity.mask_mode == "sound" and not config.profanity.mask_sound_path.strip():
        raise ConfigError(
            "profanity.mask_sound_path must be set to a non-empty path when "
            "profanity.mask_mode is 'sound'"
        )
    if config.hook_banner.mode not in ("hook", "persistent"):
        raise ConfigError(
            f"hook_banner.mode must be 'hook' or 'persistent', got {config.hook_banner.mode!r}"
        )
    if config.hook_banner.position not in ("top", "bottom"):
        raise ConfigError(
            f"hook_banner.position must be 'top' or 'bottom', got {config.hook_banner.position!r}"
        )
    if config.hook_banner.size <= 0 or config.hook_banner.cta_size <= 0:
        raise ConfigError(
            f"hook_banner sizes must be > 0, got size={config.hook_banner.size}, "
            f"cta_size={config.hook_banner.cta_size}"
        )
    if not 0.0 <= config.hook_banner.box_opacity <= 1.0:
        raise ConfigError(
            f"hook_banner.box_opacity must be within [0, 1], got {config.hook_banner.box_opacity}"
        )
    if config.hook_banner.mode == "hook":
        if config.hook_banner.duration_seconds <= 0:
            raise ConfigError(
                f"hook_banner.duration_seconds must be > 0, got {config.hook_banner.duration_seconds}"
            )
        if not 0 <= config.hook_banner.fade_seconds < config.hook_banner.duration_seconds:
            raise ConfigError(
                f"hook_banner.fade_seconds must be within [0, duration_seconds), got "
                f"{config.hook_banner.fade_seconds}"
            )
    # Fail-loud collision guard (HOOK-02): a banner and burned-in subtitles
    # anchored to the same zone would overlap by construction.
    if (
        config.hook_banner.enabled
        and config.subtitles.enabled
        and config.hook_banner.position == config.subtitles.position
    ):
        raise ConfigError(
            f"hook_banner.position and subtitles.position are both "
            f"{config.hook_banner.position!r}; the banner would overlap burned-in "
            "captions - set them to different zones"
        )

    if config.emphasis.max_moves < 0:
        raise ConfigError(
            f"emphasis.max_moves must be >= 0, got {config.emphasis.max_moves}"
        )
    if config.emphasis.zoom_amount <= 1.0:
        raise ConfigError(
            f"emphasis.zoom_amount must be > 1.0, got {config.emphasis.zoom_amount}"
        )
    if config.emphasis.ramp_seconds <= 0:
        raise ConfigError(
            f"emphasis.ramp_seconds must be > 0, got {config.emphasis.ramp_seconds}"
        )
    if config.emphasis.min_hold_seconds < 0:
        raise ConfigError(
            f"emphasis.min_hold_seconds must be >= 0, got {config.emphasis.min_hold_seconds}"
        )
    if config.social_overlay.duration_seconds <= 0:
        raise ConfigError(
            f"social_overlay.duration_seconds must be > 0, got {config.social_overlay.duration_seconds}"
        )
    if config.social_overlay.slide_seconds <= 0:
        raise ConfigError(
            f"social_overlay.slide_seconds must be > 0, got {config.social_overlay.slide_seconds}"
        )
    if config.social_overlay.slide_seconds * 2 >= config.social_overlay.duration_seconds:
        raise ConfigError(
            "social_overlay.slide_seconds*2 must be < duration_seconds so the capsule has a hold "
            f"(got slide={config.social_overlay.slide_seconds}, duration={config.social_overlay.duration_seconds})"
        )
    if config.social_overlay.size <= 0:
        raise ConfigError(f"social_overlay.size must be > 0, got {config.social_overlay.size}")
    if not 0.0 <= config.social_overlay.box_opacity <= 1.0:
        raise ConfigError(
            f"social_overlay.box_opacity must be within [0, 1], got {config.social_overlay.box_opacity}"
        )
    if config.outro_card.duration_seconds <= 0:
        raise ConfigError(
            f"outro_card.duration_seconds must be > 0, got {config.outro_card.duration_seconds}"
        )
    if config.outro_card.nick_size <= 0 or config.outro_card.cta_size <= 0:
        raise ConfigError(
            f"outro_card.nick_size and outro_card.cta_size must be > 0, got "
            f"nick_size={config.outro_card.nick_size}, cta_size={config.outro_card.cta_size}"
        )
    if config.outro_card.pattern_count < 1:
        raise ConfigError(
            f"outro_card.pattern_count must be >= 1, got {config.outro_card.pattern_count}"
        )
    if config.outro_card.fps <= 0:
        raise ConfigError(f"outro_card.fps must be > 0, got {config.outro_card.fps}")
    if config.top_moments.rate_per_hour <= 0:
        raise ConfigError(
            f"top_moments.rate_per_hour must be > 0, got {config.top_moments.rate_per_hour}"
        )
    if config.top_moments.minimum < 1:
        raise ConfigError(
            f"top_moments.minimum must be >= 1, got {config.top_moments.minimum}"
        )
    if config.thumbnail.width <= 0 or config.thumbnail.height <= 0:
        raise ConfigError(
            f"thumbnail.width and thumbnail.height must be > 0, got "
            f"{config.thumbnail.width}x{config.thumbnail.height}"
        )
    if config.thumbnail.font_size <= 0:
        raise ConfigError(f"thumbnail.font_size must be > 0, got {config.thumbnail.font_size}")
    if config.thumbnail.max_lines < 1:
        raise ConfigError(f"thumbnail.max_lines must be >= 1, got {config.thumbnail.max_lines}")
    if not 0.0 <= config.thumbnail.box_opacity <= 1.0:
        raise ConfigError(
            f"thumbnail.box_opacity must be within [0, 1], got {config.thumbnail.box_opacity}"
        )
    if config.thumbnail.position not in ("top", "center", "bottom"):
        raise ConfigError(
            f"thumbnail.position must be 'top', 'center' or 'bottom', got {config.thumbnail.position!r}"
        )
    if config.thumbnail.timestamp_strategy not in ("energy", "midpoint"):
        raise ConfigError(
            f"thumbnail.timestamp_strategy must be 'energy' or 'midpoint', got "
            f"{config.thumbnail.timestamp_strategy!r}"
        )
