import pytest

from scripts.cold_open import (
    VALID_COLD_OPEN_TRANSITIONS,
    build_cold_open_command,
    cold_open_window,
)
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


def test_build_cold_open_command_seeks_the_teaser_on_a_second_decode():
    # Not a split of the first input: the teaser sits at the end of the clip, so
    # that branch is read to EOF before it yields anything and the main branch's
    # frames pile up in the split's buffer until ffmpeg abandons them. Five
    # published clips came out as a 1.7-second teaser with silence after it.
    command = build_cold_open_command("base.mp4", "out.mp4", at=8.2, duration=2.5, transition="cut")
    assert command.count("base.mp4") == 2
    assert command[command.index("-ss") + 1] == "8.2"
    assert command[command.index("-t") + 1] == "2.5"
    graph = _command_str(command)
    assert "split" not in graph
    assert "[1:v]setpts=PTS-STARTPTS[teaserv]" in graph
    assert "[1:a]asetpts=PTS-STARTPTS[teasera]" in graph


def test_build_cold_open_command_joins_the_teaser_onto_the_whole_clip():
    command = build_cold_open_command("base.mp4", "out.mp4", at=8.2, duration=2.5,
                                      transition="whip_pan", transition_duration=0.25)
    graph = _command_str(command)
    assert "[teaserv][0:v]xfade=" in graph
    assert "[teasera][0:a]acrossfade=d=0.25[aout]" in graph


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


def _words(*pairs):
    return [{"word": w, "start": s, "end": e} for w, s, e in pairs]


def test_cold_open_window_covers_the_whole_punch_line_not_a_flat_two_seconds():
    # The 2026-08-10 failure: a fixed 2s window teased "меня зовут Джорно
    # Джованна" and cut "и у меня есть мечта" - the punch itself.
    words = _words(
        ("меня", 5.0, 5.3), ("зовут", 5.3, 5.7), ("Джорно", 5.7, 6.2),
        ("Джованна", 6.2, 6.9), ("и", 7.0, 7.1), ("у", 7.1, 7.2),
        ("меня", 7.2, 7.5), ("есть", 7.5, 7.8), ("мечта", 7.8, 8.4),
    )

    window = cold_open_window(words, 5.0, 20.0)

    assert window["at"] == 5.0
    assert window["at"] + window["duration"] == 8.4


def test_cold_open_window_caps_a_run_on_phrase_but_keeps_the_punch_at_its_front():
    # Group voice chat runs sentences together, so the detected phrase can be
    # far longer than the joke. Capping from the end used to push the punch out
    # of the teaser ("нас трахают" -> "мы сейчас отбиваемся").
    words = _words(*[(f"w{i}", float(i), i + 0.9) for i in range(12)])

    window = cold_open_window(words, 0.0, 30.0)

    # The cap now lands on the last word that fully fits (w3 ends at 3.9)
    # instead of slicing at a flat 4.0s wherever that falls inside a word.
    assert window == {"at": 0.0, "duration": 3.9}


def test_cold_open_window_snaps_a_mid_word_punch_back_to_the_word_start():
    # punch_at comes from a transcript SEGMENT start, which lands a few
    # hundredths inside the first word often enough that 11 of 16 teasers in
    # the 2026-08-12 batch opened on a half-spoken word ("Я как дал" -> "как дал").
    words = _words(("Я", 23.10, 23.30), ("как", 23.30, 23.60), ("дал", 23.60, 24.10))

    window = cold_open_window(words, 23.15, 30.0)

    assert window["at"] == 23.10


def test_cold_open_window_slides_back_only_when_the_punch_is_near_the_end():
    words = _words(("панч", 18.6, 19.0))

    window = cold_open_window(words, 18.6, 19.1)

    assert window["at"] < 18.6
    assert round(window["at"] + window["duration"], 3) <= 19.1


def test_cold_open_window_stops_at_a_pause_between_phrases():
    words = _words(("панч", 2.0, 2.6), ("тут", 2.6, 3.0), ("другое", 5.0, 5.6))

    window = cold_open_window(words, 2.0, 20.0)

    assert window["at"] + window["duration"] <= 5.0


def test_cold_open_window_never_overshoots_the_clip():
    words = _words(("панч", 17.0, 19.2))

    window = cold_open_window(words, 17.0, 19.1)

    assert window["at"] + window["duration"] <= 19.1


def test_cold_open_window_returns_none_when_the_punch_sits_past_the_clip():
    assert cold_open_window(_words(("панч", 1.0, 1.5)), 25.0, 20.0) is None
