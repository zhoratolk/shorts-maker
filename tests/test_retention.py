import json

from scripts.retention import (
    analyze_curve,
    build_records,
    fetch_retention_curve,
    render_retention_markdown,
    summarize_retention,
    write_retention_insights,
    _load_tag_map,
)


def _flat_curve(value: float, points: int = 21) -> list[tuple[float, float]]:
    return [(round(i / (points - 1), 4), value) for i in range(points)]


def _cliff_curve() -> list[tuple[float, float]]:
    # Full at the start, a sharp 30% cliff at 40% elapsed, low tail.
    return [
        (0.0, 1.0),
        (0.1, 0.98),
        (0.2, 0.95),
        (0.3, 0.9),
        (0.4, 0.6),  # cliff: 0.9 -> 0.6
        (0.5, 0.55),
        (0.7, 0.5),
        (1.0, 0.45),
    ]


# --- analyze_curve ---------------------------------------------------------

def test_analyze_curve_empty_is_unknown():
    result = analyze_curve([])
    assert result["length_signal"] == "unknown"
    assert result["intro_retention"] is None
    assert result["cliffs"] == []


def test_analyze_curve_single_point_is_unknown():
    assert analyze_curve([(0.0, 1.0)])["length_signal"] == "unknown"


def test_analyze_curve_detects_biggest_drop_and_cliff():
    result = analyze_curve(_cliff_curve())
    assert result["biggest_drop"]["at"] == 0.4
    assert abs(result["biggest_drop"]["delta"] - 0.3) < 1e-9
    assert 0.4 in result["cliffs"]


def test_analyze_curve_length_signal_could_be_longer_when_end_high():
    # Flat at 0.8 -> end retention 0.8 >= 0.7 -> could_be_longer.
    assert analyze_curve(_flat_curve(0.8))["length_signal"] == "could_be_longer"


def test_analyze_curve_length_signal_too_long_when_end_low():
    curve = [(0.0, 1.0), (0.5, 0.6), (1.0, 0.2)]  # end 0.2 <= 0.35
    assert analyze_curve(curve)["length_signal"] == "too_long"


def test_analyze_curve_length_signal_ok_in_middle_band():
    curve = [(0.0, 1.0), (0.5, 0.7), (1.0, 0.5)]  # end 0.5 in (0.35, 0.7)
    assert analyze_curve(curve)["length_signal"] == "ok"


def test_analyze_curve_intro_retention_reads_near_start():
    curve = [(0.0, 1.0), (0.05, 0.9), (0.5, 0.7), (1.0, 0.5)]
    assert analyze_curve(curve)["intro_retention"] == 0.9


def test_analyze_curve_no_drop_leaves_biggest_drop_none():
    # Monotonically rising (never drops) -> no positive delta -> None.
    curve = [(0.0, 0.5), (0.5, 0.6), (1.0, 0.7)]
    assert analyze_curve(curve)["biggest_drop"] is None


# --- summarize_retention ---------------------------------------------------

def _record(video_id, curve, tag=None, title=None):
    return {"video_id": video_id, "title": title, "tag": tag, "analysis": analyze_curve(curve)}


def test_summarize_skips_unknown_curves():
    records = [_record("a", []), _record("b", [])]
    summary = summarize_retention(records)
    assert summary["clips_analyzed"] == 0
    assert summary["mean_intro_retention"] is None


def test_summarize_counts_length_signals_and_means():
    records = [
        _record("a", _flat_curve(0.8)),  # could_be_longer
        _record("b", [(0.0, 1.0), (0.5, 0.6), (1.0, 0.2)]),  # too_long
    ]
    summary = summarize_retention(records)
    assert summary["clips_analyzed"] == 2
    assert summary["length_signal_counts"]["could_be_longer"] == 1
    assert summary["length_signal_counts"]["too_long"] == 1
    assert summary["mean_intro_retention"] is not None


def test_summarize_common_cliff_zone_bucketed_in_fifths():
    # Cliff at 0.4 elapsed -> falls in the 40-60% bucket.
    summary = summarize_retention([_record("a", _cliff_curve())])
    assert summary["common_cliff_zone"] == "40-60%"


def test_summarize_by_tag_present_only_when_tagged_and_ranks():
    records = [
        _record("a", _flat_curve(0.9), tag="clutch"),
        _record("b", _flat_curve(0.3), tag="banter"),
    ]
    summary = summarize_retention(records)
    assert set(summary["by_tag"]) == {"clutch", "banter"}
    assert summary["by_tag"]["clutch"]["mean_average_watch"] > summary["by_tag"]["banter"]["mean_average_watch"]


def test_summarize_by_tag_empty_when_no_tags():
    assert summarize_retention([_record("a", _flat_curve(0.8))])["by_tag"] == {}


# --- render ---------------------------------------------------------------

def test_render_markdown_empty_message():
    md = render_retention_markdown([], summarize_retention([]))
    assert "No clips had retention data" in md


def test_render_markdown_lists_clips_and_tags():
    records = [
        _record("vid1", _flat_curve(0.9), tag="clutch", title="Clutch win"),
        _record("vid2", _cliff_curve(), tag="banter", title="Funny bit"),
    ]
    md = render_retention_markdown(records, summarize_retention(records))
    assert "# Retention analysis" in md
    assert "Clutch win" in md
    assert "By moment tag" in md
    assert "clutch" in md


def test_render_markdown_sorts_worst_hook_first():
    weak = _record("weak", [(0.0, 1.0), (0.05, 0.3), (1.0, 0.2)], title="WEAK")
    strong = _record("strong", _flat_curve(0.95), title="STRONG")
    md = render_retention_markdown([strong, weak], summarize_retention([strong, weak]))
    assert md.index("WEAK") < md.index("STRONG")


# --- persistence + join ----------------------------------------------------

def test_write_retention_insights_round_trips(tmp_path):
    summary = summarize_retention([_record("a", _flat_curve(0.8))])
    path = tmp_path / "work" / "insights.json"
    write_retention_insights(summary, str(path))
    assert json.loads(path.read_text(encoding="utf-8"))["clips_analyzed"] == 1


def test_load_tag_map_missing_file_is_empty(tmp_path):
    assert _load_tag_map(str(tmp_path / "nope.json")) == {}


def test_load_tag_map_reads_video_tag_and_duration(tmp_path):
    queue = {
        "entries": [
            {"video_id": "vid1", "moment_tag": "clutch", "source_duration": 42.0},
            {"video_id": None, "moment_tag": "ignored"},  # not uploaded -> skipped
        ]
    }
    path = tmp_path / "queue.json"
    path.write_text(json.dumps(queue), encoding="utf-8")
    tag_map = _load_tag_map(str(path))
    assert tag_map == {"vid1": {"tag": "clutch", "duration": 42.0}}


# --- fetch (fake service) --------------------------------------------------

class _FakeReports:
    def __init__(self, rows):
        self._rows = rows

    def query(self, **kwargs):
        self._kwargs = kwargs
        return self

    def execute(self):
        return {"rows": self._rows}


class _FakeAnalytics:
    def __init__(self, rows):
        self._reports = _FakeReports(rows)

    def reports(self):
        return self._reports


def test_fetch_retention_curve_sorts_and_floats():
    service = _FakeAnalytics([[0.5, 0.6], [0.0, 1.0], [1.0, 0.4]])
    curve = fetch_retention_curve(service, "chan", "vid", "2024-01-01", "2024-02-01")
    assert curve == [(0.0, 1.0), (0.5, 0.6), (1.0, 0.4)]


def test_fetch_retention_curve_empty_rows():
    service = _FakeAnalytics([])
    assert fetch_retention_curve(service, "chan", "vid", "2024-01-01", "2024-02-01") == []


def test_build_records_attaches_tag_and_analysis():
    service = _FakeAnalytics([[0.0, 1.0], [0.5, 0.8], [1.0, 0.75]])
    videos = [{"video_id": "vid1", "title": "T"}]
    tag_map = {"vid1": {"tag": "clutch", "duration": 30.0}}
    records = build_records(service, "chan", videos, "2024-01-01", "2024-02-01", tag_map)
    assert records[0]["tag"] == "clutch"
    assert records[0]["analysis"]["length_signal"] == "could_be_longer"
