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
SUBTITLE_MARGIN_V = {"bottom": 380, "top": 120, "center": 0}


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
    cues: list[dict], font: str, size: int, color: str, outline_color: str, highlight_color: str,
    position: str, margin_v: int, play_res_x: int, play_res_y: int,
) -> str:
    """Bakes cues into a self-contained .ass with PlayResX/Y matching the render canvas.

    ffmpeg's `subtitles` filter has no header info to go on for a plain .srt, so it
    assumes a 384x288 reference canvas and scales font/margins from there — on a
    1080x1920 canvas that blows FontSize/MarginV up by ~6.7x and the text lands off
    the top of frame. Writing PlayResX/Y equal to the actual output size avoids that
    scaling entirely, so style values apply at face value.

    `highlight_color` becomes the `\\c` override color used by per-word overlay Dialogue
    events (Layer 1) that `render_clip` builds for cues carrying word-level timing — one
    base event (Layer 0, always visible, base `color`) per cue plus one overlay event per
    word, each spanning exactly that word's own timespan with only that word
    opaque/highlighted and every other word alpha-transparent. Cues without word-level
    data (the plain `.srt` fallback) get only the base event, exactly as before.
    `margin_v` is caller-supplied rather than derived from `position` here, so it can be
    tied to actual crop geometry — see `compute_subtitle_margin_v`.
    """
    alignment = SUBTITLE_ALIGNMENT[position]
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
        f"Style: Default,{font},{size},{ass_color(color)},{ass_color(highlight_color)},{ass_color(outline_color)},"
        f"&H00000000,1,0,0,0,100,100,0,0,1,4,2,{alignment},10,10,{margin_v},1\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    highlight_tag = ass_color(highlight_color)
    events_parts = []
    for cue in cues:
        events_parts.append(
            f"Dialogue: 0,{format_ass_timestamp(cue['start'])},{format_ass_timestamp(cue['end'])},"
            f"Default,,0,0,0,,{cue['text'].replace(chr(10), '\\N')}\n"
        )
        if "words" in cue:
            for index, word in enumerate(cue["words"]):
                parts = []
                for i, w in enumerate(cue["words"]):
                    token = w["word"].strip()
                    if i == index:
                        parts.append(f"{{\\alpha&H00&\\c{highlight_tag}&}}{token}{{\\c}}")
                    else:
                        parts.append(f"{{\\alpha&HFF&}}{token}")
                overlay_text = " ".join(parts)
                events_parts.append(
                    f"Dialogue: 1,{format_ass_timestamp(word['start'])},{format_ass_timestamp(word['end'])},"
                    f"Default,,0,0,0,,{overlay_text}\n"
                )
    return header + "".join(events_parts)


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
        top_pad = round(total_pad / 2)
        return f"scale={TARGET_WIDTH}:{scaled_height},pad={TARGET_WIDTH}:{TARGET_HEIGHT}:0:{top_pad}:black"

    if crop_style == "original-16:9":
        scaled_height = round(src_height * TARGET_WIDTH / src_width)
        top_pad = round((TARGET_HEIGHT - scaled_height) / 2)
        return f"scale={TARGET_WIDTH}:{scaled_height},pad={TARGET_WIDTH}:{TARGET_HEIGHT}:0:{top_pad}:black"

    raise RenderError(
        f"crop_style must be a resolved value (zoom/pad/original-16:9), got {crop_style!r}. "
        "'auto' must be resolved to a concrete style before reaching render.py."
    )


def compute_subtitle_margin_v(position: str, crop_style: str, src_width: int, src_height: int) -> int:
    if position != "bottom":
        return SUBTITLE_MARGIN_V[position]

    if crop_style == "zoom":
        return SUBTITLE_MARGIN_V["bottom"]

    if crop_style in ("pad", "original-16:9"):
        scaled_height = round(src_height * TARGET_WIDTH / src_width)
        top_pad = round((TARGET_HEIGHT - scaled_height) / 2)
        bottom_bar_height = TARGET_HEIGHT - top_pad - scaled_height
        return max(SUBTITLE_MARGIN_V["bottom"], bottom_bar_height // 2)

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


def build_video_effects_chain(vignette: bool, grain_strength: int) -> str | None:
    """Optional cinematic touch-ups applied after crop, before subtitles are
    burned in - so grain/vignette don't degrade caption readability.
    """
    if grain_strength < 0 or grain_strength > 100:
        raise RenderError(f"grain_strength must be between 0 and 100, got {grain_strength}")

    filters = []
    if vignette:
        filters.append("vignette")
    if grain_strength > 0:
        filters.append(f"noise=alls={grain_strength}:allf=t")
    return ",".join(filters) if filters else None


def build_punch_zoom_filter(punch_at: float, zoom_amount: float = 1.15, ramp: float = 0.25) -> str:
    """A snappy camera punch-in at punch_at (clip-relative seconds): holds at
    1x, ramps up to zoom_amount over `ramp` seconds, then holds zoomed for
    the rest of the clip - it does not zoom back out, matching how editors
    punch in on a punchline/reaction and stay there through the next cut.

    Re-crops the already-1080x1920 frame around its center using an
    FFmpeg per-frame expression (evaluated via the `t` time variable), then
    rescales back to 1080x1920 so downstream filters see a constant size.
    """
    if zoom_amount <= 1.0:
        raise RenderError(f"zoom_amount must be > 1.0, got {zoom_amount}")
    if ramp <= 0:
        raise RenderError(f"ramp must be > 0, got {ramp}")
    if punch_at < 0:
        raise RenderError(f"punch_at must be >= 0, got {punch_at}")

    ramp_end = punch_at + ramp
    zoom_expr = (
        f"if(lt(t,{punch_at}),1,"
        f"if(lt(t,{ramp_end}),1+({zoom_amount}-1)*(t-{punch_at})/{ramp},{zoom_amount}))"
    )
    return (
        f"crop=w='{TARGET_WIDTH}/({zoom_expr})':h='{TARGET_HEIGHT}/({zoom_expr})':"
        f"x='(in_w-out_w)/2':y='(in_h-out_h)/2',scale={TARGET_WIDTH}:{TARGET_HEIGHT}"
    )


def build_audio_filter_chain(denoise: bool, loudnorm: bool, fade_filter: str | None) -> str | None:
    """Combines the optional cleanup filters and the fade into one -af chain.

    Order matters: denoise the raw signal first, normalize loudness on the
    cleaned signal, then fade last so the fade-out isn't undone by loudnorm.
    """
    filters = []
    if denoise:
        filters.append("afftdn")
    if loudnorm:
        filters.append("loudnorm=I=-16:TP=-1.5:LRA=11")
    if fade_filter:
        filters.append(fade_filter)
    return ",".join(filters) if filters else None


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
    denoise: bool = False,
    loudnorm: bool = False,
    vignette: bool = False,
    grain_strength: int = 0,
    punch_zoom_at: float | None = None,
    punch_zoom_amount: float = 1.15,
    punch_zoom_ramp: float = 0.25,
) -> list[str]:
    clip_duration = end - start
    tail_available = 0.0 if video_duration is None else max(0.0, video_duration - end)
    extend, fade_start, fade_duration = compute_fade_plan(clip_duration, fade_seconds, tail_available)
    total_duration = round(clip_duration + extend, 3)

    video_filter = crop_filter
    if punch_zoom_at is not None:
        video_filter = f"{video_filter},{build_punch_zoom_filter(punch_zoom_at, punch_zoom_amount, punch_zoom_ramp)}"
    effects_chain = build_video_effects_chain(vignette, grain_strength)
    if effects_chain:
        video_filter = f"{video_filter},{effects_chain}"
    if subtitles_path is not None:
        escaped_path = subtitles_path.replace("\\", "/").replace(":", "\\:")
        video_filter = f"{video_filter},subtitles='{escaped_path}'"
        if subtitle_style is not None:
            style = build_subtitle_force_style(
                subtitle_style["font"], subtitle_style["size"],
                subtitle_style["color"], subtitle_style["outline_color"], subtitle_style["position"],
            )
            video_filter = f"{video_filter}:force_style='{style}'"

    fade_filter = None
    if fade_duration > 0:
        # -ss before -i makes ffmpeg's own output timeline start at 0, so the fade's
        # start offset is relative to the trimmed clip, not the source video.
        video_filter = f"{video_filter},fade=t=out:st={fade_start}:d={fade_duration}"
        fade_filter = f"afade=t=out:st={fade_start}:d={fade_duration}"

    audio_filter_chain = build_audio_filter_chain(denoise, loudnorm, fade_filter)
    audio_args = ["-af", audio_filter_chain] if audio_filter_chain else []

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


def build_jumpcut_command(
    input_path: str,
    output_path: str,
    clip_start: float,
    clip_end: float,
    keep_segments: list[tuple[float, float]],
    crop_filter: str,
    subtitles_path: str | None = None,
    fade_seconds: float = 0.0,
    subtitle_style: dict | None = None,
    denoise: bool = False,
    loudnorm: bool = False,
    vignette: bool = False,
    grain_strength: int = 0,
    punch_zoom_at: float | None = None,
    punch_zoom_amount: float = 1.15,
    punch_zoom_ramp: float = 0.25,
) -> list[str]:
    """Like build_ffmpeg_command, but keep_segments (absolute source-file
    seconds, from jumpcuts.compute_keep_segments) are trimmed out of the
    decoded window and concatenated before crop/effects/subtitles/fade are
    applied - this is what actually cuts the dead air out of the clip
    instead of just rendering start..end verbatim.

    punch_zoom_at, if set, must already be expressed in seconds on the
    *spliced* output timeline (see jumpcuts.remap_timestamp), not the
    original source timeline - the concat above changes where anything
    after the first cut lands.
    """
    if not keep_segments:
        raise RenderError("keep_segments must not be empty")

    # -ss before -i seeks fast and resets the decoded timeline to 0, so every
    # segment boundary below must be expressed relative to clip_start.
    relative_segments = [(seg_start - clip_start, seg_end - clip_start) for seg_start, seg_end in keep_segments]

    trim_stages = []
    concat_refs = []
    for index, (seg_start, seg_end) in enumerate(relative_segments):
        trim_stages.append(f"[0:v]trim=start={seg_start}:end={seg_end},setpts=PTS-STARTPTS[v{index}]")
        trim_stages.append(f"[0:a]atrim=start={seg_start}:end={seg_end},asetpts=PTS-STARTPTS[a{index}]")
        concat_refs.append(f"[v{index}][a{index}]")
    concat_stage = f"{''.join(concat_refs)}concat=n={len(relative_segments)}:v=1:a=1[vcat][acat]"

    total_duration = round(sum(seg_end - seg_start for seg_start, seg_end in relative_segments), 3)
    _, fade_start, fade_duration = compute_fade_plan(total_duration, fade_seconds, tail_available=0.0)

    video_ops = [crop_filter]
    if punch_zoom_at is not None:
        video_ops.append(build_punch_zoom_filter(punch_zoom_at, punch_zoom_amount, punch_zoom_ramp))
    effects_chain = build_video_effects_chain(vignette, grain_strength)
    if effects_chain:
        video_ops.append(effects_chain)
    if subtitles_path is not None:
        escaped_path = subtitles_path.replace("\\", "/").replace(":", "\\:")
        subtitles_clause = f"subtitles='{escaped_path}'"
        if subtitle_style is not None:
            style = build_subtitle_force_style(
                subtitle_style["font"], subtitle_style["size"],
                subtitle_style["color"], subtitle_style["outline_color"], subtitle_style["position"],
            )
            subtitles_clause = f"{subtitles_clause}:force_style='{style}'"
        video_ops.append(subtitles_clause)

    fade_filter = None
    if fade_duration > 0:
        video_ops.append(f"fade=t=out:st={fade_start}:d={fade_duration}")
        fade_filter = f"afade=t=out:st={fade_start}:d={fade_duration}"

    audio_filter_chain = build_audio_filter_chain(denoise, loudnorm, fade_filter) or "anull"

    video_stage = f"[vcat]{','.join(video_ops)}[vout]"
    audio_stage = f"[acat]{audio_filter_chain}[aout]"
    filter_complex = ";".join(trim_stages + [concat_stage, video_stage, audio_stage])

    return [
        "ffmpeg", "-y",
        "-ss", str(clip_start),
        "-i", input_path,
        "-t", str(round(clip_end - clip_start, 3)),
        "-filter_complex", filter_complex,
        "-map", "[vout]",
        "-map", "[aout]",
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
    denoise: bool = False,
    loudnorm: bool = False,
    vignette: bool = False,
    grain_strength: int = 0,
    punch_zoom_amount: float = 1.15,
    punch_zoom_ramp: float = 0.25,
    runner=subprocess.run,
) -> list[str]:
    start, end = clamp_clip_bounds(plan_entry["start"], plan_entry["end"], video_duration)
    crop_style = plan_entry["crop_style"]
    crop_filter = compute_crop_filter(crop_style, src_width, src_height)
    punch_zoom_at = plan_entry.get("punch_zoom_at")
    subtitles_path = plan_entry.get("subtitles_path")

    if subtitles_path is not None and subtitle_style is not None:
        import sys

        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from scripts.subtitles import group_words_into_cues, parse_srt

        words_path = Path(subtitles_path).with_name(Path(subtitles_path).stem + "_words.json")
        if words_path.exists():
            words = json.loads(words_path.read_text(encoding="utf-8"))
            cues = group_words_into_cues(words, max_words=subtitle_style["words_per_cue"])
        else:
            cues = parse_srt(Path(subtitles_path).read_text(encoding="utf-8"))

        margin_v = compute_subtitle_margin_v(
            subtitle_style["position"], crop_style, src_width, src_height
        )
        ass_content = build_ass_content(
            cues, subtitle_style["font"], subtitle_style["size"], subtitle_style["color"],
            subtitle_style["outline_color"], subtitle_style["highlight_color"],
            subtitle_style["position"], margin_v, TARGET_WIDTH, TARGET_HEIGHT,
        )
        subtitles_path = str(Path(subtitles_path).with_suffix(".ass"))
        Path(subtitles_path).write_text(ass_content, encoding="utf-8")
        subtitle_style = None  # baked into the .ass style block already; no force_style needed

    keep_segments_raw = plan_entry.get("keep_segments")
    if keep_segments_raw is not None:
        keep_segments = [(segment[0], segment[1]) for segment in keep_segments_raw]
        command = build_jumpcut_command(
            input_path, output_path, start, end, keep_segments, crop_filter, subtitles_path,
            fade_seconds, subtitle_style, denoise, loudnorm,
            vignette, grain_strength, punch_zoom_at, punch_zoom_amount, punch_zoom_ramp,
        )
    else:
        command = build_ffmpeg_command(
            input_path, output_path, start, end, crop_filter, subtitles_path,
            fade_seconds, video_duration, subtitle_style, denoise, loudnorm,
            vignette, grain_strength, punch_zoom_at, punch_zoom_amount, punch_zoom_ramp,
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
    parser.add_argument("--sub-size", type=int, default=92)
    parser.add_argument("--sub-color", default="white")
    parser.add_argument("--sub-outline-color", default="black")
    parser.add_argument("--sub-highlight-color", default="yellow")
    parser.add_argument("--sub-position", default="bottom", choices=sorted(SUBTITLE_ALIGNMENT))
    parser.add_argument("--sub-words-per-cue", type=int, default=4)
    parser.add_argument(
        "--denoise", action=argparse.BooleanOptionalAction, default=True,
        help="Apply an FFmpeg noise-reduction filter (afftdn) to each clip's audio",
    )
    parser.add_argument(
        "--loudnorm", action=argparse.BooleanOptionalAction, default=True,
        help="Normalize each clip's audio loudness (EBU R128 via FFmpeg's loudnorm)",
    )
    parser.add_argument(
        "--vignette", action=argparse.BooleanOptionalAction, default=False,
        help="Darken the frame edges for a cinematic look (FFmpeg vignette filter)",
    )
    parser.add_argument(
        "--grain-strength", type=int, default=0,
        help="Add film-grain noise at this strength, 0-100 (0 = off, FFmpeg noise filter)",
    )
    parser.add_argument(
        "--punch-zoom-amount", type=float, default=1.15,
        help="Zoom multiplier for a plan entry's punch_zoom_at (e.g. 1.15 = 15%% punch-in)",
    )
    parser.add_argument(
        "--punch-zoom-ramp", type=float, default=0.25,
        help="Seconds the punch-in zoom takes to ramp from 1x to the full amount",
    )
    args = parser.parse_args()

    subtitle_style = {
        "font": args.sub_font,
        "size": args.sub_size,
        "color": args.sub_color,
        "outline_color": args.sub_outline_color,
        "highlight_color": args.sub_highlight_color,
        "position": args.sub_position,
        "words_per_cue": args.sub_words_per_cue,
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
            denoise=args.denoise,
            loudnorm=args.loudnorm,
            vignette=args.vignette,
            grain_strength=args.grain_strength,
            punch_zoom_amount=args.punch_zoom_amount,
            punch_zoom_ramp=args.punch_zoom_ramp,
        )
        print(output_path)


if __name__ == "__main__":
    main()
