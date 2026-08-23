from __future__ import annotations

import pytest

from scripts.crop_focus import (
    CropFocusError,
    PAN_MIN_SPREAD_PCT,
    STATIC_MEAN_DIFF,
    aggregate_contributions,
    best_focus_pct,
    column_scores,
    frame_contributions,
    plan_focus,
    sample_frames,
)

WIDTH = 16
HEIGHT = 4


def make_frame(bright_columns, *, width=WIDTH, height=HEIGHT, level=200):
    """A flat black frame with the named columns lit up."""
    row = bytes(level if col in bright_columns else 0 for col in range(width))
    return row * height


class FakeResult:
    def __init__(self, stdout=b"", stderr=b"", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def test_sample_frames_splits_the_raw_stream_into_whole_frames():
    frames = [make_frame({1}), make_frame({2}), make_frame({3})]
    captured = {}

    def runner(command, capture_output):
        captured["command"] = command
        # a trailing partial frame must be dropped, not returned short
        return FakeResult(stdout=b"".join(frames) + b"\x00\x05")

    result = sample_frames(
        "in.mp4", 12.0, 4.0, width=WIDTH, height=HEIGHT, runner=runner
    )

    assert result == frames
    assert "-ss" in captured["command"]
    assert captured["command"][captured["command"].index("-ss") + 1] == "12.000"
    assert captured["command"][captured["command"].index("-t") + 1] == "4.000"


def test_sample_frames_returns_nothing_for_an_empty_window():
    def runner(command, capture_output):  # pragma: no cover - must not be called
        raise AssertionError("ffmpeg should not run for a zero-length window")

    assert sample_frames("in.mp4", 1.0, 0.0, runner=runner) == []


def test_sample_frames_raises_on_a_failed_ffmpeg():
    def runner(command, capture_output):
        return FakeResult(stderr=b"boom", returncode=1)

    with pytest.raises(CropFocusError, match="boom"):
        sample_frames("in.mp4", 0.0, 1.0, runner=runner)


def test_column_scores_puts_the_weight_where_the_picture_moves():
    still = make_frame({2})
    frames = [still, make_frame({2, 12}), still, make_frame({2, 12})]

    scores, mean_diff = column_scores(frames, width=WIDTH, height=HEIGHT)

    # column 2 is lit in every frame (detail only); column 12 blinks (motion)
    assert scores[12] > scores[2]
    assert mean_diff > 0


def test_column_scores_reports_a_still_picture_as_no_movement():
    frames = [make_frame({4, 5, 6})] * 5

    _, mean_diff = column_scores(frames, width=WIDTH, height=HEIGHT)

    assert mean_diff == 0.0
    assert mean_diff < STATIC_MEAN_DIFF


def test_aggregate_contributions_matches_scoring_the_frames_in_one_go():
    frames = [make_frame({1}), make_frame({9}), make_frame({1})]

    whole = column_scores(frames, width=WIDTH, height=HEIGHT)
    piecewise = aggregate_contributions(
        frame_contributions(frames, width=WIDTH, height=HEIGHT)
    )

    assert whole == piecewise


def test_best_focus_pct_hugs_the_side_the_content_sits_on():
    scores = [0.0] * 16
    scores[1] = scores[2] = 100.0

    assert best_focus_pct(scores, window=4) == 0.0

    right = [0.0] * 16
    right[14] = right[15] = 100.0
    assert best_focus_pct(right, window=4) == 100.0


def test_best_focus_pct_returns_none_on_a_frame_with_no_signal():
    assert best_focus_pct([0.0] * 16, window=4) is None
    assert best_focus_pct([], window=4) is None
    # a window as wide as the frame has nothing to choose between
    assert best_focus_pct([1.0] * 16, window=16) is None


def _plan_runner(frame_sequence):
    """Feeds plan_focus a fixed list of frames, one ffmpeg call per segment."""
    calls = {"n": 0}

    def runner(command, capture_output):
        chunk = frame_sequence[calls["n"]]
        calls["n"] += 1
        return FakeResult(stdout=b"".join(chunk))

    return runner


def test_plan_focus_returns_one_focus_for_a_composition_that_stays_put():
    left = [make_frame({1, 2}), make_frame({1, 3}), make_frame({1, 2}), make_frame({1, 3})]

    result = plan_focus(
        "in.mp4", [(0.0, 2.0)], src_width=1920, src_height=1080,
        crop_width=608, sample_width=WIDTH, sample_height=HEIGHT, runner=_plan_runner([left]),
    )

    assert "focus_keyframes" not in result
    assert result["focus_x"] < 50
    assert result["static"] is False


def test_plan_focus_emits_keyframes_when_the_action_crosses_the_frame():
    # movement starts on the left and finishes on the right
    frames = [
        make_frame({0, 1}), make_frame({1, 2}), make_frame({0, 1}), make_frame({1, 2}),
        make_frame({13, 14}), make_frame({14, 15}), make_frame({13, 14}), make_frame({14, 15}),
    ]

    result = plan_focus(
        "in.mp4", [(0.0, 4.0)], src_width=1920, src_height=1080,
        crop_width=608, sample_width=WIDTH, sample_height=HEIGHT, runner=_plan_runner([frames]),
    )

    keyframes = result["focus_keyframes"]
    assert len(keyframes) >= 2
    assert keyframes[-1][1] - keyframes[0][1] >= PAN_MIN_SPREAD_PCT
    assert keyframes == sorted(keyframes)


def test_plan_focus_flags_a_clip_whose_picture_never_moves():
    frozen = [make_frame({2, 3})] * 6

    result = plan_focus(
        "in.mp4", [(0.0, 3.0)], src_width=1920, src_height=1080,
        crop_width=608, sample_width=WIDTH, sample_height=HEIGHT, runner=_plan_runner([frozen]),
    )

    assert result["static"] is True


def test_plan_focus_puts_keyframes_on_the_spliced_timeline():
    first = [make_frame({0, 1}), make_frame({1, 2}), make_frame({0, 1}), make_frame({1, 2})]
    second = [make_frame({13, 14}), make_frame({14, 15}), make_frame({13, 14}), make_frame({14, 15})]

    result = plan_focus(
        # the source gap between 2.0 and 100.0 is cut, so no timestamp may land in it
        "in.mp4", [(0.0, 2.0), (100.0, 102.0)], src_width=1920, src_height=1080,
        crop_width=608, sample_width=WIDTH, sample_height=HEIGHT, runner=_plan_runner([first, second]),
    )

    for at, _ in result["focus_keyframes"]:
        assert 0.0 <= at <= 4.0


def test_plan_focus_fails_open_when_ffmpeg_errors():
    def runner(command, capture_output):
        return FakeResult(stderr=b"no such stream", returncode=1)

    assert plan_focus(
        "in.mp4", [(0.0, 2.0)], src_width=1920, src_height=1080,
        crop_width=608, sample_width=WIDTH, sample_height=HEIGHT, runner=runner,
    ) is None


def test_plan_focus_declines_when_the_crop_is_the_whole_frame():
    def runner(command, capture_output):  # pragma: no cover - must not be called
        raise AssertionError("nothing to measure when nothing is cropped away")

    assert plan_focus(
        "in.mp4", [(0.0, 2.0)], src_width=1080, src_height=1920,
        crop_width=1080, sample_width=WIDTH, sample_height=HEIGHT, runner=runner,
    ) is None
