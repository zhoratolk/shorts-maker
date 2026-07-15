from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

# Shared render primitives live in render_common so the poster generator
# (thumbnail.py) can reuse the exact same drawtext/font helpers without
# reaching across a module boundary into render.py's privates. Re-exported
# here so existing `from scripts.render import ...` call sites keep working.
from scripts.render_common import (
    RenderError,
    TARGET_HEIGHT,
    TARGET_WIDTH,
    _drawtext_color,
    _escape_drawtext_text,
    _wrap_banner_lines,
    encode_flags,
    resolve_banner_font,
)

# Phase 10 overlay finalize pass (outro card + social popups). render_clip
# uses these three; the remaining builders (build_social_popup_nodes,
# build_outro_nodes, _popup_slide_x) live in scripts.overlay_pass and are
# exercised there / by tests importing them directly.
from scripts.overlay_pass import (
    OUTRO_PATTERNS,
    build_overlay_pass_command,
    plan_popup_times,
)

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


VALID_EMPHASIS_KINDS = {"zoom": 1.0, "punch": 0.6, "cut_in": 0.15}
VALID_EMPHASIS_TARGETS = ("action", "plate", "face")


def build_emphasis_filter(
    moves: list[dict],
    *,
    zoom_amount: float = 1.12,
    ramp: float = 0.18,
    min_hold: float = 0.25,
    max_moves: int = 2,
    plate_focus_y: float = 0.72,
    face_focus: tuple[float, float] | None = None,
) -> str | None:
    """Transient, multi-move "editor punch" zoom applied *inside* a clip
    (Phase 9), distinct from build_punch_zoom_filter's single ramp-and-hold.

    Each move pulses: ease-in to zoom_amount over `ramp` s, hold at peak, then
    ease-out back to 1x - so several accents can fire across one continuous
    clip without the frame ratcheting ever tighter, the way a human editor
    punches in on a reaction or a hot gameplay beat and then releases. All
    moves fold into ONE time-varying crop node (evaluated per frame via `t`),
    then scale back so downstream filters always see a constant 1080x1920.

    Works on any crop_style: at rest z=1 => out_w==in_w => the focal x/y shift
    terms multiply by 0, so the frame is byte-identical to no-emphasis between
    moves and whenever `moves` is empty. (This is why it can safely run on
    pad/original-16:9, which punch_zoom_at is barred from: the pulse returns to
    1x and never leaves the frame permanently re-cropped.)

    Focal point per move.target:
      - 'action' (default): frame centre.
      - 'plate': biased down toward the nick-plate / lower third (plate_focus_y).
      - 'face':  face_focus (facecam region centre) when provided, else centre
                 (no webcam yet - gated by EmphasisConfig.face_enabled upstream).
    move.kind tunes snappiness via the ramp multiplier in VALID_EMPHASIS_KINDS:
    'zoom' eases (full ramp), 'punch' is quicker, 'cut_in' near-instant.

    Returns None when there is nothing to apply, so callers omit the filter
    entirely (fail-open / backward-compatible).
    """
    if zoom_amount <= 1.0:
        raise RenderError(f"emphasis zoom_amount must be > 1.0, got {zoom_amount}")
    if ramp <= 0:
        raise RenderError(f"emphasis ramp must be > 0, got {ramp}")
    if min_hold < 0:
        raise RenderError(f"emphasis min_hold must be >= 0, got {min_hold}")
    if max_moves <= 0 or not moves:
        return None

    ordered = sorted(moves, key=lambda m: float(m["at"]))[:max_moves]

    z_branches: list[tuple[float, float, str]] = []
    fx_branches: list[tuple[float, float, float]] = []
    fy_branches: list[tuple[float, float, float]] = []
    prev_end = -1.0
    for move in ordered:
        at = float(move["at"])
        duration = float(move["duration"])
        if at < 0:
            raise RenderError(f"emphasis move 'at' must be >= 0, got {at}")
        if duration <= 0:
            raise RenderError(f"emphasis move 'duration' must be > 0, got {duration}")
        kind = move.get("kind", "zoom")
        if kind not in VALID_EMPHASIS_KINDS:
            raise RenderError(
                f"emphasis move 'kind' must be one of {sorted(VALID_EMPHASIS_KINDS)}, got {kind!r}"
            )
        target = move.get("target", "action")
        if target not in VALID_EMPHASIS_TARGETS:
            raise RenderError(
                f"emphasis move 'target' must be one of {list(VALID_EMPHASIS_TARGETS)}, got {target!r}"
            )

        r = ramp * VALID_EMPHASIS_KINDS[kind]
        # Clamp duration up so a move always fits ramp-in + min_hold + ramp-out;
        # the piecewise expression below assumes rout_start >= rin_end.
        dur = max(duration, 2 * r + min_hold)
        # Skip a move that would start before the previous one has released,
        # rather than emit overlapping between() windows that double-zoom.
        if at < prev_end:
            continue
        end = at + dur
        rin_end = at + r
        rout_start = end - r
        z = zoom_amount
        z_expr = (
            f"if(lt(t,{rin_end:.4f}),1+({z}-1)*(t-{at:.4f})/{r:.4f},"
            f"if(lt(t,{rout_start:.4f}),{z},"
            f"1+({z}-1)*({end:.4f}-t)/{r:.4f}))"
        )
        z_branches.append((at, end, z_expr))

        if target == "plate":
            fx, fy = 0.5, plate_focus_y
        elif target == "face" and face_focus is not None:
            fx, fy = face_focus
        else:
            fx, fy = 0.5, 0.5
        fx_branches.append((at, end, fx))
        fy_branches.append((at, end, fy))
        prev_end = end

    if not z_branches:
        return None

    def _fold_expr(branches: list[tuple[float, float, str]], rest: str) -> str:
        expr = rest
        for at, end, val in reversed(branches):
            expr = f"if(between(t,{at:.4f},{end:.4f}),{val},{expr})"
        return expr

    z_of_t = _fold_expr(z_branches, "1")
    fx_of_t = _fold_expr([(a, e, f"{v}") for a, e, v in fx_branches], "0.5")
    fy_of_t = _fold_expr([(a, e, f"{v}") for a, e, v in fy_branches], "0.5")

    return (
        f"crop=w='{TARGET_WIDTH}/({z_of_t})':h='{TARGET_HEIGHT}/({z_of_t})':"
        f"x='(in_w-out_w)*({fx_of_t})':y='(in_h-out_h)*({fy_of_t})',"
        f"scale={TARGET_WIDTH}:{TARGET_HEIGHT}"
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


def build_profanity_mask_filter(
    spans: list[tuple[float, float]],
    duck_volume: float = 0.12,
    garble_freq: float = 1800.0,
    garble_width_octaves: float = 4.0,
    warble_freq: float = 18.0,
    warble_depth: float = 0.7,
) -> str | None:
    """A time-windowed duck+garble mask (AUDIO-02/AUDIO-03, D-03: duck the
    word's volume down and layer a bandreject+tremolo garble on top - not a
    clean beep, not a silence cut) gated by a shared `enable` timeline
    expression so it applies only inside the given clip-relative spans and
    passes the rest of the clip's audio through unmodified (07-RESEARCH.md
    Pattern 1, live-verified against ffmpeg 8.1.2).

    Multiple spans are OR-composed into one `between(t,s,e)+...` expression
    reused across all three filters, keeping the filter graph flat (3 nodes
    regardless of span count - 07-RESEARCH.md Pitfall 5).

    Returns None when spans is empty (no masking needed).
    """
    if not spans:
        return None
    if not (0.0 < duck_volume < 1.0):
        raise RenderError(f"duck_volume must be between 0 and 1 (exclusive), got {duck_volume}")
    for start, end in spans:
        if start < 0 or end <= start:
            raise RenderError(f"invalid profanity span ({start}, {end})")

    enable_expr = "+".join(f"between(t,{start},{end})" for start, end in spans)
    return (
        f"volume=enable='{enable_expr}':volume={duck_volume},"
        f"bandreject=enable='{enable_expr}':f={garble_freq}:width_type=o:w={garble_width_octaves},"
        f"tremolo=enable='{enable_expr}':f={warble_freq}:d={warble_depth}"
    )


def build_profanity_sound_filter(
    spans: list[tuple[float, float]],
    sound_input_index: int,
) -> tuple[str, list[str], int] | None:
    """Builds the mute-clause + censor-branch pieces of the custom-sound
    profanity mask (07-05 mask_mode="sound"): instead of duck+garble, the
    main track is muted inside each span (same shared OR-composed `enable`
    timeline as build_profanity_mask_filter, so both masks stay on one
    timeline expression) and a censor sound clip (already opened as input
    index `sound_input_index`) is looped, trimmed to each span's duration,
    delayed to the span's start, and later amixed on top by the caller.

    Returns (mute_clause, censor_branches, num_extra_inputs) - the caller is
    responsible for adding the sound file as an extra -i input and folding
    censor_branches + an amix stage into its own filter_complex.
    censor_branches is [asplit_stage?, branch_0, branch_1, ...] - the asplit
    stage is only present when there is more than one span (single-span case
    reads directly from [sound_input_index:a], no asplit needed).

    Returns None when spans is empty (no masking needed - mirrors
    build_profanity_mask_filter).
    """
    if not spans:
        return None
    for start, end in spans:
        if start < 0 or end <= start:
            raise RenderError(f"invalid profanity span ({start}, {end})")

    enable_expr = "+".join(f"between(t,{start},{end})" for start, end in spans)
    mute_clause = f"volume=enable='{enable_expr}':volume=0"

    span_count = len(spans)
    censor_branches: list[str] = []
    if span_count > 1:
        split_labels = "".join(f"[s{i}]" for i in range(span_count))
        censor_branches.append(f"[{sound_input_index}:a]asplit={span_count}{split_labels}")
        sources = [f"[s{i}]" for i in range(span_count)]
    else:
        sources = [f"[{sound_input_index}:a]"]

    for index, (start, end) in enumerate(spans):
        span_duration = round(end - start, 3)
        start_ms = round(start * 1000)
        censor_branches.append(
            f"{sources[index]}aloop=loop=-1:size=2e9,atrim=0:{span_duration},"
            f"asetpts=PTS-STARTPTS,adelay={start_ms}:all=1[c{index}]"
        )

    return mute_clause, censor_branches, 1


def build_audio_filter_chain(
    denoise: bool, loudnorm: bool, fade_filter: str | None, denoise_strength: float = 6.0,
    profanity_filter: str | None = None,
) -> str | None:
    """Combines the optional cleanup filters, the profanity mask, and the
    fade into one -af chain.

    Order matters: denoise the raw signal first, normalize loudness on the
    cleaned signal, then apply the profanity mask (07-RESEARCH.md Pattern 1 -
    it must come after loudnorm so loudnorm's own gain-riding can't partially
    undo the duck), then fade last so the fade-out isn't undone by loudnorm.
    """
    filters = []
    if denoise:
        filters.append(f"afftdn=nr={denoise_strength}")
    if loudnorm:
        filters.append("loudnorm=I=-16:TP=-1.5:LRA=11")
    if profanity_filter:
        filters.append(profanity_filter)
    if fade_filter:
        filters.append(fade_filter)
    return ",".join(filters) if filters else None


# Top edge of the banner block: clears the ~120px platform top-UI band
# (username/follow chrome) with a small margin. Bottom-positioned banners
# stay above the ~480px caption/engagement zone.
HOOK_BANNER_TOP_Y = 140
HOOK_BANNER_BOTTOM_CLEARANCE = 480


def build_hook_banner_filter(
    text: str,
    mode: str,
    cta_text: str = "",
    font: str = "Arial Black",
    cta_font: str = "Arial Bold",
    size: int = 58,
    cta_size: int = 36,
    color: str = "white",
    cta_color: str = "#ffe98a",
    box_color: str = "black",
    box_opacity: float = 0.55,
    position: str = "top",
    duration_seconds: float = 3.0,
    fade_seconds: float = 0.4,
    max_lines: int = 2,
    line_gap: int = 20,
) -> str | None:
    """Chained-drawtext hook banner (HOOK-01): one clause per wrapped title
    line plus an optional CTA/nick line under it. Multi-line MUST be chained
    clauses, never an embedded \\n - a literal \\n inside text= renders as a
    stray lowercase n when the command is built as an argv list
    (08-RESEARCH Pitfall 2, live-verified).

    mode="hook": every clause is gated to the first duration_seconds via
    enable= plus an alpha fade-out (fade_seconds=0 -> hard cut, enable only).
    mode="persistent" (the ROADMAP 2026-07-12 locked default): no gating,
    the plate shows for the whole clip.

    Returns None for empty/whitespace text (fail-open, HOOK-03) - the caller
    omits the filter entirely, keeping the command byte-identical to today.
    """
    if not text or not text.strip():
        return None
    if mode not in ("hook", "persistent"):
        raise RenderError(f"banner mode must be 'hook' or 'persistent', got {mode!r}")
    if position not in ("top", "bottom"):
        raise RenderError(f"banner position must be 'top' or 'bottom', got {position!r}")
    if size <= 0 or cta_size <= 0:
        raise RenderError(f"banner font sizes must be > 0, got size={size}, cta_size={cta_size}")
    if not 0.0 <= box_opacity <= 1.0:
        raise RenderError(f"banner box_opacity must be within [0, 1], got {box_opacity}")
    if mode == "hook":
        if duration_seconds <= 0:
            raise RenderError(f"banner duration_seconds must be > 0 in hook mode, got {duration_seconds}")
        if fade_seconds < 0 or fade_seconds >= duration_seconds:
            raise RenderError(
                f"banner fade_seconds must be within [0, duration_seconds), got {fade_seconds}"
            )

    # fontfile paths carry a drive colon on Windows - escape it exactly like
    # the subtitles= path clause below does.
    font_path = resolve_banner_font(font).replace(":", "\\:")
    cta_font_path = resolve_banner_font(cta_font).replace(":", "\\:")
    boxcolor = f"{_drawtext_color(box_color)}@{box_opacity}"

    # ~22 chars/line was measured (not estimated) at fontsize=58 on a real
    # rendered frame (08-RESEARCH A1); scale the budget mechanically.
    max_chars = max(8, round(22 * 58 / size))
    lines = _wrap_banner_lines(text.strip(), max_chars, max_lines)
    cta = cta_text.strip()

    line_height = size + line_gap
    block_height = len(lines) * line_height + (cta_size + line_gap if cta else 0)
    y0 = (
        HOOK_BANNER_TOP_Y
        if position == "top"
        else TARGET_HEIGHT - HOOK_BANNER_BOTTOM_CLEARANCE - block_height
    )

    clauses = []
    for index, line in enumerate(lines):
        clauses.append(
            f"drawtext=fontfile='{font_path}':text='{_escape_drawtext_text(line)}':"
            f"fontsize={size}:fontcolor={_drawtext_color(color)}:expansion=none:"
            f"x=(w-text_w)/2:y={y0 + index * line_height}:box=1:boxcolor={boxcolor}:boxborderw=24"
        )
    if cta:
        clauses.append(
            f"drawtext=fontfile='{cta_font_path}':text='{_escape_drawtext_text(cta)}':"
            f"fontsize={cta_size}:fontcolor={_drawtext_color(cta_color)}:expansion=none:"
            f"x=(w-text_w)/2:y={y0 + len(lines) * line_height}:box=1:boxcolor={boxcolor}:boxborderw=16"
        )

    if mode == "hook":
        suffix = f":enable='between(t,0,{duration_seconds})'"
        if fade_seconds > 0:
            fade_start = round(duration_seconds - fade_seconds, 3)
            suffix += f":alpha='if(lt(t,{fade_start}),1,max(0,1-(t-{fade_start})/{fade_seconds}))'"
        clauses = [f"{clause}{suffix}" for clause in clauses]

    return ",".join(clauses)


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
    profanity_filter: str | None = None,
    profanity_sound: tuple[str, str, list[str]] | None = None,
    video_codec: str = "libx264",
    preset: str | None = None,
    crf: int | None = None,
    banner_filter: str | None = None,
    emphasis_filter: str | None = None,
) -> list[str]:
    """profanity_sound, when set, is (sound_path, mute_clause,
    censor_branches) from build_profanity_sound_filter - folds BOTH video
    and audio into one -filter_complex (mirroring build_jumpcut_command's
    [vout]/[aout] structure) since -vf cannot coexist with -filter_complex.
    When None (the default / garble-mask path), the original plain -vf/-af
    command is produced byte-identically."""
    clip_duration = end - start
    tail_available = 0.0 if video_duration is None else max(0.0, video_duration - end)
    extend, fade_start, fade_duration = compute_fade_plan(clip_duration, fade_seconds, tail_available)
    total_duration = round(clip_duration + extend, 3)

    video_filter = crop_filter
    if punch_zoom_at is not None:
        video_filter = f"{video_filter},{build_punch_zoom_filter(punch_zoom_at, punch_zoom_amount, punch_zoom_ramp)}"
    # Mid-clip emphasis pulses (Phase 9): after punch-zoom, before effects/
    # banner/subtitles so the transient zoom acts on raw video content and
    # never shifts the burned-in banner or captions (same ordering rule as
    # banner_filter below, applied in all three command builders).
    if emphasis_filter:
        video_filter = f"{video_filter},{emphasis_filter}"
    effects_chain = build_video_effects_chain(vignette, grain_strength)
    if effects_chain:
        video_filter = f"{video_filter},{effects_chain}"
    # After punch-zoom (so the zoom crop can never clip/shift the banner),
    # before subtitles (captions stay the last visual layer) - 08-RESEARCH
    # Pattern 2; same ordering in all three command builders.
    if banner_filter:
        video_filter = f"{video_filter},{banner_filter}"
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

    if profanity_sound is not None:
        sound_path, mute_clause, censor_branches = profanity_sound
        if not Path(sound_path).exists():
            raise RenderError(f"profanity censor sound file not found: {sound_path}")

        audio_filter_chain = build_audio_filter_chain(
            denoise, loudnorm, fade_filter, denoise_strength, mute_clause
        ) or "anull"
        span_count = sum(1 for branch in censor_branches if "adelay=" in branch)
        amix_stage = (
            "[main]" + "".join(f"[c{i}]" for i in range(span_count))
            + f"amix=inputs={span_count + 1}:duration=first:normalize=0[aout]"
        )
        filter_complex = ";".join(
            [f"[0:v]{video_filter}[vout]", f"[0:a]{audio_filter_chain}[main]", *censor_branches, amix_stage]
        )
        return [
            "ffmpeg", "-y",
            "-loglevel", "error",
            # -t must precede its -i: placed after input_path it would bind
            # to the NEXT input (the censor sound), leaving the main input
            # unbounded and encoding the whole rest of the source.
            "-ss", str(start),
            "-t", str(total_duration),
            "-i", input_path,
            "-i", sound_path,
            "-filter_complex", filter_complex,
            "-map", "[vout]",
            "-map", "[aout]",
            *encode_flags(video_codec, preset, crf),
            "-c:a", "aac",
            output_path,
        ]

    audio_filter_chain = build_audio_filter_chain(
        denoise, loudnorm, fade_filter, denoise_strength, profanity_filter
    )
    audio_args = ["-af", audio_filter_chain] if audio_filter_chain else []

    return [
        "ffmpeg", "-y",
        "-loglevel", "error",
        "-ss", str(start),
        "-t", str(total_duration),
        "-i", input_path,
        "-vf", video_filter,
        *audio_args,
        *encode_flags(video_codec, preset, crf),
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
    profanity_filter: str | None = None,
    profanity_sound: tuple[str, str, list[str]] | None = None,
    video_codec: str = "libx264",
    preset: str | None = None,
    crf: int | None = None,
    banner_filter: str | None = None,
    emphasis_filter: str | None = None,
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
    # Mid-clip emphasis pulses (Phase 9) - after punch-zoom, before effects/
    # banner/subtitles (same ordering as build_ffmpeg_command).
    if emphasis_filter:
        video_ops.append(emphasis_filter)
    effects_chain = build_video_effects_chain(vignette, grain_strength)
    if effects_chain:
        video_ops.append(effects_chain)
    # After punch-zoom, before subtitles - 08-RESEARCH Pattern 2.
    if banner_filter:
        video_ops.append(banner_filter)
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

    video_stage = f"[vcat]{','.join(video_ops)}[vout]"

    extra_inputs: list[str] = []
    if profanity_sound is not None:
        sound_path, mute_clause, censor_branches = profanity_sound
        if not Path(sound_path).exists():
            raise RenderError(f"profanity censor sound file not found: {sound_path}")

        audio_filter_chain = build_audio_filter_chain(
            denoise, loudnorm, fade_filter, denoise_strength, mute_clause
        ) or "anull"
        span_count = sum(1 for branch in censor_branches if "adelay=" in branch)
        amix_stage = (
            "[main]" + "".join(f"[c{i}]" for i in range(span_count))
            + f"amix=inputs={span_count + 1}:duration=first:normalize=0[aout]"
        )
        audio_stage = f"[acat]{audio_filter_chain}[main]"
        filter_complex = ";".join(stages + [video_stage, audio_stage, *censor_branches, amix_stage])
        extra_inputs = ["-i", sound_path]
    else:
        audio_filter_chain = build_audio_filter_chain(
            denoise, loudnorm, fade_filter, denoise_strength, profanity_filter
        ) or "anull"
        audio_stage = f"[acat]{audio_filter_chain}[aout]"
        filter_complex = ";".join(stages + [video_stage, audio_stage])

    return [
        "ffmpeg", "-y",
        "-loglevel", "error",
        # -t before -i: as a trailing option it would bind to the next input
        # (extra_inputs' censor sound) instead of bounding this clip.
        "-ss", str(clip_start),
        "-t", str(round(clip_end - clip_start, 3)),
        "-i", input_path,
        *extra_inputs,
        "-filter_complex", filter_complex,
        "-map", "[vout]",
        "-map", "[aout]",
        *encode_flags(video_codec, preset, crf),
        "-c:a", "aac",
        output_path,
    ]


def _build_compilation_fold(
    flat_segments: list[tuple[int, float, float]],
    boundary_transitions: list[str],
    transition_duration: float,
    min_overlap_seconds: float,
) -> tuple[list[str], float]:
    """Builds the pairwise xfade/acrossfade fold stages for a compilation
    whose flattened member segments carry at least one non-cut boundary
    transition - mirrors _build_transition_fold's accumulate loop almost
    verbatim (same acc_v/acc_a accumulation, same build_transition_filter
    call, same concat=n=2 downgrade line, same acc_duration formula, same
    last-resort d_eff-vs-acc_duration safety net).

    Critical difference from _build_transition_fold (05-RESEARCH.md Pattern
    1): there is no boundary_gaps parameter and no trim-extension-into-a-gap
    step at all. Unlike a single clip's internal jump-cut boundary (which
    borrows real, already-cut, unused pause footage), a compilation stitch
    point between two separately-approved candidates has no such free
    footage to borrow - any overlap instead comes from a small, capped slice
    of each side's own *kept* content. Segment durations for the effective-
    overlap computation come directly from each flattened segment's own
    (already fixed) rel_end - rel_start, and the per-boundary cap is bounded
    to at most half of either adjacent segment's own duration rather than a
    borrowed gap - downgrading to a plain concat (like _build_transition_fold
    does) whenever the capped duration is below min_overlap_seconds.

    Returns (fold_stages, total_output_duration) - fold_stages' final node
    writes to [vcat]/[acat], same as build_compilation_command's flat-concat
    branch, so the caller's downstream video_ops/audio_stage code is
    unchanged regardless of which path built the graph. Unlike
    _build_transition_fold, trim_stages are not built here - the caller
    already built them from fixed (never-extended) flat_segments bounds.
    """
    segment_count = len(flat_segments)
    durations = [round(seg_end - seg_start, 3) for _, seg_start, seg_end in flat_segments]

    effective_duration: list[float | None] = []
    for boundary in range(segment_count - 1):
        transition_type = boundary_transitions[boundary]
        if transition_type in ("cut", "match_cut"):
            effective_duration.append(None)
            continue
        seg_a_duration = durations[boundary]
        seg_b_duration = durations[boundary + 1]
        d_eff = min(transition_duration, seg_a_duration / 2, seg_b_duration / 2)
        if d_eff < min_overlap_seconds:
            effective_duration.append(None)
            continue
        effective_duration.append(round(d_eff, 3))

    fold_stages = []
    acc_v, acc_a = "v0", "a0"
    acc_duration = durations[0]
    for index in range(1, segment_count):
        seg_duration = durations[index]
        is_last = index == segment_count - 1
        out_v = "vcat" if is_last else f"vfold{index}"
        out_a = "acat" if is_last else f"afold{index}"
        d_eff = effective_duration[index - 1]

        # Last-resort safety net, mirrors _build_transition_fold: even with
        # the per-boundary half-duration cap above, downgrade to a plain
        # concat rather than let offset go negative and raise out of
        # build_transition_filter.
        if d_eff is None or d_eff > acc_duration:
            fold_stages.append(f"[{acc_v}][{acc_a}][v{index}][a{index}]concat=n=2:v=1:a=1[{out_v}][{out_a}]")
            acc_duration = round(acc_duration + seg_duration, 3)
        else:
            offset = round(acc_duration - d_eff, 3)
            video_node = build_transition_filter(
                boundary_transitions[index - 1], d_eff, offset, acc_v, f"v{index}", out_v
            )
            fold_stages.append(video_node)
            fold_stages.append(f"[{acc_a}][a{index}]acrossfade=d={d_eff}[{out_a}]")
            acc_duration = round(acc_duration + seg_duration - d_eff, 3)

        acc_v, acc_a = out_v, out_a

    return fold_stages, acc_duration


def build_compilation_command(
    input_path: str,
    output_path: str,
    members: list[dict],
    crop_filter: str,
    boundary_transitions: list[str] | None = None,
    transition_duration: float = 0.35,
    min_overlap_seconds: float = 0.12,
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
    profanity_filter: str | None = None,
    profanity_sound: tuple[str, str, list[str]] | None = None,
    video_codec: str = "libx264",
    preset: str | None = None,
    crf: int | None = None,
    banner_filter: str | None = None,
    emphasis_filter: str | None = None,
) -> list[str]:
    """Multi-input ffmpeg command builder for a COMP-02 compilation entry:
    opens the source video once per compilation member (own -ss/-i/-t per
    member) rather than one -ss/-i spanning the whole compilation's time
    range - members can sit arbitrarily far apart in source time, and ffmpeg
    never decodes the span between them.

    Each members entry is `{"start": float, "end": float, "keep_segments":
    list[[float, float]] | None}` in absolute source-file seconds - exactly
    the "segments" shape build_compilation_entry (Plan 05-02) produces on a
    PLAN.json "compilation" entry. Every member's own segments (its internal
    jump cuts if it has keep_segments, else its single start/end window) are
    flattened into one render-order list, folded pairwise via the same
    build_transition_filter/concat-downgrade machinery build_jumpcut_command
    already uses for single-clip jump cuts (see _build_compilation_fold for
    the one deliberate difference: no borrowed pause-gap overlap). crop/
    punch-zoom/subtitles/fade are applied exactly once on the folded result
    (D-06), reusing build_jumpcut_command's own post-fold tail verbatim.
    """
    if not members:
        raise RenderError("members must not be empty")
    if len(members) < 2:
        raise RenderError("a compilation needs >= 2 members")

    if boundary_transitions is not None:
        for transition_type in boundary_transitions:
            if transition_type not in VALID_TRANSITIONS:
                raise RenderError(
                    f"boundary_transitions entries must be one of {sorted(VALID_TRANSITIONS)}, "
                    f"got {transition_type!r}"
                )

    # -ss before -i on each input seeks fast and resets that input's own
    # decoded timeline to 0 - every flattened segment below is expressed
    # relative to its own member's start, not the source file's absolute time.
    input_args: list[str] = []
    for member in members:
        # -t before this member's -i: trailing it would bind to the NEXT
        # member's input (or the censor sound), shifting every duration by one.
        input_args += [
            "-ss", str(member["start"]),
            "-t", str(round(member["end"] - member["start"], 3)),
            "-i", input_path,
        ]

    flat_segments: list[tuple[int, float, float]] = []
    for input_index, member in enumerate(members):
        keep_segments = member.get("keep_segments")
        if keep_segments:
            for seg_start, seg_end in keep_segments:
                flat_segments.append(
                    (input_index, round(seg_start - member["start"], 3), round(seg_end - member["start"], 3))
                )
        else:
            flat_segments.append((input_index, 0.0, round(member["end"] - member["start"], 3)))

    expected_length = len(flat_segments) - 1
    if boundary_transitions is not None and len(boundary_transitions) != expected_length:
        raise RenderError(
            f"boundary_transitions length ({len(boundary_transitions)}) must equal "
            f"flattened segment count - 1 ({expected_length})"
        )

    trim_stages = []
    for flat_index, (input_index, rel_start, rel_end) in enumerate(flat_segments):
        trim_stages.append(
            f"[{input_index}:v]trim=start={rel_start}:end={rel_end},setpts=PTS-STARTPTS[v{flat_index}]"
        )
        trim_stages.append(
            f"[{input_index}:a]atrim=start={rel_start}:end={rel_end},asetpts=PTS-STARTPTS[a{flat_index}]"
        )

    uses_fold = boundary_transitions is not None and any(
        transition_type not in ("cut", "match_cut") for transition_type in boundary_transitions
    )

    if not uses_fold:
        concat_refs = "".join(f"[v{i}][a{i}]" for i in range(len(flat_segments)))
        concat_stage = f"{concat_refs}concat=n={len(flat_segments)}:v=1:a=1[vcat][acat]"
        stages = trim_stages + [concat_stage]
        total_duration = round(sum(rel_end - rel_start for _, rel_start, rel_end in flat_segments), 3)
    else:
        fold_stages, total_duration = _build_compilation_fold(
            flat_segments, boundary_transitions, transition_duration, min_overlap_seconds
        )
        stages = trim_stages + fold_stages

    _, fade_start, fade_duration = compute_fade_plan(total_duration, fade_seconds, tail_available=0.0)

    video_ops = [crop_filter]
    if punch_zoom_at is not None:
        video_ops.append(build_punch_zoom_filter(punch_zoom_at, punch_zoom_amount, punch_zoom_ramp))
    # Mid-clip emphasis pulses (Phase 9) - after punch-zoom, before effects/
    # banner/subtitles (same ordering as build_ffmpeg_command).
    if emphasis_filter:
        video_ops.append(emphasis_filter)
    effects_chain = build_video_effects_chain(vignette, grain_strength)
    if effects_chain:
        video_ops.append(effects_chain)
    # After punch-zoom, before subtitles - 08-RESEARCH Pattern 2.
    if banner_filter:
        video_ops.append(banner_filter)
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

    video_stage = f"[vcat]{','.join(video_ops)}[vout]"

    extra_inputs: list[str] = []
    if profanity_sound is not None:
        sound_path, mute_clause, censor_branches = profanity_sound
        if not Path(sound_path).exists():
            raise RenderError(f"profanity censor sound file not found: {sound_path}")

        audio_filter_chain = build_audio_filter_chain(
            denoise, loudnorm, fade_filter, denoise_strength, mute_clause
        ) or "anull"
        span_count = sum(1 for branch in censor_branches if "adelay=" in branch)
        amix_stage = (
            "[main]" + "".join(f"[c{i}]" for i in range(span_count))
            + f"amix=inputs={span_count + 1}:duration=first:normalize=0[aout]"
        )
        audio_stage = f"[acat]{audio_filter_chain}[main]"
        filter_complex = ";".join(stages + [video_stage, audio_stage, *censor_branches, amix_stage])
        extra_inputs = ["-i", sound_path]
    else:
        audio_filter_chain = build_audio_filter_chain(
            denoise, loudnorm, fade_filter, denoise_strength, profanity_filter
        ) or "anull"
        audio_stage = f"[acat]{audio_filter_chain}[aout]"
        filter_complex = ";".join(stages + [video_stage, audio_stage])

    return [
        "ffmpeg", "-y",
        "-loglevel", "error",
        *input_args,
        *extra_inputs,
        "-filter_complex", filter_complex,
        "-map", "[vout]",
        "-map", "[aout]",
        *encode_flags(video_codec, preset, crf),
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
    profanity_duck_volume: float = 0.12,
    profanity_garble_freq: float = 1800.0,
    profanity_garble_width_octaves: float = 4.0,
    profanity_warble_freq: float = 18.0,
    profanity_warble_depth: float = 0.7,
    profanity_mask_mode: str = "garble",
    profanity_mask_sound_path: str = "",
    video_codec: str = "libx264",
    preset: str | None = None,
    crf: int | None = None,
    banner_mode: str = "persistent",
    banner_font: str = "Arial Black",
    banner_size: int = 58,
    banner_color: str = "white",
    banner_cta_text: str = "",
    banner_cta_font: str = "Arial Bold",
    banner_cta_size: int = 36,
    banner_cta_color: str = "#ffe98a",
    banner_box_color: str = "black",
    banner_box_opacity: float = 0.55,
    banner_position: str = "top",
    banner_duration_seconds: float = 3.0,
    banner_fade_seconds: float = 0.4,
    emphasis_enabled: bool = False,
    emphasis_zoom_amount: float = 1.12,
    emphasis_ramp: float = 0.18,
    emphasis_min_hold: float = 0.25,
    emphasis_max_moves: int = 2,
    emphasis_plate_focus_y: float = 0.72,
    emphasis_face_enabled: bool = False,
    emphasis_face_focus: tuple[float, float] | None = None,
    social_enabled: bool = False,
    social_platforms: list[str] | None = None,
    social_icon_paths: dict[str, str] | None = None,
    social_labels: dict[str, str] | None = None,
    social_duration: float = 3.0,
    social_slide_seconds: float = 0.4,
    social_size: int = 44,
    social_box_color: str = "#9146ff",
    social_box_opacity: float = 0.92,
    social_font: str = "Arial Bold",
    social_y: int | None = None,
    outro_enabled: bool = False,
    outro_duration: float = 2.5,
    outro_nick: str = "",
    outro_cta: str = "",
    outro_icon_path: str = "",
    outro_font: str = "Arial Black",
    outro_nick_size: int = 120,
    outro_cta_size: int = 56,
    outro_pattern_count: int = 5,
    outro_fps: int = 30,
    queue_index: int = 0,
    runner=subprocess.run,
) -> list[str]:
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

    # Mid-clip emphasis moves (Phase 9). Unlike punch_zoom_at there is no
    # crop_style guard: each move pulses back to 1x, so on pad/original-16:9 it
    # only tightens transiently and never leaves the frame re-cropped. Built
    # once here and threaded to whichever command builder runs below, mirroring
    # banner_filter. Absent/empty emphasis_moves => emphasis_filter stays None
    # => rendering is byte-identical to today.
    emphasis_moves = plan_entry.get("emphasis_moves")
    emphasis_filter = None
    if emphasis_enabled and emphasis_moves:
        emphasis_filter = build_emphasis_filter(
            emphasis_moves,
            zoom_amount=emphasis_zoom_amount,
            ramp=emphasis_ramp,
            min_hold=emphasis_min_hold,
            max_moves=emphasis_max_moves,
            plate_focus_y=emphasis_plate_focus_y,
            face_focus=emphasis_face_focus if emphasis_face_enabled else None,
        )

    subtitles_path = plan_entry.get("subtitles_path")

    banner_text = plan_entry.get("banner_text")
    # Fail-loud collision guard (HOOK-02, 08-RESEARCH Pitfall 3): checked
    # here, BEFORE the ASS-bake block below nulls subtitle_style. Same
    # explanatory style as the punch_zoom_at guard above.
    if banner_text and subtitles_path is not None and subtitle_style is not None \
            and banner_position == subtitle_style["position"]:
        raise RenderError(
            f"banner position {banner_position!r} collides with subtitles position "
            f"{subtitle_style['position']!r}; set config.hook_banner.position and "
            "config.subtitles.position to different zones"
        )
    banner_filter = None
    if banner_text:
        banner_filter = build_hook_banner_filter(
            banner_text, banner_mode,
            cta_text=banner_cta_text, font=banner_font, cta_font=banner_cta_font,
            size=banner_size, cta_size=banner_cta_size, color=banner_color,
            cta_color=banner_cta_color, box_color=banner_box_color,
            box_opacity=banner_box_opacity, position=banner_position,
            duration_seconds=banner_duration_seconds, fade_seconds=banner_fade_seconds,
        )

    profanity_spans_raw = plan_entry.get("profanity_spans")
    profanity_filter = None
    # (spans, sound_path) - resolved into a (sound_path, mute_clause,
    # censor_branches) profanity_sound tuple per-branch below, once the
    # correct sound_input_index (1 for single-input builders, len(members)
    # for compilation) is known.
    profanity_sound_pending: tuple[list[tuple[float, float]], str] | None = None
    if profanity_spans_raw:
        profanity_spans = [(span[0], span[1]) for span in profanity_spans_raw]
        if profanity_mask_mode == "sound" and profanity_mask_sound_path and Path(profanity_mask_sound_path).exists():
            profanity_sound_pending = (profanity_spans, profanity_mask_sound_path)
        else:
            if profanity_mask_mode == "sound":
                print(
                    f"[warn] profanity mask_mode=sound but sound file {profanity_mask_sound_path!r} "
                    "is missing/empty; falling back to garble mask",
                    file=sys.stderr,
                )
            profanity_filter = build_profanity_mask_filter(
                profanity_spans,
                duck_volume=profanity_duck_volume,
                garble_freq=profanity_garble_freq,
                garble_width_octaves=profanity_garble_width_octaves,
                warble_freq=profanity_warble_freq,
                warble_depth=profanity_warble_depth,
            )

    if subtitles_path is not None and subtitle_style is not None:
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

    if plan_entry.get("type") == "compilation":
        # Compilation entries (COMP-02, Plan 05-02's build_compilation_entry)
        # have no top-level start/end - each member carries its own, clamped
        # individually below rather than once for the whole compilation.
        segments = plan_entry.get("segments")
        if not segments:
            raise RenderError("compilation plan_entry must have a non-empty 'segments' list")

        members: list[dict] = []
        for segment in segments:
            member_start, member_end = clamp_clip_bounds(segment["start"], segment["end"], video_duration)
            member: dict = {"start": member_start, "end": member_end}
            if segment.get("keep_segments"):
                member["keep_segments"] = [(seg[0], seg[1]) for seg in segment["keep_segments"]]
            members.append(member)

        profanity_sound = None
        if profanity_sound_pending is not None:
            spans, sound_path = profanity_sound_pending
            sound_filter_result = build_profanity_sound_filter(spans, sound_input_index=len(members))
            if sound_filter_result is not None:
                mute_clause, censor_branches, _ = sound_filter_result
                profanity_sound = (sound_path, mute_clause, censor_branches)

        command = build_compilation_command(
            input_path, output_path, members, crop_filter,
            boundary_transitions=plan_entry.get("boundary_transitions"),
            transition_duration=transition_duration,
            min_overlap_seconds=min_overlap_seconds,
            subtitles_path=subtitles_path,
            fade_seconds=fade_seconds,
            subtitle_style=subtitle_style,
            denoise=denoise,
            loudnorm=loudnorm,
            vignette=vignette,
            grain_strength=grain_strength,
            punch_zoom_at=punch_zoom_at,
            punch_zoom_amount=punch_zoom_amount,
            punch_zoom_ramp=punch_zoom_ramp,
            denoise_strength=denoise_strength,
            profanity_filter=profanity_filter,
            profanity_sound=profanity_sound,
            video_codec=video_codec,
            preset=preset, crf=crf,
            banner_filter=banner_filter,
            emphasis_filter=emphasis_filter,
        )
    else:
        start, end = clamp_clip_bounds(plan_entry["start"], plan_entry["end"], video_duration)

        profanity_sound = None
        if profanity_sound_pending is not None:
            spans, sound_path = profanity_sound_pending
            # Single existing -i input for both build_jumpcut_command and
            # build_ffmpeg_command, so the sound file always lands at index 1.
            sound_filter_result = build_profanity_sound_filter(spans, sound_input_index=1)
            if sound_filter_result is not None:
                mute_clause, censor_branches, _ = sound_filter_result
                profanity_sound = (sound_path, mute_clause, censor_branches)

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

                sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
                from scripts.jumpcuts import compute_boundary_gaps

                boundary_gaps = compute_boundary_gaps(keep_segments)
            command = build_jumpcut_command(
                input_path, output_path, start, end, keep_segments, crop_filter, subtitles_path,
                fade_seconds, subtitle_style, denoise, loudnorm,
                vignette, grain_strength, punch_zoom_at, punch_zoom_amount, punch_zoom_ramp,
                denoise_strength, boundary_transitions, boundary_gaps, transition_duration, min_overlap_seconds,
                profanity_filter, profanity_sound, video_codec,
                preset=preset, crf=crf,
                banner_filter=banner_filter,
                emphasis_filter=emphasis_filter,
            )
        else:
            command = build_ffmpeg_command(
                input_path, output_path, start, end, crop_filter, subtitles_path,
                fade_seconds, video_duration, subtitle_style, denoise, loudnorm,
                vignette, grain_strength, punch_zoom_at, punch_zoom_amount, punch_zoom_ramp,
                denoise_strength, profanity_filter, profanity_sound, video_codec,
                banner_filter=banner_filter,
                emphasis_filter=emphasis_filter,
            )

    result = runner(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise RenderError(f"ffmpeg failed for {output_path}: {result.stderr}")

    # Phase 10 overlay finalize pass: social popups + animated outro card, run
    # as a second pass over the just-rendered clip. Isolated here so the base
    # command builders stay byte-identical when disabled. Fail-open: any error
    # (missing icon, no `gradients` filter, ...) leaves the base clip in place.
    popups: list[dict] = []
    outro: dict | None = None
    if social_enabled and social_platforms:
        active = [
            platform for platform in social_platforms
            if (social_icon_paths or {}).get(platform) or (social_labels or {}).get(platform)
        ]
        if active:
            try:
                clip_duration = probe_video(output_path, runner=runner)["duration"]
            except (RenderError, KeyError, ValueError):
                clip_duration = 0.0
            for (at, dur), platform in zip(
                plan_popup_times(len(active), clip_duration, social_duration), active
            ):
                popups.append({
                    "icon_path": (social_icon_paths or {}).get(platform, ""),
                    "label": (social_labels or {}).get(platform, platform),
                    "at": at, "duration": dur,
                })
    if outro_enabled and (outro_nick or outro_cta or outro_icon_path):
        pattern_slots = max(1, min(outro_pattern_count, len(OUTRO_PATTERNS)))
        outro = {
            "duration": outro_duration, "nick": outro_nick, "cta": outro_cta,
            "icon_path": outro_icon_path, "font": outro_font,
            "nick_size": outro_nick_size, "cta_size": outro_cta_size,
            "pattern_index": queue_index % pattern_slots,
        }

    if popups or outro:
        final_path = Path(output_path)
        tmp_path = final_path.with_name(final_path.stem + "__overlay" + final_path.suffix)
        try:
            finalize_command = build_overlay_pass_command(
                output_path, str(tmp_path), popups=popups, outro=outro,
                video_codec=video_codec, preset=preset, crf=crf,
                popup_y=social_y, popup_size=social_size,
                popup_box_color=social_box_color, popup_box_opacity=social_box_opacity,
                popup_font=social_font, popup_slide_seconds=social_slide_seconds,
                outro_fps=outro_fps,
            )
            finalize_result = runner(finalize_command, capture_output=True, text=True)
            if finalize_result.returncode != 0:
                raise RenderError(finalize_result.stderr)
            tmp_path.replace(final_path)
        except Exception as error:  # noqa: BLE001 - fail-open, keep the base clip
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
            print(
                f"[warn] overlay finalize pass failed for {output_path}, keeping base clip: {error}",
                file=sys.stderr,
            )

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
    parser.add_argument(
        "--profanity-duck-volume", type=float, default=0.12,
        help="Volume multiplier applied inside a plan entry's profanity_spans (AUDIO-02 duck depth)",
    )
    parser.add_argument(
        "--profanity-garble-freq", type=float, default=1800.0,
        help="bandreject center frequency (Hz) for the profanity mask's garble layer (AUDIO-03)",
    )
    parser.add_argument(
        "--profanity-garble-width-octaves", type=float, default=4.0,
        help="bandreject width, in octaves, for the profanity mask's garble layer (AUDIO-03)",
    )
    parser.add_argument(
        "--profanity-warble-freq", type=float, default=18.0,
        help="tremolo modulation frequency (Hz) for the profanity mask's garble layer (D-03)",
    )
    parser.add_argument(
        "--profanity-warble-depth", type=float, default=0.7,
        help="tremolo modulation depth for the profanity mask's garble layer (D-03)",
    )
    parser.add_argument(
        "--profanity-mask-mode", default="garble", choices=["garble", "sound"],
        help="Which mask to apply inside a plan entry's profanity_spans: garble (duck+bandreject+tremolo) "
        "or sound (mute the span and overlay --profanity-mask-sound-path)",
    )
    parser.add_argument(
        "--profanity-mask-sound-path", default="",
        help="Path to a custom censor audio clip, used only when --profanity-mask-mode=sound "
        "(a missing file fails open to the garble mask)",
    )
    parser.add_argument(
        "--video-codec", default="libx264",
        help="ffmpeg -c:v encoder to use, e.g. h264_nvenc for NVIDIA hardware encoding (default: libx264)",
    )
    parser.add_argument(
        "--preset", default=None,
        help="ffmpeg -preset for the video encoder, e.g. veryfast for a faster libx264 encode at a "
        "size cost (default: unset = encoder's own default, byte-identical to before). x264/x265 only.",
    )
    parser.add_argument(
        "--crf", type=int, default=None,
        help="ffmpeg -crf quality/size knob for x264/x265 (lower = better/bigger; default: unset = "
        "encoder default). Leave unset for hardware encoders like h264_nvenc.",
    )
    # --banner-* flags are harmless no-ops for plan entries without banner_text
    # (same convention as --profanity-*).
    parser.add_argument(
        "--banner-mode", default="persistent", choices=["hook", "persistent"],
        help="Hook banner mode for plan entries with banner_text: hook (first --banner-duration-seconds, "
        "then gone) or persistent (whole clip + optional CTA line, the default)",
    )
    parser.add_argument("--banner-font", default="Arial Black")
    parser.add_argument("--banner-size", type=int, default=58)
    parser.add_argument("--banner-color", default="white")
    parser.add_argument(
        "--banner-cta-text", default="",
        help="Optional CTA/nick line drawn under the banner title (empty = no CTA line)",
    )
    parser.add_argument("--banner-cta-font", default="Arial Bold")
    parser.add_argument("--banner-cta-size", type=int, default=36)
    parser.add_argument("--banner-cta-color", default="#ffe98a")
    parser.add_argument("--banner-box-color", default="black")
    parser.add_argument("--banner-box-opacity", type=float, default=0.55)
    parser.add_argument("--banner-position", default="top", choices=["top", "bottom"])
    parser.add_argument("--banner-duration-seconds", type=float, default=3.0)
    parser.add_argument(
        "--banner-fade-seconds", type=float, default=0.4,
        help="Hook-mode fade-out length in seconds (0 = hard cut)",
    )
    parser.add_argument(
        "--emphasis-enabled", action="store_true",
        help="Apply mid-clip emphasis_moves from the plan entry (Phase 9); off = ignored",
    )
    parser.add_argument("--emphasis-zoom-amount", type=float, default=1.12)
    parser.add_argument("--emphasis-ramp", type=float, default=0.18)
    parser.add_argument("--emphasis-min-hold", type=float, default=0.25)
    parser.add_argument("--emphasis-max-moves", type=int, default=2)
    parser.add_argument("--emphasis-plate-focus-y", type=float, default=0.72)
    parser.add_argument(
        "--emphasis-face-enabled", action="store_true",
        help="Allow target='face' moves to aim at the facecam region (off: fall back to centre)",
    )
    # --social-* / --outro-* drive the Phase 10 overlay finalize pass. All are
    # harmless no-ops unless --social-enabled / --outro-enabled is set (same
    # convention as --banner-* / --emphasis-*).
    parser.add_argument(
        "--social-enabled", action="store_true",
        help="Draw sliding social capsules (twitch/kick) over each clip (Phase 10)",
    )
    parser.add_argument("--social-twitch-label", default="", help="Twitch capsule link text, e.g. twitch.tv/zhorikp")
    parser.add_argument("--social-twitch-icon", default="", help="Twitch capsule glyph PNG path")
    parser.add_argument("--social-kick-label", default="", help="Kick capsule link text (stub until a Kick glyph exists)")
    parser.add_argument("--social-kick-icon", default="", help="Kick capsule glyph PNG path (empty = text-only stub)")
    parser.add_argument("--social-duration", type=float, default=3.0)
    parser.add_argument("--social-slide-seconds", type=float, default=0.4)
    parser.add_argument("--social-size", type=int, default=44)
    parser.add_argument("--social-box-color", default="#9146ff")
    parser.add_argument("--social-box-opacity", type=float, default=0.92)
    parser.add_argument("--social-font", default="Arial Bold")
    parser.add_argument("--social-y", type=int, default=None, help="Capsule top Y in px (default ~52%% height)")
    parser.add_argument(
        "--outro-enabled", action="store_true",
        help="Append an animated end card (nick + platform glyph + link) to each clip (Phase 10)",
    )
    parser.add_argument("--outro-duration", type=float, default=2.5)
    parser.add_argument("--outro-nick", default="", help="Channel nick shown on the end card, e.g. ZhorikP")
    parser.add_argument("--outro-cta", default="", help="Link/CTA line under the nick, e.g. twitch.tv/zhorikp")
    parser.add_argument("--outro-icon", default="", help="Platform glyph PNG shown above the nick")
    parser.add_argument("--outro-font", default="Arial Black")
    parser.add_argument("--outro-nick-size", type=int, default=120)
    parser.add_argument("--outro-cta-size", type=int, default=56)
    parser.add_argument(
        "--outro-pattern-count", type=int, default=5,
        help="How many gradient presets to rotate through (by clip index) so consecutive shorts differ",
    )
    parser.add_argument("--outro-fps", type=int, default=30)
    args = parser.parse_args()

    # Fixed platform order for the popup pass; a platform is active only if it
    # carries a label or an icon (so the Kick stub disappears until configured).
    social_platforms = ["twitch", "kick"]
    social_icon_paths = {"twitch": args.social_twitch_icon, "kick": args.social_kick_icon}
    social_labels = {"twitch": args.social_twitch_label, "kick": args.social_kick_label}

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
            profanity_duck_volume=args.profanity_duck_volume,
            profanity_garble_freq=args.profanity_garble_freq,
            profanity_garble_width_octaves=args.profanity_garble_width_octaves,
            profanity_warble_freq=args.profanity_warble_freq,
            profanity_warble_depth=args.profanity_warble_depth,
            video_codec=args.video_codec,
            preset=args.preset,
            crf=args.crf,
            profanity_mask_mode=args.profanity_mask_mode,
            profanity_mask_sound_path=args.profanity_mask_sound_path,
            banner_mode=args.banner_mode,
            banner_font=args.banner_font,
            banner_size=args.banner_size,
            banner_color=args.banner_color,
            banner_cta_text=args.banner_cta_text,
            banner_cta_font=args.banner_cta_font,
            banner_cta_size=args.banner_cta_size,
            banner_cta_color=args.banner_cta_color,
            banner_box_color=args.banner_box_color,
            banner_box_opacity=args.banner_box_opacity,
            banner_position=args.banner_position,
            banner_duration_seconds=args.banner_duration_seconds,
            banner_fade_seconds=args.banner_fade_seconds,
            emphasis_enabled=args.emphasis_enabled,
            emphasis_zoom_amount=args.emphasis_zoom_amount,
            emphasis_ramp=args.emphasis_ramp,
            emphasis_min_hold=args.emphasis_min_hold,
            emphasis_max_moves=args.emphasis_max_moves,
            emphasis_plate_focus_y=args.emphasis_plate_focus_y,
            emphasis_face_enabled=args.emphasis_face_enabled,
            social_enabled=args.social_enabled,
            social_platforms=social_platforms,
            social_icon_paths=social_icon_paths,
            social_labels=social_labels,
            social_duration=args.social_duration,
            social_slide_seconds=args.social_slide_seconds,
            social_size=args.social_size,
            social_box_color=args.social_box_color,
            social_box_opacity=args.social_box_opacity,
            social_font=args.social_font,
            social_y=args.social_y,
            outro_enabled=args.outro_enabled,
            outro_duration=args.outro_duration,
            outro_nick=args.outro_nick,
            outro_cta=args.outro_cta,
            outro_icon_path=args.outro_icon,
            outro_font=args.outro_font,
            outro_nick_size=args.outro_nick_size,
            outro_cta_size=args.outro_cta_size,
            outro_pattern_count=args.outro_pattern_count,
            outro_fps=args.outro_fps,
            queue_index=index,
        )
        print(output_path)


if __name__ == "__main__":
    main()
