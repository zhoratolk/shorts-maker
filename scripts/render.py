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

# MUST mirror scripts.transitions.TRANSITION_TYPES (drift-guarded by
# test_valid_transitions_matches_transitions_module_canonical_enum). Duplicated
# here rather than imported so render.py stays importable/runnable as a
# standalone CLI (`python scripts/render.py`) without a sys.path insert to
# reach scripts.transitions.
VALID_TRANSITIONS = frozenset({"cut", "crossfade", "whip_pan", "mask_wipe", "glitch", "match_cut"})

# xfade transition names for the 4 types that map directly onto a single
# native ffmpeg xfade transition (04-RESEARCH.md Pattern 3). glitch has no
# single matching xfade name and is built as a small chain (Pattern 4);
# cut/match_cut render as a plain concat, no xfade node at all.
_XFADE_TRANSITION_NAMES = {
    "crossfade": "fade",
    "whip_pan": "hblur",
    "mask_wipe": "wipeleft",
}


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


def _escape_ass_text(text: str) -> str:
    """Escapes ASS override-block syntax (`{`/`}`) and the tag escape
    character (`\\`) in caption text before it's interpolated into a
    Dialogue line. Transcribed/edited caption text can plausibly contain any
    of these (code-reading, chat-quote, emoticon) - left unescaped, they can
    prematurely close or inject arbitrary `{\\...}` override tags into the
    rendered subtitle stream. Backslash must be escaped first so escaping
    braces afterward doesn't double-escape the backslashes it just inserted.
    """
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


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
        escaped_text = _escape_ass_text(cue["text"]).replace(chr(10), "\\N")
        events_parts.append(
            f"Dialogue: 0,{format_ass_timestamp(cue['start'])},{format_ass_timestamp(cue['end'])},"
            f"Default,,0,0,0,,{escaped_text}\n"
        )
        if "words" in cue:
            for index, word in enumerate(cue["words"]):
                parts = []
                for i, w in enumerate(cue["words"]):
                    token = _escape_ass_text(w["word"].strip())
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


def build_transition_filter(
    transition_type: str, duration: float, offset: float, in_a: str, in_b: str, out_label: str
) -> str | None:
    """Returns the ffmpeg xfade-based video-graph node fragment for a boundary
    transition, following the build_video_effects_chain/build_punch_zoom_filter
    shape: validate up front, build the filter string purely from the
    enum-constrained transition_type plus internally-computed duration/offset
    floats - never from raw external text (V5 Input Validation).

    cut/match_cut are rendered as a plain concat (no overlap needed), so this
    returns None for those two; the caller builds the audio side of a non-cut
    transition separately via acrossfade=d=<duration> (see build_jumpcut_command).
    in_a/in_b/out_label are plain (unbracketed) filter-graph label names -
    this function wraps them in brackets itself, matching the trim_stages
    label convention already used in build_jumpcut_command.
    """
    if transition_type not in VALID_TRANSITIONS:
        raise RenderError(
            f"transition_type must be one of {sorted(VALID_TRANSITIONS)}, got {transition_type!r}"
        )
    if duration <= 0:
        raise RenderError(f"duration must be > 0, got {duration}")
    if offset < 0:
        raise RenderError(f"offset must be >= 0, got {offset}")

    if transition_type in ("cut", "match_cut"):
        return None

    if transition_type == "glitch":
        # 04-RESEARCH.md Pattern 4: no single native xfade transition reads as
        # "glitch" - blend on a pixelize xfade then layer an RGB channel split
        # and noise on top for the transition's duration.
        return (
            f"[{in_a}][{in_b}]xfade=transition=pixelize:duration={duration}:offset={offset},"
            f"rgbashift=rh=8:bh=-8:edge=smear,noise=alls=25:allf=t+u[{out_label}]"
        )

    xfade_name = _XFADE_TRANSITION_NAMES[transition_type]
    return f"[{in_a}][{in_b}]xfade=transition={xfade_name}:duration={duration}:offset={offset}[{out_label}]"


def build_audio_filter_chain(
    denoise: bool, loudnorm: bool, fade_filter: str | None, denoise_strength: float = 6.0
) -> str | None:
    """Combines the optional cleanup filters and the fade into one -af chain.

    Order matters: denoise the raw signal first, normalize loudness on the
    cleaned signal, then fade last so the fade-out isn't undone by loudnorm.
    """
    filters = []
    if denoise:
        filters.append(f"afftdn=nr={denoise_strength}")
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
    denoise_strength: float = 6.0,
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

    audio_filter_chain = build_audio_filter_chain(denoise, loudnorm, fade_filter, denoise_strength)
    audio_args = ["-af", audio_filter_chain] if audio_filter_chain else []

    return [
        "ffmpeg", "-y",
        "-loglevel", "error",
        "-ss", str(start),
        "-i", input_path,
        "-t", str(total_duration),
        "-vf", video_filter,
        *audio_args,
        "-c:v", "libx264",
        "-c:a", "aac",
        output_path,
    ]


def _build_transition_fold(
    relative_segments: list[tuple[float, float]],
    boundary_transitions: list[str],
    boundary_gaps: list[float] | None,
    transition_duration: float,
    min_overlap_seconds: float,
) -> tuple[list[str], list[str], float]:
    """Builds the sequential-fold trim/join stages for a jumpcut command that
    has at least one non-cut boundary transition (04-RESEARCH.md Pitfall 2:
    concat is N-ary, xfade is pairwise, so a mix of cut and fancy boundaries
    can't be expressed by a single N-ary concat node).

    Segment trims are extended into their adjacent boundary's pause gap
    (Pitfall 1) only for boundaries that actually get a real transition, so
    xfade/acrossfade overlap is always borrowed dead air, never real kept
    content. Cut/match_cut boundaries, and non-cut boundaries whose gap - or
    whose adjacent kept-segment duration - is below min_overlap_seconds
    (TRANS-03 render-layer fallback), join via a plain 2-input concat instead
    - trims for those segments are left exactly as computed by the caller.
    A short kept segment must never be asked to host more overlap than it
    actually has, or the xfade offset computed below goes negative and
    build_transition_filter raises - defeating the TRANS-03 fallback
    guarantee. A second, last-resort guard right before the xfade call
    downgrades to concat if the accumulated fold duration still can't cover
    d_eff (e.g. a segment borrowed into from both sides).

    Returns (trim_stages, fold_stages, total_output_duration) - fold_stages'
    final node writes to [vcat]/[acat] so the caller's downstream video_ops/
    audio_stage code is unchanged regardless of which path built the graph.
    """
    segment_count = len(relative_segments)
    if boundary_gaps is None:
        boundary_gaps = [0.0] * (segment_count - 1)

    starts = [seg_start for seg_start, seg_end in relative_segments]
    ends = [seg_end for seg_start, seg_end in relative_segments]

    # Effective xfade duration per boundary - None means "downgrade to a
    # plain cut join" (cut/match_cut requested, or gap too small to borrow).
    effective_duration: list[float | None] = []
    for boundary in range(segment_count - 1):
        transition_type = boundary_transitions[boundary]
        gap = boundary_gaps[boundary]
        # Cap the borrowable overlap by the adjacent kept segments' own
        # durations too, not just the pause gap - a short kept segment
        # (nothing in jumpcuts.py enforces a minimum) can't host more
        # overlap than it actually contains without going negative below.
        seg_a_duration = ends[boundary] - starts[boundary]
        seg_b_duration = ends[boundary + 1] - starts[boundary + 1]
        max_borrowable = min(gap, seg_a_duration, seg_b_duration)
        if transition_type in ("cut", "match_cut") or max_borrowable < min_overlap_seconds:
            effective_duration.append(None)
            continue
        d_eff = min(transition_duration, max_borrowable)
        d_eff = max(min_overlap_seconds, min(d_eff, max_borrowable))
        effective_duration.append(round(d_eff, 3))

    # Extend trims into the borrowed gap - symmetric split, always <= gap
    # (d_eff <= gap by construction above) so trims never cross into either
    # side's real kept content.
    for boundary, d_eff in enumerate(effective_duration):
        if d_eff is None:
            continue
        extend_into_a = round(d_eff / 2, 3)
        extend_into_b = round(d_eff - extend_into_a, 3)
        ends[boundary] = round(ends[boundary] + extend_into_a, 3)
        starts[boundary + 1] = round(starts[boundary + 1] - extend_into_b, 3)

    trim_stages = []
    for index in range(segment_count):
        trim_stages.append(f"[0:v]trim=start={starts[index]}:end={ends[index]},setpts=PTS-STARTPTS[v{index}]")
        trim_stages.append(f"[0:a]atrim=start={starts[index]}:end={ends[index]},asetpts=PTS-STARTPTS[a{index}]")

    fold_stages = []
    acc_v, acc_a = "v0", "a0"
    acc_duration = round(ends[0] - starts[0], 3)
    for index in range(1, segment_count):
        seg_duration = round(ends[index] - starts[index], 3)
        is_last = index == segment_count - 1
        out_v = "vcat" if is_last else f"vfold{index}"
        out_a = "acat" if is_last else f"afold{index}"
        d_eff = effective_duration[index - 1]

        # Last-resort safety net: even with the per-boundary cap above, a
        # segment borrowed into from both sides (two adjacent transitions)
        # could still leave less accumulated duration than d_eff wants to
        # borrow. Downgrade to a plain concat rather than let offset go
        # negative and raise out of build_transition_filter.
        if d_eff is None or d_eff > acc_duration:
            fold_stages.append(f"[{acc_v}][{acc_a}][v{index}][a{index}]concat=n=2:v=1:a=1[{out_v}][{out_a}]")
            acc_duration = round(acc_duration + seg_duration, 3)
        else:
            # Pattern 3: xfade offset is where segment A's accumulated
            # footage would end minus the overlap duration.
            offset = round(acc_duration - d_eff, 3)
            video_node = build_transition_filter(
                boundary_transitions[index - 1], d_eff, offset, acc_v, f"v{index}", out_v
            )
            fold_stages.append(video_node)
            fold_stages.append(f"[{acc_a}][a{index}]acrossfade=d={d_eff}[{out_a}]")
            acc_duration = round(acc_duration + seg_duration - d_eff, 3)

        acc_v, acc_a = out_v, out_a

    return trim_stages, fold_stages, acc_duration


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
    denoise_strength: float = 6.0,
    boundary_transitions: list[str] | None = None,
    boundary_gaps: list[float] | None = None,
    transition_duration: float = 0.35,
    min_overlap_seconds: float = 0.12,
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

    boundary_transitions (one entry per boundary, len == len(keep_segments)-1)
    is optional; when it is None or every entry is cut/match_cut, this
    produces the exact same flat trim + concat=n=N graph as today
    (backward compatibility). When at least one boundary requests a real
    transition, the graph is instead built as a sequential fold (see
    _build_transition_fold) that borrows overlap from boundary_gaps -
    04-RESEARCH.md Pitfall 1/2, Pattern 3.
    """
    if not keep_segments:
        raise RenderError("keep_segments must not be empty")

    if boundary_transitions is not None:
        for transition_type in boundary_transitions:
            if transition_type not in VALID_TRANSITIONS:
                raise RenderError(
                    f"boundary_transitions entries must be one of {sorted(VALID_TRANSITIONS)}, "
                    f"got {transition_type!r}"
                )

    # -ss before -i seeks fast and resets the decoded timeline to 0, so every
    # segment boundary below must be expressed relative to clip_start.
    relative_segments = [(seg_start - clip_start, seg_end - clip_start) for seg_start, seg_end in keep_segments]

    uses_fold = boundary_transitions is not None and any(
        transition_type not in ("cut", "match_cut") for transition_type in boundary_transitions
    )

    if not uses_fold:
        trim_stages = []
        concat_refs = []
        for index, (seg_start, seg_end) in enumerate(relative_segments):
            trim_stages.append(f"[0:v]trim=start={seg_start}:end={seg_end},setpts=PTS-STARTPTS[v{index}]")
            trim_stages.append(f"[0:a]atrim=start={seg_start}:end={seg_end},asetpts=PTS-STARTPTS[a{index}]")
            concat_refs.append(f"[v{index}][a{index}]")
        concat_stage = f"{''.join(concat_refs)}concat=n={len(relative_segments)}:v=1:a=1[vcat][acat]"
        stages = trim_stages + [concat_stage]
        total_duration = round(sum(seg_end - seg_start for seg_start, seg_end in relative_segments), 3)
    else:
        trim_stages, fold_stages, total_duration = _build_transition_fold(
            relative_segments, boundary_transitions, boundary_gaps, transition_duration, min_overlap_seconds
        )
        stages = trim_stages + fold_stages

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

    audio_filter_chain = build_audio_filter_chain(denoise, loudnorm, fade_filter, denoise_strength) or "anull"

    video_stage = f"[vcat]{','.join(video_ops)}[vout]"
    audio_stage = f"[acat]{audio_filter_chain}[aout]"
    filter_complex = ";".join(stages + [video_stage, audio_stage])

    return [
        "ffmpeg", "-y",
        "-loglevel", "error",
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
    denoise_strength: float = 6.0,
    transition_duration: float = 0.35,
    min_overlap_seconds: float = 0.12,
    runner=subprocess.run,
) -> list[str]:
    start, end = clamp_clip_bounds(plan_entry["start"], plan_entry["end"], video_duration)
    crop_style = plan_entry["crop_style"]
    crop_filter = compute_crop_filter(crop_style, src_width, src_height)
    punch_zoom_at = plan_entry.get("punch_zoom_at")
    if punch_zoom_at is not None and crop_style != "zoom":
        # pad/original-16:9 scale the source to fill TARGET_WIDTH with no
        # horizontal slack (only top/bottom letterbox bars) - punch-zoom's
        # crop is centered on both axes, so it always eats into real video
        # content on the sides for these styles instead of just tightening
        # the letterbox, defeating the reason pad/original-16:9 was chosen.
        raise RenderError(
            f"punch_zoom_at requires crop_style='zoom' (got {crop_style!r}); "
            "on pad/original-16:9 the punch-zoom crop cuts into real frame content, not just the letterbox bars"
        )
    subtitles_path = plan_entry.get("subtitles_path")

    if subtitles_path is not None and subtitle_style is not None:
        import sys

        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from scripts.subtitles import group_words_into_cues, parse_srt

        words_path = Path(subtitles_path).with_name(Path(subtitles_path).stem + "_words.json")
        if words_path.exists():
            words = json.loads(words_path.read_text(encoding="utf-8"))
            cues = group_words_into_cues(
                words, max_words=subtitle_style["words_per_cue"],
                strip_punctuation=subtitle_style.get("strip_punctuation", True),
            )
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
        boundary_transitions = plan_entry.get("boundary_transitions")
        boundary_gaps = None
        if boundary_transitions is not None:
            expected_length = len(keep_segments) - 1
            if len(boundary_transitions) != expected_length:
                raise RenderError(
                    f"boundary_transitions length ({len(boundary_transitions)}) must equal "
                    f"len(keep_segments) - 1 ({expected_length})"
                )
            import sys

            sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
            from scripts.jumpcuts import compute_boundary_gaps

            boundary_gaps = compute_boundary_gaps(keep_segments)
        command = build_jumpcut_command(
            input_path, output_path, start, end, keep_segments, crop_filter, subtitles_path,
            fade_seconds, subtitle_style, denoise, loudnorm,
            vignette, grain_strength, punch_zoom_at, punch_zoom_amount, punch_zoom_ramp,
            denoise_strength, boundary_transitions, boundary_gaps, transition_duration, min_overlap_seconds,
        )
    else:
        command = build_ffmpeg_command(
            input_path, output_path, start, end, crop_filter, subtitles_path,
            fade_seconds, video_duration, subtitle_style, denoise, loudnorm,
            vignette, grain_strength, punch_zoom_at, punch_zoom_amount, punch_zoom_ramp,
            denoise_strength,
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
        "--sub-strip-punctuation", action=argparse.BooleanOptionalAction, default=True,
        help="Strip leading/trailing punctuation from burned-in caption words (default: on)",
    )
    parser.add_argument(
        "--denoise", action=argparse.BooleanOptionalAction, default=True,
        help="Apply an FFmpeg noise-reduction filter (afftdn) to each clip's audio",
    )
    parser.add_argument(
        "--denoise-strength", type=float, default=6.0,
        help="afftdn noise-reduction amount in dB, 0.01-97 (FFmpeg default 12 is aggressive on "
        "mixed game+voice audio and can smear non-voice sound into a wind-like artifact)",
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
    parser.add_argument(
        "--transition-duration", type=float, default=0.35,
        help="Target xfade/acrossfade duration in seconds for a plan entry's boundary_transitions "
        "(clamped down to the available pause gap per boundary)",
    )
    parser.add_argument(
        "--min-overlap-seconds", type=float, default=0.12,
        help="A boundary_transitions entry whose borrowed pause gap is below this many seconds "
        "falls back to a plain cut instead of a transition (TRANS-03)",
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
        "strip_punctuation": args.sub_strip_punctuation,
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
            denoise_strength=args.denoise_strength,
            loudnorm=args.loudnorm,
            vignette=args.vignette,
            grain_strength=args.grain_strength,
            punch_zoom_amount=args.punch_zoom_amount,
            punch_zoom_ramp=args.punch_zoom_ramp,
            transition_duration=args.transition_duration,
            min_overlap_seconds=args.min_overlap_seconds,
        )
        print(output_path)


if __name__ == "__main__":
    main()
