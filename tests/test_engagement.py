"""The swipe-away ratio: joining it to clips, and reading it by group."""

from scripts.engagement import MIN_VIEWS, group_medians, ratio_rows, render


def entry(video_id, **fields):
    base = {"video_id": video_id, "clip_id": video_id, "tags": ["war thunder"]}
    base.update(fields)
    return base


def test_ratio_rows_computes_the_share_that_kept_watching():
    rows = ratio_rows({"a": {"views": 1000, "engaged": 430}}, [entry("a")])
    assert rows[0]["ratio"] == 43.0


def test_ratio_rows_drops_clips_too_small_to_read():
    # A handful of views puts the ratio anywhere between 0 and 100%; including
    # those would make the group medians noise.
    engagement = {"a": {"views": MIN_VIEWS - 1, "engaged": 1}}
    assert ratio_rows(engagement, [entry("a")]) == []


def test_ratio_rows_ignores_videos_missing_from_the_queue():
    assert ratio_rows({"ghost": {"views": 900, "engaged": 400}}, []) == []


def test_group_medians_orders_by_median_and_skips_small_groups():
    rows = [
        {"ratio": 50.0, "opening": "standalone"},
        {"ratio": 60.0, "opening": "standalone"},
        {"ratio": 20.0, "opening": "context"},
    ]
    assert group_medians(rows, "opening", min_group=2) == [("standalone", 2, 55.0)]


def test_group_medians_skips_unlabelled_clips():
    rows = [{"ratio": 40.0, "opening": None}, {"ratio": 50.0, "opening": None}]
    assert group_medians(rows, "opening", min_group=1) == []


def test_render_reports_the_channel_median():
    rows = [{"ratio": 40.0, "opening": None, "game": None, "moment_tag": None},
            {"ratio": 50.0, "opening": None, "game": None, "moment_tag": None}]
    assert "45.0%" in render(rows)


def test_render_survives_an_empty_channel():
    assert "0" in render([])
