import pytest

from scripts.render import RenderError, clamp_clip_bounds, compute_crop_filter


def test_clamp_clip_bounds_passthrough_when_within_range():
    assert clamp_clip_bounds(10.0, 40.0, video_duration=100.0) == (10.0, 40.0)


def test_clamp_clip_bounds_clamps_end_to_duration():
    assert clamp_clip_bounds(90.0, 120.0, video_duration=100.0) == (90.0, 100.0)


def test_clamp_clip_bounds_clamps_negative_start_to_zero():
    assert clamp_clip_bounds(-5.0, 10.0, video_duration=100.0) == (0.0, 10.0)


def test_clamp_clip_bounds_raises_when_start_after_clamped_end():
    with pytest.raises(RenderError, match="clip bounds invalid"):
        clamp_clip_bounds(150.0, 200.0, video_duration=100.0)


def test_clamp_clip_bounds_raises_on_non_positive_duration():
    with pytest.raises(RenderError, match="video_duration"):
        clamp_clip_bounds(0.0, 10.0, video_duration=0.0)


def test_compute_crop_filter_zoom():
    result = compute_crop_filter("zoom", src_width=1920, src_height=1080)
    assert result == "crop=608:1080:656:0,scale=1080:1920"


def test_compute_crop_filter_pad():
    result = compute_crop_filter("pad", src_width=1920, src_height=1080)
    assert result == "scale=1080:608,pad=1080:1920:0:394:black"


def test_compute_crop_filter_original_16_9():
    result = compute_crop_filter("original-16:9", src_width=1920, src_height=1080)
    assert result == "scale=1080:608,pad=1080:1920:0:656:black"


def test_compute_crop_filter_rejects_unresolved_auto():
    with pytest.raises(RenderError, match="resolved value"):
        compute_crop_filter("auto", src_width=1920, src_height=1080)
