"""Loop seam: crossfade a replay of the clip's own opening onto its own tail,
so a platform's auto-repeat (Shorts/Reels/TikTok all loop by default) blends
into a seamless wrap instead of hard-cutting from the real ending back to the
real start. Only worth it on clips whose end and start can plausibly blend -
Claude decides per clip in SKILL.md step 5 (PLAN.json's `loop: true`), same
opt-in footing as cold_open.

Kept in its own module (imported by render.py's render_clip), same footing as
cold_open.py: a SECOND ffmpeg pass over an already fully-rendered clip
(subtitles/banner/punch-zoom/emphasis are already baked in, so the replay is
a byte-for-byte copy of the clip's own opening frames, not a separately-
composed render). Runs after cold-open and before the overlay finalize pass,
same ordering rationale as cold_open's own module docstring. Fail-open: any
error keeps the base clip.

Intentionally self-contained (no import from render.py) to avoid a circular
import (render.py imports this module) - same rationale as cold_open.py.
"""

from __future__ import annotations

from scripts.render_common import RenderError, encode_flags

# Deliberately narrower than cold_open's transition menu: whip_pan/mask_wipe
# read as punchy "snap into the moment" reveals, wrong feel for a smooth
# loop seam. A loop only needs a plain dissolve or a hard "cut" (an exact
# appended replay, no blend) - it's about the seam being unsurprising, not
# eye-catching.
_XFADE_NAMES = {"crossfade": "fade"}
VALID_LOOP_TRANSITIONS = frozenset({"cut", *_XFADE_NAMES})


def build_loop_outro_command(
    base_clip: str,
    output_path: str,
    base_duration: float,
    *,
    transition: str = "crossfade",
    transition_duration: float = 0.4,
    video_codec: str = "libx264",
    preset: str | None = None,
    crf: int | None = None,
) -> list[str]:
    """Builds the command that crossfades a [0, transition_duration) replay
    of `base_clip`'s own opening onto its tail. Both video and audio are
    split from the SAME single input (a loop-replay branch trimmed off the
    top, plus the untouched full clip), so the two streams can never drift
    out of sync with each other - same pattern as build_cold_open_command.

    transition_duration is clamped to at most base_duration (a replay can't
    be longer than the clip itself) rather than raising - a silent clamp
    matching the TRANS-03 downgrade-to-concat convention used elsewhere in
    this codebase, so a misconfigured value degrades the look instead of
    failing the whole clip.

    With the crossfade transition, the replay window IS the overlap, so it
    eats into the tail's own runtime instead of extending it - net output
    duration barely changes. The "cut" variant does add transition_duration
    of runtime (a literal appended copy, no blend).
    """
    if transition not in VALID_LOOP_TRANSITIONS:
        raise RenderError(
            f"loop transition must be one of {sorted(VALID_LOOP_TRANSITIONS)}, got {transition!r}"
        )
    if base_duration <= 0:
        raise RenderError(f"base_duration must be > 0, got {base_duration}")
    if transition_duration <= 0:
        raise RenderError(f"loop transition_duration must be > 0, got {transition_duration}")

    d = round(min(transition_duration, base_duration), 3)
    use_xfade = transition != "cut"

    graph = [
        "[0:v]split=2[mainv][loopbasev]",
        f"[loopbasev]trim=start=0:end={d},setpts=PTS-STARTPTS[loopv]",
        "[0:a]asplit=2[maina][loopbasea]",
        f"[loopbasea]atrim=start=0:end={d},asetpts=PTS-STARTPTS[loopa]",
    ]

    if use_xfade:
        # offset is on the main clip's own timeline (the first xfade input) -
        # the transition begins base_duration - d in, so the overlap eats
        # into the tail, never before it.
        offset = round(base_duration - d, 3)
        xfade_name = _XFADE_NAMES[transition]
        graph.append(f"[mainv][loopv]xfade=transition={xfade_name}:duration={d}:offset={offset}[vout]")
        graph.append(f"[maina][loopa]acrossfade=d={d}[aout]")
    else:
        graph.append("[mainv][maina][loopv][loopa]concat=n=2:v=1:a=1[vout][aout]")

    return [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", base_clip,
        "-filter_complex", ";".join(graph),
        "-map", "[vout]", "-map", "[aout]",
        *encode_flags(video_codec, preset, crf), "-c:a", "aac",
        "-movflags", "+faststart",
        output_path,
    ]
