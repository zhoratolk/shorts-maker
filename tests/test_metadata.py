import pytest

from scripts.metadata import render_metadata_text, write_metadata_file


def test_render_metadata_text_youtube_block():
    text = render_metadata_text({
        "youtube": {"title": "Boss Rage Quit", "description": "He lost it.", "tags": ["gaming", "funny"]},
    })

    assert "=== YOUTUBE ===" in text
    assert "Title: Boss Rage Quit" in text
    assert "Description:\nHe lost it." in text
    assert "Tags: gaming, funny" in text


def test_render_metadata_text_youtube_title_en_line():
    text = render_metadata_text({
        "youtube": {
            "title": "Босс в ярости",
            "title_en": "Boss Rage Quit",
            "description": "d",
            "tags": ["t"],
        },
    })

    assert "Title: Босс в ярости" in text
    assert "Title (EN): Boss Rage Quit" in text


def test_render_metadata_text_youtube_no_title_en_no_line():
    text = render_metadata_text({
        "youtube": {"title": "Босс", "description": "d", "tags": ["t"]},
    })

    assert "Title (EN):" not in text


def test_render_metadata_text_caption_platform_block():
    text = render_metadata_text({
        "tiktok": {"caption": "He rage quit! #gaming #funny"},
    })

    assert "=== TIKTOK ===" in text
    assert "He rage quit! #gaming #funny" in text


def test_render_metadata_text_multiple_platforms_sorted():
    text = render_metadata_text({
        "youtube": {"title": "T", "description": "D", "tags": []},
        "tiktok": {"caption": "tiktok caption"},
    })

    assert text.index("=== TIKTOK ===") < text.index("=== YOUTUBE ===")


def test_render_metadata_text_unknown_platform_raises():
    with pytest.raises(ValueError, match="unknown"):
        render_metadata_text({"twitter": {"caption": "x"}})


def test_write_metadata_file_writes_rendered_text(tmp_path):
    path = tmp_path / "0001-boss-rage-quit.txt"
    write_metadata_file({"instagram": {"caption": "caption text"}}, str(path))

    content = path.read_text(encoding="utf-8")
    assert "=== INSTAGRAM ===" in content
    assert "caption text" in content


def test_render_metadata_text_renders_advisory_risk_subblock_when_present():
    text = render_metadata_text({
        "youtube": {
            "title": "Boss Rage Quit",
            "description": "He lost it.",
            "tags": ["gaming", "funny"],
            "risk": {
                "platform": "youtube",
                "risk_level": "medium",
                "flags": ["gambling"],
                "flagged_spans": [{"start": 1, "end": 2, "reason": "gambling", "matched_text": "казино"}],
                "confidence": "medium",
                "last_checked": "2026-07-07",
            },
        },
    })

    assert "Monetization risk (advisory)" in text
    assert "medium" in text
    assert "gambling" in text
    assert "2026-07-07" in text
    # Never framed as a certainty / gate.
    assert "will be demonetized" not in text.lower()


def test_render_metadata_text_unchanged_when_risk_absent():
    with_risk_fields = {
        "tiktok": {"caption": "He rage quit! #gaming #funny"},
    }
    text = render_metadata_text(with_risk_fields)

    assert "Monetization risk" not in text
    assert "=== TIKTOK ===" in text
    assert "He rage quit! #gaming #funny" in text


def test_render_metadata_text_risk_subblock_none_level_still_renders():
    text = render_metadata_text({
        "instagram": {
            "caption": "caption text",
            "risk": {
                "platform": "instagram",
                "risk_level": "none",
                "flags": [],
                "flagged_spans": [],
                "confidence": "low",
                "last_checked": "2026-07-07",
            },
        },
    })

    assert "Monetization risk (advisory)" in text
    assert "none" in text
