"""Phase 10 overlay finalize pass: the animated outro card + sliding social
popups, both applied as a SECOND ffmpeg pass over an already-rendered clip.

Kept in its own module (imported by render.py's render_clip) so the three
primary command builders and their fiddly filter_complex graphs stay in
render.py, untouched: when Phase 10 is disabled the base clip IS the final
clip, byte-identical. The pass is fail-open (any error keeps the base clip),
matching the diarization/audio_energy/hook_banner footing.
"""

from __future__ import annotations

from scripts.render_common import (
    TARGET_HEIGHT,
    TARGET_WIDTH,
    RenderError,
    _drawtext_color,
    _escape_drawtext_text,
    resolve_banner_font,
)

# Animated-gradient background presets for the end card. The preset is chosen
# per clip by queue_index % pattern_count so consecutive shorts don't share a
# look (the "меняться от шортса к шортсу" ask). c0/c1 are 0xRRGGBB; type/speed
# feed FFmpeg's `gradients` source (self-animating, so the card moves without
# any per-frame drawtext math). type values are limited to the four the filter
# actually supports: linear, radial, circular, spiral.
OUTRO_PATTERNS = [
    {"c0": "0x9146ff", "c1": "0x1f0a3a", "type": "radial", "speed": "0.015"},
    {"c0": "0x1f9bd6", "c1": "0x0a2038", "type": "linear", "speed": "0.020"},
    {"c0": "0xd61f8f", "c1": "0x3a0a24", "type": "spiral", "speed": "0.012"},
    {"c0": "0x1fd67a", "c1": "0x0a3824", "type": "circular", "speed": "0.018"},
    {"c0": "0xd6941f", "c1": "0x382408", "type": "linear", "speed": "0.016"},
]


def _popup_slide_x(at: float, dur: float, slide: float, capsule_w: int, margin: int) -> str:
    """Per-frame x expression for a capsule that slides in from the left edge,
    holds at `margin`, then slides back out. Off-screen start is -capsule_w so
    the whole capsule (box + icon + text, which all reuse this expression) is
    fully hidden before/after its window. Single-quoted by the caller so the
    commas inside if()/lt() are protected from the filtergraph parser.
    """
    a = round(at, 3)
    e = round(at + dur, 3)
    s = round(slide, 3)
    hold_end = round(e - s, 3)
    slide_in = f"(0-{capsule_w})+({capsule_w}+{margin})*(t-{a})/{s}"
    slide_out = f"{margin}-({capsule_w}+{margin})*(t-{hold_end})/{s}"
    return f"if(lt(t,{round(a + s, 3)}),{slide_in},if(lt(t,{hold_end}),{margin},{slide_out}))"


def plan_popup_times(
    count: int, clip_duration: float, popup_duration: float, edge: float = 0.3
) -> list[tuple[float, float]]:
    """Spread `count` social popups across a clip. Returns (at, dur) per popup;
    a popup that can't fit at least 1s of visible time before the tail `edge`
    is dropped (so the returned list may be shorter than count on a short clip
    - fail-open, never raises). Anchor fractions keep two popups (twitch+kick)
    comfortably apart with only one on screen at a time.
    """
    if count <= 0 or clip_duration <= 0:
        return []
    presets = {1: [0.22], 2: [0.16, 0.58], 3: [0.14, 0.44, 0.72]}
    fracs = presets.get(count, [(i + 1) / (count + 1) for i in range(count)])
    times: list[tuple[float, float]] = []
    for frac in fracs:
        at = round(clip_duration * frac, 3)
        dur = round(min(popup_duration, clip_duration - edge - at), 3)
        if dur >= 1.0:
            times.append((at, dur))
    return times


def build_social_popup_nodes(
    popups: list[dict],
    icon_index: dict[str, int],
    *,
    video_in: str = "0:v",
    margin: int = 40,
    y: int | None = None,
    size: int = 44,
    box_color: str = "#9146ff",
    box_opacity: float = 0.92,
    text_color: str = "white",
    font: str = "Arial Bold",
    slide_seconds: float = 0.4,
) -> tuple[list[str], str]:
    """Chained overlay nodes (drawbox capsule + optional icon overlay +
    drawtext link label, all sharing one slide-in x expression) for a list of
    social popups. Returns (filter_nodes, out_label). icon_index maps an icon
    path to its ffmpeg input index (base clip is input 0). A popup whose
    icon_path is missing from icon_index renders text-only (the Kick stub path
    until a Kick glyph asset exists).
    """
    if y is None:
        y = int(TARGET_HEIGHT * 0.52)
    font_path = resolve_banner_font(font).replace(":", "\\:")
    boxcolor = f"{_drawtext_color(box_color)}@{box_opacity}"
    pad = 24
    gap = 18
    hc = size + 44
    icon_side = size + 8
    nodes: list[str] = []
    cur = f"[{video_in}]"
    for j, popup in enumerate(popups):
        label = str(popup.get("label", "")).strip()
        at = float(popup["at"])
        dur = float(popup["duration"])
        has_icon = bool(popup.get("icon_path")) and popup["icon_path"] in icon_index
        text_w = max(1, round(len(label) * size * 0.6))
        icon_block = (icon_side + gap) if has_icon else 0
        wc = pad + icon_block + text_w + pad
        xc = _popup_slide_x(at, dur, slide_seconds, wc, margin)
        window = f"between(t,{round(at, 3)},{round(at + dur, 3)})"

        box_out = f"[pbox{j}]"
        nodes.append(
            f"{cur}drawbox=x='{xc}':y={y}:w={wc}:h={hc}:color={boxcolor}:t=fill:"
            f"enable='{window}'{box_out}"
        )
        cur = box_out

        if has_icon:
            icon_input = icon_index[popup["icon_path"]]
            icon_y = y + (hc - icon_side) // 2
            nodes.append(f"[{icon_input}:v]scale={icon_side}:{icon_side}[picon{j}]")
            pic_out = f"[ppic{j}]"
            nodes.append(
                f"{cur}[picon{j}]overlay=x='{xc}+{pad}':y={icon_y}:"
                f"enable='{window}'{pic_out}"
            )
            cur = pic_out

        text_x = f"{xc}+{pad}+{icon_block}"
        text_y = y + (hc - size) // 2
        txt_out = f"[ptxt{j}]"
        nodes.append(
            f"{cur}drawtext=fontfile='{font_path}':text='{_escape_drawtext_text(label)}':"
            f"fontsize={size}:fontcolor={_drawtext_color(text_color)}:expansion=none:"
            f"x='{text_x}':y={text_y}:enable='{window}'{txt_out}"
        )
        cur = txt_out
    return nodes, cur


def build_outro_nodes(
    outro: dict, icon_index: dict[str, int], *, fps: int = 30
) -> tuple[list[str], str, str]:
    """Nodes for the animated end card: a self-animating `gradients` background
    (preset chosen by outro['pattern_index']), the nick + CTA drawtext (both
    fading in over the first 0.5s), and the platform glyph fading in above the
    nick. Returns (filter_nodes, video_out_label, audio_out_label). The audio
    is a matched-format silence so the card can concat onto the base clip.
    """
    dur = round(float(outro["duration"]), 3)
    nick = str(outro.get("nick", "")).strip()
    cta = str(outro.get("cta", "")).strip()
    preset = OUTRO_PATTERNS[int(outro.get("pattern_index", 0)) % len(OUTRO_PATTERNS)]
    font = outro.get("font", "Arial Black")
    nick_size = int(outro.get("nick_size", 120))
    cta_size = int(outro.get("cta_size", 56))
    font_path = resolve_banner_font(font).replace(":", "\\:")
    fade_in = "if(lt(t,0.5),t/0.5,1)"
    nick_y = int(TARGET_HEIGHT * 0.40)

    nodes: list[str] = [
        f"gradients=s={TARGET_WIDTH}x{TARGET_HEIGHT}:c0={preset['c0']}:c1={preset['c1']}:"
        f"type={preset['type']}:speed={preset['speed']}:d={dur}:r={fps},"
        f"format=yuv420p,setsar=1[obg]"
    ]
    cur = "[obg]"
    if nick:
        out = "[onick]"
        nodes.append(
            f"{cur}drawtext=fontfile='{font_path}':text='{_escape_drawtext_text(nick)}':"
            f"fontsize={nick_size}:fontcolor=white:expansion=none:x=(w-text_w)/2:y={nick_y}:"
            f"alpha='{fade_in}':box=1:boxcolor=black@0.35:boxborderw=28{out}"
        )
        cur = out
    if cta:
        out = "[octa]"
        nodes.append(
            f"{cur}drawtext=fontfile='{font_path}':text='{_escape_drawtext_text(cta)}':"
            f"fontsize={cta_size}:fontcolor=0xffe98a:expansion=none:x=(w-text_w)/2:"
            f"y={nick_y + nick_size + 40}:alpha='{fade_in}'{out}"
        )
        cur = out
    icon_path = outro.get("icon_path", "")
    if icon_path and icon_path in icon_index:
        glyph_h = 220
        glyph_y = max(0, nick_y - glyph_h - 40)
        nodes.append(
            f"[{icon_index[icon_path]}:v]scale=-1:{glyph_h},format=rgba,"
            f"fade=t=in:st=0:d=0.5:alpha=1[oglyph]"
        )
        out = "[outv]"
        nodes.append(f"{cur}[oglyph]overlay=x=(W-w)/2:y={glyph_y}:eof_action=repeat{out}")
        cur = out

    nodes.append(f"anullsrc=r=48000:cl=stereo,atrim=0:{dur},asetpts=PTS-STARTPTS[oa]")
    return nodes, cur, "[oa]"


def build_overlay_pass_command(
    base_clip: str,
    output_path: str,
    *,
    popups: list[dict] | None = None,
    outro: dict | None = None,
    video_codec: str = "libx264",
    margin: int = 40,
    popup_y: int | None = None,
    popup_size: int = 44,
    popup_box_color: str = "#9146ff",
    popup_box_opacity: float = 0.92,
    popup_font: str = "Arial Bold",
    popup_slide_seconds: float = 0.4,
    outro_fps: int = 30,
) -> list[str]:
    """Assemble the single-pass overlay command over an already-rendered clip:
    social popups drawn onto the base video, then (if present) the animated
    outro card concatenated onto the end. Icon inputs are deduped and appended
    after the base clip (input 0). Raises RenderError if there is nothing to do
    - the caller guards on that, so it never happens in practice.
    """
    popups = popups or []
    if not popups and not outro:
        raise RenderError("build_overlay_pass_command needs at least one popup or an outro")

    icon_paths: list[str] = []
    for popup in popups:
        path = popup.get("icon_path")
        if path and path not in icon_paths:
            icon_paths.append(path)
    if outro and outro.get("icon_path") and outro["icon_path"] not in icon_paths:
        icon_paths.append(outro["icon_path"])
    icon_index = {path: idx + 1 for idx, path in enumerate(icon_paths)}

    graph: list[str] = []
    if popups:
        popup_nodes, decorated = build_social_popup_nodes(
            popups, icon_index, video_in="0:v", margin=margin, y=popup_y,
            size=popup_size, box_color=popup_box_color, box_opacity=popup_box_opacity,
            font=popup_font, slide_seconds=popup_slide_seconds,
        )
        graph.extend(popup_nodes)
    else:
        decorated = "[0:v]"

    if outro:
        # Normalize the decorated base to the outro's fps + pixfmt + SAR so the
        # concat with the generated card is always valid regardless of the
        # source clip's frame rate.
        graph.append(f"{decorated}fps={outro_fps},format=yuv420p,setsar=1[basev]")
        graph.append(
            "[0:a]aformat=sample_rates=48000:channel_layouts=stereo,asetpts=PTS-STARTPTS[basea]"
        )
        outro_nodes, outro_v, outro_a = build_outro_nodes(outro, icon_index, fps=outro_fps)
        graph.extend(outro_nodes)
        graph.append(f"[basev][basea]{outro_v}{outro_a}concat=n=2:v=1:a=1[vout][aout]")
        vmap, amap = "[vout]", "[aout]"
    else:
        # decorated is a real filtergraph pad ([ptxtN]) so it keeps its
        # brackets; the base audio is a raw input stream, mapped as 0:a WITHOUT
        # brackets (bracketed labels are filtergraph pads only).
        vmap, amap = decorated, "0:a"

    inputs: list[str] = ["-i", base_clip]
    for path in icon_paths:
        inputs += ["-i", path]

    return [
        "ffmpeg", "-y", "-loglevel", "error",
        *inputs,
        "-filter_complex", ";".join(graph),
        "-map", vmap, "-map", amap,
        "-c:v", video_codec, "-c:a", "aac",
        "-movflags", "+faststart",
        output_path,
    ]
