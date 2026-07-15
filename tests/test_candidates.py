import json
from pathlib import Path

import pytest

from scripts.candidates import (
    Candidate,
    append_compilation_sections_markdown,
    compute_moment_budget,
    format_timecode,
    merge_candidate_files,
    merge_candidates,
    render_candidates_markdown,
    select_top_moments,
    write_candidates_json,
)


def test_compute_moment_budget_three_per_hour():
    # The locked example: a 3h recording at rate 3 => 9 total moments.
    assert compute_moment_budget(3 * 3600, rate_per_hour=3.0) == 9


def test_compute_moment_budget_rounds_and_floors():
    # 1.5h * 3 = 4.5 -> 4 (Python round() is banker's rounding, ties to even)
    assert compute_moment_budget(90 * 60, rate_per_hour=3.0) == 4
    # 2h * 3 = 6 exactly
    assert compute_moment_budget(2 * 3600, rate_per_hour=3.0) == 6
    # 10-minute recording: 0.5 moments -> floored to minimum 1
    assert compute_moment_budget(10 * 60, rate_per_hour=3.0) == 1
    assert compute_moment_budget(0, rate_per_hour=3.0) == 0


def test_compute_moment_budget_configurable_rate():
    assert compute_moment_budget(2 * 3600, rate_per_hour=5.0) == 10


def test_select_top_moments_keeps_highest_scores_in_timeline_order():
    candidates = [
        {"id": 1, "start": 10.0, "score": 2},
        {"id": 2, "start": 20.0, "score": 5},
        {"id": 3, "start": 30.0, "score": 4},
        {"id": 4, "start": 40.0, "score": 1},
    ]
    kept = select_top_moments(candidates, 2)
    # top two by score are ids 2 (5) and 3 (4), returned chronologically
    assert [c["id"] for c in kept] == [2, 3]


def test_select_top_moments_missing_score_sorts_last():
    candidates = [
        {"id": 1, "start": 5.0},          # no score -> treated as 0
        {"id": 2, "start": 8.0, "score": 3},
    ]
    assert [c["id"] for c in select_top_moments(candidates, 1)] == [2]


def test_select_top_moments_budget_at_or_over_count_returns_all():
    candidates = [{"id": 1, "start": 1.0, "score": 1}, {"id": 2, "start": 2.0, "score": 2}]
    assert len(select_top_moments(candidates, 5)) == 2


def test_select_top_moments_zero_budget_or_empty():
    assert select_top_moments([{"id": 1, "start": 1.0, "score": 5}], 0) == []
    assert select_top_moments([], 3) == []


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
        {
            "id": 1,
            "start": 10.0,
            "end": 20.0,
            "reason": "first joke",
            "coherence": None,
            "tag": None,
            "sub_threshold": False,
            "group_id": None,
            "unmatched": False,
        }
    ]


def test_merge_candidates_carries_optional_coherence_field():
    chunk = [{"start": 10.0, "end": 20.0, "reason": "clean monologue", "coherence": 5}]

    merged = merge_candidates([chunk])

    assert merged == [Candidate(id=1, start=10.0, end=20.0, reason="clean monologue", coherence=5)]


def test_merge_candidates_coherence_defaults_to_none_when_absent():
    chunk = [{"start": 10.0, "end": 20.0, "reason": "no speaker data"}]

    merged = merge_candidates([chunk])

    assert merged[0].coherence is None


def test_render_candidates_markdown_includes_coherence_when_present():
    candidates = [Candidate(id=1, start=10.0, end=20.0, reason="clean monologue", coherence=5)]

    markdown = render_candidates_markdown(candidates)

    assert markdown == "# Candidates\n\n1. `00:00:10` - `00:00:20` — clean monologue (целостность: 5/5)\n"


def test_merge_candidates_carries_tag_or_sub_threshold_fields_when_present():
    chunk = [
        {
            "start": 10.0,
            "end": 15.0,
            "reason": "died to boss",
            "tag": "died to same boss",
            "sub_threshold": True,
            "group_id": 2,
            "unmatched": False,
        }
    ]

    merged = merge_candidates([chunk])

    assert merged == [
        Candidate(
            id=1,
            start=10.0,
            end=15.0,
            reason="died to boss",
            tag="died to same boss",
            sub_threshold=True,
            group_id=2,
            unmatched=False,
        )
    ]


def test_merge_candidates_tag_or_sub_threshold_fields_default_when_absent():
    chunk = [{"start": 10.0, "end": 20.0, "reason": "no sub-threshold data"}]

    merged = merge_candidates([chunk])

    assert merged[0].tag is None
    assert merged[0].sub_threshold is False
    assert merged[0].group_id is None
    assert merged[0].unmatched is False


def test_append_compilation_sections_markdown_adds_group_and_unmatched_sections(tmp_path):
    path = str(tmp_path / "CANDIDATES.md")
    Path(path).write_text("# Candidates\n\n1. `00:00:10` - `00:00:20` — first joke\n", encoding="utf-8")

    groups = [
        {
            "members": [{"id": 4}, {"id": 7}],
            "title": "Boss Rage Compilation",
        }
    ]
    unmatched = [
        {"start": 12.3, "end": 15.1, "reason": "died alone", "tag": "solo death"},
    ]

    append_compilation_sections_markdown(path, groups, unmatched)

    result = Path(path).read_text(encoding="utf-8")

    assert "## Sub-Threshold Compilations" in result
    assert "#4" in result
    assert "#7" in result
    assert "Boss Rage Compilation" in result
    assert "## Unmatched Sub-Threshold" in result
    assert "`00:00:12` - `00:00:15`" in result
    assert "died alone" in result
    assert "solo death" in result
    # Original numbered candidate list must be untouched.
    assert "1. `00:00:10` - `00:00:20` — first joke" in result


def test_append_compilation_sections_markdown_defaults_missing_fields(tmp_path):
    path = str(tmp_path / "CANDIDATES.md")
    Path(path).write_text("# Candidates\n\n1. `00:00:10` - `00:00:20` — first joke\n", encoding="utf-8")

    groups = [
        {
            # One member omits 'id'; group omits 'title'.
            "members": [{"id": 4}, {}],
        }
    ]
    unmatched = [
        # 'reason' and 'tag' omitted; 'start'/'end' stay required.
        {"start": 12.3, "end": 15.1},
    ]

    append_compilation_sections_markdown(path, groups, unmatched)

    result = Path(path).read_text(encoding="utf-8")

    assert "#4" in result
    assert "#?" in result
    assert "(untitled compilation)" in result
    assert "`00:00:12` - `00:00:15`" in result
    assert "(no reason given)" in result
    assert "(untagged)" in result
    # Original numbered candidate list must be untouched.
    assert "1. `00:00:10` - `00:00:20` — first joke" in result


def test_append_compilation_sections_markdown_noop_when_both_empty(tmp_path):
    path = str(tmp_path / "CANDIDATES.md")
    original = "# Candidates\n\n1. `00:00:10` - `00:00:20` — first joke\n"
    Path(path).write_text(original, encoding="utf-8")

    append_compilation_sections_markdown(path, [], [])

    assert Path(path).read_text(encoding="utf-8") == original
