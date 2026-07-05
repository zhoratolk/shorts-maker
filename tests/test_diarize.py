import json

from scripts import diarize as diarize_module
from scripts.diarize import (
    assign_speaker_to_segment,
    attach_speakers_to_segments,
    is_diarized,
    label_speakers_by_first_appearance,
    diarize_transcript,
)


def test_is_diarized_false_when_no_segments():
    assert is_diarized({"segments": []}) is False


def test_is_diarized_false_when_segments_missing_speaker():
    assert is_diarized({"segments": [{"start": 0.0, "end": 1.0}]}) is False


def test_is_diarized_true_when_all_segments_have_speaker():
    transcript = {"segments": [{"start": 0.0, "end": 1.0, "speaker": "Голос 1"}]}
    assert is_diarized(transcript) is True


def test_label_speakers_by_first_appearance_orders_by_start():
    turns = [
        {"start": 5.0, "end": 6.0, "speaker": "SPEAKER_01"},
        {"start": 0.0, "end": 1.0, "speaker": "SPEAKER_00"},
        {"start": 10.0, "end": 11.0, "speaker": "SPEAKER_01"},
    ]

    labels = label_speakers_by_first_appearance(turns)

    assert labels == {"SPEAKER_00": "Голос 1", "SPEAKER_01": "Голос 2"}


def test_assign_speaker_to_segment_picks_max_overlap():
    turns = [
        {"start": 0.0, "end": 4.0, "speaker": "A"},
        {"start": 4.0, "end": 10.0, "speaker": "B"},
    ]

    # overlap with A = 3.0s, overlap with B = 1.0s
    assert assign_speaker_to_segment({"start": 1.0, "end": 5.0}, turns) == "A"


def test_assign_speaker_to_segment_falls_back_to_nearest_when_no_overlap():
    turns = [
        {"start": 0.0, "end": 2.0, "speaker": "A"},
        {"start": 10.0, "end": 12.0, "speaker": "B"},
    ]

    # gap segment at 2.0-3.0, closer to A's end (2.0) than B's start (10.0)
    assert assign_speaker_to_segment({"start": 2.5, "end": 3.0}, turns) == "A"


def test_assign_speaker_to_segment_picks_max_overlap_when_spanning_two_turns():
    turns = [
        {"start": 0.0, "end": 4.0, "speaker": "A"},
        {"start": 4.0, "end": 10.0, "speaker": "B"},
    ]

    # overlap with A = 0.5s, overlap with B = 4.0s
    assert assign_speaker_to_segment({"start": 3.5, "end": 8.0}, turns) == "B"


def test_assign_speaker_to_segment_returns_none_when_no_turns():
    assert assign_speaker_to_segment({"start": 0.0, "end": 1.0}, []) is None


def test_attach_speakers_to_segments_preserves_existing_fields():
    segments = [{"start": 0.0, "end": 1.0, "text": "hi"}]
    turns = [{"start": 0.0, "end": 1.0, "speaker": "Голос 1"}]

    labeled = attach_speakers_to_segments(segments, turns)

    assert labeled == [{"start": 0.0, "end": 1.0, "text": "hi", "speaker": "Голос 1"}]


def test_diarize_transcript_skips_pipeline_when_already_diarized(tmp_path, monkeypatch):
    transcript_path = tmp_path / "video.json"
    transcript = {
        "video_path": "video.mp4",
        "segments": [{"start": 0.0, "end": 1.0, "text": "hi", "speaker": "Голос 1"}],
    }
    transcript_path.write_text(json.dumps(transcript), encoding="utf-8")

    def boom(*args, **kwargs):
        raise AssertionError("should not run diarization pipeline when already cached")

    monkeypatch.setattr(diarize_module, "extract_audio_wav", boom)
    monkeypatch.setattr(diarize_module, "run_diarization_pipeline", boom)

    result = diarize_transcript("video.mp4", str(transcript_path), pipeline=None)

    assert result == transcript


def test_diarize_transcript_labels_segments_and_writes_cache(tmp_path, monkeypatch):
    transcript_path = tmp_path / "video.json"
    transcript = {
        "video_path": "video.mp4",
        "segments": [
            {"start": 0.0, "end": 2.0, "text": "hello"},
            {"start": 2.0, "end": 4.0, "text": "world"},
        ],
    }
    transcript_path.write_text(json.dumps(transcript), encoding="utf-8")

    monkeypatch.setattr(diarize_module, "extract_audio_wav", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        diarize_module,
        "run_diarization_pipeline",
        lambda *args, **kwargs: [
            {"start": 0.0, "end": 2.0, "speaker": "SPEAKER_00"},
            {"start": 2.0, "end": 4.0, "speaker": "SPEAKER_01"},
        ],
    )

    result = diarize_transcript("video.mp4", str(transcript_path), pipeline=object())

    assert result["segments"] == [
        {"start": 0.0, "end": 2.0, "text": "hello", "speaker": "Голос 1"},
        {"start": 2.0, "end": 4.0, "text": "world", "speaker": "Голос 2"},
    ]
    on_disk = json.loads(transcript_path.read_text(encoding="utf-8"))
    assert on_disk["segments"][0]["speaker"] == "Голос 1"
