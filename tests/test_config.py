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
    assert config.clip.fade_seconds == 0.5
    assert config.crop.mode == "auto"
    assert config.facecam.enabled is False
    assert config.facecam.mode == "manual_region"
    assert config.subtitles.enabled is False
    assert config.subtitles.words_per_cue == 4
    assert config.subtitles.max_gap_seconds == 1.2
    assert config.content.allow_mature is True
    assert config.diarization.enabled is False
    assert config.diarization.num_speakers is None
    assert config.diarization.min_speakers is None
    assert config.diarization.max_speakers is None
    assert config.audio_energy.enabled is False
    assert config.audio_energy.threshold_db == 6.0
    assert config.audio_energy.floor_lufs == -35.0
    assert config.audio_energy.baseline_window_seconds == 20.0
    assert config.audio_energy.min_duration == 0.3
    assert config.audio_energy.merge_gap_seconds == 1.0


def test_load_config_audio_energy_custom_values(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        audio_energy:
          enabled: true
          threshold_db: 8.0
        """,
    )

    config = load_config(path)

    assert config.audio_energy.enabled is True
    assert config.audio_energy.threshold_db == 8.0


def test_load_config_audio_energy_threshold_db_must_be_positive(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        audio_energy:
          threshold_db: 0
        """,
    )

    with pytest.raises(ConfigError, match="audio_energy.threshold_db"):
        load_config(path)


def test_load_config_audio_energy_merge_gap_seconds_rejects_negative(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        audio_energy:
          merge_gap_seconds: -1
        """,
    )

    with pytest.raises(ConfigError, match="audio_energy.merge_gap_seconds"):
        load_config(path)


def test_load_config_diarization_custom_values(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        diarization:
          enabled: true
          min_speakers: 2
          max_speakers: 4
        """,
    )

    config = load_config(path)

    assert config.diarization.enabled is True
    assert config.diarization.min_speakers == 2
    assert config.diarization.max_speakers == 4


def test_load_config_diarization_num_speakers_zero_raises(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        diarization:
          num_speakers: 0
        """,
    )

    with pytest.raises(ConfigError, match="diarization.num_speakers"):
        load_config(path)


def test_load_config_diarization_min_greater_than_max_raises(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        diarization:
          min_speakers: 5
          max_speakers: 2
        """,
    )

    with pytest.raises(ConfigError, match="diarization.min_speakers must be <= diarization.max_speakers"):
        load_config(path)


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


def test_load_config_fade_seconds_must_be_non_negative(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        clip:
          fade_seconds: -0.1
        """,
    )

    with pytest.raises(ConfigError, match="fade_seconds"):
        load_config(path)


def test_load_config_subtitles_words_per_cue_must_be_positive(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        subtitles:
          words_per_cue: 0
        """,
    )

    with pytest.raises(ConfigError, match="words_per_cue"):
        load_config(path)


def test_load_config_subtitles_max_gap_seconds_must_be_positive(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        subtitles:
          max_gap_seconds: 0
        """,
    )

    with pytest.raises(ConfigError, match="max_gap_seconds"):
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


def test_load_config_metadata_defaults(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        """,
    )

    config = load_config(path)

    assert config.metadata.enabled is True
    assert config.metadata.platforms == ["youtube", "tiktok", "instagram"]
    assert config.metadata.language == "auto"


def test_load_config_metadata_empty_platforms_when_enabled_raises(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        metadata:
          enabled: true
          platforms: []
        """,
    )

    with pytest.raises(ConfigError, match="metadata.platforms"):
        load_config(path)


def test_load_config_metadata_unknown_platform_raises(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        metadata:
          platforms: [youtube, twitter]
        """,
    )

    with pytest.raises(ConfigError, match="metadata.platforms"):
        load_config(path)


def test_load_config_content_allow_mature_can_be_disabled(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        content:
          allow_mature: false
        """,
    )

    config = load_config(path)

    assert config.content.allow_mature is False


def test_load_config_audio_defaults(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        """,
    )

    config = load_config(path)

    assert config.audio.denoise is True
    assert config.audio.denoise_strength == 6.0
    assert config.audio.loudnorm is True


def test_load_config_audio_can_be_disabled(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        audio:
          denoise: false
          loudnorm: false
        """,
    )

    config = load_config(path)

    assert config.audio.denoise is False
    assert config.audio.loudnorm is False


def test_load_config_audio_denoise_strength_custom(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        audio:
          denoise_strength: 15
        """,
    )

    config = load_config(path)

    assert config.audio.denoise_strength == 15


def test_load_config_audio_denoise_strength_rejects_out_of_range(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        audio:
          denoise_strength: 0
        """,
    )

    with pytest.raises(ConfigError, match="audio.denoise_strength"):
        load_config(path)


def test_load_config_effects_defaults(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        """,
    )

    config = load_config(path)

    assert config.effects.vignette is False
    assert config.effects.grain_strength == 0


def test_load_config_effects_can_be_enabled(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        effects:
          vignette: true
          grain_strength: 20
        """,
    )

    config = load_config(path)

    assert config.effects.vignette is True
    assert config.effects.grain_strength == 20


def test_load_config_effects_grain_strength_out_of_range_raises(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        effects:
          grain_strength: 150
        """,
    )

    with pytest.raises(ConfigError, match="grain_strength must be between 0 and 100"):
        load_config(path)


def test_load_config_effects_punch_zoom_defaults(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        """,
    )

    config = load_config(path)

    assert config.effects.punch_zoom_amount == 1.15
    assert config.effects.punch_zoom_ramp == 0.25


def test_load_config_effects_punch_zoom_amount_must_exceed_one(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        effects:
          punch_zoom_amount: 1.0
        """,
    )

    with pytest.raises(ConfigError, match="punch_zoom_amount must be > 1.0"):
        load_config(path)


def test_load_config_effects_punch_zoom_ramp_must_be_positive(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        effects:
          punch_zoom_ramp: 0
        """,
    )

    with pytest.raises(ConfigError, match="punch_zoom_ramp must be > 0"):
        load_config(path)


def test_load_config_jumpcuts_defaults(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        """,
    )

    config = load_config(path)

    assert config.jumpcuts.enabled is False
    assert config.jumpcuts.detect_min_seconds == 0.15
    assert config.jumpcuts.cut_threshold_seconds == 0.4


def test_load_config_jumpcuts_can_be_enabled(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        jumpcuts:
          enabled: true
          detect_min_seconds: 0.2
          cut_threshold_seconds: 0.5
        """,
    )

    config = load_config(path)

    assert config.jumpcuts.enabled is True
    assert config.jumpcuts.detect_min_seconds == 0.2
    assert config.jumpcuts.cut_threshold_seconds == 0.5


def test_load_config_jumpcuts_cut_threshold_must_be_at_least_detect_min(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        jumpcuts:
          detect_min_seconds: 0.5
          cut_threshold_seconds: 0.2
        """,
    )

    with pytest.raises(ConfigError, match="cut_threshold_seconds must be >= jumpcuts.detect_min_seconds"):
        load_config(path)


def test_load_config_visual_defaults(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        """,
    )

    config = load_config(path)

    assert config.visual.enabled is False
    assert config.visual.frame_interval_seconds == 120.0
    assert config.visual.detect_game_context is True
    assert config.visual.detect_visual_candidates is True


def test_load_config_visual_can_be_enabled(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        visual:
          enabled: true
          frame_interval_seconds: 60
          detect_visual_candidates: false
        """,
    )

    config = load_config(path)

    assert config.visual.enabled is True
    assert config.visual.frame_interval_seconds == 60
    assert config.visual.detect_game_context is True
    assert config.visual.detect_visual_candidates is False


def test_load_config_visual_frame_interval_must_be_positive(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        visual:
          frame_interval_seconds: 0
        """,
    )

    with pytest.raises(ConfigError, match="frame_interval_seconds must be > 0"):
        load_config(path)


def test_load_config_metadata_disabled_allows_empty_platforms(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        metadata:
          enabled: false
          platforms: []
        """,
    )

    config = load_config(path)

    assert config.metadata.enabled is False
    assert config.metadata.platforms == []


def test_load_config_subtitles_defaults_size_and_highlight_color(tmp_path):
    path = write_config(tmp_path, 'input_dir: "F:/in"\noutput_dir: "F:/out"\n')

    config = load_config(path)

    assert config.subtitles.size == 92
    assert config.subtitles.highlight_color == "yellow"
    assert config.subtitles.strip_punctuation is True


def test_load_config_analysis_default_hype_phrases(tmp_path):
    path = write_config(tmp_path, 'input_dir: "F:/in"\noutput_dir: "F:/out"\n')

    config = load_config(path)

    assert config.analysis.hype_phrases == [
        "завоз", "ору", "кринж", "база", "это база", "мем вышел", "жиза", "воу-воу",
        "рофл", "дичь", "жесть", "разрыв", "го клип", "клипани", "красава", "топчик", "агонь",
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


def test_load_config_monetization_defaults(tmp_path):
    path = write_config(tmp_path, 'input_dir: "F:/in"\noutput_dir: "F:/out"\n')

    config = load_config(path)

    assert config.monetization.enabled is True
    assert config.monetization.rules_path == "data/monetization_rules.yaml"


def test_load_config_monetization_custom_values_round_trip(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        monetization:
          enabled: false
          rules_path: "data/custom_rules.yaml"
        """,
    )

    config = load_config(path)

    assert config.monetization.enabled is False
    assert config.monetization.rules_path == "data/custom_rules.yaml"


def test_load_config_monetization_audio_fingerprint_defaults_disabled(tmp_path):
    path = write_config(tmp_path, 'input_dir: "F:/in"\noutput_dir: "F:/out"\n')

    config = load_config(path)

    assert config.monetization.audio_fingerprint_enabled is False
    assert config.monetization.enable_lookup is False


def test_load_config_monetization_audio_fingerprint_custom_values_round_trip(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        monetization:
          audio_fingerprint_enabled: true
          enable_lookup: true
        """,
    )

    config = load_config(path)

    assert config.monetization.audio_fingerprint_enabled is True
    assert config.monetization.enable_lookup is True


def test_default_config_publish_enabled_is_false():
    from scripts.config import Config

    config = Config(input_dir="F:/in", output_dir="F:/out")

    assert config.publish.enabled is False


def test_load_config_publish_defaults_when_section_missing(tmp_path):
    path = write_config(tmp_path, 'input_dir: "F:/in"\noutput_dir: "F:/out"\n')

    config = load_config(path)

    assert config.publish.enabled is False
    assert config.publish.daily_slots_utc == ["09:00", "15:00", "20:00"]
    assert config.publish.queue_path == "work/_publish/queue.json"
    assert config.publish.notifications_path == "work/_publish/notifications.log"
    assert config.publish.client_secret_path == "client_secret.json"
    assert config.publish.upload_token_path == "upload_token.json"


def test_load_config_publish_custom_values_round_trip(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        publish:
          enabled: true
          daily_slots_utc: ["10:30", "22:00"]
        """,
    )

    config = load_config(path)

    assert config.publish.enabled is True
    assert config.publish.daily_slots_utc == ["10:30", "22:00"]


def test_load_config_publish_invalid_slot_format_raises(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        publish:
          daily_slots_utc: ["9am"]
        """,
    )

    with pytest.raises(ConfigError, match="daily_slots_utc"):
        load_config(path)


def test_load_config_publish_invalid_slot_hour_out_of_range_raises(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        publish:
          daily_slots_utc: ["25:00"]
        """,
    )

    with pytest.raises(ConfigError, match="daily_slots_utc"):
        load_config(path)


def test_load_config_publish_empty_slots_when_enabled_raises(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        publish:
          enabled: true
          daily_slots_utc: []
        """,
    )

    with pytest.raises(ConfigError, match="daily_slots_utc"):
        load_config(path)
