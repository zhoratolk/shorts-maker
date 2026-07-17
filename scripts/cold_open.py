"""Cold-open teaser: prepend a short slice of the clip's own punch/climax
moment to the very front, so the first couple seconds answer "what just
happened" before the clip plays from its real start - the viewer has to keep
watching to find out.

Kept in its own module (imported by render.py's render_clip), same footing as
overlay_pass.py: a SECOND ffmpeg pass over an already fully-rendered clip
(subtitles/banner/punch-zoom/emphasis are already baked in, so the teaser is
a byte-for-byte replay of that moment, not a separately-composed render).
Runs BEFORE the overlay finalize pass so social popups / the outro card time
themselves against the new, longer duration. Fail-open: any error keeps the
base clip - matches the diarization/audio_energy/overlay-pass footing.

Intentionally self-contained (no import from render.py) to avoid a circular
import (render.py imports this module); the small xfade-name table below is
a narrower, cold-open-specific subset and does NOT need to mirror
scripts.transitions.TRANSITION_TYPES the way render.py's boundary
transitions do.
"""

from __future__ import annotations

from scripts.render_common import RenderError, encode_flags

# glitch/match_cut are intentionally excluded from this feature's scope - a
# whip-pan/crossfade/mask-wipe "snap into the moment" reads as a punchy
# teaser transition; "cut" (plain concat, no overlap) is offered as a hard
# no-frills option.
_XFADE_NAMES = {"crossfade": "fade", "whip_pan": "hblur", "mask_wipe": "wipeleft"}
VALID_COLD_OPEN_TRANSITIONS = frozenset({"cut", *_XFADE_NAMES})


def build_cold_open_command(
    base_clip: str,
    output_path: str,
    at: float,
    duration: float,
    *,
    transition: str = "whip_pan",
    transition_duration: float = 0.25,
    video_codec: str = "libx264",
    preset: str | None = None,
    crf: int | None = None,
) -> list[str]:
    """Builds the command that prepends a [at, at+duration) slice of
    `base_clip` to its own front, joined by `transition`. Both video and
    audio are split from the SAME single input (a teaser branch trimmed off
    the top, plus the untouched full clip), so the two streams can never
    drift out of sync with each other.

    transition_duration is clamped to at most `duration` (a transition can't
    overlap more than the teaser itself is long) rather than raising - a
    silent clamp here matches the TRANS-03 downgrade-to-concat convention
    used for boundary transitions elsewhere in this codebase, so a
    misconfigured value degrades the look instead of failing the whole clip.
    """
    if transition not in VALID_COLD_OPEN_TRANSITIONS:
        raise RenderError(
            f"cold-open transition must be one of {sorted(VALID_COLD_OPEN_TRANSITIONS)}, got {transition!r}"
        )
    if at < 0:
        raise RenderError(f"cold-open at must be >= 0, got {at}")
    if duration <= 0:
        raise RenderError(f"cold-open duration must be > 0, got {duration}")

    at = round(at, 3)
    duration = round(duration, 3)
    trans_duration = round(min(max(transition_duration, 0.0), duration), 3)
    use_xfade = transition != "cut" and trans_duration > 0

    graph = [
        "[0:v]split=2[mainv][teaserbasev]",
        f"[teaserbasev]trim=start={at}:end={round(at + duration, 3)},setpts=PTS-STARTPTS[teaserv]",
        "[0:a]asplit=2[maina][teaserbasea]",
        f"[teaserbasea]atrim=start={at}:end={round(at + duration, 3)},asetpts=PTS-STARTPTS[teasera]",
    ]

    if use_xfade:
        # offset is on the combined [teaserv][mainv] timeline: where the
        # transition begins is the teaser's own duration minus the overlap,
        # so the overlap eats into the tail of the teaser, never before it.
        offset = round(duration - trans_duration, 3)
        xfade_name = _XFADE_NAMES[transition]
        graph.append(
            f"[teaserv][mainv]xfade=transition={xfade_name}:duration={trans_duration}:offset={offset}[vout]"
        )
        graph.append(f"[teasera][maina]acrossfade=d={trans_duration}[aout]")
    else:
        graph.append("[teaserv][teasera][mainv][maina]concat=n=2:v=1:a=1[vout][aout]")

    return [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", base_clip,
        "-filter_complex", ";".join(graph),
        "-map", "[vout]", "-map", "[aout]",
        *encode_flags(video_codec, preset, crf), "-c:a", "aac",
        "-movflags", "+faststart",
        output_path,
    ]
