import pytest

from scripts.loop import VALID_LOOP_TRANSITIONS, build_loop_outro_command
from scripts.render_common import RenderError


def _command_str(command: list[str]) -> str:
    idx = command.index("-filter_complex")
    return command[idx + 1]


def test_valid_transitions_is_cut_and_crossfade_only():
    # Deliberately narrower than cold_open's menu (see module docstring) -
    # whip_pan/mask_wipe don't read as a smooth loop seam.
    assert VALID_LOOP_TRANSITIONS == {"cut", "crossfade"}


def test_build_loop_outro_command_xfade_path_uses_xfade_and_acrossfade():
    command = build_loop_outro_command(
        "base.mp4", "out.mp4", base_duration=30.0,
        transition="crossfade", transition_duration=0.4,
    )
    graph = _command_str(command)
    assert "xfade=transition=fade:duration=0.4:offset=29.6" in graph
    assert "acrossfade=d=0.4" in graph
    assert "concat" not in graph


def test_build_loop_outro_command_cut_uses_plain_concat_no_xfade():
    command = build_loop_outro_command("base.mp4", "out.mp4", base_duration=30.0, transition="cut")
    graph = _command_str(command)
    assert "xfade" not in graph
    assert "acrossfade" not in graph
    assert "concat=n=2:v=1:a=1[vout][aout]" in graph


def test_build_loop_outro_command_replay_trim_matches_transition_duration():
    command = build_loop_outro_command(
        "base.mp4", "out.mp4", base_duration=30.0, transition="cut", transition_duration=0.6
    )
    graph = _command_str(command)
    assert "trim=start=0:end=0.6" in graph
    assert "atrim=start=0:end=0.6" in graph


def test_build_loop_outro_command_transition_duration_clamped_to_base_duration():
    # transition_duration (5.0) longer than the clip itself (1.0) must not
    # produce a negative xfade offset - clamp to base_duration instead of
    # raising.
    command = build_loop_outro_command(
        "base.mp4", "out.mp4", base_duration=1.0,
        transition="crossfade", transition_duration=5.0,
    )
    graph = _command_str(command)
    assert "xfade=transition=fade:duration=1.0:offset=0.0" in graph


def test_build_loop_outro_command_maps_video_and_audio_outputs():
    command = build_loop_outro_command("base.mp4", "out.mp4", base_duration=10.0, transition="cut")
    assert "-map" in command
    assert "[vout]" in command
    assert "[aout]" in command
    assert command[command.index("-i") + 1] == "base.mp4"
    assert command[-1] == "out.mp4"


def test_build_loop_outro_command_rejects_invalid_transition():
    with pytest.raises(RenderError, match="loop transition"):
        build_loop_outro_command("base.mp4", "out.mp4", base_duration=10.0, transition="whip_pan")


def test_build_loop_outro_command_rejects_non_positive_base_duration():
    with pytest.raises(RenderError, match="base_duration must be > 0"):
        build_loop_outro_command("base.mp4", "out.mp4", base_duration=0.0)


def test_build_loop_outro_command_rejects_non_positive_transition_duration():
    with pytest.raises(RenderError, match="transition_duration must be > 0"):
        build_loop_outro_command("base.mp4", "out.mp4", base_duration=10.0, transition_duration=0.0)
