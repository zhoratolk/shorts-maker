import pytest

from scripts.frames import FrameExtractionError, compute_frame_timestamps, extract_frames


def test_compute_frame_timestamps_evenly_spaced():
    result = compute_frame_timestamps(0.0, 300.0, interval_seconds=120.0)

    assert result == [0.0, 120.0, 240.0]


def test_compute_frame_timestamps_exact_multiple_excludes_end():
    result = compute_frame_timestamps(0.0, 240.0, interval_seconds=120.0)

    assert result == [0.0, 120.0]


def test_compute_frame_timestamps_short_chunk_yields_single_frame():
    result = compute_frame_timestamps(100.0, 150.0, interval_seconds=120.0)

    assert result == [100.0]


def test_compute_frame_timestamps_rejects_non_positive_interval():
    with pytest.raises(ValueError, match="interval_seconds must be > 0"):
        compute_frame_timestamps(0.0, 300.0, interval_seconds=0.0)


def test_compute_frame_timestamps_rejects_non_positive_span():
    with pytest.raises(ValueError, match="chunk_end must be greater than chunk_start"):
        compute_frame_timestamps(300.0, 100.0, interval_seconds=120.0)


def test_extract_frames_writes_one_file_per_timestamp(tmp_path):
    captured = []

    class FakeResult:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_runner(command, capture_output, text):
        captured.append(command)
        return FakeResult()

    output_dir = tmp_path / "frames"
    paths = extract_frames(
        "in.mp4", [0.0, 120.0, 240.0], str(output_dir), prefix="chunk0001", runner=fake_runner
    )

    assert paths == [
        str(output_dir / "chunk0001_000.jpg"),
        str(output_dir / "chunk0001_001.jpg"),
        str(output_dir / "chunk0001_002.jpg"),
    ]
    assert len(captured) == 3
    assert captured[1][:5] == ["ffmpeg", "-y", "-ss", "120.0", "-i"]


def test_extract_frames_raises_on_ffmpeg_failure(tmp_path):
    class FakeResult:
        returncode = 1
        stdout = ""
        stderr = "no such filter"

    with pytest.raises(FrameExtractionError, match="ffmpeg failed extracting frame at 0.0s"):
        extract_frames(
            "in.mp4", [0.0], str(tmp_path), runner=lambda command, capture_output, text: FakeResult()
        )
