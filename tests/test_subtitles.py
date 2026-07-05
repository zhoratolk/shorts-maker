from scripts.subtitles import (
    format_srt_timestamp,
    group_words_into_cues,
    parse_srt,
    render_srt,
    strip_display_punctuation,
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
        {"start": 0.0, "end": 0.6, "text": "one two", "words": words[0:2]},
        {"start": 0.6, "end": 1.2, "text": "three four", "words": words[2:4]},
        {"start": 1.2, "end": 1.5, "text": "five", "words": words[4:5]},
    ]


def test_group_words_into_cues_empty_input():
    assert group_words_into_cues([], max_words=4) == []


def test_group_words_into_cues_splits_early_on_long_gap():
    words = [
        {"word": "one", "start": 0.0, "end": 0.3},
        {"word": "two", "start": 0.3, "end": 0.6},
        # 5 second silence here - "three"/"four" haven't been said yet
        {"word": "three", "start": 5.6, "end": 5.9},
        {"word": "four", "start": 5.9, "end": 6.2},
    ]

    cues = group_words_into_cues(words, max_words=4, max_gap_seconds=1.2)

    assert cues == [
        {"start": 0.0, "end": 0.6, "text": "one two", "words": words[0:2]},
        {"start": 5.6, "end": 6.2, "text": "three four", "words": words[2:4]},
    ]


def test_group_words_into_cues_keeps_short_gap_in_same_cue():
    words = [
        {"word": "one", "start": 0.0, "end": 0.3},
        {"word": "two", "start": 1.0, "end": 1.3},
    ]

    cues = group_words_into_cues(words, max_words=4, max_gap_seconds=1.2)

    assert cues == [{"start": 0.0, "end": 1.3, "text": "one two", "words": words}]


def test_group_words_into_cues_strips_word_whitespace():
    words = [{"word": " hello ", "start": 0.0, "end": 0.5}, {"word": "world", "start": 0.5, "end": 1.0}]

    cues = group_words_into_cues(words, max_words=4)

    assert cues == [
        {
            "start": 0.0, "end": 1.0, "text": "hello world",
            "words": [
                {"word": "hello", "start": 0.0, "end": 0.5},
                {"word": "world", "start": 0.5, "end": 1.0},
            ],
        }
    ]


def test_strip_display_punctuation_removes_leading_trailing_marks():
    assert strip_display_punctuation("привет,") == "привет"
    assert strip_display_punctuation('"что?!"') == "что"
    assert strip_display_punctuation("— ладно...") == "ладно"


def test_strip_display_punctuation_leaves_internal_characters_alone():
    assert strip_display_punctuation("по-другому") == "по-другому"
    assert strip_display_punctuation("don't") == "don't"


def test_group_words_into_cues_strips_punctuation_by_default():
    words = [
        {"word": "Привет,", "start": 0.0, "end": 0.3},
        {"word": "мир!", "start": 0.3, "end": 0.6},
    ]

    cues = group_words_into_cues(words, max_words=4)

    assert cues[0]["text"] == "Привет мир"
    assert cues[0]["words"] == [
        {"word": "Привет", "start": 0.0, "end": 0.3},
        {"word": "мир", "start": 0.3, "end": 0.6},
    ]


def test_group_words_into_cues_can_disable_punctuation_stripping():
    words = [{"word": "Привет,", "start": 0.0, "end": 0.3}]

    cues = group_words_into_cues(words, max_words=4, strip_punctuation=False)

    assert cues[0]["text"] == "Привет,"
    assert cues[0]["words"] == words


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
