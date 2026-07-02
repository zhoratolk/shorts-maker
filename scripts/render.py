from __future__ import annotations

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
