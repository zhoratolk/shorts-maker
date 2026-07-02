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
