"""Motion profile of a whole recording: how much the picture changes, second by second.

The cheapest possible answer to "is anything happening here", and the one that has to
be ruled out before a vision model is worth its weight. crop_focus.py already computes
this quantity - the mean absolute difference between consecutive grayscale frames - and
already has a threshold for it (STATIC_MEAN_DIFF = 1.2, "a still picture with a voice
over it: a scoreboard, a menu, a map screen"). It applies it to one finished clip. This
sweeps the same measurement across an entire recording.

One ffmpeg pass, not one per window: seeking to eight hundred windows separately costs
eight hundred decoder startups, while decoding the file once at two frames a second and
bucketing afterwards costs one. The frames are 160x90 grayscale and never touch the
disk - the same shape crop_focus.sample_frames pipes.

    python experiments/motion_profile.py --video vod.mkv --out profile.json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

WIDTH, HEIGHT = 160, 90
FRAME_BYTES = WIDTH * HEIGHT


def frame_stream(video: str, fps: float, start: float | None, duration: float | None):
    """Raw grayscale frames from one decode pass, yielded as bytes."""
    command = ["ffmpeg", "-nostdin", "-v", "error"]
    if start is not None:
        command += ["-ss", f"{start:.3f}"]
    command += ["-i", video]
    if duration is not None:
        command += ["-t", f"{duration:.3f}"]
    command += [
        "-vf", f"fps={fps},scale={WIDTH}:{HEIGHT},format=gray",
        "-f", "rawvideo", "-",
    ]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        while True:
            buffer = process.stdout.read(FRAME_BYTES)
            if len(buffer) < FRAME_BYTES:
                break
            yield buffer
    finally:
        process.stdout.close()
        process.wait()


def mean_abs_diff(a: bytes, b: bytes) -> float:
    """Mean |a - b| over the frame, on the 0-255 scale crop_focus uses.

    Plain Python rather than numpy: this runs inside the pipeline's container, the
    loop is 14400 bytes per frame pair, and the decode dominates either way.
    """
    total = 0
    for x, y in zip(a, b):
        total += x - y if x > y else y - x
    return total / FRAME_BYTES


def profile(video: str, fps: float, window: float,
            start: float | None = None, duration: float | None = None) -> list[dict]:
    """Mean inter-frame difference per `window` seconds of the recording."""
    per_window: list[dict] = []
    bucket: list[float] = []
    previous: bytes | None = None
    index = 0
    offset = start or 0.0

    for frame in frame_stream(video, fps, start, duration):
        if previous is not None:
            bucket.append(mean_abs_diff(previous, frame))
        previous = frame
        index += 1
        at = index / fps
        if at >= (len(per_window) + 1) * window:
            per_window.append({
                "at": round(offset + len(per_window) * window, 2),
                "mean_diff": round(sum(bucket) / len(bucket), 4) if bucket else 0.0,
                "min_diff": round(min(bucket), 4) if bucket else 0.0,
                "frames": len(bucket) + 1,
            })
            bucket = []
    if bucket:
        per_window.append({
            "at": round(offset + len(per_window) * window, 2),
            "mean_diff": round(sum(bucket) / len(bucket), 4),
            "min_diff": round(min(bucket), 4),
            "frames": len(bucket) + 1,
        })
    return per_window


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--fps", type=float, default=2.0)
    parser.add_argument("--window", type=float, default=20.0)
    parser.add_argument("--start", type=float, default=None)
    parser.add_argument("--duration", type=float, default=None)
    args = parser.parse_args()

    began = time.time()
    windows = profile(args.video, args.fps, args.window, args.start, args.duration)
    elapsed = time.time() - began
    covered = sum(w["frames"] for w in windows) / args.fps

    Path(args.out).write_text(json.dumps({
        "video": args.video, "fps": args.fps, "window": args.window,
        "seconds_covered": round(covered, 1), "wall_seconds": round(elapsed, 1),
        "windows": windows,
    }, ensure_ascii=False), encoding="utf-8")
    print(f"{len(windows)} окон, {covered:.0f} с видео за {elapsed:.0f} с "
          f"({covered / elapsed if elapsed else 0:.0f}x реального времени)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
