from scripts.naming import build_clip_filename, slugify


def test_slugify_ascii_title():
    assert slugify("Boss Rage Quit") == "boss-rage-quit"


def test_slugify_cyrillic_title():
    assert slugify("Босс психует") == "boss-psikhuet"


def test_slugify_strips_punctuation():
    assert slugify("Wait... WHAT?!") == "wait-what"


def test_slugify_collapses_multiple_separators():
    assert slugify("too   many   spaces") == "too-many-spaces"


def test_build_clip_filename_prefixes_video_stem_index_and_appends_extension():
    assert build_clip_filename("MyStream_2026", 1, "Boss Rage Quit") == "mystream-2026-0001-boss-rage-quit.mp4"


def test_build_clip_filename_custom_extension():
    assert build_clip_filename("MyStream", 12, "Funny moment", extension="txt") == "mystream-0012-funny-moment.txt"
