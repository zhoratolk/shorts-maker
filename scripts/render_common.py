"""Shared render primitives: the target frame geometry, the RenderError type,
and the low-level drawtext/font text helpers.

Extracted from render.py so both render.py and the poster generator
(thumbnail.py) draw the SAME captions the SAME way without thumbnail.py
reaching into render.py's private helpers across a module boundary. render.py
re-exports every name here, so existing `from scripts.render import ...`
call sites (and tests) keep working unchanged.
"""

from __future__ import annotations

import sys

# Output frame geometry - every vertical clip and poster targets this.
TARGET_WIDTH = 1080
TARGET_HEIGHT = 1920


class RenderError(ValueError):
    pass


VALID_TRANSITIONS = frozenset({"cut", "crossfade", "whip_pan", "mask_wipe", "glitch", "match_cut"})

# xfade transition names for the 3 types that map directly onto a single
# native ffmpeg xfade transition (04-RESEARCH.md Pattern 3). glitch has no
# single matching xfade name and is built as a small chain (Pattern 4);
# cut/match_cut render as a plain concat, no xfade node at all.
_XFADE_TRANSITION_NAMES = {
    "crossfade": "fade",
    "whip_pan": "hblur",
    "mask_wipe": "wipeleft",
}


def build_transition_filter(
    transition_type: str, duration: float, offset: float, in_a: str, in_b: str, out_label: str
) -> str | None:
    """The ffmpeg xfade-based video-graph node for one join between two clips.

    Lives here rather than in render.py because loop.py needs the identical
    vocabulary and deliberately does not import render.py (render.py imports
    loop.py - see loop.py's module docstring). Both callers therefore share
    one definition of what a transition IS, instead of each keeping its own
    half of the menu.

    cut/match_cut are rendered as a plain concat (no overlap needed), so this
    returns None for those two; the caller builds the audio side of a non-cut
    transition separately via acrossfade=d=<duration>. in_a/in_b/out_label are
    plain (unbracketed) filter-graph label names - this function wraps them in
    brackets itself.
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
        # Both effects are gated to the transition window. Without `enable` they sit
        # downstream of xfade in the chain and therefore process every frame that passes
        # through it - the whole rest of the clip, not the seam. One boundary then left
        # the entire short with shifted colour channels and grain, which reads as a
        # broken render rather than as an edit.
        window = f"between(t\\,{offset}\\,{offset + duration})"
        return (
            f"[{in_a}][{in_b}]xfade=transition=pixelize:duration={duration}:offset={offset},"
            f"rgbashift=rh=8:bh=-8:edge=smear:enable='{window}',"
            f"noise=alls=25:allf=t+u:enable='{window}'[{out_label}]"
        )

    xfade_name = _XFADE_TRANSITION_NAMES[transition_type]
    return f"[{in_a}][{in_b}]xfade=transition={xfade_name}:duration={duration}:offset={offset}[{out_label}]"


def encode_flags(video_codec: str, preset: str | None = None, crf: int | None = None) -> list[str]:
    """Video-encode ffmpeg flags: always `-c:v <codec>`, plus optional
    `-preset`/`-crf` speed-vs-size knobs. Both default to None so the emitted
    command is byte-identical to before this knob existed (ffmpeg's own
    encoder defaults apply). Opt-in only: e.g. preset='veryfast' trades size
    for a much faster libx264 encode. Note preset/crf are meaningful for the
    x264/x265 software encoders; leave them unset for hardware encoders like
    h264_nvenc (which use their own -cq/-preset vocabulary)."""
    flags = ["-c:v", video_codec]
    if preset:
        flags += ["-preset", preset]
    if crf is not None:
        flags += ["-crf", str(crf)]
    return flags


def hwaccel_flags(hwaccel: str) -> list[str]:
    """`-hwaccel <value>` for the SOURCE input's decode, e.g. "cuda" on an
    NVIDIA ffmpeg build - must precede the `-i` it applies to. "none" (the
    default everywhere this is threaded through) omits the flag entirely,
    byte-identical to before this knob existed. The filter chain downstream
    stays CPU-side regardless (crop/subtitles/effects never run on GPU
    frames), so this only ever speeds up decode, never changes output
    pixels - safe to enable independent of video_codec."""
    if not hwaccel or hwaccel == "none":
        return []
    return ["-hwaccel", hwaccel]


# Banner fonts: this Windows ffmpeg build ships fontconfig without a config
# file, so drawtext's font=<name> lookup fails outright ("Fontconfig error:
# Cannot load default config file") - an explicit fontfile= path is mandatory
# (08-RESEARCH Pitfall 1, live-verified). ariblk.ttf/arialbd.ttf ship with
# Windows and carry full Cyrillic coverage (visually verified); non-Windows
# users set config.hook_banner.font to an explicit .ttf/.otf path instead of
# a name, same spirit as config.subtitles.font's platform note.
HOOK_BANNER_FONT_PATHS = {
    "Arial Black": "C:/Windows/Fonts/ariblk.ttf",
    "Arial Bold": "C:/Windows/Fonts/arialbd.ttf",
}


def resolve_banner_font(font: str) -> str:
    """Resolves a friendly banner font name to an explicit font-file path.

    Values that already look like a path (.ttf/.otf suffix or a path
    separator) pass through verbatim (forward-slash normalized) - the
    non-Windows escape hatch. Never falls back to drawtext's font=<name>
    form, which fails on this build (see HOOK_BANNER_FONT_PATHS comment).
    """
    if "/" in font or "\\" in font or font.lower().endswith((".ttf", ".otf")):
        return font.replace("\\", "/")
    try:
        return HOOK_BANNER_FONT_PATHS[font]
    except KeyError as error:
        raise RenderError(
            f"unknown banner font {font!r}; use one of {sorted(HOOK_BANNER_FONT_PATHS)} "
            "or an explicit .ttf/.otf file path"
        ) from error


def _escape_drawtext_text(text: str) -> str:
    """drawtext's text= argument treats backslash, quote, colon and comma as
    filtergraph syntax. Backslash must be escaped first (mirrors
    _escape_ass_text) so later rules never re-escape its output. % is
    deliberately left alone - every banner clause sets expansion=none, which
    disables drawtext's strftime-style %-expansion entirely.
    """
    return (
        text.replace("\\", "\\\\").replace("'", "\\'")
        .replace(":", "\\:").replace(",", "\\,")
    )


def _wrap_banner_lines(text: str, max_chars: int, max_lines: int) -> list[str]:
    """Greedy word-wrap for the banner title (drawtext has no auto-wrap).
    A single word longer than max_chars stays alone on its own line; text
    needing more than max_lines is truncated with an ellipsis + [warn]
    (fail-open, never raises - 08-RESEARCH Pitfall 4).
    """
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if len(candidate) <= max_chars or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    if len(lines) > max_lines:
        print(
            f"[warn] banner text truncated to {max_lines} line(s): {text!r}",
            file=sys.stderr,
        )
        lines = lines[:max_lines]
        lines[-1] = f"{lines[-1]}…"
    return lines


def _drawtext_color(value: str) -> str:
    """drawtext accepts named colors and 0xRRGGBB; config uses #RRGGBB."""
    return f"0x{value[1:]}" if value.startswith("#") else value
