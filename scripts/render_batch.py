"""Config-driven batch render: one command that turns a PLAN.json into finished
clips without anyone hand-assembling render.py's ~60 flags.

Why this exists: every optional render feature (profanity beeps, subtitle
censoring, the social capsule, emphasis zooms, the outro card) is a silent
no-op when its flag is missing - render.py still exits 0 and writes a clip that
merely lacks the feature. Hand-built command lines therefore fail quietly, and
did (2026-08-06: a batch shipped with no beeps and no censored captions). Here
the flags are derived from config.yaml, so a feature can only be off if the
config says it's off.

It also owns the two-pass split that loop clips require: overlay_pass.py
*concatenates* the outro card after the loop seam, so a loop clip and an outro
card are mutually exclusive, and --outro-enabled is global with no per-entry
override. Entries carrying "loop": true are therefore rendered in their own
pass with --loop-enabled and without --outro-enabled/--cold-open-enabled.

Everything except the subprocess dispatch is a pure function, so the flag
derivation is unit-tested rather than eyeballed.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

# Running this file directly puts scripts/ on sys.path, not the repo root, so
# `scripts` is not importable as a package - and SKILL.md documents running it
# exactly that way. Put the repo root first, before the sibling imports below.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.config import Config, load_config
from scripts.crop_focus import plan_focus
from scripts.render_common import SOCIAL_PLATFORMS


class RenderBatchError(RuntimeError):
    pass


def is_loop_entry(entry: dict) -> bool:
    """A plan entry renders as a loop when it carries a truthy "loop" key -
    the same key render.py gates its loop seam on."""
    return bool(entry.get("loop"))


DEAD_ZONE_START_SECONDS = 8.0
DEAD_ZONE_END_SECONDS = 16.0
DEAD_ZONE_MAX_GAP_SECONDS = 2.5


def dead_zone_gap(words: list[dict], clip_length: float | None = None) -> float:
    """Longest wordless stretch overlapping the clip's 8-16s dead zone.

    Measured over 112 published clips (2026-08-23): the retention curve is
    flat for the first four seconds regardless of cold open, and clips that
    went on to get >=800 views separate from clips that got <600 only from 8s
    onward, peaking apart at 12s. Whatever holds a viewer lives in that
    stretch, so a clip that goes quiet across it is spending its decisive
    seconds on nothing.

    Only the silence half of the 8-16s rule is mechanical. Whether the talking
    that fills the zone is an actual second beat or just setup being narrated
    is a judgment call, and stays with SKILL.md step 5 - this catches the
    blatant case, it does not certify the rest.
    """
    usable = sorted(
        (w for w in words if w.get("start") is not None and w.get("end") is not None),
        key=lambda w: w["start"],
    )
    if not usable:
        return 0.0

    # The zone stops where the clip does. Measured to a fixed 16 seconds, a clip of
    # twelve - easy to reach after aggressive jump cuts on a twenty-second moment - was
    # warned about eight seconds of silence in a stretch that does not exist in it. False
    # warnings on every short clip are how an operator learns to scroll past the real ones.
    zone_end = DEAD_ZONE_END_SECONDS if clip_length is None else min(DEAD_ZONE_END_SECONDS, clip_length)
    if zone_end <= DEAD_ZONE_START_SECONDS:
        return 0.0

    edges = [(DEAD_ZONE_START_SECONDS, usable[0]["start"])]
    edges += [(prev["end"], nxt["start"]) for prev, nxt in zip(usable, usable[1:])]
    edges.append((usable[-1]["end"], zone_end))

    longest = 0.0
    for gap_start, gap_end in edges:
        overlap = min(gap_end, zone_end) - max(gap_start, DEAD_ZONE_START_SECONDS)
        longest = max(longest, overlap)
    return round(longest, 3)


def _entry_length(entry: dict) -> float | None:
    """How long the finished clip is, or None when the entry does not say.

    Imported here rather than at module scope: enqueue_batch imports this module back,
    and the shape logic lives there - duplicating it is what produced a reader that
    crashed on every compilation while its own tests passed.
    """
    from scripts.enqueue_batch import clip_duration

    try:
        return clip_duration(entry)
    except (KeyError, TypeError, ValueError):
        return None


def dead_zone_warnings(entries: list[dict], *, max_gap: float = DEAD_ZONE_MAX_GAP_SECONDS) -> list[str]:
    """One warning line per plan entry that goes quiet inside the dead zone.

    Warns rather than blocks: the words file is optional, the threshold is a
    heuristic, and a clip can legitimately carry the zone visually (a long
    silent fail landing). Blocking on a heuristic would cost more good clips
    than it saves bad ones.
    """
    warnings = []
    for entry in entries:
        subtitles_path = entry.get("subtitles_path")
        if not subtitles_path:
            continue
        words_path = Path(subtitles_path).with_name(Path(subtitles_path).stem + "_words.json")
        if not words_path.exists():
            continue
        try:
            words = json.loads(words_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        gap = dead_zone_gap(words, clip_length=_entry_length(entry))
        if gap >= max_gap:
            name = entry.get("output_filename", "<unnamed clip>")
            warnings.append(
                f"[warn] {name}: {gap}s of silence inside the {DEAD_ZONE_START_SECONDS:.0f}-"
                f"{DEAD_ZONE_END_SECONDS:.0f}s dead zone - that stretch is where clips separate "
                f"on views; tighten it or drop the clip"
            )
    return warnings


def entry_segments(entry: dict) -> list[tuple[float, float]] | None:
    """The clip's absolute source windows, or None for a shape that has no
    single source window to sample (a compilation entry).

    Deliberately not entry_source_window above: that one answers "roughly
    where in the recording is this moment" for the poster frame, so it spans
    across cut pauses. Sampling has to walk the kept segments themselves, or
    it measures footage the clip does not contain.
    """
    keep_segments = entry.get("keep_segments")
    if keep_segments:
        return [(float(a), float(b)) for a, b in keep_segments]
    start, end = entry.get("start"), entry.get("end")
    if start is None or end is None:
        return None
    return [(float(start), float(end))]


def autoloop_entries(video_path: str, entries: list[dict]) -> tuple[bool, list[str]]:
    """Picks each rotate-loop entry's junction transition by measuring it.

    A rotate loop has two joins with opposite needs. The wrap (last frame ->
    first frame on replay) is exact by construction and never gets a
    transition. The INTERNAL junction glues the clip's end onto its own
    beginning - usually two unrelated scenes - and a hard cut there is the
    one visible flaw of the shape.

    Which it is cannot be known without looking, so this looks: the frames
    either side of the junction go through the same similarity/motion
    analysis the jump-cut boundaries already use. Matching frames keep "cut"
    (blending them would smear a join that is invisible as-is); a scene jump
    gets a real transition. An entry that names `loop_transition` itself is
    left alone. Fail-open: anything unmeasurable stays "cut".
    """
    from scripts.transitions import (
        _BOUNDARY_FRAME_OFFSET, analyze_motion_at_boundary,
        analyze_similarity_at_boundary,
    )

    pending = [
        entry for entry in entries
        if is_loop_entry(entry) and not entry.get("loop_transition")
    ]
    if not pending:
        return False, []

    import tempfile

    warnings: list[str] = []
    filled = False
    for entry in pending:
        # The junction is the clip's own end meeting its own start, so the
        # frames to compare are at the clip's boundaries in SOURCE seconds.
        segments = entry_segments(entry)
        if not segments:
            continue
        clip_start, clip_end = segments[0][0], segments[-1][1]
        try:
            with tempfile.TemporaryDirectory() as tmp:
                before = str(Path(tmp) / "before.png")
                after = str(Path(tmp) / "after.png")
                for path, at in ((before, clip_end - _BOUNDARY_FRAME_OFFSET),
                                 (after, clip_start + _BOUNDARY_FRAME_OFFSET)):
                    subprocess.run(
                        ["ffmpeg", "-v", "error", "-ss", f"{at:.3f}", "-i", video_path,
                         "-frames:v", "1", "-y", path],
                        check=True, capture_output=True,
                    )
                similarity = analyze_similarity_at_boundary(before, after)
                motion = analyze_motion_at_boundary(before, after)
        except Exception as error:  # noqa: BLE001 - fail-open, "cut" is still valid
            warnings.append(f"[warn] {entry.get('output_filename')}: loop junction not measured ({error})")
            continue

        entry["loop_transition"] = classify_loop_junction(similarity, motion)
        filled = True
    return filled, warnings


# Junction thresholds, measured on real material rather than assumed
# (2026-08-23, four junctions across three November recordings):
#
#   two frames 0.05s apart, same shot   similarity 0.997   motion 5.60
#   two static stats screens            similarity 1.000   motion 0.16
#   two unrelated scenes                similarity 0.414   motion 5.75
#   two unrelated scenes                similarity 0.318   motion 5.53
#
# Motion is worthless here and the first attempt at this used it anyway:
# Farneback optical flow between two UNRELATED frames returns noise of the
# same magnitude as flow between two adjacent frames of one shot (5.75 vs
# 5.60), so it cannot tell a scene jump from no jump at all. It only
# separates "frozen picture" from "anything else". Histogram similarity is
# what actually answers the question being asked.
LOOP_JUNCTION_MATCH_SIMILARITY = 0.90   # same shot - blending would smear it
LOOP_JUNCTION_RELATED_SIMILARITY = 0.60  # related enough for a soft dissolve
LOOP_JUNCTION_STILL_MOTION = 1.0         # below this the picture is frozen


def classify_loop_junction(similarity: float | None, motion: float | None) -> str:
    """The transition for one rotate-loop junction, from visual continuity.

    Deliberately not scripts.transitions.classify_transition: that tree
    weighs motion and audio because it grades cuts BETWEEN takes, where a
    loud moment justifies a loud transition. This junction is a splice
    inside one clip and asks one narrower question - do these two frames
    belong to the same picture? - which similarity answers on its own.
    """
    if similarity is None:
        return "cut"
    if similarity >= LOOP_JUNCTION_MATCH_SIMILARITY:
        return "match_cut"
    if similarity >= LOOP_JUNCTION_RELATED_SIMILARITY:
        return "crossfade"
    # A hard scene jump. whip_pan sells it as a snap when the picture is
    # alive; on a frozen one (menu -> scoreboard) a motion blur reads as a
    # rendering fault, so a wipe carries the change deliberately instead.
    if motion is not None and motion < LOOP_JUNCTION_STILL_MOTION:
        return "mask_wipe"
    return "whip_pan"


def autoframe_entries(
    video_path: str,
    entries: list[dict],
    src_width: int,
    src_height: int,
    *,
    target_width: int,
    target_height: int,
) -> tuple[bool, list[str]]:
    """Fills in the crop framing for every `zoom` entry that didn't spell it
    out, and warns about clips whose picture never moves.

    This exists because omitting `crop_focus_x` is invisible: the clip renders
    fine, dead-centre, and nothing complains - so it gets skipped, and on
    2026-08-23 it was skipped on all twelve clips of a batch, several of which
    were centred on a black margin or on the boundary between the game view
    and a HUD panel. An explicit value in the plan always wins; this only
    answers where the plan said nothing.

    Mutates `entries` in place and returns (changed, warnings).
    """
    changed = False
    warnings: list[str] = []
    crop_width = min(round(src_height * target_width / target_height), src_width)
    for entry in entries:
        if entry.get("crop_style") != "zoom":
            continue
        if entry.get("crop_focus_x") is not None or entry.get("crop_focus_keyframes"):
            continue
        segments = entry_segments(entry)
        if not segments:
            continue
        framing = plan_focus(
            video_path, segments, src_width, src_height, crop_width=crop_width
        )
        if framing is None:
            continue
        name = entry.get("output_filename", "<unnamed clip>")
        if "focus_keyframes" in framing:
            entry["crop_focus_keyframes"] = framing["focus_keyframes"]
        else:
            entry["crop_focus_x"] = framing["focus_x"]
        changed = True
        if framing.get("static"):
            warnings.append(
                f"[warn] {name}: the picture barely moves for the whole clip (a scoreboard, "
                f"a menu, a map screen) - framing cannot fix that, judge whether the moment "
                f"is worth shipping on audio alone"
            )
    return changed, warnings


def unused_feature_warnings(config: Config, entries: list[dict]) -> list[str]:
    """One warning per feature switched on in config but absent from every plan entry.

    These features are gated by two keys that have to agree: the config switch,
    and a per-clip field SKILL.md step 5 is supposed to write. With the switch
    on and the field missing, render.py's per-entry gate renders nothing at
    all - no error, no log line, no visible difference except the effect the
    clip never got. That is how cold_open, punch_zoom_at and loop disappeared
    from four batches in a row (2026-08-27..2026-09-04, 40 clips, none of them
    carrying any of the three): a hand-written plan emitter simply never wrote
    the keys, and nothing downstream had a reason to complain.

    Warns on absence across the WHOLE plan, not per clip. A clip without a cold
    open is a judgment call - step 5 is meant to say no to most clips. Every
    clip of a batch without one means the judgment was never made.
    """
    def missing(field: str) -> bool:
        return not any(entry.get(field) for entry in entries)

    warnings: list[str] = []
    if config.cold_open.enabled and missing("cold_open"):
        warnings.append(
            "[warn] cold_open.enabled is on, but no plan entry carries a cold_open field - "
            "every clip renders without a teaser. Step 5 picks the punch moment per clip."
        )
    if config.emphasis.enabled and missing("emphasis_moves"):
        warnings.append(
            "[warn] emphasis.enabled is on, but no plan entry carries emphasis_moves - "
            "every clip renders without mid-clip punch-ins."
        )
    if config.loop.enabled and missing("loop"):
        warnings.append(
            "[warn] loop.enabled is on, but no plan entry carries a loop field - nothing in "
            "this batch was judged loop-worthy. Expected sometimes, wrong if step 5 skipped it."
        )
    # punch_zoom has no config switch of its own: it is legal only on a zoom
    # crop (render.py rejects it on pad/original-16:9), so the zoom clips are
    # what stands in for one here.
    if any(entry.get("crop_style") == "zoom" for entry in entries) and missing("punch_zoom_at"):
        warnings.append(
            "[warn] the plan has zoom-crop clips but no punch_zoom_at anywhere - no clip "
            "snaps in on its punchline."
        )
    return warnings


def unknown_moment_tag_warnings(entries: list[dict]) -> list[str]:
    """One warning per plan entry whose moment_tag is not in the vocabulary.

    A tag outside the closed list is not a render problem - the clip comes out
    identical - which is exactly why it needs saying here, before the render
    spends the GPU. It is a statistics problem that only shows up months later:
    the clip publishes, retention.py buckets it under a name nothing else uses,
    and the moment kind it belongs to is short one data point forever. That is
    how 234 clips produced 168 tags, 152 of them used once.

    Not a gate. A batch that ships with a wrong tag is better than a batch that
    does not ship, and the fix is a one-word edit in the plan.
    """
    from scripts.moment_tags import MOMENT_TAGS, canonical_tag

    warnings: list[str] = []
    for entry in entries:
        raw = entry.get("moment_tag")
        name = entry.get("output_filename", "<без имени>")
        if not raw:
            warnings.append(
                f"[warn] {name}: no moment_tag - this clip stays out of the retention "
                f"learning loop. Pick one of: {', '.join(MOMENT_TAGS)}"
            )
        elif canonical_tag(raw) is None:
            warnings.append(
                f"[warn] {name}: moment_tag {raw!r} is not in the vocabulary - it will "
                f"bucket alone. Pick one of: {', '.join(MOMENT_TAGS)}"
            )
    return warnings


# The two answers to "could someone who has seen nothing else follow the first
# thing said in this clip?". Deliberately a pair rather than a score: the call is
# made by whoever writes the plan, and a scale would invite splitting hairs over
# a distinction that only matters at the extremes.
OPENINGS = ("standalone", "context")


def opening_warnings(entries: list[dict]) -> list[str]:
    """One warning per plan entry that does not say what kind of opening it has.

    Measured 2026-09-10 on 228 published clips: the share of viewers who keep
    watching past the first seconds (YouTube's engagedViews/views, the "Реакция
    зрителей" bar in Studio) is what decides how far a Short travels - it
    correlates +0.35 with views, and clips that stalled at 100-250 views ran
    17-24% while clips that reached 900+ ran 42-53%, inside the same batch on
    the same day. Publish slot, clip length, opening brightness, opening
    loudness and time-to-first-word explained none of the spread.

    Reading the fourteen best and fourteen worst openings did: the weak ones
    open on a reply or a reference to something the viewer has not seen ("кто
    это врач", "тебя защитил своим кубиком", "нет дали лучший отряд"), the
    strong ones open on a statement that stands by itself ("Лучшая зенитка в
    игре - Дерево", "Мы сильно тонем - Мы не тонем"). A first-word regex does
    NOT reproduce the split (42.6% vs 44.6%), so the difference is in meaning,
    not in vocabulary - which is why this is a field someone fills in rather
    than a check the code performs.

    Recording it is the whole point: the rule is a hypothesis with a good
    illustration, not a measured fact, and it stays that way until a few
    batches carry the label and the two groups can be compared. Not a gate.
    """
    warnings: list[str] = []
    for entry in entries:
        value = entry.get("opening")
        name = entry.get("output_filename", "<без имени>")
        if value is None:
            warnings.append(
                f"[warn] {name}: no opening - this clip stays out of the "
                f"standalone-opening experiment. Set one of: {', '.join(OPENINGS)}"
            )
        elif value not in OPENINGS:
            warnings.append(
                f"[warn] {name}: opening {value!r} is not one of "
                f"{', '.join(OPENINGS)}"
            )
    return warnings


def split_plan(entries: list[dict]) -> tuple[list[dict], list[dict]]:
    """Splits plan entries into (regular, loop), preserving order within each
    group."""
    regular = [entry for entry in entries if not is_loop_entry(entry)]
    loops = [entry for entry in entries if is_loop_entry(entry)]
    return regular, loops


def _toggle(name: str, value: bool) -> list[str]:
    """argparse.BooleanOptionalAction flag: always emit an explicit form so the
    config wins over render.py's own default."""
    return [f"--{name}" if value else f"--no-{name}"]


def build_render_args(
    config: Config,
    video_path: str,
    plan_path: str,
    output_dir: str,
    *,
    loop_pass: bool = False,
) -> list[str]:
    """Builds the full render.py argv (positionals first) for one pass.

    loop_pass=True renders the loop clips: --loop-enabled on, outro and cold
    open off. The cold-open flag is withheld rather than left to render.py's
    per-entry gate, so a plan entry that wrongly carries a cold_open field
    still can't break the loop seam.
    """
    subtitles = config.subtitles
    audio = config.audio
    effects = config.effects
    args: list[str] = [video_path, plan_path, output_dir]

    args += ["--fade-seconds", str(config.clip.fade_seconds)]

    args += [
        "--sub-font", subtitles.font,
        "--sub-size", str(subtitles.size),
        "--sub-color", subtitles.color,
        "--sub-outline-color", subtitles.outline,
        "--sub-highlight-color", subtitles.highlight_color,
        "--sub-position", subtitles.position,
        "--sub-words-per-cue", str(subtitles.words_per_cue),
    ]
    args += _toggle("sub-strip-punctuation", subtitles.strip_punctuation)
    args += _toggle("censor-subtitles", subtitles.censor_profanity)
    args += [
        "--censor-keep-ratio", str(subtitles.censor_keep_ratio),
        "--profanity-wordlist", subtitles.censor_wordlist,
    ]

    args += _toggle("denoise", audio.denoise)
    args += ["--denoise-strength", str(audio.denoise_strength)]
    args += _toggle("loudnorm", audio.loudnorm)

    args += _toggle("vignette", effects.vignette)
    args += [
        "--grain-strength", str(effects.grain_strength),
        "--punch-zoom-amount", str(effects.punch_zoom_amount),
        "--punch-zoom-ramp", str(effects.punch_zoom_ramp),
    ]

    if config.transitions.enabled:
        args += [
            "--transition-duration", str(config.transitions.transition_duration),
            "--min-overlap-seconds", str(config.transitions.min_overlap_seconds),
        ]

    if config.profanity.enabled:
        profanity = config.profanity
        args += [
            "--profanity-duck-volume", str(profanity.duck_volume),
            "--profanity-garble-freq", str(profanity.garble_freq),
            "--profanity-garble-width-octaves", str(profanity.garble_width_octaves),
            "--profanity-warble-freq", str(profanity.warble_freq),
            "--profanity-warble-depth", str(profanity.warble_depth),
            "--profanity-mask-mode", profanity.mask_mode,
        ]
        if profanity.mask_sound_path:
            args += [
                "--profanity-mask-sound-path", profanity.mask_sound_path,
                "--profanity-mask-sound-volume", str(profanity.mask_sound_volume),
            ]

    if config.hook_banner.enabled:
        banner = config.hook_banner
        args += [
            "--banner-mode", banner.mode,
            "--banner-font", banner.font,
            "--banner-size", str(banner.size),
            "--banner-color", banner.color,
            "--banner-cta-font", banner.cta_font,
            "--banner-cta-size", str(banner.cta_size),
            "--banner-cta-color", banner.cta_color,
            "--banner-box-color", banner.box_color,
            "--banner-box-opacity", str(banner.box_opacity),
            "--banner-position", banner.position,
            "--banner-duration-seconds", str(banner.duration_seconds),
            "--banner-fade-seconds", str(banner.fade_seconds),
        ]
        if banner.cta_text:
            args += ["--banner-cta-text", banner.cta_text]

    if config.emphasis.enabled:
        emphasis = config.emphasis
        args += [
            "--emphasis-enabled",
            "--emphasis-zoom-amount", str(emphasis.zoom_amount),
            "--emphasis-ramp", str(emphasis.ramp_seconds),
            "--emphasis-min-hold", str(emphasis.min_hold_seconds),
            "--emphasis-max-moves", str(emphasis.max_moves),
        ]
        if emphasis.face_enabled:
            args += ["--emphasis-face-enabled"]

    if config.social_overlay.enabled:
        social = config.social_overlay
        args += [
            "--social-enabled",
            "--social-duration", str(social.duration_seconds),
            "--social-slide-seconds", str(social.slide_seconds),
            "--social-size", str(social.size),
            "--social-box-color", social.box_color,
            "--social-box-opacity", str(social.box_opacity),
            "--social-font", social.font,
        ]
        if social.y is not None:
            args += ["--social-y", str(social.y)]
        for platform in SOCIAL_PLATFORMS:
            if platform not in social.platforms:
                continue
            label = social.labels.get(platform, "")
            icon = social.icon_paths.get(platform, "")
            if label:
                args += [f"--social-{platform}-label", label]
            if icon:
                args += [f"--social-{platform}-icon", icon]

    if config.video.codec:
        args += ["--video-codec", config.video.codec]
    if config.video.preset:
        args += ["--preset", config.video.preset]
    if config.video.crf is not None:
        args += ["--crf", str(config.video.crf)]
    if config.video.hwaccel and config.video.hwaccel != "none":
        args += ["--hwaccel", config.video.hwaccel]
    if config.video.parallel_clips > 1:
        args += ["--render-parallel-clips", str(config.video.parallel_clips)]

    if loop_pass:
        loop = config.loop
        args += [
            "--loop-enabled",
            "--loop-mode", loop.mode,
            # "auto" is a planning-time instruction to autoloop_entries, not
            # something render.py knows how to render - by the time the flag
            # is built every loop entry already carries its measured value,
            # and the flag is only the fallback for one that could not be.
            "--loop-rotate-transition",
            "cut" if loop.rotate_transition == "auto" else loop.rotate_transition,
            "--loop-transition", loop.transition,
            "--loop-transition-duration", str(loop.transition_duration),
        ]
        return args

    if config.cold_open.enabled:
        cold_open = config.cold_open
        args += [
            "--cold-open-enabled",
            "--cold-open-transition", cold_open.transition,
            "--cold-open-transition-duration", str(cold_open.transition_duration),
        ]

    if config.outro_card.enabled:
        outro = config.outro_card
        args += [
            "--outro-enabled",
            "--outro-duration", str(outro.duration_seconds),
            "--outro-font", outro.font,
            "--outro-nick-size", str(outro.nick_size),
            "--outro-tagline-size", str(outro.tagline_size),
            "--outro-cta-size", str(outro.cta_size),
            "--outro-pattern-count", str(outro.pattern_count),
            "--outro-fps", str(outro.fps),
        ]
        for flag, value in (
            ("--outro-nick", outro.nick),
            ("--outro-tagline", outro.tagline),
            ("--outro-cta", outro.cta_text),
            ("--outro-icon", outro.icon_path),
        ):
            if value:
                args += [flag, value]

    return args


def write_pass_plan(entries: list[dict], plan_path: str, suffix: str) -> str:
    """Writes a pass's subset of entries next to the source plan and returns
    the new path. Written without a BOM: json.loads chokes on one, and these
    files are read back by render.py."""
    source = Path(plan_path)
    target = source.with_name(f"{source.stem}_{suffix}{source.suffix}")
    target.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(target)


def _thumbnail_text(entry: dict) -> str:
    """Poster caption: an explicit thumbnail_text, else the hook banner's text,
    else a clean text-free frame.

    The banner text is safe to reuse because the poster is cut from the SOURCE
    recording, not from the rendered clip - there is no burned-in banner on
    that frame to duplicate.
    """
    return str(entry.get("thumbnail_text") or entry.get("banner_text") or "")


def entry_source_window(entry: dict) -> tuple[float, float]:
    """The clip's span in SOURCE seconds. With jump cuts that's the first kept
    segment's start to the last one's end - the poster frame only has to land
    inside the moment, not inside a specific kept sub-segment."""
    keep = entry.get("keep_segments")
    if keep:
        return float(keep[0][0]), float(keep[-1][1])
    return float(entry["start"]), float(entry["end"])


def load_energy_spikes(config: Config, video_path: str) -> list[dict]:
    """Reads the cached audio-energy spikes for a recording, or [] when the
    pass never ran (fail-open, same as everywhere else in the pipeline).

    Written by scripts/audio_energy.py as {"start","end","reason"} - no
    strength field - so spikes are weighted here by how long they last: a
    sustained burst is a better poster moment than a single transient tick.
    """
    stem = Path(video_path).stem
    cache = Path(config.output_dir) / "transcripts" / f"{stem}_energy_spikes.json"
    if not cache.exists():
        # Loud, because the degradation is otherwise invisible: posters just
        # quietly become clip midpoints. Missing means the audio-energy pass
        # never ran for this recording - re-run scripts/ingest.py.
        print(
            f"[warn] no audio-energy cache at {cache} - every poster falls back to the "
            "clip midpoint; run scripts/ingest.py for this recording",
            file=sys.stderr,
        )
        return []
    try:
        raw = json.loads(cache.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"[warn] energy spikes unreadable, poster falls back to midpoint: {error}", file=sys.stderr)
        return []
    return [
        {"at": round((float(spike["start"]) + float(spike["end"])) / 2.0, 3),
         "weight": round(float(spike["end"]) - float(spike["start"]), 3)}
        for spike in raw
    ]


def spikes_within(spikes: list[dict], start: float, end: float) -> list[dict]:
    """The spikes falling inside one clip's source window, re-based to seconds
    from the window's start so pick_thumbnail_timestamp's safe-band maths works
    on the clip's own timeline."""
    return [
        {"at": spike["at"] - start, "weight": spike["weight"]}
        for spike in spikes
        if start <= spike["at"] <= end
    ]


def _poster_focus(entry: dict) -> float:
    """Where across the frame the poster should be cut from, as a percentage.

    The same number the clip itself is framed with. It used to read "focus_x_pct", a key
    nothing in this codebase ever writes - autoframe_entries writes crop_focus_x and
    crop_focus_keyframes - so every poster was centred no matter where the clip looked.
    On a clip framed hard left or right the cover art showed a different part of the
    picture than the video, which is exactly the mismatch thumbnail.py exists to avoid.

    A panning clip has no single answer, so the poster takes the first keyframe: the
    frame it is cut from is near the start.
    """
    keyframes = entry.get("crop_focus_keyframes")
    if keyframes:
        return float(keyframes[0][1])
    return float(entry.get("crop_focus_x", 50.0))


def generate_thumbnails(
    config: Config, entries: list[dict], output_dir: str, video_path: str
) -> list[str]:
    """Best-effort poster per clip, cut from the SOURCE recording rather than
    from the rendered clip.

    The rendered clip is already letterboxed for pad/original-16:9 crop styles
    and carries burned-in captions, so a frame lifted from it makes a poster
    with black bars and a subtitle across it. The source frame is clean 16:9:
    the cover-fit in build_thumbnail_command zooms it to fill 1080x1920 edge to
    edge, which is what a thumbnail needs.

    Fail-open like every other optional feature: a poster failure is warned
    about and never undoes an already-rendered clip.
    """
    from scripts.thumbnail import generate_thumbnail, pick_thumbnail_timestamp

    thumbnail = config.thumbnail
    all_spikes = load_energy_spikes(config, video_path) if thumbnail.timestamp_strategy == "energy" else []
    written: list[str] = []
    for entry in entries:
        clip_path = Path(output_dir) / entry["output_filename"]
        # JPEG, not PNG: a 1080x1920 PNG of a busy game frame runs up to
        # ~2.2 MB and YouTube refuses a thumbnail over 2 MB outright.
        poster_path = clip_path.with_suffix(".thumb.jpg")
        try:
            start, end = entry_source_window(entry)
            timestamp = start + pick_thumbnail_timestamp(
                end - start, spikes_within(all_spikes, start, end)
            )
            generate_thumbnail(
                video_path,
                _thumbnail_text(entry),
                str(poster_path),
                timestamp=timestamp,
                width=thumbnail.width,
                height=thumbnail.height,
                font=thumbnail.font,
                font_size=thumbnail.font_size,
                text_color=thumbnail.text_color,
                box_color=thumbnail.box_color,
                box_opacity=thumbnail.box_opacity,
                position=thumbnail.position,
                max_lines=thumbnail.max_lines,
                focus_x_pct=_poster_focus(entry),
            )
        except Exception as error:  # noqa: BLE001 - fail-open by design
            print(f"[warn] no thumbnail for {clip_path.name}: {error}", file=sys.stderr)
            continue
        written.append(str(poster_path))
    return written


def run_pass(
    config: Config,
    video_path: str,
    plan_path: str,
    output_dir: str,
    *,
    loop_pass: bool,
    dry_run: bool = False,
    runner=subprocess.run,
) -> int:
    command = [sys.executable, "-m", "scripts.render"] + build_render_args(
        config, video_path, plan_path, output_dir, loop_pass=loop_pass
    )
    label = "loop" if loop_pass else "regular"
    if dry_run:
        print(f"[{label}] " + subprocess.list2cmdline(command))
        return 0
    print(f"[{label}] rendering {plan_path}", file=sys.stderr)
    return runner(command).returncode


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render a PLAN.json with every flag derived from config.yaml, "
        "splitting loop clips into their own outro-free pass.",
    )
    parser.add_argument("input_video", help="Path to the source recording")
    parser.add_argument("plan_json", help="Path to PLAN.json: a list of clip plan entries")
    parser.add_argument(
        "--config", default="config.yaml", help="Config file to read every render setting from"
    )
    parser.add_argument(
        "--output-dir", default=None, help="Override config.output_dir for this run"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print the render commands instead of running them"
    )
    parser.add_argument(
        "--enqueue", action="store_true",
        help="Put the batch on the publish grid once it has rendered - enqueue AND upload "
             "to YouTube (scripts/enqueue_batch.py)",
    )
    parser.add_argument(
        "--enqueue-local-only", action="store_true",
        help="With --enqueue: write the local queue but do not upload to YouTube",
    )
    args = parser.parse_args()

    config = load_config(args.config)
    output_dir = args.output_dir or config.output_dir
    entries = json.loads(Path(args.plan_json).read_text(encoding="utf-8-sig"))
    if not entries:
        parser.error(f"{args.plan_json} has no plan entries")
    for warning in dead_zone_warnings(entries):
        print(warning, file=sys.stderr)
    for warning in unused_feature_warnings(config, entries):
        print(warning, file=sys.stderr)
    for warning in unknown_moment_tag_warnings(entries):
        print(warning, file=sys.stderr)
    for warning in opening_warnings(entries):
        print(warning, file=sys.stderr)

    # Imported here rather than at module scope: render.py pulls in the whole
    # render stack, and the flag derivation above must stay importable on its
    # own (that is what makes it unit-testable without ffmpeg).
    from scripts.render import TARGET_HEIGHT, TARGET_WIDTH, probe_video

    framed = False
    if not args.dry_run:
        try:
            probe = probe_video(args.input_video)
            framed, frame_warnings = autoframe_entries(
                args.input_video, entries, probe["width"], probe["height"],
                target_width=TARGET_WIDTH, target_height=TARGET_HEIGHT,
            )
        except Exception as error:  # noqa: BLE001 - fail-open, centre crop is still valid
            print(f"[warn] auto crop framing skipped: {error}", file=sys.stderr)
            frame_warnings = []
        for warning in frame_warnings:
            print(warning, file=sys.stderr)

        try:
            looped, loop_warnings = autoloop_entries(args.input_video, entries)
            framed = framed or looped
        except Exception as error:  # noqa: BLE001 - fail-open, "cut" is still valid
            print(f"[warn] loop junction selection skipped: {error}", file=sys.stderr)
            loop_warnings = []
        for warning in loop_warnings:
            print(warning, file=sys.stderr)

    regular, loops = split_plan(entries)

    passes: list[tuple[list[dict], str, bool]] = []
    if regular:
        path = (
            write_pass_plan(regular, args.plan_json, "regular")
            if (loops or framed) else args.plan_json
        )
        passes.append((regular, path, False))
    if loops:
        passes.append((loops, write_pass_plan(loops, args.plan_json, "loop"), True))

    rendered: list[dict] = []
    for pass_entries, pass_plan, loop_pass in passes:
        code = run_pass(
            config, args.input_video, pass_plan, output_dir,
            loop_pass=loop_pass, dry_run=args.dry_run,
        )
        if code != 0:
            raise SystemExit(f"render failed ({'loop' if loop_pass else 'regular'} pass), exit {code}")
        rendered += pass_entries

    if args.dry_run:
        return
    if config.thumbnail.enabled:
        generate_thumbnails(config, rendered, output_dir, args.input_video)
    print(f"{len(rendered)} clips rendered into {output_dir}")

    if args.enqueue:
        # Imported here, not at module scope: enqueue_batch imports this module
        # back for is_loop_entry, and rendering must not depend on the publish
        # half being importable.
        from scripts.enqueue_batch import enqueue_batch, upload_queued_batch

        enqueue_batch(config, args.plan_json, output_dir)
        if config.publish.enabled and not args.enqueue_local_only:
            # From the config, not from literals. Both paths are declared and validated
            # in config.py and were then ignored here, so moving the secrets out of the
            # repository root - the sensible thing to do with them - produced a
            # FileNotFoundError at the very end of a render that had already run for
            # hours, with the config fields quietly implying otherwise.
            upload_queued_batch(
                config, config.publish.client_secret_path, config.publish.upload_token_path
            )


if __name__ == "__main__":
    main()
