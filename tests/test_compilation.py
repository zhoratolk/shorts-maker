import pytest

from scripts.compilation import CompilationError, MIN_GROUP_SIZE, build_compilation_entry


def make_member(video_stem, start, end, keep_segments=None):
    member = {"video_stem": video_stem, "start": start, "end": end}
    if keep_segments is not None:
        member["keep_segments"] = keep_segments
    return member


def test_build_compilation_entry_rejects_single_member_group():
    members = [make_member("mystream", 0, 20)]

    with pytest.raises(CompilationError, match="a compilation group needs >= 2 members, got 1"):
        build_compilation_entry(members, 150, "zoom")


def test_build_compilation_entry_requires_same_video_stem():
    members = [make_member("mystream_a", 0, 20), make_member("mystream_b", 30, 50)]

    with pytest.raises(CompilationError, match="video_stem"):
        build_compilation_entry(members, 150, "zoom")


def test_build_compilation_entry_builds_valid_entry_from_two_members():
    members = [make_member("mystream", 0, 20), make_member("mystream", 30, 45)]

    entry = build_compilation_entry(members, 150, "zoom")

    assert entry["type"] == "compilation"
    assert entry["crop_style"] == "zoom"
    assert entry["segments"] == [
        {"start": 0, "end": 20},
        {"start": 30, "end": 45},
    ]


def test_build_compilation_entry_caps_at_compilation_max_seconds_dropping_weakest():
    # Durations: 60, 60, 60 - strongest-first order. Cap 150 lets the first
    # two through (running total 120) but the third would push to 180 > 150.
    members = [
        make_member("mystream", 0, 60),
        make_member("mystream", 100, 160),
        make_member("mystream", 200, 260),
    ]

    entry = build_compilation_entry(members, 150, "zoom")

    assert len(entry["segments"]) == 2
    assert entry["segments"][0]["start"] == 0
    assert entry["segments"][1]["start"] == 100


def test_build_compilation_entry_raises_when_capping_leaves_fewer_than_min_group_size():
    # Strongest member alone (duration 200) already exceeds the 150s cap, so
    # capping drops it and everything after it, leaving zero fitted members.
    members = [
        make_member("mystream", 0, 200),
        make_member("mystream", 300, 320),
    ]

    with pytest.raises(CompilationError):
        build_compilation_entry(members, 150, "zoom")


def test_build_compilation_entry_rejects_boundary_transitions_length_mismatch():
    # member 1 has no keep_segments (flattened count 1), member 2 has a
    # 2-segment keep_segments (flattened count 2) - total flattened = 3,
    # so boundary_transitions must have length 2, not 1.
    members = [
        make_member("mystream", 0, 20),
        make_member("mystream", 30, 50, keep_segments=[[30, 35], [40, 50]]),
    ]

    with pytest.raises(CompilationError, match="boundary_transitions"):
        build_compilation_entry(members, 150, "zoom", boundary_transitions=["cut"])


def test_build_compilation_entry_caps_and_truncates_boundary_transitions():
    # Same 60/60/60 setup as the capping-only test above: cap 150 drops the
    # third member, leaving 2 fitted members (1 boundary). boundary_transitions
    # is sized for the PRE-cap 3-member list (2 boundaries), exactly as
    # SKILL.md step 5b bullet 5 computes it today, before capping ever runs.
    members = [
        make_member("mystream", 0, 60),
        make_member("mystream", 100, 160),
        make_member("mystream", 200, 260),
    ]

    entry = build_compilation_entry(
        members, 150, "zoom", boundary_transitions=["crossfade", "whip_pan"]
    )

    assert len(entry["segments"]) == 2
    assert entry["boundary_transitions"] == ["crossfade"]


def test_build_compilation_entry_still_rejects_too_short_boundary_transitions():
    # Same 3-member/cap-150 setup, but boundary_transitions=[] is genuinely
    # too short even after truncation (fewer than the fitted list's 1
    # required boundary) - truncation must never pad, only shrink.
    members = [
        make_member("mystream", 0, 60),
        make_member("mystream", 100, 160),
        make_member("mystream", 200, 260),
    ]

    with pytest.raises(CompilationError, match="boundary_transitions"):
        build_compilation_entry(members, 150, "zoom", boundary_transitions=[])


def test_build_compilation_entry_omits_optional_fields_when_none():
    members = [make_member("mystream", 0, 20), make_member("mystream", 30, 45)]

    entry = build_compilation_entry(members, 150, "zoom")

    assert "boundary_transitions" not in entry
    assert "punch_zoom_at" not in entry
    assert "subtitles_path" not in entry
    assert "metadata_path" not in entry
    assert "output_filename" not in entry


def test_min_group_size_constant_is_two():
    assert MIN_GROUP_SIZE == 2
