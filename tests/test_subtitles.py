from scripts.subtitles import format_srt_timestamp, group_words_into_cues, parse_srt, render_srt


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
