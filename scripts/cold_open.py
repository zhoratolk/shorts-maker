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


COLD_OPEN_MIN_SECONDS = 1.2
COLD_OPEN_MAX_SECONDS = 4.0
_PHRASE_GAP_SECONDS = 0.6


def cold_open_window(
    words: list[dict],
    punch_at: float,
    clip_duration: float,
    *,
    min_seconds: float = COLD_OPEN_MIN_SECONDS,
    max_seconds: float = COLD_OPEN_MAX_SECONDS,
) -> dict | None:
    """Teaser window for a punch moment: {"at", "duration"}, or None if unusable.

    The window opens ON the punch and runs to the end of its line, so the
    teaser carries the whole joke instead of a fixed slice of it. A flat 2s
    duration cut the line in half on 10 of 18 clips of the 2026-08-10 batch -
    "меня зовут Джорно Джованна" teased without "и у меня есть мечта", "у меня
    пошло" without "мы сами себя перефигачили".

    Deliberately NOT anchored to the end of the line: group voice chat runs
    sentences together with sub-0.6s gaps, so the detected "phrase" often
    swallows the next thought, and ending on it threw the punch out of the
    teaser entirely ("нас трахают" -> "мы сейчас отбиваемся"). Starting on the
    punch and taking as much of the line as fits keeps the payoff in frame
    whether or not the phrase boundary was found correctly.

    words: the clip's own {"word","start","end"} list, already clip-relative
    and post-jumpcut-remap (same input subtitles.py takes). punch_at is on that
    same timeline. The line ends at the first gap longer than
    _PHRASE_GAP_SECONDS, and the window is capped at max_seconds, floored at
    min_seconds, and always fits inside clip_duration: render.py cuts the
    teaser out of the already-rendered clip, so an overshoot of even 7ms cost
    a clip its whole cold open on 2026-08-10 (clip 0010, [17.107, 19.107] in
    19.1s). Returns None when the clip is too short to hold any teaser.
    """
    if clip_duration <= 0 or punch_at < 0 or punch_at >= clip_duration:
        return None

    phrase: list[dict] = []
    for word in words:
        if word["start"] >= punch_at - 0.05:
            if phrase and word["start"] - phrase[-1]["end"] > _PHRASE_GAP_SECONDS:
                break
            phrase.append(word)

    # Both edges snap to whole words. punch_at comes from a transcript SEGMENT
    # start, which routinely lands a few hundredths INSIDE the first word, and
    # the max_seconds cap below chops wherever it falls - on the 2026-08-12
    # batch that clipped a word off 11 of 16 teasers ("Я как дал" teased as
    # "как дал", "Жаль союзников" as "Жаль").
    start = phrase[0]["start"] if phrase else punch_at
    # Sub-0.6s gaps run separate sentences together, so the phrase scan above
    # keeps going into the next thought and the cap then chops it mid-clause
    # ("а это нахуй натрий, блядь. Когда ты себя в карман"). Stop on the first
    # sentence-ending word that still leaves a usable teaser.
    for index, word in enumerate(phrase):
        if word["word"].strip().endswith((".", "!", "?", "…")) and \
                word["end"] - start >= min_seconds:
            phrase = phrase[:index + 1]
            break
    end = phrase[-1]["end"] if phrase else start + min_seconds
    if end - start > max_seconds:
        fitting = [w for w in phrase if w["end"] - start <= max_seconds]
        end = fitting[-1]["end"] if fitting else start + max_seconds
    if end - start < min_seconds:
        # Floor the teaser by taking whole following words, not a bare +1.2s -
        # but never across a phrase gap, or the teaser swallows the next
        # thought the phrase scan deliberately stopped before.
        cursor = end
        for word in words:
            if word["start"] < cursor:
                continue
            if word["start"] - cursor > _PHRASE_GAP_SECONDS:
                break
            cursor = word["end"]
            if cursor - start >= min_seconds:
                break
        end = cursor if cursor - start >= min_seconds else start + min_seconds
    end = min(end, clip_duration)
    duration = max(end - start, 0.0)
    # Only when the punch sits too close to the clip's end does the window slide
    # backwards, and only far enough to keep min_seconds of teaser. The slide
    # snaps back to a word start too, for the same reason the head does.
    if start + min_seconds > clip_duration:
        earliest = max(0.0, clip_duration - min_seconds)
        heads = [w["start"] for w in words if w["start"] <= earliest]
        start = heads[-1] if heads else earliest
        duration = clip_duration - start
    at = min(start, max(0.0, clip_duration - duration))
    duration = min(duration, clip_duration - at)
    if duration <= 0:
        return None
    return {"at": round(at, 3), "duration": round(duration, 3)}


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
    audio of the teaser come from the SAME file as the clip itself - a second,
    seeked decode of it - so the two streams can never drift out of sync with
    each other.

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

    # The teaser comes from a SECOND decode of the same file, seeked with -ss,
    # rather than from a split of the first. A split cannot serve this shape: the
    # teaser sits at the end of the clip, so that branch has to be read to EOF
    # before it yields anything, and every frame the main branch needs meanwhile
    # has to be held in the split's buffer. On a 1080x1920 clip that is gigabytes,
    # ffmpeg gives up on the main branch, and xfade then emits only the teaser -
    # exit code 0, a clip 1.7 seconds long where the overlay pass pads the picture
    # back out and the audio after the teaser is digital silence. Five published
    # Barotrauma clips shipped exactly that way (2026-09-05 and 09-06 batches);
    # the ones whose teaser sat earlier in the clip survived, which is why it
    # looked random. loop.py hit the same wall on 2026-08-27 and fixed it the same
    # way - see its comment for the audio-only half of the story.
    #
    # Decoding twice costs a decode and nothing else: it is the same file, so the
    # two streams still cannot drift apart, which was the whole point of the split.
    inputs = ["-i", base_clip, "-ss", str(at), "-t", str(duration), "-i", base_clip]
    graph = [
        "[1:v]setpts=PTS-STARTPTS[teaserv]",
        "[1:a]asetpts=PTS-STARTPTS[teasera]",
    ]

    if use_xfade:
        # offset is on the combined [teaserv][mainv] timeline: where the
        # transition begins is the teaser's own duration minus the overlap,
        # so the overlap eats into the tail of the teaser, never before it.
        offset = round(duration - trans_duration, 3)
        xfade_name = _XFADE_NAMES[transition]
        graph.append(
            f"[teaserv][0:v]xfade=transition={xfade_name}:duration={trans_duration}:offset={offset}[vout]"
        )
        graph.append(f"[teasera][0:a]acrossfade=d={trans_duration}[aout]")
    else:
        graph.append("[teaserv][teasera][0:v][0:a]concat=n=2:v=1:a=1[vout][aout]")

    return [
        "ffmpeg", "-y", "-loglevel", "error",
        *inputs,
        "-filter_complex", ";".join(graph),
        "-map", "[vout]", "-map", "[aout]",
        *encode_flags(video_codec, preset, crf), "-c:a", "aac",
        "-movflags", "+faststart",
        output_path,
    ]
