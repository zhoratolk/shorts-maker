"""Two ways to make a clip survive the platform's auto-repeat.

`build_punch_rotate_command` (2026-08-23) is the structural one: it ROTATES
the clip around its punch, so the punch half moves to the front and is cut
from the tail. Output is [punch][setup] instead of [setup][punch]. The wrap
seam is then exact by construction - the setup's last frame is the punch's
first frame in the source timeline - so a platform repeat reads as one
continuous "setup -> punch" cycle instead of replaying the payoff twice.
This is what a loop clip is actually for, and it needs no cold open: the
punch already opens the clip, without being duplicated at the end.

`build_loop_outro_command` (below) is the cosmetic one: it leaves clip order
alone and crossfades a replay of the opening onto the tail, so the repeat
blends instead of hard-cutting. Measured over the first 7 published loop
clips it moved tail retention from 14.7% to a median 16.2% - inside the
noise - because the hook still sat at the end where a scrolling viewer never
reached it. Kept for clips whose ending genuinely matches their opening.

Loop seam: crossfade a replay of the clip's own opening onto its own tail,
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


ROTATE_MIN_PUNCH_SECONDS = 1.5
ROTATE_MIN_SETUP_SECONDS = 4.0


def punch_rotate_at(
    words: list[dict],
    punch_at: float,
    clip_duration: float,
    *,
    min_punch_seconds: float = ROTATE_MIN_PUNCH_SECONDS,
    min_setup_seconds: float = ROTATE_MIN_SETUP_SECONDS,
) -> float | None:
    """Where to cut a clip in two so the punch half can lead. Returns the
    rotate point in clip-relative seconds, or None when the clip can't hold
    the shape.

    Snaps to a whole word start for the same reason cold_open_window does:
    punch_at comes from a transcript SEGMENT start, which routinely lands a
    few hundredths INSIDE the first word, and rotating there clips the
    payoff's first consonant - audible on a hard cut, which is what the
    rotate junction is by default.

    Both halves are floored. A punch half under min_punch_seconds gives a
    hook too short to register before the setup starts; a setup half under
    min_setup_seconds means almost the whole clip moved and the "loop"
    degenerates into the original order with a jump cut in it.
    """
    if clip_duration <= 0 or punch_at <= 0 or punch_at >= clip_duration:
        return None

    starts = [word["start"] for word in words if word["start"] >= punch_at - 0.05]
    rotate_at = round(starts[0] if starts else punch_at, 3)

    if rotate_at < min_setup_seconds:
        return None
    if clip_duration - rotate_at < min_punch_seconds:
        return None
    return rotate_at


def build_punch_rotate_command(
    base_clip: str,
    output_path: str,
    rotate_at: float,
    base_duration: float,
    *,
    transition: str = "cut",
    transition_duration: float = 0.0,
    video_codec: str = "libx264",
    preset: str | None = None,
    crf: int | None = None,
) -> list[str]:
    """Builds the command that rotates `base_clip` around `rotate_at`:
    [rotate_at, end) plays first, [0, rotate_at) follows. Both video and
    audio are split from the SAME single input, so the two streams can never
    drift out of sync - same pattern as build_cold_open_command.

    `transition` applies to the INTERNAL junction only (punch -> setup, which
    is the one narrative jump the shape introduces). The wrap seam needs no
    transition: those two frames were already adjacent in the source.

    Defaults to "cut" because the internal junction is meant to read as a
    snap away from the payoff - the same reason cold_open reaches for
    whip_pan rather than a dissolve. transition_duration is clamped to the
    punch half's own length, matching the TRANS-03 downgrade-to-concat
    convention used elsewhere in this codebase.
    """
    if transition not in VALID_LOOP_TRANSITIONS:
        raise RenderError(
            f"loop transition must be one of {sorted(VALID_LOOP_TRANSITIONS)}, got {transition!r}"
        )
    if base_duration <= 0:
        raise RenderError(f"base_duration must be > 0, got {base_duration}")
    if not 0 < rotate_at < base_duration:
        raise RenderError(
            f"rotate_at must sit strictly inside the clip (0, {base_duration}), got {rotate_at}"
        )

    rotate_at = round(rotate_at, 3)
    punch_length = round(base_duration - rotate_at, 3)
    trans_duration = round(min(max(transition_duration, 0.0), punch_length), 3)
    use_xfade = transition != "cut" and trans_duration > 0

    graph = [
        "[0:v]split=2[setupbasev][punchbasev]",
        f"[setupbasev]trim=start=0:end={rotate_at},setpts=PTS-STARTPTS[setupv]",
        f"[punchbasev]trim=start={rotate_at},setpts=PTS-STARTPTS[punchv]",
        "[0:a]asplit=2[setupbasea][punchbasea]",
        f"[setupbasea]atrim=start=0:end={rotate_at},asetpts=PTS-STARTPTS[setupa]",
        f"[punchbasea]atrim=start={rotate_at},asetpts=PTS-STARTPTS[puncha]",
    ]

    if use_xfade:
        # offset is on the combined [punch][setup] timeline: the overlap eats
        # into the tail of the punch half, never before it.
        offset = round(punch_length - trans_duration, 3)
        xfade_name = _XFADE_NAMES[transition]
        graph.append(
            f"[punchv][setupv]xfade=transition={xfade_name}:duration={trans_duration}:offset={offset}[vout]"
        )
        graph.append(f"[puncha][setupa]acrossfade=d={trans_duration}[aout]")
    else:
        graph.append("[punchv][puncha][setupv][setupa]concat=n=2:v=1:a=1[vout][aout]")

    return [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", base_clip,
        "-filter_complex", ";".join(graph),
        "-map", "[vout]", "-map", "[aout]",
        *encode_flags(video_codec, preset, crf), "-c:a", "aac",
        "-movflags", "+faststart",
        output_path,
    ]


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
