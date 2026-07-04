import pytest

from scripts.silence import (
    SilenceDetectionError,
    detect_silences,
    find_pauses,
    measure_loudness,
)


class FakeResult:
    def __init__(self, stderr: str, returncode: int = 0):
        self.stderr = stderr
        self.returncode = returncode
        self.stdout = ""


LOUDNORM_STDERR = """Output #0, null, to 'pipe:':
[Parsed_loudnorm_0 @ 0000017]
{
\t"input_i" : "-23.18",
\t"input_tp" : "-18.60",
\t"input_lra" : "0.20",
\t"input_thresh" : "-33.32",
\t"output_i" : "-22.98",
\t"output_tp" : "-18.12",
\t"output_lra" : "0.70",
\t"output_thresh" : "-33.09",
\t"normalization_type" : "dynamic",
\t"target_offset" : "-1.02"
}
[out#0/null @ 000001] video:0KiB audio:1881KiB subtitle:0KiB other streams:0KiB global headers:0KiB muxing overhead: unknown
size=N/A time=00:00:05.10 bitrate=N/A speed=71.8x elapsed=0:00:00.07
"""

SILENCEDETECT_STDERR = """Input #0, mov,mp4,m4a,3gp,3g2,mj2, from 'silence_test.mp4':
[Parsed_silencedetect_0 @ 000001] silence_start: 1.999909
[Parsed_silencedetect_0 @ 000001] silence_end: 3.000113 | silence_duration: 1.000204
"""


def test_measure_loudness_parses_json_from_ffmpeg_stderr():
    result = measure_loudness("in.mp4", runner=lambda *a, **k: FakeResult(LOUDNORM_STDERR))

    assert result["input_i"] == -23.18
    assert result["input_thresh"] == -33.32
    assert "normalization_type" not in result


def test_measure_loudness_raises_when_no_json_present():
    with pytest.raises(SilenceDetectionError, match="no loudnorm JSON"):
        measure_loudness("in.mp4", runner=lambda *a, **k: FakeResult("no json here"))


def test_detect_silences_parses_start_end_pairs():
    result = detect_silences(
        "in.mp4", threshold_db=-33.32, runner=lambda *a, **k: FakeResult(SILENCEDETECT_STDERR)
    )

    assert result == [{"start": 1.999909, "end": 3.000113, "duration": 1.000204}]


def test_detect_silences_returns_empty_list_when_no_silence_found():
    result = detect_silences(
        "in.mp4", threshold_db=-33.32,
        runner=lambda *a, **k: FakeResult("Input #0 ...\nno silence markers\n"),
    )

    assert result == []


def test_find_pauses_uses_adaptive_threshold_from_loudness(monkeypatch):
    calls = []

    def fake_runner(command, capture_output, text):
        calls.append(command)
        if "loudnorm=print_format=json" in command:
            return FakeResult(LOUDNORM_STDERR)
        return FakeResult(SILENCEDETECT_STDERR)

    result = find_pauses("in.mp4", min_duration=0.3, runner=fake_runner)

    assert result == [{"start": 1.999909, "end": 3.000113, "duration": 1.000204}]
    silencedetect_command = calls[1]
    assert "silencedetect=noise=-33.32dB:d=0.3" in silencedetect_command
