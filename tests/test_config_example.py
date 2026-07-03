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
    assert config.metadata.enabled is True
    assert config.metadata.platforms == ["youtube", "tiktok", "instagram"]
    assert config.content.allow_mature is True
