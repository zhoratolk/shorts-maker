import pytest

from scripts.style_profile import derive_profile, format_naming_examples_block


def _record(video_id, title, view_count, average_view_percentage, published_at="2026-01-01T00:00:00Z"):
    return {
        "video_id": video_id,
        "title": title,
        "published_at": published_at,
        "view_count": view_count,
        "like_count": None,
        "comment_count": None,
        "views_in_range": None,
        "average_view_duration": None,
        "average_view_percentage": average_view_percentage,
        "traffic_sources": {},
    }


def test_derive_profile_naming_examples_are_concrete_not_prose():
    records = [
        _record("a", "Boss Rage Quit Moment", 50000, 62.0),
        _record("b", "Clutch 1v5 Ace", 12000, 30.0),
    ]

    profile = derive_profile(records)

    assert "naming_examples" in profile
    assert len(profile["naming_examples"]) >= 1
    top = profile["naming_examples"][0]
    # Concrete: must carry the actual title string plus a numeric signal, not a
    # prose description of "style" (PITFALL 5).
    assert top["title"] in {"Boss Rage Quit Moment", "Clutch 1v5 Ace"}
    assert isinstance(top["signal"], (int, float))
    for example in profile["naming_examples"]:
        assert "style" not in example.get("title", "").lower() or example["title"] in {
            "Boss Rage Quit Moment",
            "Clutch 1v5 Ace",
        }


def test_derive_profile_ranks_naming_examples_by_performance_signal():
    records = [
        _record("a", "Low Performer", 100, 5.0),
        _record("b", "High Performer", 90000, 71.5),
    ]

    profile = derive_profile(records)

    titles_in_order = [example["title"] for example in profile["naming_examples"]]
    assert titles_in_order[0] == "High Performer"


def test_derive_profile_emits_structured_moment_selection_examples():
    records = [
        _record("a", "Boss Rage Quit Moment", 50000, 62.0),
    ]

    profile = derive_profile(records)

    assert "moment_examples" in profile
    assert isinstance(profile["moment_examples"], list)
    for entry in profile["moment_examples"]:
        assert isinstance(entry, dict)
        assert "title" in entry
        assert "signal" in entry
        assert isinstance(entry["signal"], (int, float))


def test_derive_profile_has_machine_readable_schema():
    records = [_record("a", "Boss Rage Quit Moment", 50000, 62.0)]

    profile = derive_profile(records)

    assert "schema_version" in profile
    assert isinstance(profile["schema_version"], int)
    assert isinstance(profile["naming_examples"], list)
    assert isinstance(profile["moment_examples"], list)


def test_derive_profile_empty_input_fails_open():
    profile = derive_profile([])

    assert profile["schema_version"] >= 1
    assert profile["naming_examples"] == []
    assert profile["moment_examples"] == []


def test_privacy_write_profile_default_target_is_under_gitignored_work_dir():
    from pathlib import Path

    from scripts.style_profile import write_profile

    records = [_record("fake-channel-id", "TOTALLY FAKE TITLE FOR PRIVACY TEST", 1, 1.0)]
    profile = derive_profile(records)

    written_path = write_profile(profile)

    resolved = Path(written_path).resolve()
    work_dir = (Path(__file__).parent.parent / "work").resolve()
    assert work_dir in resolved.parents or resolved == work_dir

    import shutil
    import subprocess

    if shutil.which("git"):
        result = subprocess.run(
            ["git", "check-ignore", str(written_path)],
            cwd=str(Path(__file__).parent.parent),
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"expected {written_path} to be git-ignored"


def test_format_naming_examples_block_renders_ranked_titles():
    profile = {
        "naming_examples": [
            {"title": "Boss Rage Quit Moment", "signal": 62.0},
            {"title": "Clutch 1v5 Ace", "signal": 30.0},
        ]
    }

    block = format_naming_examples_block(profile)

    lines = block.split("\n")
    assert len(lines) == 2
    assert lines[0].startswith("1.")
    assert "Boss Rage Quit Moment" in lines[0]
    assert "62.0" in lines[0]
    assert lines[1].startswith("2.")
    assert "Clutch 1v5 Ace" in lines[1]


def test_format_naming_examples_block_empty_when_no_examples():
    assert format_naming_examples_block({"naming_examples": []}) == ""
    assert format_naming_examples_block({}) == ""


def test_format_naming_examples_block_respects_limit():
    profile = {
        "naming_examples": [
            {"title": "High Performer", "signal": 90.0},
            {"title": "Low Performer", "signal": 5.0},
            {"title": "Boss Rage Quit Moment", "signal": 3.0},
        ]
    }

    block = format_naming_examples_block(profile, limit=2)

    lines = block.split("\n")
    assert len(lines) == 2
    assert "High Performer" in lines[0]
    assert "Low Performer" in lines[1]
    assert "Boss Rage Quit Moment" not in block
