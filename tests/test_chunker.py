import json
from pathlib import Path

import pytest

from scripts.chunker import Chunk, split_into_chunks, write_chunks


def test_split_into_chunks_empty_segments_returns_empty_list():
    assert split_into_chunks([], chunk_minutes=35) == []


def test_split_into_chunks_zero_or_negative_chunk_minutes_raises():
    with pytest.raises(ValueError, match="chunk_minutes"):
        split_into_chunks([{"start": 0.0, "end": 1.0, "text": "hi"}], chunk_minutes=0)


def test_split_into_chunks_groups_segments_by_window():
    segments = [
        {"start": 0.0, "end": 5.0, "text": "a"},
        {"start": 30.0, "end": 35.0, "text": "b"},
        {"start": 90.0, "end": 95.0, "text": "c"},
        {"start": 120.0, "end": 125.0, "text": "d"},
    ]

    chunks = split_into_chunks(segments, chunk_minutes=1)

    assert chunks == [
        Chunk(index=0, start=0.0, end=35.0, segments=[segments[0], segments[1]]),
        Chunk(index=1, start=90.0, end=95.0, segments=[segments[2]]),
        Chunk(index=2, start=120.0, end=125.0, segments=[segments[3]]),
    ]


def test_split_into_chunks_single_segment():
    segments = [{"start": 0.0, "end": 2.0, "text": "hello"}]

    chunks = split_into_chunks(segments, chunk_minutes=35)

    assert chunks == [Chunk(index=0, start=0.0, end=2.0, segments=segments)]


def test_write_chunks_creates_one_file_per_chunk(tmp_path):
    chunks = [
        Chunk(index=0, start=0.0, end=5.0, segments=[{"start": 0.0, "end": 5.0, "text": "a"}]),
        Chunk(index=1, start=90.0, end=95.0, segments=[{"start": 90.0, "end": 95.0, "text": "c"}]),
    ]

    output_dir = str(tmp_path / "chunks")
    paths = write_chunks(chunks, output_dir)

    assert paths == [
        str(Path(output_dir) / "chunk_0000.json"),
        str(Path(output_dir) / "chunk_0001.json"),
    ]
    written = json.loads(Path(paths[0]).read_text(encoding="utf-8"))
    assert written == {
        "index": 0,
        "start": 0.0,
        "end": 5.0,
        "segments": [{"start": 0.0, "end": 5.0, "text": "a"}],
    }
