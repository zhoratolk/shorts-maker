import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.jumpcuts import (
    compute_boundary_gaps,
    compute_boundary_windows,
    compute_keep_segments,
    drop_boundary,
    remap_timestamp,
    remap_words,
    total_kept_duration,
)


def test_compute_keep_segments_no_long_pauses_returns_single_segment():
    result = compute_keep_segments(10.0, 40.0, pauses=[], max_pause_seconds=0.4)

    assert result == [(10.0, 40.0)]


def test_compute_keep_segments_short_pause_under_threshold_ignored():
    pauses = [{"start": 20.0, "end": 20.3, "duration": 0.3}]

    result = compute_keep_segments(10.0, 40.0, pauses, max_pause_seconds=0.4)

    assert result == [(10.0, 40.0)]


def test_compute_keep_segments_long_pause_inside_clip_splits_into_two():
    pauses = [{"start": 20.0, "end": 21.5, "duration": 1.5}]

    result = compute_keep_segments(10.0, 40.0, pauses, max_pause_seconds=0.4)

    assert result == [(10.0, 20.0), (21.5, 40.0)]


def test_compute_keep_segments_multiple_pauses_produce_multiple_segments():
    pauses = [
        {"start": 15.0, "end": 16.0, "duration": 1.0},
        {"start": 25.0, "end": 27.0, "duration": 2.0},
    ]

    result = compute_keep_segments(10.0, 40.0, pauses, max_pause_seconds=0.4)

    assert result == [(10.0, 15.0), (16.0, 25.0), (27.0, 40.0)]


def test_compute_keep_segments_pause_overlapping_clip_start_clamps_to_start():
    pauses = [{"start": 5.0, "end": 12.0, "duration": 7.0}]

    result = compute_keep_segments(10.0, 40.0, pauses, max_pause_seconds=0.4)

    assert result == [(12.0, 40.0)]


def test_compute_keep_segments_pause_overlapping_clip_end_clamps_to_end():
    pauses = [{"start": 38.0, "end": 45.0, "duration": 7.0}]

    result = compute_keep_segments(10.0, 40.0, pauses, max_pause_seconds=0.4)

    assert result == [(10.0, 38.0)]


def test_compute_keep_segments_pause_outside_clip_ignored():
    pauses = [{"start": 100.0, "end": 105.0, "duration": 5.0}]

    result = compute_keep_segments(10.0, 40.0, pauses, max_pause_seconds=0.4)

    assert result == [(10.0, 40.0)]


def test_compute_keep_segments_rejects_non_positive_span():
    with pytest.raises(ValueError, match="clip_end must be greater than clip_start"):
        compute_keep_segments(40.0, 10.0, [], max_pause_seconds=0.4)


def test_total_kept_duration_sums_segments():
    assert total_kept_duration([(10.0, 20.0), (25.0, 40.0)]) == 25.0


def test_remap_timestamp_within_first_segment():
    segments = [(10.0, 20.0), (25.0, 40.0)]

    assert remap_timestamp(12.0, segments) == 2.0


def test_remap_timestamp_within_second_segment_offsets_by_prior_duration():
    segments = [(10.0, 20.0), (25.0, 40.0)]

    # first segment keeps 10s (10.0-20.0); 2s into the second segment lands at 12.0
    assert remap_timestamp(27.0, segments) == 12.0


def test_remap_timestamp_inside_cut_gap_returns_none():
    segments = [(10.0, 20.0), (25.0, 40.0)]

    assert remap_timestamp(22.0, segments) is None


def test_remap_timestamp_before_first_segment_returns_none():
    segments = [(10.0, 20.0), (25.0, 40.0)]

    assert remap_timestamp(5.0, segments) is None


def test_remap_timestamp_after_last_segment_returns_none():
    segments = [(10.0, 20.0), (25.0, 40.0)]

    assert remap_timestamp(45.0, segments) is None


def test_remap_words_shifts_words_onto_spliced_timeline():
    segments = [(10.0, 20.0), (25.0, 40.0)]
    words = [
        {"word": "hello", "start": 12.0, "end": 12.5},
        {"word": "world", "start": 27.0, "end": 27.4},
    ]

    result = remap_words(words, segments)

    assert result == [
        {"word": "hello", "start": 2.0, "end": 2.5},
        {"word": "world", "start": 12.0, "end": 12.4},
    ]


def test_remap_words_drops_word_inside_cut_gap():
    segments = [(10.0, 20.0), (25.0, 40.0)]
    words = [
        {"word": "kept", "start": 12.0, "end": 12.5},
        {"word": "cut", "start": 21.0, "end": 22.0},
    ]

    result = remap_words(words, segments)

    assert result == [{"word": "kept", "start": 2.0, "end": 2.5}]


def test_compute_boundary_gap_single_segment_returns_empty():
    assert compute_boundary_gaps([(0.0, 10.0)]) == []


def test_compute_boundary_gap_two_segments_returns_the_cut_pause():
    assert compute_boundary_gaps([(0.0, 10.0), (12.5, 20.0)]) == [2.5]


def test_compute_boundary_gap_multiple_segments_includes_zero_gap_when_abutting():
    result = compute_boundary_gaps([(0.0, 5.0), (6.0, 9.0), (9.0, 14.0)])

    assert result == [1.0, 0.0]


def test_compute_boundary_gap_length_matches_boundary_count():
    segments = [(0.0, 5.0), (6.0, 9.0), (9.0, 14.0), (20.0, 25.0)]

    result = compute_boundary_gaps(segments)

    assert len(result) == len(segments) - 1


def test_compute_boundary_windows_single_segment_returns_empty():
    assert compute_boundary_windows([(0.0, 10.0)]) == []


def test_compute_boundary_windows_two_segments_returns_the_gap_window():
    assert compute_boundary_windows([(0.0, 10.0), (12.5, 20.0)]) == [(10.0, 12.5)]


def test_compute_boundary_windows_multiple_segments():
    segments = [(0.0, 5.0), (6.0, 9.0), (9.0, 14.0)]

    assert compute_boundary_windows(segments) == [(5.0, 6.0), (9.0, 9.0)]


def test_drop_boundary_merges_the_two_straddling_segments():
    segments = [(0.0, 10.0), (12.5, 20.0)]

    assert drop_boundary(segments, 0) == [(0.0, 20.0)]


def test_drop_boundary_merges_only_the_targeted_pair_leaves_others():
    segments = [(0.0, 5.0), (6.0, 9.0), (10.0, 14.0)]

    assert drop_boundary(segments, 1) == [(0.0, 5.0), (6.0, 14.0)]


def test_drop_boundary_first_of_three_keeps_the_third_untouched():
    segments = [(0.0, 5.0), (6.0, 9.0), (10.0, 14.0)]

    assert drop_boundary(segments, 0) == [(0.0, 9.0), (10.0, 14.0)]


def test_drop_boundary_rejects_out_of_range_index():
    with pytest.raises(ValueError, match="boundary_index 1 out of range for 1 segment"):
        drop_boundary([(0.0, 10.0)], 1)


def test_drop_boundary_rejects_negative_index():
    with pytest.raises(ValueError, match="boundary_index -1 out of range"):
        drop_boundary([(0.0, 10.0), (12.0, 20.0)], -1)


def _run_cli(tmp_path, args):
    return subprocess.run(
        [sys.executable, "scripts/jumpcuts.py", *args],
        capture_output=True, text=True, cwd=Path(__file__).resolve().parent.parent,
    )


def test_cli_keep_segments_writes_json_file(tmp_path):
    pauses_path = tmp_path / "pauses.json"
    pauses_path.write_text(json.dumps([{"start": 20.0, "end": 21.5, "duration": 1.5}]), encoding="utf-8")
    output_path = tmp_path / "keep.json"

    result = _run_cli(
        tmp_path,
        ["keep-segments", str(pauses_path), "10.0", "40.0", str(output_path), "--max-pause-seconds", "0.4"],
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(output_path.read_text(encoding="utf-8")) == [[10.0, 20.0], [21.5, 40.0]]


def test_cli_boundary_windows_prints_gap_windows(tmp_path):
    keep_segments_path = tmp_path / "keep.json"
    keep_segments_path.write_text(json.dumps([[10.0, 20.0], [25.0, 40.0]]), encoding="utf-8")

    result = _run_cli(tmp_path, ["boundary-windows", str(keep_segments_path)])

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == [[20.0, 25.0]]


def test_cli_drop_boundary_writes_merged_json_file(tmp_path):
    keep_segments_path = tmp_path / "keep.json"
    keep_segments_path.write_text(json.dumps([[10.0, 20.0], [25.0, 40.0]]), encoding="utf-8")
    output_path = tmp_path / "keep_merged.json"

    result = _run_cli(tmp_path, ["drop-boundary", str(keep_segments_path), "0", str(output_path)])

    assert result.returncode == 0, result.stderr
    assert json.loads(output_path.read_text(encoding="utf-8")) == [[10.0, 40.0]]


def test_cli_remap_words_writes_json_file(tmp_path):
    words_path = tmp_path / "words.json"
    words_path.write_text(
        json.dumps([{"word": "hi", "start": 12.0, "end": 12.5}]), encoding="utf-8"
    )
    keep_segments_path = tmp_path / "keep.json"
    keep_segments_path.write_text(json.dumps([[10.0, 20.0], [25.0, 40.0]]), encoding="utf-8")
    output_path = tmp_path / "remapped.json"

    result = _run_cli(
        tmp_path,
        ["remap-words", str(words_path), str(keep_segments_path), str(output_path)],
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(output_path.read_text(encoding="utf-8")) == [{"word": "hi", "start": 2.0, "end": 2.5}]
