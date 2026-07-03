from scripts.subtitles import (
    build_karaoke_text,
    format_srt_timestamp,
    group_words_into_cues,
    group_words_into_karaoke_cues,
    parse_srt,
    render_srt,
)


def test_group_words_into_cues_splits_by_max_words():
    words = [
        {"word": "one", "start": 0.0, "end": 0.3},
        {"word": "two", "start": 0.3, "end": 0.6},
        {"word": "three", "start": 0.6, "end": 0.9},
        {"word": "four", "start": 0.9, "end": 1.2},
        {"word": "five", "start": 1.2, "end": 1.5},
    ]

    cues = group_words_into_cues(words, max_words=2)

    assert cues == [
        {"start": 0.0, "end": 0.6, "text": "one two"},
        {"start": 0.6, "end": 1.2, "text": "three four"},
        {"start": 1.2, "end": 1.5, "text": "five"},
    ]


def test_group_words_into_cues_empty_input():
    assert group_words_into_cues([], max_words=4) == []


def test_group_words_into_cues_strips_word_whitespace():
    words = [{"word": " hello ", "start": 0.0, "end": 0.5}, {"word": "world", "start": 0.5, "end": 1.0}]

    cues = group_words_into_cues(words, max_words=4)

    assert cues == [{"start": 0.0, "end": 1.0, "text": "hello world"}]


def test_format_srt_timestamp():
    assert format_srt_timestamp(0.0) == "00:00:00,000"
    assert format_srt_timestamp(65.25) == "00:01:05,250"
    assert format_srt_timestamp(3661.007) == "01:01:01,007"


def test_render_srt_formats_cues():
    cues = [
        {"start": 0.0, "end": 0.6, "text": "one two"},
        {"start": 0.6, "end": 1.2, "text": "three four"},
    ]

    result = render_srt(cues)

    assert result == (
        "1\n"
        "00:00:00,000 --> 00:00:00,600\n"
        "one two\n"
        "\n"
        "2\n"
        "00:00:00,600 --> 00:00:01,200\n"
        "three four\n"
        "\n"
    )


def test_render_srt_empty_cues():
    assert render_srt([]) == ""


def test_parse_srt_round_trips_render_srt():
    cues = [
        {"start": 0.0, "end": 0.6, "text": "one two"},
        {"start": 0.6, "end": 1.2, "text": "three four"},
    ]

    assert parse_srt(render_srt(cues)) == cues


def test_parse_srt_empty_text():
    assert parse_srt("") == []


def test_build_karaoke_text_single_word():
    words = [{"word": "hello", "start": 0.0, "end": 0.4}]

    assert build_karaoke_text(words) == "{\\k40}hello"


def test_build_karaoke_text_two_words_with_gap():
    words = [
        {"word": "hello", "start": 0.0, "end": 0.4},
        {"word": "world", "start": 0.5, "end": 1.0},
    ]

    assert build_karaoke_text(words) == "{\\k40}hello{\\k10} {\\k50}world"


def test_build_karaoke_text_clamps_negative_gap_to_zero():
    words = [
        {"word": "hello", "start": 0.0, "end": 0.5},
        {"word": "world", "start": 0.4, "end": 0.9},
    ]

    assert build_karaoke_text(words) == "{\\k50}hello{\\k0} {\\k50}world"


def test_build_karaoke_text_strips_word_whitespace():
    words = [{"word": " hello ", "start": 0.0, "end": 0.3}]

    assert build_karaoke_text(words) == "{\\k30}hello"


def test_group_words_into_karaoke_cues_matches_plain_grouping_boundaries():
    words = [
        {"word": "one", "start": 0.0, "end": 0.3},
        {"word": "two", "start": 0.3, "end": 0.6},
        {"word": "three", "start": 0.6, "end": 0.9},
    ]

    cues = group_words_into_karaoke_cues(words, max_words=2)

    assert [(cue["start"], cue["end"]) for cue in cues] == [(0.0, 0.6), (0.6, 0.9)]
    assert cues[0]["text"] == "{\\k30}one{\\k0} {\\k30}two"
    assert cues[1]["text"] == "{\\k30}three"


def test_group_words_into_karaoke_cues_empty_input():
    assert group_words_into_karaoke_cues([], max_words=4) == []
