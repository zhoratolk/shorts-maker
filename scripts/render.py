from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

TARGET_WIDTH = 1080
TARGET_HEIGHT = 1920


class RenderError(ValueError):
    pass


def clamp_clip_bounds(start: float, end: float, video_duration: float) -> tuple[float, float]:
    if video_duration <= 0:
        raise RenderError("video_duration must be > 0")
    clamped_start = max(0.0, start)
    clamped_end = min(end, video_duration)
    if clamped_start >= clamped_end:
        raise RenderError(
            f"clip bounds invalid after clamping: start={clamped_start}, end={clamped_end}"
        )
    return clamped_start, clamped_end


def compute_crop_filter(crop_style: str, src_width: int, src_height: int) -> str:
    if crop_style == "zoom":
        crop_width = min(round(src_height * TARGET_WIDTH / TARGET_HEIGHT), src_width)
        x_offset = round((src_width - crop_width) / 2)
        return f"crop={crop_width}:{src_height}:{x_offset}:0,scale={TARGET_WIDTH}:{TARGET_HEIGHT}"

    if crop_style == "pad":
        scaled_height = round(src_height * TARGET_WIDTH / src_width)
        total_pad = TARGET_HEIGHT - scaled_height
        top_pad = round(total_pad * 0.3)
        return f"scale={TARGET_WIDTH}:{scaled_height},pad={TARGET_WIDTH}:{TARGET_HEIGHT}:0:{top_pad}:black"

    if crop_style == "original-16:9":
        scaled_height = round(src_height * TARGET_WIDTH / src_width)
        top_pad = round((TARGET_HEIGHT - scaled_height) / 2)
        return f"scale={TARGET_WIDTH}:{scaled_height},pad={TARGET_WIDTH}:{TARGET_HEIGHT}:0:{top_pad}:black"

    raise RenderError(
        f"crop_style must be a resolved value (zoom/pad/original-16:9), got {crop_style!r}. "
        "'auto' must be resolved to a concrete style before reaching render.py."
    )


def build_ffmpeg_command(
    input_path: str,
    output_path: str,
    start: float,
    end: float,
    crop_filter: str,
    subtitles_path: str | None = None,
) -> list[str]:
    duration = end - start
    video_filter = crop_filter
    if subtitles_path is not None:
        escaped_path = subtitles_path.replace("\\", "/").replace(":", "\\:")
        video_filter = f"{video_filter},subtitles='{escaped_path}'"

    return [
        "ffmpeg", "-y",
        "-ss", str(start),
        "-i", input_path,
        "-t", str(duration),
        "-vf", video_filter,
        "-c:v", "libx264",
        "-c:a", "aac",
        output_path,
    ]


def probe_video(video_path: str, runner=subprocess.run) -> dict:
    command = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", video_path,
    ]
    result = runner(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise RenderError(f"ffprobe failed for {video_path}: {result.stderr}")

    data = json.loads(result.stdout)
    video_stream = next(stream for stream in data["streams"] if stream["codec_type"] == "video")
    return {
        "duration": float(data["format"]["duration"]),
        "width": int(video_stream["width"]),
        "height": int(video_stream["height"]),
    }


def render_clip(
    input_path: str,
    output_path: str,
    plan_entry: dict,
    video_duration: float,
    src_width: int,
    src_height: int,
    runner=subprocess.run,
) -> list[str]:
    start, end = clamp_clip_bounds(plan_entry["start"], plan_entry["end"], video_duration)
    crop_filter = compute_crop_filter(plan_entry["crop_style"], src_width, src_height)
    subtitles_path = plan_entry.get("subtitles_path")
    command = build_ffmpeg_command(input_path, output_path, start, end, crop_filter, subtitles_path)

    result = runner(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise RenderError(f"ffmpeg failed for {output_path}: {result.stderr}")
    return command


def main() -> None:
    parser = argparse.ArgumentParser(description="Render approved clips from a PLAN.json")
    parser.add_argument("input_video", help="Path to the source recording")
    parser.add_argument("plan_json", help="Path to PLAN.json: a list of clip plan entries")
    parser.add_argument("output_dir", help="Directory to write rendered clips into")
    args = parser.parse_args()

    video_info = probe_video(args.input_video)
    plan = json.loads(Path(args.plan_json).read_text(encoding="utf-8"))

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    for index, entry in enumerate(plan):
        output_path = str(output_dir / entry.get("output_filename", f"clip_{index:04d}.mp4"))
        render_clip(
            args.input_video, output_path, entry,
            video_duration=video_info["duration"],
            src_width=video_info["width"],
            src_height=video_info["height"],
        )
        print(output_path)


if __name__ == "__main__":
    main()
