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
