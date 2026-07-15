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
    assert config.clip.compilation_max_seconds == 150
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


def test_load_config_compilation_max_seconds_custom_value(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        clip:
          compilation_max_seconds: 120
        """,
    )

    config = load_config(path)

    assert config.clip.compilation_max_seconds == 120


def test_load_config_compilation_max_seconds_must_exceed_max_seconds(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        clip:
          max_seconds: 60
          compilation_max_seconds: 60
        """,
    )

    with pytest.raises(ConfigError, match="compilation_max_seconds"):
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
    assert config.metadata.english_title is False


def test_load_config_metadata_english_title_true(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "D:/in"
        output_dir: "D:/out"
        metadata:
          english_title: true
        """,
    )

    assert load_config(path).metadata.english_title is True


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


def test_load_config_transitions_defaults_when_section_missing(tmp_path):
    path = write_config(tmp_path, 'input_dir: "F:/in"\noutput_dir: "F:/out"\n')

    config = load_config(path)

    assert config.transitions.enabled is False
    assert config.transitions.transition_duration == 0.35
    assert config.transitions.min_overlap_seconds == 0.12
    assert config.transitions.strong_signal_percentile == 85.0
    assert config.transitions.match_cut_similarity == 0.90


def test_load_config_transitions_custom_values_round_trip(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        transitions:
          enabled: true
          transition_duration: 0.35
          min_overlap_seconds: 0.12
          strong_signal_percentile: 85.0
          match_cut_similarity: 0.90
        """,
    )

    config = load_config(path)

    assert config.transitions.enabled is True
    assert config.transitions.transition_duration == 0.35
    assert config.transitions.min_overlap_seconds == 0.12
    assert config.transitions.strong_signal_percentile == 85.0
    assert config.transitions.match_cut_similarity == 0.90


def test_load_config_transitions_transition_duration_must_be_positive(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        transitions:
          transition_duration: 0
        """,
    )

    with pytest.raises(ConfigError, match="transitions.transition_duration"):
        load_config(path)


def test_load_config_transitions_min_overlap_seconds_must_be_positive(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        transitions:
          min_overlap_seconds: 0
        """,
    )

    with pytest.raises(ConfigError, match="transitions.min_overlap_seconds"):
        load_config(path)


def test_load_config_transitions_min_overlap_seconds_exceeding_duration_raises(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        transitions:
          transition_duration: 0.2
          min_overlap_seconds: 0.5
        """,
    )

    with pytest.raises(ConfigError, match="transitions.min_overlap_seconds"):
        load_config(path)


def test_load_config_transitions_strong_signal_percentile_out_of_range_raises(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        transitions:
          strong_signal_percentile: 100
        """,
    )

    with pytest.raises(ConfigError, match="transitions.strong_signal_percentile"):
        load_config(path)


def test_load_config_transitions_strong_signal_percentile_zero_raises(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        transitions:
          strong_signal_percentile: 0
        """,
    )

    with pytest.raises(ConfigError, match="transitions.strong_signal_percentile"):
        load_config(path)


def test_load_config_transitions_match_cut_similarity_out_of_range_raises(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        transitions:
          match_cut_similarity: 1.5
        """,
    )

    with pytest.raises(ConfigError, match="transitions.match_cut_similarity"):
        load_config(path)


def test_load_config_transitions_match_cut_similarity_negative_raises(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        transitions:
          match_cut_similarity: -0.1
        """,
    )

    with pytest.raises(ConfigError, match="transitions.match_cut_similarity"):
        load_config(path)


def test_default_config_tiktok_and_instagram_enabled_is_false():
    from scripts.config import Config

    config = Config(input_dir="F:/in", output_dir="F:/out")

    assert config.publish.tiktok_enabled is False
    assert config.publish.instagram_enabled is False


def test_load_config_tiktok_instagram_defaults_when_section_missing(tmp_path):
    path = write_config(tmp_path, 'input_dir: "F:/in"\noutput_dir: "F:/out"\n')

    config = load_config(path)

    assert config.publish.tiktok_enabled is False
    assert config.publish.instagram_enabled is False
    assert config.publish.tiktok_queue_path == "work/_publish/tiktok_queue.json"
    assert config.publish.instagram_queue_path == "work/_publish/instagram_queue.json"
    assert config.publish.tiktok_client_key_path == "tiktok_client_key.json"
    assert config.publish.tiktok_token_path == "tiktok_token.json"
    assert config.publish.instagram_client_secret_path == "instagram_client_secret.json"
    assert config.publish.instagram_token_path == "instagram_token.json"


def test_load_config_tiktok_instagram_custom_values_round_trip(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        publish:
          tiktok_enabled: true
          instagram_enabled: true
          tiktok_queue_path: "work/_publish/custom_tiktok.json"
        """,
    )

    config = load_config(path)

    assert config.publish.tiktok_enabled is True
    assert config.publish.instagram_enabled is True
    assert config.publish.tiktok_queue_path == "work/_publish/custom_tiktok.json"
    # Unspecified fields keep their defaults
    assert config.publish.instagram_queue_path == "work/_publish/instagram_queue.json"
    assert config.publish.tiktok_client_key_path == "tiktok_client_key.json"
    assert config.publish.tiktok_token_path == "tiktok_token.json"
    assert config.publish.instagram_client_secret_path == "instagram_client_secret.json"
    assert config.publish.instagram_token_path == "instagram_token.json"


def test_load_config_profanity_defaults_when_section_missing(tmp_path):
    path = write_config(tmp_path, 'input_dir: "F:/in"\noutput_dir: "F:/out"\n')

    config = load_config(path)

    assert config.profanity.enabled is False
    assert config.profanity.wordlist_path == "data/profanity_wordlist.yaml"
    assert config.profanity.pad_seconds == 0.08
    assert config.profanity.max_masked_spans_per_clip == 40
    assert config.profanity.duck_volume == 0.12
    assert config.profanity.garble_freq == 1800.0
    assert config.profanity.garble_width_octaves == 4.0
    assert config.profanity.warble_freq == 18.0
    assert config.profanity.warble_depth == 0.7
    assert config.profanity.mask_mode == "garble"
    assert config.profanity.mask_sound_path == ""
    assert config.profanity.mask_onset_seconds == 0.0


def test_load_config_profanity_custom_values_round_trip(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        profanity:
          enabled: true
          wordlist_path: "data/custom_wordlist.yaml"
          pad_seconds: 0.1
          max_masked_spans_per_clip: 10
          duck_volume: 0.2
          garble_freq: 1500.0
          garble_width_octaves: 3.0
          warble_freq: 20.0
          warble_depth: 0.5
          mask_mode: "sound"
          mask_sound_path: "data/censor.wav"
          mask_onset_seconds: 0.12
        """,
    )

    config = load_config(path)

    assert config.profanity.enabled is True
    assert config.profanity.wordlist_path == "data/custom_wordlist.yaml"
    assert config.profanity.pad_seconds == 0.1
    assert config.profanity.max_masked_spans_per_clip == 10
    assert config.profanity.duck_volume == 0.2
    assert config.profanity.garble_freq == 1500.0
    assert config.profanity.garble_width_octaves == 3.0
    assert config.profanity.warble_freq == 20.0
    assert config.profanity.warble_depth == 0.5
    assert config.profanity.mask_mode == "sound"
    assert config.profanity.mask_sound_path == "data/censor.wav"
    assert config.profanity.mask_onset_seconds == 0.12


def test_load_config_profanity_pad_seconds_negative_raises(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        profanity:
          pad_seconds: -0.01
        """,
    )

    with pytest.raises(ConfigError, match="profanity.pad_seconds"):
        load_config(path)


def test_load_config_profanity_max_masked_spans_per_clip_zero_raises(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        profanity:
          max_masked_spans_per_clip: 0
        """,
    )

    with pytest.raises(ConfigError, match="profanity.max_masked_spans_per_clip"):
        load_config(path)


def test_load_config_profanity_duck_volume_zero_raises(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        profanity:
          duck_volume: 0
        """,
    )

    with pytest.raises(ConfigError, match="profanity.duck_volume"):
        load_config(path)


def test_load_config_profanity_duck_volume_one_raises(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        profanity:
          duck_volume: 1
        """,
    )

    with pytest.raises(ConfigError, match="profanity.duck_volume"):
        load_config(path)


def test_load_config_profanity_garble_freq_zero_raises(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        profanity:
          garble_freq: 0
        """,
    )

    with pytest.raises(ConfigError, match="profanity.garble_freq"):
        load_config(path)


def test_load_config_profanity_garble_width_octaves_zero_raises(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        profanity:
          garble_width_octaves: 0
        """,
    )

    with pytest.raises(ConfigError, match="profanity.garble_width_octaves"):
        load_config(path)


def test_load_config_profanity_warble_freq_zero_raises(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        profanity:
          warble_freq: 0
        """,
    )

    with pytest.raises(ConfigError, match="profanity.warble_freq"):
        load_config(path)


def test_load_config_profanity_warble_depth_zero_raises(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        profanity:
          warble_depth: 0
        """,
    )

    with pytest.raises(ConfigError, match="profanity.warble_depth"):
        load_config(path)


def test_load_config_profanity_warble_depth_above_one_raises(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        profanity:
          warble_depth: 1.1
        """,
    )

    with pytest.raises(ConfigError, match="profanity.warble_depth"):
        load_config(path)


def test_load_config_profanity_mask_mode_invalid_raises(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        profanity:
          mask_mode: "explode"
        """,
    )

    with pytest.raises(ConfigError, match="profanity.mask_mode"):
        load_config(path)


def test_load_config_profanity_mask_onset_seconds_negative_raises(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        profanity:
          mask_onset_seconds: -0.01
        """,
    )

    with pytest.raises(ConfigError, match="profanity.mask_onset_seconds"):
        load_config(path)


def test_load_config_profanity_mask_mode_sound_requires_sound_path(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        profanity:
          mask_mode: "sound"
          mask_sound_path: ""
        """,
    )

    with pytest.raises(ConfigError, match="profanity.mask_sound_path"):
        load_config(path)


def test_load_config_profanity_mask_mode_sound_with_whitespace_path_raises(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        profanity:
          mask_mode: "sound"
          mask_sound_path: "   "
        """,
    )

    with pytest.raises(ConfigError, match="profanity.mask_sound_path"):
        load_config(path)


def test_load_config_profanity_mask_mode_sound_with_path_loads_ok(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        profanity:
          mask_mode: "sound"
          mask_sound_path: "data/censor.wav"
        """,
    )

    config = load_config(path)

    assert config.profanity.mask_mode == "sound"
    assert config.profanity.mask_sound_path == "data/censor.wav"


def test_load_config_transitions_unknown_field_raises(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        transitions:
          not_a_real_field: 1
        """,
    )

    with pytest.raises(ConfigError, match="transitions"):
        load_config(path)


def test_load_config_hook_banner_defaults_when_section_missing(tmp_path):
    path = write_config(tmp_path, 'input_dir: "F:/in"\noutput_dir: "F:/out"\n')

    config = load_config(path)

    assert config.hook_banner.enabled is False
    assert config.hook_banner.mode == "persistent"
    assert config.hook_banner.cta_text == ""
    assert config.hook_banner.duration_seconds == 3.0
    assert config.hook_banner.fade_seconds == 0.4
    assert config.hook_banner.font == "Arial Black"
    assert config.hook_banner.size == 58
    assert config.hook_banner.color == "white"
    assert config.hook_banner.cta_font == "Arial Bold"
    assert config.hook_banner.cta_size == 36
    assert config.hook_banner.cta_color == "#ffe98a"
    assert config.hook_banner.box_color == "black"
    assert config.hook_banner.box_opacity == 0.55
    assert config.hook_banner.position == "top"


def test_load_config_hook_banner_custom_values_round_trip(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        hook_banner:
          enabled: true
          mode: "hook"
          cta_text: "youtube.com/@nick"
          duration_seconds: 2.5
          fade_seconds: 0.3
          size: 48
          position: "bottom"
        """,
    )

    config = load_config(path)

    assert config.hook_banner.enabled is True
    assert config.hook_banner.mode == "hook"
    assert config.hook_banner.cta_text == "youtube.com/@nick"
    assert config.hook_banner.duration_seconds == 2.5
    assert config.hook_banner.fade_seconds == 0.3
    assert config.hook_banner.size == 48
    assert config.hook_banner.position == "bottom"


def test_load_config_rejects_bad_hook_banner_mode(tmp_path):
    path = write_config(
        tmp_path,
        'input_dir: "F:/in"\noutput_dir: "F:/out"\nhook_banner:\n  mode: "forever"\n',
    )

    with pytest.raises(ConfigError, match="hook_banner.mode"):
        load_config(path)


def test_load_config_rejects_bad_hook_banner_position(tmp_path):
    path = write_config(
        tmp_path,
        'input_dir: "F:/in"\noutput_dir: "F:/out"\nhook_banner:\n  position: "center"\n',
    )

    with pytest.raises(ConfigError, match="hook_banner.position"):
        load_config(path)


def test_load_config_rejects_hook_banner_fade_at_or_above_duration(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        hook_banner:
          mode: "hook"
          duration_seconds: 2.0
          fade_seconds: 2.0
        """,
    )

    with pytest.raises(ConfigError, match="hook_banner.fade_seconds"):
        load_config(path)


def test_load_config_rejects_banner_subtitles_position_collision(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        subtitles:
          enabled: true
          position: "top"
        hook_banner:
          enabled: true
          position: "top"
        """,
    )

    with pytest.raises(ConfigError, match="would overlap burned-in"):
        load_config(path)


def test_load_config_banner_collision_ok_when_either_disabled(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        subtitles:
          enabled: true
          position: "top"
        hook_banner:
          enabled: false
          position: "top"
        """,
    )

    config = load_config(path)

    assert config.hook_banner.enabled is False


def test_load_config_emphasis_defaults_when_section_missing(tmp_path):
    path = write_config(tmp_path, 'input_dir: "F:/in"\noutput_dir: "F:/out"\n')

    config = load_config(path)

    assert config.emphasis.enabled is False
    assert config.emphasis.max_moves == 2
    assert config.emphasis.zoom_amount == 1.12
    assert config.emphasis.ramp_seconds == 0.18
    assert config.emphasis.min_hold_seconds == 0.25
    assert config.emphasis.face_enabled is False


def test_load_config_emphasis_custom_values_round_trip(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        emphasis:
          enabled: true
          max_moves: 3
          zoom_amount: 1.2
          ramp_seconds: 0.25
          min_hold_seconds: 0.3
          face_enabled: true
        """,
    )

    config = load_config(path)

    assert config.emphasis.enabled is True
    assert config.emphasis.max_moves == 3
    assert config.emphasis.zoom_amount == 1.2
    assert config.emphasis.face_enabled is True


def test_load_config_rejects_bad_emphasis_values(tmp_path):
    for section, marker in [
        ("max_moves: -1", "emphasis.max_moves"),
        ("zoom_amount: 1.0", "emphasis.zoom_amount"),
        ("ramp_seconds: 0", "emphasis.ramp_seconds"),
        ("min_hold_seconds: -0.1", "emphasis.min_hold_seconds"),
    ]:
        path = write_config(
            tmp_path,
            f'input_dir: "F:/in"\noutput_dir: "F:/out"\nemphasis:\n  {section}\n',
        )
        with pytest.raises(ConfigError, match=marker):
            load_config(path)


def test_load_config_top_moments_defaults_and_custom(tmp_path):
    path = write_config(tmp_path, 'input_dir: "F:/in"\noutput_dir: "F:/out"\n')
    config = load_config(path)
    assert config.top_moments.rate_per_hour == 3.0
    assert config.top_moments.minimum == 1

    path = write_config(
        tmp_path,
        'input_dir: "F:/in"\noutput_dir: "F:/out"\ntop_moments:\n  rate_per_hour: 5.0\n  minimum: 2\n',
    )
    config = load_config(path)
    assert config.top_moments.rate_per_hour == 5.0
    assert config.top_moments.minimum == 2


def test_load_config_rejects_bad_top_moments_values(tmp_path):
    for section, marker in [
        ("rate_per_hour: 0", "top_moments.rate_per_hour"),
        ("minimum: 0", "top_moments.minimum"),
    ]:
        path = write_config(
            tmp_path,
            f'input_dir: "F:/in"\noutput_dir: "F:/out"\ntop_moments:\n  {section}\n',
        )
        with pytest.raises(ConfigError, match=marker):
            load_config(path)


def test_load_config_phase10_defaults_when_sections_missing(tmp_path):
    path = write_config(tmp_path, 'input_dir: "F:/in"\noutput_dir: "F:/out"\n')

    config = load_config(path)

    assert config.social_overlay.enabled is False
    assert config.social_overlay.platforms == ["twitch"]
    assert config.social_overlay.box_color == "#9146ff"
    assert config.social_overlay.y is None
    assert config.outro_card.enabled is False
    assert config.outro_card.pattern_count == 5
    assert config.outro_card.fps == 30


def test_load_config_phase10_custom_values_round_trip(tmp_path):
    path = write_config(
        tmp_path,
        """
        input_dir: "F:/in"
        output_dir: "F:/out"
        social_overlay:
          enabled: true
          platforms: ["twitch", "kick"]
          icon_paths:
            twitch: "assets/overlays/twitch_glyph.png"
          labels:
            twitch: "twitch.tv/zhorikp"
            kick: "kick.com/zhorikp"
          duration_seconds: 4.0
        outro_card:
          enabled: true
          nick: "ZhorikP"
          cta_text: "twitch.tv/zhorikp"
          pattern_count: 3
        """,
    )

    config = load_config(path)

    assert config.social_overlay.enabled is True
    assert config.social_overlay.platforms == ["twitch", "kick"]
    assert config.social_overlay.labels["kick"] == "kick.com/zhorikp"
    assert config.social_overlay.duration_seconds == 4.0
    assert config.outro_card.enabled is True
    assert config.outro_card.nick == "ZhorikP"
    assert config.outro_card.pattern_count == 3


def test_load_config_rejects_bad_phase10_values(tmp_path):
    for section, marker in [
        ("social_overlay:\n  duration_seconds: 0", "social_overlay.duration_seconds"),
        ("social_overlay:\n  slide_seconds: 0", "social_overlay.slide_seconds"),
        ("social_overlay:\n  slide_seconds: 2.0\n  duration_seconds: 3.0", "slide_seconds\\*2"),
        ("social_overlay:\n  box_opacity: 1.5", "social_overlay.box_opacity"),
        ("outro_card:\n  duration_seconds: 0", "outro_card.duration_seconds"),
        ("outro_card:\n  pattern_count: 0", "outro_card.pattern_count"),
        ("outro_card:\n  fps: 0", "outro_card.fps"),
    ]:
        path = write_config(
            tmp_path,
            f'input_dir: "F:/in"\noutput_dir: "F:/out"\n{section}\n',
        )
        with pytest.raises(ConfigError, match=marker):
            load_config(path)
