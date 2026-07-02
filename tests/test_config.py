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
