import pytest

from scripts.cold_open import VALID_COLD_OPEN_TRANSITIONS, build_cold_open_command
from scripts.render_common import RenderError


def _command_str(command: list[str]) -> str:
    idx = command.index("-filter_complex")
    return command[idx + 1]


def test_valid_transitions_excludes_glitch_and_match_cut():
    # Deliberately narrower than render.py's boundary-transition enum (see
    # module docstring) - not a drift-guarded mirror of it.
    assert VALID_COLD_OPEN_TRANSITIONS == {"cut", "crossfade", "whip_pan", "mask_wipe"}


def test_build_cold_open_command_xfade_path_uses_xfade_and_acrossfade():
    command = build_cold_open_command(
        "base.mp4", "out.mp4", at=8.2, duration=2.5,
        transition="whip_pan", transition_duration=0.25,
    )
    graph = _command_str(command)
    assert "xfade=transition=hblur:duration=0.25:offset=2.25" in graph
    assert "acrossfade=d=0.25" in graph
    assert "concat" not in graph


def test_build_cold_open_command_cut_uses_plain_concat_no_xfade():
    command = build_cold_open_command("base.mp4", "out.mp4", at=8.2, duration=2.5, transition="cut")
    graph = _command_str(command)
    assert "xfade" not in graph
    assert "acrossfade" not in graph
    assert "concat=n=2:v=1:a=1[vout][aout]" in graph


def test_build_cold_open_command_teaser_trim_matches_at_and_duration():
    command = build_cold_open_command("base.mp4", "out.mp4", at=8.2, duration=2.5, transition="cut")
    graph = _command_str(command)
    assert "trim=start=8.2:end=10.7" in graph
    assert "atrim=start=8.2:end=10.7" in graph


def test_build_cold_open_command_transition_duration_clamped_to_teaser_duration():
    # transition_duration (5.0) longer than the teaser itself (1.0) must not
    # produce a negative xfade offset - clamp to duration instead of raising.
    command = build_cold_open_command(
        "base.mp4", "out.mp4", at=0.0, duration=1.0,
        transition="crossfade", transition_duration=5.0,
    )
    graph = _command_str(command)
    assert "xfade=transition=fade:duration=1.0:offset=0.0" in graph


def test_build_cold_open_command_maps_video_and_audio_outputs():
    command = build_cold_open_command("base.mp4", "out.mp4", at=1.0, duration=1.0, transition="cut")
    assert "-map" in command
    assert "[vout]" in command
    assert "[aout]" in command
    assert command[command.index("-i") + 1] == "base.mp4"
    assert command[-1] == "out.mp4"


def test_build_cold_open_command_rejects_invalid_transition():
    with pytest.raises(RenderError, match="cold-open transition"):
        build_cold_open_command("base.mp4", "out.mp4", at=1.0, duration=1.0, transition="glitch")


def test_build_cold_open_command_rejects_negative_at():
    with pytest.raises(RenderError, match="at must be >= 0"):
        build_cold_open_command("base.mp4", "out.mp4", at=-1.0, duration=1.0)


def test_build_cold_open_command_rejects_non_positive_duration():
    with pytest.raises(RenderError, match="duration must be > 0"):
        build_cold_open_command("base.mp4", "out.mp4", at=0.0, duration=0.0)
