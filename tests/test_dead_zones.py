"""Finding the stretches of a session where nothing clippable can happen."""

import pytest

from scripts.dead_zones import (VOCABULARIES, bucket_ratios, dead_spans, merge_spans,
                                smoothed)


def words_at(times_and_words):
    return [{"start": at, "word": word} for at, word in times_and_words]


def test_bucket_ratios_counts_the_share_of_matching_words():
    pattern = VOCABULARIES["barotrauma"]
    words = words_at([(0.0, "купить"), (1.0, "пушку"), (2.0, "и"), (3.0, "поплыли")])
    assert bucket_ratios(words, pattern, step=120.0) == [(0.0, 0.5)]


def test_bucket_ratios_keeps_buckets_apart():
    pattern = VOCABULARIES["barotrauma"]
    words = words_at([(10.0, "продай"), (130.0, "плыви"), (140.0, "влево")])
    assert bucket_ratios(words, pattern, step=120.0) == [(0.0, 1.0), (120.0, 0.0)]


def test_smoothed_shortens_at_the_ends_rather_than_padding():
    # Padding with zeros would make the first and last buckets look livelier than they
    # are, and a session's shopping usually sits exactly there.
    series = [(0.0, 1.0), (120.0, 1.0), (240.0, 1.0)]
    assert smoothed(series, 3) == [(0.0, 1.0), (120.0, 1.0), (240.0, 1.0)]


def test_smoothed_averages_over_the_window():
    series = [(0.0, 0.0), (120.0, 1.0), (240.0, 0.0)]
    assert smoothed(series, 3)[1] == (120.0, pytest.approx(1 / 3))


def test_merge_spans_joins_neighbours_and_closes_the_last_bucket():
    # A span ends at the END of its last bucket, not at the bucket's start - otherwise
    # every span is reported two minutes shorter than it is.
    assert merge_spans([0.0, 120.0, 240.0], step=120.0) == [(0.0, 360.0)]


def test_merge_spans_splits_on_a_real_gap():
    assert merge_spans([0.0, 600.0], step=120.0) == [(0.0, 120.0), (600.0, 720.0)]


def test_dead_spans_finds_a_long_stretch_of_shop_talk():
    words = []
    # Twenty minutes of ordinary play, then twenty of shopping.
    for i in range(600):
        words.append({"start": i * 2.0, "word": "плыви"})
    for i in range(600):
        words.append({"start": 1200.0 + i * 2.0,
                      "word": "купить" if i % 20 == 0 else "так"})
    spans = dead_spans(words)
    assert spans, "участок закупки не найден"
    start, end = spans[0]
    assert start >= 600.0, "начало уехало в геймплейную часть"
    assert end >= 1800.0


def test_dead_spans_is_quiet_on_a_recording_without_one():
    words = [{"start": i * 2.0, "word": "плыви"} for i in range(1800)]
    assert dead_spans(words) == []


def test_dead_spans_rejects_a_game_with_no_vocabulary():
    with pytest.raises(ValueError, match="нет словаря"):
        dead_spans([{"start": 0.0, "word": "x"}], game="minecraft")
