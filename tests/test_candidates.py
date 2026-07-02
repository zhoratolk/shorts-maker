import json
from pathlib import Path

import pytest

from scripts.candidates import (
    Candidate,
    format_timecode,
    merge_candidate_files,
    merge_candidates,
    render_candidates_markdown,
    write_candidates_json,
)


def test_format_timecode_zero():
    assert format_timecode(0) == "00:00:00"


def test_format_timecode_over_an_hour():
    assert format_timecode(3661) == "01:01:01"


def test_format_timecode_negative_raises():
    with pytest.raises(ValueError, match="total_seconds"):
        format_timecode(-1)


def test_merge_candidates_sorts_by_start_and_assigns_sequential_ids():
    chunk_a = [{"start": 120.0, "end": 130.0, "reason": "second joke"}]
    chunk_b = [{"start": 10.0, "end": 20.0, "reason": "first joke"}]

    merged = merge_candidates([chunk_a, chunk_b])

    assert merged == [
        Candidate(id=1, start=10.0, end=20.0, reason="first joke"),
        Candidate(id=2, start=120.0, end=130.0, reason="second joke"),
    ]


def test_merge_candidate_files_reads_directory_in_sorted_order(tmp_path):
    (tmp_path / "candidates_chunk_0001.json").write_text(
        json.dumps([{"start": 120.0, "end": 130.0, "reason": "second joke"}]), encoding="utf-8"
    )
    (tmp_path / "candidates_chunk_0000.json").write_text(
        json.dumps([{"start": 10.0, "end": 20.0, "reason": "first joke"}]), encoding="utf-8"
    )

    merged = merge_candidate_files(str(tmp_path))

    assert merged == [
        Candidate(id=1, start=10.0, end=20.0, reason="first joke"),
        Candidate(id=2, start=120.0, end=130.0, reason="second joke"),
    ]


def test_render_candidates_markdown_empty():
    assert render_candidates_markdown([]) == "# Candidates\n\nNo candidates found.\n"


def test_render_candidates_markdown_lists_entries():
    candidates = [
        Candidate(id=1, start=10.0, end=20.0, reason="first joke"),
        Candidate(id=2, start=3661.0, end=3665.0, reason="second joke"),
    ]

    markdown = render_candidates_markdown(candidates)

    assert markdown == (
        "# Candidates\n\n"
        "1. `00:00:10` - `00:00:20` — first joke\n"
        "2. `01:01:01` - `01:01:05` — second joke\n"
    )


def test_write_candidates_json_round_trips(tmp_path):
    candidates = [Candidate(id=1, start=10.0, end=20.0, reason="first joke")]
    path = str(tmp_path / "candidates.json")

    write_candidates_json(candidates, path)

    assert json.loads(Path(path).read_text(encoding="utf-8")) == [
        {"id": 1, "start": 10.0, "end": 20.0, "reason": "first joke"}
    ]
