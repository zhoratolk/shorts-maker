import pytest

from scripts.metadata import CONTACT_FOOTER, TELEGRAM_URL, TWITCH_URL, render_metadata_text, strip_mature_disclaimer, write_metadata_file


def test_render_metadata_text_youtube_block():
    text = render_metadata_text({
        "youtube": {"title": "Boss Rage Quit", "description": "He lost it.", "tags": ["gaming", "funny"]},
    })

    assert "=== YOUTUBE ===" in text
    assert "Title: Boss Rage Quit" in text
    assert "Description:\nHe lost it." in text
    assert "Tags: gaming, funny" in text


def test_render_metadata_text_youtube_description_always_has_contact_footer():
    text = render_metadata_text({
        "youtube": {"title": "T", "description": "D", "tags": []},
    })

    assert TWITCH_URL in text
    assert TELEGRAM_URL in text
    assert CONTACT_FOOTER in text
    # Footer sits between the description and the Tags line.
    assert text.index("Description:") < text.index(CONTACT_FOOTER) < text.index("Tags:")


def test_render_metadata_text_caption_platforms_have_no_contact_footer():
    text = render_metadata_text({
        "tiktok": {"caption": "He rage quit! #gaming #funny"},
    })

    assert TWITCH_URL not in text


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


# --- дисклеймер про мат: срезается кодом, а не памятью того, кто пишет метадату


def test_strip_mature_disclaimer_removes_whole_line_and_gap():
    text = (
        "Товарищ вытащил себе ноги и умер от болевого шока.\n"
        "Содержит ненормативную лексику (замаскирована).\n"
        "\n"
        "#barotrauma #стрим"
    )
    assert strip_mature_disclaimer(text) == (
        "Товарищ вытащил себе ноги и умер от болевого шока.\n\n#barotrauma #стрим"
    )


def test_strip_mature_disclaimer_removes_age_warning_prefix_line():
    assert strip_mature_disclaimer("⚠️ 18+ жёсткий момент\nОписание.") == "Описание."


def test_strip_mature_disclaimer_keeps_line_that_only_mentions_it_mid_sentence():
    text = "Спор о том, кто тут ругается матом, закончился ничем."
    assert strip_mature_disclaimer(text) == text


def test_render_metadata_text_drops_disclaimer_from_description_and_caption():
    rendered = render_metadata_text(
        {
            "youtube": {
                "title": "Заголовок",
                "description": "Первая строка.\nСодержит ненормативную лексику (замаскирована).",
                "tags": ["тег"],
            },
            "tiktok": {"caption": "Капшн 💀\n18+ осторожно"},
        }
    )
    assert "ненормативную" not in rendered
    assert "18+" not in rendered
    assert "Первая строка." in rendered
    assert "Капшн 💀" in rendered
