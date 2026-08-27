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

from scripts.render_common import (
    VALID_TRANSITIONS,
    RenderError,
    build_transition_filter,
    encode_flags,
)

# The full menu, same as every other join in this pipeline.
#
# This used to be narrowed to {cut, crossfade}, on the argument that "a loop
# seam should be unsurprising, not eye-catching". That argument is sound - but
# it is about the WRAP seam, and this constant does not gate the wrap. Rotate
# mode has two joins and they are opposites:
#
#   * the wrap (last frame -> first frame on replay) is exact by construction,
#     because those frames were adjacent in the source. Nothing to hide, and
#     no transition is ever applied there.
#   * the INTERNAL junction (punch end -> setup start) glues the clip's own
#     end onto its own beginning. Those are usually different scenes entirely,
#     and a hard cut there is the one visible flaw of the whole shape.
#
# So the junction wants exactly what cold_open wants - a punchy "snap into the
# moment" - and narrowing it to a dissolve was solving the wrong seam's
# problem (found 2026-08-23, after a loop was rejected outright for a mismatch
# that a transition is meant to cover).
VALID_LOOP_TRANSITIONS = VALID_TRANSITIONS

# `seam` mode is the older, purely cosmetic shape: it appends a replay of the
# clip's opening and dissolves into it, leaving the running order untouched.
# THAT is the seam the narrow menu was written for, and there the original
# argument holds exactly - a replay should slip past unnoticed, so it gets a
# plain dissolve or an unblended append and nothing louder.
_SEAM_XFADE_NAMES = {"crossfade": "fade"}
VALID_SEAM_TRANSITIONS = frozenset({"cut", *_SEAM_XFADE_NAMES})


ROTATE_MIN_PUNCH_SECONDS = 1.5
ROTATE_MIN_SETUP_SECONDS = 4.0


LAST_PHRASE_GAP_SECONDS = 0.6


def phrase_starts(
    words: list[dict],
    *,
    gap_seconds: float = LAST_PHRASE_GAP_SECONDS,
    splice_points: list[float] | None = None,
) -> list[float]:
    """Every phrase boundary in the clip, ascending - the first word of each.

    Two things separate one phrase from the next:

      * a gap of at least `gap_seconds` between words. Group voice chat runs
        sentences together with sub-0.6s gaps, so anything tighter splits
        mid-sentence (same threshold cold_open_window uses).
      * a JUMP CUT. `splice_points` are the cut boundaries on this clip's own
        timeline, and a cut is the strongest phrase boundary there is: the
        pause was long enough that it got deleted outright. Without this the
        removal of a pause also removes the evidence that it was ever there,
        and a heavily cut clip reads as one continuous phrase from its first
        word - which is exactly what happened to two of three loop clips on
        2026-08-23, both of which then rendered unrotated.
    """
    usable = [w for w in words if w.get("start") is not None and w.get("end") is not None]
    if not usable:
        return []

    usable.sort(key=lambda w: w["start"])
    cuts = sorted(splice_points or [])
    starts = [round(usable[0]["start"], 3)]
    for previous, word in zip(usable, usable[1:]):
        gap = word["start"] - previous["end"]
        # A splice sits at a single instant; a word may start a hair before
        # or after it once timestamps are rounded, so allow a small tolerance.
        spliced = any(previous["end"] - 0.05 <= cut <= word["start"] + 0.05 for cut in cuts)
        if gap >= gap_seconds or spliced:
            starts.append(round(word["start"], 3))
    return starts


def last_phrase_start(
    words: list[dict],
    *,
    gap_seconds: float = LAST_PHRASE_GAP_SECONDS,
    splice_points: list[float] | None = None,
) -> float | None:
    """Start of the clip's final spoken phrase, or None for no usable words.

    Strategy 3 is defined as "the hook is the clip's final spoken beat", so
    that beat's own start IS the rotate point - no separate hand-set field
    needed.
    """
    starts = phrase_starts(words, gap_seconds=gap_seconds, splice_points=splice_points)
    return starts[-1] if starts else None


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

    Defaults to "cut" so an explicit call keeps its old output byte for byte;
    the *automatic* choice is made a layer up, by measuring the junction (see
    render_batch.autoloop_entries). A junction whose two frames already match
    wants "cut" - blending them would smear a join that is invisible as-is;
    one that jumps scenes wants a real transition. transition_duration is clamped to the
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
    use_xfade = transition not in ("cut", "match_cut") and trans_duration > 0

    graph = [
        "[0:v]split=2[setupbasev][punchbasev]",
        f"[setupbasev]trim=start=0:end={rotate_at},setpts=PTS-STARTPTS[setupv]",
        f"[punchbasev]trim=start={rotate_at},setpts=PTS-STARTPTS[punchv]",
    ]
    inputs = ["-i", base_clip]

    if use_xfade:
        # The audio halves come from two decodes of the same file rather than one
        # asplit, and only on this path. acrossfade drains its FIRST input to EOF
        # before it emits a frame, and an asplit branch cannot then hand the second
        # branch the clip's opening - those frames went past while the punch half was
        # being read to the end. ffmpeg reports that as one line, "No filtered frames
        # for output stream", and still exits 0: the rotated clip comes out with no
        # audio track at all, and the only other sign is the overlay pass that runs
        # next failing on "Stream map '0:a' matches no streams". Two clips shipped
        # silent that way on 2026-08-27; the ones whose junction measured `match_cut`
        # were fine, because that path concats instead.
        #
        # Decoding twice costs a decode and nothing else - it is the same file, so the
        # two halves still cannot drift apart, which is the whole reason the video
        # split exists.
        inputs = ["-i", base_clip, "-i", base_clip]
        graph.append(f"[0:a]atrim=start={rotate_at},asetpts=PTS-STARTPTS[puncha]")
        graph.append(f"[1:a]atrim=start=0:end={rotate_at},asetpts=PTS-STARTPTS[setupa]")
        # offset is on the combined [punch][setup] timeline: the overlap eats
        # into the tail of the punch half, never before it.
        offset = round(punch_length - trans_duration, 3)
        graph.append(
            build_transition_filter(transition, trans_duration, offset, "punchv", "setupv", "vout")
        )
        graph.append(f"[puncha][setupa]acrossfade=d={trans_duration}[aout]")
    else:
        graph.append("[0:a]asplit=2[setupbasea][punchbasea]")
        graph.append(f"[setupbasea]atrim=start=0:end={rotate_at},asetpts=PTS-STARTPTS[setupa]")
        graph.append(f"[punchbasea]atrim=start={rotate_at},asetpts=PTS-STARTPTS[puncha]")
        graph.append("[punchv][puncha][setupv][setupa]concat=n=2:v=1:a=1[vout][aout]")

    return [
        "ffmpeg", "-y", "-loglevel", "error",
        *inputs,
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
    if transition not in VALID_SEAM_TRANSITIONS:
        raise RenderError(
            f"loop transition must be one of {sorted(VALID_SEAM_TRANSITIONS)}, got {transition!r}"
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
        xfade_name = _SEAM_XFADE_NAMES[transition]
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
