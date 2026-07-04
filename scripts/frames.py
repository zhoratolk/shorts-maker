from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


class FrameExtractionError(ValueError):
    pass


def compute_frame_timestamps(chunk_start: float, chunk_end: float, interval_seconds: float) -> list[float]:
    """Evenly spaced sample points within [chunk_start, chunk_end), interval_seconds
    apart, starting at chunk_start - one still frame per point is enough for a
    human (or Claude) to tell what game/topic is on screen at that point in
    the chunk, without decoding video.
    """
    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be > 0")
    if chunk_end <= chunk_start:
        raise ValueError("chunk_end must be greater than chunk_start")

    timestamps = []
    t = chunk_start
    while t < chunk_end:
        timestamps.append(round(t, 3))
        t += interval_seconds
    return timestamps


def extract_frames(
    video_path: str, timestamps: list[float], output_dir: str, prefix: str = "frame", runner=subprocess.run
) -> list[str]:
    """Extracts one JPEG still per timestamp via ffmpeg (-ss before -i: fast
    seek, no full decode). Returns the written paths in timestamp order.
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    paths = []
    for index, timestamp in enumerate(timestamps):
        output_path = str(Path(output_dir) / f"{prefix}_{index:03d}.jpg")
        command = [
            "ffmpeg", "-y",
            "-ss", str(timestamp),
            "-i", video_path,
            "-frames:v", "1",
            "-q:v", "2",
            output_path,
        ]
        result = runner(command, capture_output=True, text=True)
        if result.returncode != 0:
            raise FrameExtractionError(f"ffmpeg failed extracting frame at {timestamp}s: {result.stderr}")
        paths.append(output_path)
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract evenly-spaced still frames from a chunk's time range for visual review"
    )
    parser.add_argument("video_path", help="Path to the source video")
    parser.add_argument("chunk_start", type=float, help="Chunk start, seconds")
    parser.add_argument("chunk_end", type=float, help="Chunk end, seconds")
    parser.add_argument("output_dir", help="Directory to write frame_NNN.jpg files into")
    parser.add_argument(
        "--interval-seconds", type=float, default=120.0,
        help="Seconds between sampled frames (default: 120)",
    )
    parser.add_argument("--prefix", default="frame", help="Output filename prefix (default: frame)")
    args = parser.parse_args()

    timestamps = compute_frame_timestamps(args.chunk_start, args.chunk_end, args.interval_seconds)
    paths = extract_frames(args.video_path, timestamps, args.output_dir, args.prefix)
    for path in paths:
        print(path)


if __name__ == "__main__":
    main()
