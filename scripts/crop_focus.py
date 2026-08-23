"""Automatic horizontal framing for `zoom` clips.

A 9:16 crop out of a 16:9 recording throws away about two thirds of the
width, so *where* the window sits is a real editorial decision - and it is one
that is easy to skip, because omitting the field still renders a perfectly
valid (dead-centre) clip. This module removes the chance to skip it: it
measures where the picture actually lives and answers with a `crop_focus_x`,
or with `crop_focus_keyframes` when the interesting part moves across the
frame during the clip.

The measurement is deliberately crude and dependency-free: sample the clip's
own frames as small grayscale stills, score each pixel column by how much it
CHANGES between samples (motion - a driving view, a fight, a character
walking) plus how much detail it holds (a UI panel full of text beats an
empty black margin), then slide the crop window across and keep the best
position. Motion is weighted well above detail on purpose: a static HUD is
information, but a moving picture is what holds a viewer.

Every entry point fails open - any ffmpeg problem, an unreadable stream, a
degenerate frame - returns None, and the caller renders the centre crop it
would have rendered anyway.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

SAMPLE_WIDTH = 160
SAMPLE_HEIGHT = 90
SAMPLE_FPS = 2.0
# A column that changes is worth much more than one that is merely busy.
MOTION_WEIGHT = 4.0
DETAIL_WEIGHT = 1.0
# Below this mean inter-frame difference (0-255 scale) the clip is a still
# picture with a voice over it - a scoreboard, a menu, a map screen.
STATIC_MEAN_DIFF = 1.2
# Panning is only worth it when the best window genuinely travels; anything
# smaller reads as jitter and is better served by one fixed focus_x.
PAN_MIN_SPREAD_PCT = 18.0
MAX_KEYFRAMES = 3


class CropFocusError(RuntimeError):
    pass


def sample_frames(
    video_path: str,
    start: float,
    duration: float,
    *,
    width: int = SAMPLE_WIDTH,
    height: int = SAMPLE_HEIGHT,
    fps: float = SAMPLE_FPS,
    runner=subprocess.run,
) -> list[bytes]:
    """Grayscale stills for [start, start+duration), one every 1/fps seconds.

    Piped as rawvideo instead of written out as files: a few hundred 160x90
    frames are smaller than the JPEG overhead of storing them, and there is
    nothing to clean up afterwards.
    """
    if duration <= 0:
        return []
    command = [
        "ffmpeg", "-v", "error",
        "-ss", f"{start:.3f}", "-i", video_path, "-t", f"{duration:.3f}",
        "-vf", f"fps={fps},scale={width}:{height},format=gray",
        "-f", "rawvideo", "-",
    ]
    result = runner(command, capture_output=True)
    if result.returncode != 0:
        stderr = result.stderr or b""
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", "replace")
        raise CropFocusError(stderr[-400:])
    frame_size = width * height
    data = result.stdout or b""
    return [
        data[i:i + frame_size]
        for i in range(0, len(data) - frame_size + 1, frame_size)
    ]


def frame_contributions(
    frames: list[bytes], *, width: int = SAMPLE_WIDTH, height: int = SAMPLE_HEIGHT
) -> list[tuple[list[float], list[float], float, int]]:
    """One (motion, detail, diff_total, diff_pixels) tuple per frame.

    Split out from the scoring so the pixels are walked exactly once: the
    whole-clip score and every per-bucket score are then plain sums over these
    contributions, instead of re-reading the same frames three more times.
    """
    contributions = []
    for index, frame in enumerate(frames):
        previous = frames[index - 1] if index else None
        motion = [0.0] * width
        detail = [0.0] * width
        diff_total = 0.0
        for row in range(height):
            base = row * width
            for col in range(1, width):
                detail[col] += abs(frame[base + col] - frame[base + col - 1])
            if previous is not None:
                for col in range(width):
                    delta = abs(frame[base + col] - previous[base + col])
                    motion[col] += delta
                    diff_total += delta
        if width > 1:
            detail[0] = detail[1]
        contributions.append(
            (motion, detail, diff_total, width * height if previous is not None else 0)
        )
    return contributions


def aggregate_contributions(
    contributions: list[tuple[list[float], list[float], float, int]],
) -> tuple[list[float], float]:
    """Per-column interest score plus the mean inter-frame difference.

    The second value is what tells a moving clip from a still screenshot with
    a voice over it, and it falls out of the same numbers as the first.
    """
    if not contributions:
        return [], 0.0
    width = len(contributions[0][0])
    scores = [0.0] * width
    diff_total = 0.0
    diff_pixels = 0
    for motion, detail, frame_diff, pixels in contributions:
        for col in range(width):
            scores[col] += MOTION_WEIGHT * motion[col] + DETAIL_WEIGHT * detail[col]
        diff_total += frame_diff
        diff_pixels += pixels
    return scores, (diff_total / diff_pixels if diff_pixels else 0.0)


def column_scores(
    frames: list[bytes], *, width: int = SAMPLE_WIDTH, height: int = SAMPLE_HEIGHT
) -> tuple[list[float], float]:
    """Convenience wrapper over the two functions above, for a caller that has
    frames in hand and does not need the per-frame breakdown."""
    return aggregate_contributions(frame_contributions(frames, width=width, height=height))


def best_focus_pct(scores: list[float], window: int) -> float | None:
    """Position (0-100, the same scale as crop_focus_x) of the highest-scoring
    window. None when the frame carries no signal at all, so the caller keeps
    the centre crop rather than committing to an arbitrary edge.
    """
    if not scores or window <= 0 or window >= len(scores):
        return None
    if not any(scores):
        return None
    running = sum(scores[:window])
    best_total, best_left = running, 0
    for left in range(1, len(scores) - window + 1):
        running += scores[left + window - 1] - scores[left - 1]
        if running > best_total:
            best_total, best_left = running, left
    return round(best_left / (len(scores) - window) * 100.0, 1)


def _bucket(items: list, count: int) -> list[list]:
    if count <= 1 or len(items) < count:
        return [items]
    size = len(items) / count
    return [items[round(i * size):round((i + 1) * size)] for i in range(count)]


def plan_focus(
    video_path: str,
    segments: list[tuple[float, float]],
    src_width: int,
    src_height: int,
    *,
    crop_width: int,
    max_keyframes: int = MAX_KEYFRAMES,
    pan_min_spread: float = PAN_MIN_SPREAD_PCT,
    sample_width: int = SAMPLE_WIDTH,
    sample_height: int = SAMPLE_HEIGHT,
    sample_fps: float = SAMPLE_FPS,
    runner=subprocess.run,
) -> dict | None:
    """`{"focus_x": pct, "static": bool}` or
    `{"focus_keyframes": [[at, pct], ...], "static": bool}`, or None when
    nothing could be measured.

    `segments` are the clip's absolute source windows (its keep_segments, or
    one [start, end] pair). Keyframe timestamps come back on the clip's own
    RENDERED timeline, which is what the plan entry needs: cut pauses simply
    never contribute samples.
    """
    window = max(1, round(sample_width * crop_width / src_width))
    if window >= sample_width:
        return None
    samples: list[tuple[float, bytes]] = []
    rendered_offset = 0.0
    try:
        for seg_start, seg_end in segments:
            duration = seg_end - seg_start
            frames = sample_frames(
                video_path, seg_start, duration,
                width=sample_width, height=sample_height, fps=sample_fps, runner=runner,
            )
            for index, frame in enumerate(frames):
                samples.append((rendered_offset + index / sample_fps, frame))
            rendered_offset += duration
    except (CropFocusError, OSError):
        return None
    if len(samples) < 2:
        return None

    contributions = frame_contributions(
        [frame for _, frame in samples], width=sample_width, height=sample_height
    )
    scores, mean_diff = aggregate_contributions(contributions)
    overall = best_focus_pct(scores, window)
    if overall is None:
        return None
    static = mean_diff < STATIC_MEAN_DIFF

    indexed = list(zip([at for at, _ in samples], contributions))
    buckets = _bucket(indexed, min(max_keyframes, max(1, len(indexed) // 4)))
    per_bucket: list[tuple[float, float]] = []
    for bucket in buckets:
        if len(bucket) < 2:
            continue
        bucket_scores, _ = aggregate_contributions([c for _, c in bucket])
        pct = best_focus_pct(bucket_scores, window)
        if pct is None:
            continue
        midpoint = round((bucket[0][0] + bucket[-1][0]) / 2, 2)
        per_bucket.append((midpoint, pct))

    if len(per_bucket) >= 2:
        spread = max(pct for _, pct in per_bucket) - min(pct for _, pct in per_bucket)
        if spread >= pan_min_spread:
            return {
                "focus_keyframes": [[at, pct] for at, pct in per_bucket],
                "static": static,
            }
    return {"focus_x": overall, "static": static}


def main() -> None:
    import argparse
    import json

    parser = argparse.ArgumentParser(
        description="Measure where a zoom clip's picture sits and print the crop "
                    "framing for its plan entry",
    )
    parser.add_argument("video")
    parser.add_argument("segments_json", help="[[start, end], ...] absolute source seconds")
    parser.add_argument("--src-width", type=int, required=True)
    parser.add_argument("--src-height", type=int, required=True)
    parser.add_argument("--crop-width", type=int, required=True)
    args = parser.parse_args()

    raw = json.loads(Path(args.segments_json).read_text(encoding="utf-8"))
    segments = [(float(a), float(b)) for a, b in raw]
    print(json.dumps(
        plan_focus(
            args.video, segments, args.src_width, args.src_height,
            crop_width=args.crop_width,
        ),
        ensure_ascii=False,
    ))


if __name__ == "__main__":
    main()
