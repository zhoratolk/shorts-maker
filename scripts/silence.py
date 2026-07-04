from __future__ import annotations

import argparse
import json
import re
import subprocess


class SilenceDetectionError(ValueError):
    pass


def measure_loudness(path: str, runner=subprocess.run) -> dict:
    """Runs ffmpeg's loudnorm filter in JSON mode to get this file's own
    integrated loudness and EBU R128 gating threshold (input_thresh) -
    the adaptive baseline detect_silences should use instead of a guessed
    fixed dB value.
    """
    command = [
        "ffmpeg", "-i", path, "-map", "0:a",
        "-af", "loudnorm=print_format=json",
        "-f", "null", "-",
    ]
    result = runner(command, capture_output=True, text=True)
    try:
        start = result.stderr.index("{")
    except ValueError as error:
        raise SilenceDetectionError(f"no loudnorm JSON found in ffmpeg output for {path}") from error

    data, _ = json.JSONDecoder().raw_decode(result.stderr, start)
    return {key: float(value) for key, value in data.items() if key != "normalization_type"}


def detect_silences(
    path: str, threshold_db: float, min_duration: float = 0.5, runner=subprocess.run
) -> list[dict]:
    """Runs ffmpeg's silencedetect filter and returns every silent segment
    at least min_duration seconds long as {"start", "end", "duration"}.
    """
    command = [
        "ffmpeg", "-i", path, "-map", "0:a",
        "-af", f"silencedetect=noise={threshold_db}dB:d={min_duration}",
        "-f", "null", "-",
    ]
    result = runner(command, capture_output=True, text=True)
    starts = [float(value) for value in re.findall(r"silence_start:\s*(-?[\d.]+)", result.stderr)]
    ends = [float(value) for value in re.findall(r"silence_end:\s*(-?[\d.]+)", result.stderr)]
    return [
        {"start": start, "end": end, "duration": round(end - start, 6)}
        for start, end in zip(starts, ends)
    ]


def find_pauses(path: str, min_duration: float = 0.5, runner=subprocess.run) -> list[dict]:
    """Adaptive pause detection: measures this file's own gating threshold
    first (measure_loudness), then feeds it into detect_silences instead of
    a fixed dB guess - the threshold that counts as "silence" varies a lot
    between a quiet mic and a loud stream, so a fixed value under/over-detects.
    """
    loudness = measure_loudness(path, runner=runner)
    return detect_silences(path, threshold_db=loudness["input_thresh"], min_duration=min_duration, runner=runner)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Detect pauses (silence) in a video/audio file using an adaptive threshold"
    )
    parser.add_argument("input_path", help="Path to the video or audio file")
    parser.add_argument(
        "--min-duration", type=float, default=0.5,
        help="Minimum pause duration in seconds to report (default: 0.5)",
    )
    args = parser.parse_args()

    pauses = find_pauses(args.input_path, min_duration=args.min_duration)
    print(json.dumps(pauses, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
