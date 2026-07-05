from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess


_MOMENTARY_RE = re.compile(r"t:\s*([\d.]+)\s+TARGET:.*?M:\s*(-?[\d.]+)")


def measure_momentary_loudness(path: str, runner=subprocess.run) -> list[dict]:
    """Runs ffmpeg's ebur128 filter and returns its momentary (400ms window)
    loudness samples over time - a per-instant "how loud is it right now"
    reading, sampled roughly every 100ms, used to spot sudden energy spikes
    (screams, laughs, hype yells) that a transcript-only search can miss
    entirely when the moment is wordless or Whisper mistranscribes it.
    """
    command = ["ffmpeg", "-i", path, "-map", "0:a", "-af", "ebur128", "-f", "null", "-"]
    result = runner(command, capture_output=True, text=True)
    return [
        {"time": float(match.group(1)), "momentary_lufs": float(match.group(2))}
        for match in _MOMENTARY_RE.finditer(result.stderr)
    ]


def compute_rolling_baseline(points: list[dict], window_seconds: float = 20.0) -> list[float]:
    """For each point, the median loudness over the preceding window_seconds
    (including itself) - a local "how loud has it normally been just now"
    baseline that adapts to a stream's own volume instead of a fixed dB
    guess (a loud music segment and a quiet chatting segment need different
    baselines for "spike" to mean the same thing in both).
    """
    baselines = []
    window: list[float] = []
    start_index = 0
    for index, point in enumerate(points):
        while points[index]["time"] - points[start_index]["time"] > window_seconds:
            start_index += 1
        window = [p["momentary_lufs"] for p in points[start_index : index + 1]]
        baselines.append(statistics.median(window))
    return baselines


def detect_energy_spikes(
    points: list[dict],
    threshold_db: float = 6.0,
    floor_lufs: float = -35.0,
    baseline_window_seconds: float = 20.0,
    min_duration: float = 0.3,
    merge_gap_seconds: float = 1.0,
) -> list[dict]:
    """Flags stretches where momentary loudness jumps at least threshold_db
    above its own local rolling baseline (and clears floor_lufs, so a spike
    from near-silence to merely-quiet doesn't count) - merges stretches
    separated by a short gap, and drops anything shorter than min_duration
    as a transient blip rather than a real reaction.
    """
    if not points:
        return []

    baselines = compute_rolling_baseline(points, baseline_window_seconds)
    is_spike = [
        point["momentary_lufs"] > floor_lufs and point["momentary_lufs"] - baseline >= threshold_db
        for point, baseline in zip(points, baselines)
    ]

    raw_windows = []
    index = 0
    total = len(points)
    while index < total:
        if is_spike[index]:
            window_start = index
            while index < total and is_spike[index]:
                index += 1
            raw_windows.append((points[window_start]["time"], points[index - 1]["time"]))
        else:
            index += 1

    merged_windows: list[list[float]] = []
    for start, end in raw_windows:
        if merged_windows and start - merged_windows[-1][1] <= merge_gap_seconds:
            merged_windows[-1][1] = end
        else:
            merged_windows.append([start, end])

    return [
        {"start": start, "end": end, "reason": "audio energy spike"}
        for start, end in merged_windows
        if end - start >= min_duration
    ]


def find_energy_spikes(
    path: str,
    threshold_db: float = 6.0,
    floor_lufs: float = -35.0,
    baseline_window_seconds: float = 20.0,
    min_duration: float = 0.3,
    merge_gap_seconds: float = 1.0,
    runner=subprocess.run,
) -> list[dict]:
    points = measure_momentary_loudness(path, runner=runner)
    return detect_energy_spikes(
        points,
        threshold_db=threshold_db,
        floor_lufs=floor_lufs,
        baseline_window_seconds=baseline_window_seconds,
        min_duration=min_duration,
        merge_gap_seconds=merge_gap_seconds,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Detect sudden audio-energy spikes (screams/laughs/hype yells) via EBU R128 "
        "momentary loudness, for moments a transcript-only search can miss"
    )
    parser.add_argument("input_path", help="Path to the video or audio file")
    parser.add_argument("--threshold-db", type=float, default=6.0)
    parser.add_argument("--floor-lufs", type=float, default=-35.0)
    parser.add_argument("--baseline-window-seconds", type=float, default=20.0)
    parser.add_argument("--min-duration", type=float, default=0.3)
    parser.add_argument("--merge-gap-seconds", type=float, default=1.0)
    args = parser.parse_args()

    spikes = find_energy_spikes(
        args.input_path,
        threshold_db=args.threshold_db,
        floor_lufs=args.floor_lufs,
        baseline_window_seconds=args.baseline_window_seconds,
        min_duration=args.min_duration,
        merge_gap_seconds=args.merge_gap_seconds,
    )
    print(json.dumps(spikes, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
