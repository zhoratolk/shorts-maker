"""Thumbnail generation: pick a strong frame from a finished clip, burn a
short channel-style caption over it, and write a poster image next to the
clip - optionally uploaded via the publish queue (thumbnails.set).

One ffmpeg pass does the whole job: fast-seek a single frame, scale/crop it
to the target poster size, and chain one drawtext clause per wrapped caption
line (reusing render.py's banner text machinery so fonts/escaping/wrapping
stay identical). Pure command/timestamp/wrap logic is unit-tested; only
generate_thumbnail shells out.

Note for this channel (Shorts): the poster defaults to the clip's own 9:16
size because YouTube shows a Short's custom thumbnail on the channel grid and
when shared. Regular 16:9 videos set width/height in config.
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from scripts.render import (
    TARGET_HEIGHT,
    TARGET_WIDTH,
    _drawtext_color,
    _escape_drawtext_text,
    _wrap_banner_lines,
    resolve_banner_font,
)

# Keep the picked frame away from the very start/end of the clip: the opening
# can be a fade-in or the hook banner still animating, and the tail is often
# the outro card / fade-out - neither makes a good poster.
DEFAULT_SAFE_LO_FRAC = 0.15
DEFAULT_SAFE_HI_FRAC = 0.85


class ThumbnailError(ValueError):
    pass


def _spike_time(spike) -> float:
    """A spike may be a bare seconds float or a dict with an 'at' key."""
    return float(spike["at"]) if isinstance(spike, dict) else float(spike)


def _spike_weight(spike) -> float:
    """Ranking weight for choosing among spikes - louder/stronger wins. Bare
    floats all weigh equally (0.0), so the tie-break (nearest clip centre)
    decides."""
    if isinstance(spike, dict):
        for key in ("score", "loudness", "weight"):
            if key in spike:
                return float(spike[key])
    return 0.0


def pick_thumbnail_timestamp(
    clip_duration: float,
    energy_spikes: list | None = None,
    *,
    safe_lo_frac: float = DEFAULT_SAFE_LO_FRAC,
    safe_hi_frac: float = DEFAULT_SAFE_HI_FRAC,
) -> float:
    """Choose a timestamp (seconds into the clip) for the poster frame.

    If energy_spikes (times relative to the clip, optionally weighted) are
    given, pick the strongest one inside the safe [lo, hi] band; if none fall
    in the band, the strongest overall clamped into the band; ties break
    toward the clip centre. With no spikes, the clip midpoint. Always returns
    a time strictly inside the clip.
    """
    if clip_duration <= 0:
        raise ThumbnailError(f"clip_duration must be > 0, got {clip_duration}")

    lo = clip_duration * safe_lo_frac
    hi = clip_duration * safe_hi_frac
    centre = clip_duration / 2.0

    if not energy_spikes:
        return centre

    def clamp(value: float) -> float:
        return min(max(value, lo), hi)

    in_band = [spike for spike in energy_spikes if lo <= _spike_time(spike) <= hi]
    pool = in_band or energy_spikes
    # Strongest weight first; tie-break toward the clip centre.
    best = max(pool, key=lambda spike: (_spike_weight(spike), -abs(_spike_time(spike) - centre)))
    return clamp(_spike_time(best))


def build_thumbnail_command(
    clip_path: str,
    timestamp: float,
    text: str,
    output_path: str,
    *,
    width: int = TARGET_WIDTH,
    height: int = TARGET_HEIGHT,
    font: str = "Arial Black",
    font_size: int = 96,
    text_color: str = "white",
    box_color: str = "black",
    box_opacity: float = 0.55,
    position: str = "bottom",
    max_lines: int = 3,
    line_gap: int = 24,
) -> list[str]:
    """Builds the single-pass ffmpeg argv that grabs the frame at `timestamp`,
    covers it to width x height, and chains one boxed drawtext clause per
    wrapped caption line. Empty caption is allowed - the poster is then just
    the clean frame (no text clauses).

    Fast-seek (-ss before -i) is intentional: exact frame accuracy doesn't
    matter for a poster and it avoids decoding up to the timestamp.
    """
    if timestamp < 0:
        raise ThumbnailError(f"timestamp must be >= 0, got {timestamp}")
    if width <= 0 or height <= 0:
        raise ThumbnailError(f"width/height must be > 0, got {width}x{height}")
    if font_size <= 0:
        raise ThumbnailError(f"font_size must be > 0, got {font_size}")
    if position not in ("top", "center", "bottom"):
        raise ThumbnailError(f"position must be 'top', 'center' or 'bottom', got {position!r}")
    if not 0.0 <= box_opacity <= 1.0:
        raise ThumbnailError(f"box_opacity must be within [0, 1], got {box_opacity}")

    # Cover-fit: upscale to fill, then centre-crop to the exact poster size.
    filters = [f"scale={width}:{height}:force_original_aspect_ratio=increase", f"crop={width}:{height}"]

    caption = (text or "").strip()
    if caption:
        font_path = resolve_banner_font(font).replace(":", "\\:")
        boxcolor = f"{_drawtext_color(box_color)}@{box_opacity}"
        # Mirror render.py's measured budget: ~22 chars/line at fontsize 58.
        max_chars = max(8, round(22 * 58 / font_size))
        lines = _wrap_banner_lines(caption, max_chars, max_lines)

        line_height = font_size + line_gap
        block_height = len(lines) * line_height
        clearance = round(height * 0.14)  # keep clear of the Shorts UI overlay
        if position == "top":
            y0 = clearance
        elif position == "center":
            y0 = (height - block_height) // 2
        else:  # bottom
            y0 = height - clearance - block_height

        for index, line in enumerate(lines):
            filters.append(
                f"drawtext=fontfile='{font_path}':text='{_escape_drawtext_text(line)}':"
                f"fontsize={font_size}:fontcolor={_drawtext_color(text_color)}:expansion=none:"
                f"x=(w-text_w)/2:y={y0 + index * line_height}:box=1:boxcolor={boxcolor}:boxborderw=28"
            )

    return [
        "ffmpeg", "-y",
        "-ss", f"{timestamp:.3f}",
        "-i", clip_path,
        "-frames:v", "1",
        "-vf", ",".join(filters),
        output_path,
    ]


def generate_thumbnail(
    clip_path: str,
    text: str,
    output_path: str,
    *,
    timestamp: float,
    runner=subprocess.run,
    **kwargs,
) -> str:
    """Runs the thumbnail command and returns output_path. Raises
    ThumbnailError on a non-zero ffmpeg exit (callers wanting fail-open
    behaviour - e.g. the render pipeline - catch it and continue without a
    poster)."""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    command = build_thumbnail_command(clip_path, timestamp, text, output_path, **kwargs)
    result = runner(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise ThumbnailError(f"ffmpeg failed to write thumbnail: {result.stderr.strip()[:500]}")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a captioned poster thumbnail from a finished clip (single ffmpeg pass)."
    )
    parser.add_argument("clip_path", help="Path to the rendered clip")
    parser.add_argument("output_path", help="Path to write the thumbnail image (.png/.jpg)")
    parser.add_argument("--text", default="", help="Caption text (short/punchy); omit for a clean frame")
    parser.add_argument("--timestamp", type=float, default=None, help="Seconds into the clip (default: midpoint)")
    parser.add_argument("--duration", type=float, default=None, help="Clip duration, used to pick the midpoint")
    parser.add_argument("--width", type=int, default=TARGET_WIDTH)
    parser.add_argument("--height", type=int, default=TARGET_HEIGHT)
    parser.add_argument("--font", default="Arial Black")
    parser.add_argument("--font-size", type=int, default=96)
    parser.add_argument("--position", default="bottom", choices=["top", "center", "bottom"])
    args = parser.parse_args()

    timestamp = args.timestamp
    if timestamp is None:
        if args.duration is None:
            parser.error("provide --timestamp or --duration")
        timestamp = pick_thumbnail_timestamp(args.duration)

    output = generate_thumbnail(
        args.clip_path,
        args.text,
        args.output_path,
        timestamp=timestamp,
        width=args.width,
        height=args.height,
        font=args.font,
        font_size=args.font_size,
        position=args.position,
    )
    print(output)


if __name__ == "__main__":
    main()
