from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

TARGET_WIDTH = 1080
TARGET_HEIGHT = 1920

NAMED_ASS_COLORS = {
    "white": "&H00FFFFFF",
    "black": "&H00000000",
    "yellow": "&H0000FFFF",
    "red": "&H000000FF",
    "green": "&H0000FF00",
    "blue": "&H00FF0000",
    "cyan": "&H00FFFF00",
    "magenta": "&H00FF00FF",
}

SUBTITLE_ALIGNMENT = {"bottom": 2, "top": 8, "center": 5}
SUBTITLE_MARGIN_V = {"bottom": 280, "top": 120, "center": 0}


class RenderError(ValueError):
    pass


def ass_color(color: str) -> str:
    """Converts a named color or #RRGGBB hex string to ASS &HAABBGGRR format."""
    if color.startswith("#"):
        hex_value = color.lstrip("#")
        red, green, blue = hex_value[0:2], hex_value[2:4], hex_value[4:6]
        return f"&H00{blue}{green}{red}".upper()

    try:
        return NAMED_ASS_COLORS[color.lower()]
    except KeyError as error:
        raise RenderError(f"unknown color {color!r}; use a named color or #RRGGBB hex") from error


def build_subtitle_force_style(font: str, size: int, color: str, outline_color: str, position: str) -> str:
    if position not in SUBTITLE_ALIGNMENT:
        raise RenderError(f"subtitle position must be one of {sorted(SUBTITLE_ALIGNMENT)}, got {position!r}")

    return (
        f"FontName={font},FontSize={size},PrimaryColour={ass_color(color)},"
        f"OutlineColour={ass_color(outline_color)},BorderStyle=1,Outline=4,Shadow=2,Bold=1,"
        f"Alignment={SUBTITLE_ALIGNMENT[position]},MarginV={SUBTITLE_MARGIN_V[position]}"
    )


def format_ass_timestamp(seconds: float) -> str:
    total_cs = round(seconds * 100)
    hours, remainder_cs = divmod(total_cs, 360_000)
    minutes, remainder_cs = divmod(remainder_cs, 6_000)
    secs, centiseconds = divmod(remainder_cs, 100)
    return f"{hours:01d}:{minutes:02d}:{secs:02d}.{centiseconds:02d}"


def build_ass_content(
    cues: list[dict], font: str, size: int, color: str, outline_color: str, position: str,
    play_res_x: int, play_res_y: int,
) -> str:
    """Bakes cues into a self-contained .ass with PlayResX/Y matching the render canvas.

    ffmpeg's `subtitles` filter has no header info to go on for a plain .srt, so it
    assumes a 384x288 reference canvas and scales font/margins from there — on a
    1080x1920 canvas that blows FontSize/MarginV up by ~6.7x and the text lands off
    the top of frame. Writing PlayResX/Y equal to the actual output size avoids that
    scaling entirely, so style values apply at face value.
    """
    alignment = SUBTITLE_ALIGNMENT[position]
    margin_v = SUBTITLE_MARGIN_V[position]
    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {play_res_x}\n"
        f"PlayResY: {play_res_y}\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{font},{size},{ass_color(color)},&H000000FF,{ass_color(outline_color)},"
        f"&H00000000,1,0,0,0,100,100,0,0,1,4,2,{alignment},10,10,{margin_v},1\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    events = "".join(
        f"Dialogue: 0,{format_ass_timestamp(cue['start'])},{format_ass_timestamp(cue['end'])},"
        f"Default,,0,0,0,,{cue['text'].replace(chr(10), '\\N')}\n"
        for cue in cues
    )
    return header + events


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


def compute_fade_plan(
    clip_duration: float, fade_seconds: float, tail_available: float
) -> tuple[float, float, float]:
    """Returns (extend_seconds, fade_start, fade_duration).

    Prefers fading in footage appended *after* the clip's own end (so the fade
    starts once the last word has fully finished, not overlapping it). Falls
    back to fading into the tail of the existing content only when there's no
    source footage left to extend into (e.g. the clip already runs to the end
    of the source video).
    """
    if fade_seconds <= 0:
        return 0.0, 0.0, 0.0

    extend = round(max(0.0, min(fade_seconds, tail_available)), 3)
    if extend > 0:
        return extend, round(clip_duration, 3), extend

    effective_fade = round(min(fade_seconds, clip_duration / 2), 3)
    fade_start = round(clip_duration - effective_fade, 3)
    return 0.0, fade_start, effective_fade


def build_ffmpeg_command(
    input_path: str,
    output_path: str,
    start: float,
    end: float,
    crop_filter: str,
    subtitles_path: str | None = None,
    fade_seconds: float = 0.0,
    video_duration: float | None = None,
    subtitle_style: dict | None = None,
) -> list[str]:
    clip_duration = end - start
    tail_available = 0.0 if video_duration is None else max(0.0, video_duration - end)
    extend, fade_start, fade_duration = compute_fade_plan(clip_duration, fade_seconds, tail_available)
    total_duration = round(clip_duration + extend, 3)

    video_filter = crop_filter
    if subtitles_path is not None:
        escaped_path = subtitles_path.replace("\\", "/").replace(":", "\\:")
        video_filter = f"{video_filter},subtitles='{escaped_path}'"
        if subtitle_style is not None:
            style = build_subtitle_force_style(
                subtitle_style["font"], subtitle_style["size"],
                subtitle_style["color"], subtitle_style["outline_color"], subtitle_style["position"],
            )
            video_filter = f"{video_filter}:force_style='{style}'"

    audio_args: list[str] = []
    if fade_duration > 0:
        # -ss before -i makes ffmpeg's own output timeline start at 0, so the fade's
        # start offset is relative to the trimmed clip, not the source video.
        video_filter = f"{video_filter},fade=t=out:st={fade_start}:d={fade_duration}"
        audio_args = ["-af", f"afade=t=out:st={fade_start}:d={fade_duration}"]

    return [
        "ffmpeg", "-y",
        "-ss", str(start),
        "-i", input_path,
        "-t", str(total_duration),
        "-vf", video_filter,
        *audio_args,
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
    fade_seconds: float = 0.0,
    subtitle_style: dict | None = None,
    runner=subprocess.run,
) -> list[str]:
    start, end = clamp_clip_bounds(plan_entry["start"], plan_entry["end"], video_duration)
    crop_filter = compute_crop_filter(plan_entry["crop_style"], src_width, src_height)
    subtitles_path = plan_entry.get("subtitles_path")

    if subtitles_path is not None and subtitle_style is not None:
        import sys

        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from scripts.subtitles import parse_srt

        cues = parse_srt(Path(subtitles_path).read_text(encoding="utf-8"))
        ass_content = build_ass_content(
            cues, subtitle_style["font"], subtitle_style["size"], subtitle_style["color"],
            subtitle_style["outline_color"], subtitle_style["position"], TARGET_WIDTH, TARGET_HEIGHT,
        )
        subtitles_path = str(Path(subtitles_path).with_suffix(".ass"))
        Path(subtitles_path).write_text(ass_content, encoding="utf-8")
        subtitle_style = None  # baked into the .ass style block already; no force_style needed

    command = build_ffmpeg_command(
        input_path, output_path, start, end, crop_filter, subtitles_path,
        fade_seconds, video_duration, subtitle_style,
    )

    result = runner(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise RenderError(f"ffmpeg failed for {output_path}: {result.stderr}")
    return command


def main() -> None:
    parser = argparse.ArgumentParser(description="Render approved clips from a PLAN.json")
    parser.add_argument("input_video", help="Path to the source recording")
    parser.add_argument("plan_json", help="Path to PLAN.json: a list of clip plan entries")
    parser.add_argument("output_dir", help="Directory to write rendered clips into")
    parser.add_argument(
        "--fade-seconds", type=float, default=0.0,
        help="Fade video+audio to black/silence over this many seconds at the end of each clip",
    )
    parser.add_argument("--sub-font", default="Arial Black")
    parser.add_argument("--sub-size", type=int, default=72)
    parser.add_argument("--sub-color", default="white")
    parser.add_argument("--sub-outline-color", default="black")
    parser.add_argument("--sub-position", default="bottom", choices=sorted(SUBTITLE_ALIGNMENT))
    args = parser.parse_args()

    subtitle_style = {
        "font": args.sub_font,
        "size": args.sub_size,
        "color": args.sub_color,
        "outline_color": args.sub_outline_color,
        "position": args.sub_position,
    }

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
            fade_seconds=args.fade_seconds,
            subtitle_style=subtitle_style,
        )
        print(output_path)


if __name__ == "__main__":
    main()
