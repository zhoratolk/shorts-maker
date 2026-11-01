"""Which words were on screen when viewers left."""

import json
import os

from scripts.drop_phrases import (
    annotate_drop_phrases,
    clip_stem,
    find_words_file,
    phrase_at,
)
from scripts.retention import _load_tag_map, render_retention_markdown, summarize_retention

WORDS = [
    {"word": " Я", "start": 0.0, "end": 0.3},
    {"word": " без", "start": 0.3, "end": 0.6},
    {"word": " казны", "start": 0.6, "end": 1.0},
    {"word": " кайфую", "start": 4.0, "end": 4.6},
    {"word": " вообще.", "start": 4.6, "end": 5.2},
    {"word": " Потом", "start": 9.0, "end": 9.4},
]


def _write_words(root, video_stem, clip, words=WORDS):
    folder = root / video_stem / "subtitles"
    folder.mkdir(parents=True)
    path = folder / f"{clip}_words.json"
    path.write_text(json.dumps(words, ensure_ascii=False), encoding="utf-8")
    return path


def _record(at, duration=10.0, stem="clip-1"):
    return {
        "video_id": "vid1",
        "title": "T",
        "clip_stem": stem,
        "duration": duration,
        "analysis": {"biggest_drop": {"at": at, "delta": 0.2}},
    }


def test_clip_stem_accepts_windows_and_posix_paths():
    assert clip_stem("F:\\Готовое\\Шортс\\clip-1.mp4") == "clip-1"
    assert clip_stem("/media/clips/clip-1.mp4") == "clip-1"
    assert clip_stem("") is None
    assert clip_stem(None) is None


def test_phrase_at_takes_the_stretch_leading_up_to_the_second():
    assert phrase_at(WORDS, 5.0) == "кайфую вообще."


def test_phrase_at_ignores_words_not_yet_spoken():
    assert "Потом" not in phrase_at(WORDS, 5.0)


def test_phrase_at_silence_is_empty():
    assert phrase_at(WORDS, 8.0) == ""


def test_find_words_file_missing_is_none(tmp_path):
    assert find_words_file("nope", root=str(tmp_path)) is None


def test_find_words_file_prefers_the_newest_render(tmp_path):
    old = _write_words(tmp_path, "stream-a", "clip-1")
    new = _write_words(tmp_path, "stream-b", "clip-1")
    os.utime(old, (1_000_000, 1_000_000))
    assert find_words_file("clip-1", root=str(tmp_path)) == new


def test_annotate_places_the_drop_on_the_words(tmp_path):
    _write_words(tmp_path, "stream-a", "clip-1")
    records = [_record(at=0.5)]  # 0.5 of 10 s = 5 s

    assert annotate_drop_phrases(records, root=str(tmp_path)) == 1
    assert records[0]["drop"] == {"second": 5.0, "phrase": "кайфую вообще."}


def test_annotate_falls_back_to_last_word_end_for_length(tmp_path):
    _write_words(tmp_path, "stream-a", "clip-1")
    record = _record(at=0.5, duration=None)  # 0.5 of 9.4 s = 4.7 s

    annotate_drop_phrases([record], root=str(tmp_path))

    assert record["drop"]["second"] == 4.7


def test_annotate_leaves_records_it_cannot_place_untouched(tmp_path):
    records = [
        _record(at=0.5, stem="no-such-clip"),
        {"video_id": "v2", "analysis": {"biggest_drop": None}, "clip_stem": "clip-1"},
        {"video_id": "v3", "analysis": {"biggest_drop": {"at": 0.5, "delta": 0.1}}},
    ]
    _write_words(tmp_path, "stream-a", "clip-1")

    assert annotate_drop_phrases(records, root=str(tmp_path)) == 0
    assert all("drop" not in record for record in records)


def test_annotate_survives_a_corrupt_words_file(tmp_path):
    path = _write_words(tmp_path, "stream-a", "clip-1")
    path.write_text("{not json", encoding="utf-8")
    assert annotate_drop_phrases([_record(at=0.5)], root=str(tmp_path)) == 0


def test_tag_map_carries_the_clip_stem(tmp_path):
    queue = {"entries": [{"video_id": "vid1", "moment_tag": "clutch", "source_duration": 42.0,
                          "video_path": "F:\\Готовое\\Шортс\\clip-1.mp4"}]}
    path = tmp_path / "queue.json"
    path.write_text(json.dumps(queue), encoding="utf-8")

    assert _load_tag_map(str(path))["vid1"]["clip_stem"] == "clip-1"


def test_markdown_names_the_phrase_at_the_drop():
    record = _record(at=0.5)
    record["analysis"].update({
        "intro_retention": 0.9, "average_watch": 0.5, "end_retention": 0.3,
        "length_signal": "ok", "cliffs": [0.5],
    })
    record["drop"] = {"second": 5.0, "phrase": "кайфую вообще."}

    markdown = render_retention_markdown([record], summarize_retention([record]))

    assert "while saying: «кайфую вообще.»" in markdown
