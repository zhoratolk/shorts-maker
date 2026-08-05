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

from scripts.config import Config, load_config

SOCIAL_PLATFORMS = ("twitch", "kick", "telegram")


class RenderBatchError(RuntimeError):
    pass


def is_loop_entry(entry: dict) -> bool:
    """A plan entry renders as a loop when it carries a truthy "loop" key -
    the same key render.py gates its loop seam on."""
    return bool(entry.get("loop"))


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
            args += ["--profanity-mask-sound-path", profanity.mask_sound_path]

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

    if loop_pass:
        loop = config.loop
        args += [
            "--loop-enabled",
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
        poster_path = clip_path.with_suffix(".thumb.png")
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
                focus_x_pct=float(entry.get("focus_x_pct", 50.0)),
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
        help="Put the batch on the publish grid once it has rendered (scripts/enqueue_batch.py)",
    )
    args = parser.parse_args()

    config = load_config(args.config)
    output_dir = args.output_dir or config.output_dir
    entries = json.loads(Path(args.plan_json).read_text(encoding="utf-8-sig"))
    regular, loops = split_plan(entries)
    if not entries:
        parser.error(f"{args.plan_json} has no plan entries")

    passes: list[tuple[list[dict], str, bool]] = []
    if regular:
        path = write_pass_plan(regular, args.plan_json, "regular") if loops else args.plan_json
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
        from scripts.enqueue_batch import enqueue_batch

        enqueue_batch(config, args.plan_json, output_dir)


if __name__ == "__main__":
    main()
