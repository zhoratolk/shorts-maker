from __future__ import annotations

import argparse
import json
from pathlib import Path


def compute_keep_segments(
    clip_start: float, clip_end: float, pauses: list[dict], max_pause_seconds: float
) -> list[tuple[float, float]]:
    """Given a clip's absolute [clip_start, clip_end) window and a list of
    {"start", "end"} pause dicts (absolute source-file seconds, e.g. from
    scripts/silence.py's find_pauses), returns the sub-segments to actually
    keep - any pause inside the clip longer than max_pause_seconds is cut
    out as a jump cut. Short, natural breathing pauses at or under that
    length are left in place untouched.
    """
    if clip_end <= clip_start:
        raise ValueError("clip_end must be greater than clip_start")

    cuts = sorted(
        (max(pause["start"], clip_start), min(pause["end"], clip_end))
        for pause in pauses
        if pause["end"] - pause["start"] > max_pause_seconds
        and pause["start"] < clip_end
        and pause["end"] > clip_start
    )

    segments: list[tuple[float, float]] = []
    cursor = clip_start
    for cut_start, cut_end in cuts:
        if cut_start > cursor:
            segments.append((cursor, cut_start))
        cursor = max(cursor, cut_end)
    if cursor < clip_end:
        segments.append((cursor, clip_end))
    return segments


def total_kept_duration(keep_segments: list[tuple[float, float]]) -> float:
    return sum(end - start for start, end in keep_segments)


def compute_boundary_gaps(keep_segments: list[tuple[float, float]]) -> list[float]:
    """Returns the cut pause-gap (absolute source seconds) at each adjacent
    keep_segments boundary: gap N = keep_segments[N+1][0] - keep_segments[N][1].
    This is exactly the pause footage compute_keep_segments already cut out,
    surfaced here instead of discarded - a non-cut transition (crossfade/whip
    pan/etc.) borrows from this unused source footage as its xfade overlap
    window, so it never eats into real kept content. Result length always
    equals len(keep_segments) - 1; a single segment has zero boundaries.
    """
    return [
        keep_segments[index + 1][0] - keep_segments[index][1]
        for index in range(len(keep_segments) - 1)
    ]


def compute_boundary_windows(keep_segments: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Returns the cut pause-gap [start, end] absolute source-file window at
    each adjacent keep_segments boundary - companion to compute_boundary_gaps
    (which returns just the duration). Used to grab a verification frame at
    the midpoint of a gap before deciding whether that pause was safe to cut
    (see SKILL.md's gameplay jump-cut visual gate) or should be reversed.
    """
    return [
        (keep_segments[index][1], keep_segments[index + 1][0])
        for index in range(len(keep_segments) - 1)
    ]


def drop_boundary(keep_segments: list[tuple[float, float]], boundary_index: int) -> list[tuple[float, float]]:
    """Reverses one jump cut: merges the two segments straddling
    keep_segments' boundary_index-th gap back into a single segment, keeping
    that pause's footage in the render instead of cutting it out. Used when a
    visual check finds the gap isn't safe to cut after all.
    """
    if not 0 <= boundary_index < len(keep_segments) - 1:
        raise ValueError(f"boundary_index {boundary_index} out of range for {len(keep_segments)} segment(s)")
    merged = (keep_segments[boundary_index][0], keep_segments[boundary_index + 1][1])
    return keep_segments[:boundary_index] + [merged] + keep_segments[boundary_index + 2 :]


def remap_timestamp(t: float, keep_segments: list[tuple[float, float]]) -> float | None:
    """Maps an absolute source-file timestamp onto the spliced (concatenated)
    output timeline built from keep_segments, in order. Returns None when t
    falls inside a cut gap - whatever was at that moment (a word, a frame)
    no longer exists in the rendered output.
    """
    elapsed = 0.0
    for seg_start, seg_end in keep_segments:
        if t < seg_start:
            return None
        if t <= seg_end:
            return elapsed + (t - seg_start)
        elapsed += seg_end - seg_start
    return None


def remap_words(words: list[dict], keep_segments: list[tuple[float, float]]) -> list[dict]:
    """Shifts a list of {"word", "start", "end"} entries (absolute
    source-file seconds) onto the spliced timeline built from keep_segments.
    A word is dropped if either endpoint falls inside a cut gap - it no
    longer exists in the rendered output.
    """
    remapped = []
    for word in words:
        new_start = remap_timestamp(word["start"], keep_segments)
        new_end = remap_timestamp(word["end"], keep_segments)
        if new_start is None or new_end is None:
            continue
        remapped.append({"word": word["word"], "start": round(new_start, 3), "end": round(new_end, 3)})
    return remapped


def _cmd_keep_segments(args: argparse.Namespace) -> None:
    pauses = json.loads(Path(args.pauses_json).read_text(encoding="utf-8"))
    segments = compute_keep_segments(args.clip_start, args.clip_end, pauses, args.max_pause_seconds)
    Path(args.output_json).write_text(json.dumps(segments, indent=2), encoding="utf-8")
    print(f"{len(segments)} segment(s) written to {args.output_json}")


def _cmd_boundary_windows(args: argparse.Namespace) -> None:
    segments_raw = json.loads(Path(args.keep_segments_json).read_text(encoding="utf-8"))
    segments = [(segment[0], segment[1]) for segment in segments_raw]
    windows = compute_boundary_windows(segments)
    print(json.dumps([[start, end] for start, end in windows]))


def _cmd_drop_boundary(args: argparse.Namespace) -> None:
    segments_raw = json.loads(Path(args.keep_segments_json).read_text(encoding="utf-8"))
    segments = [(segment[0], segment[1]) for segment in segments_raw]
    result = drop_boundary(segments, args.boundary_index)
    Path(args.output_json).write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"{len(result)} segment(s) written to {args.output_json}")


def _cmd_remap_words(args: argparse.Namespace) -> None:
    words = json.loads(Path(args.words_json).read_text(encoding="utf-8"))
    segments_raw = json.loads(Path(args.keep_segments_json).read_text(encoding="utf-8"))
    segments = [(segment[0], segment[1]) for segment in segments_raw]
    remapped = remap_words(words, segments)
    Path(args.output_json).write_text(
        json.dumps(remapped, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"{len(remapped)} of {len(words)} word(s) written to {args.output_json}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute and apply jump-cut splices for a clip")
    subparsers = parser.add_subparsers(dest="command", required=True)

    keep_segments_parser = subparsers.add_parser(
        "keep-segments", help="Compute the sub-segments to keep after cutting long pauses"
    )
    keep_segments_parser.add_argument("pauses_json", help="Path to a JSON list of {start,end} pause dicts")
    keep_segments_parser.add_argument("clip_start", type=float, help="Clip start, absolute source seconds")
    keep_segments_parser.add_argument("clip_end", type=float, help="Clip end, absolute source seconds")
    keep_segments_parser.add_argument("output_json", help="Path to write the [start,end] segment list to")
    keep_segments_parser.add_argument(
        "--max-pause-seconds", type=float, default=0.4,
        help="Only pauses longer than this are cut out (default: 0.4)",
    )
    keep_segments_parser.set_defaults(func=_cmd_keep_segments)

    remap_words_parser = subparsers.add_parser(
        "remap-words", help="Shift a clip's word timestamps onto the spliced (post-jumpcut) timeline"
    )
    remap_words_parser.add_argument("words_json", help="Path to a JSON list of {word,start,end} (absolute seconds)")
    remap_words_parser.add_argument("keep_segments_json", help="Path to the keep-segments JSON from the step above")
    remap_words_parser.add_argument("output_json", help="Path to write the remapped word list to")
    remap_words_parser.set_defaults(func=_cmd_remap_words)

    boundary_windows_parser = subparsers.add_parser(
        "boundary-windows", help="Print each keep-segments boundary's cut [start,end] window"
    )
    boundary_windows_parser.add_argument("keep_segments_json", help="Path to a keep-segments JSON file")
    boundary_windows_parser.set_defaults(func=_cmd_boundary_windows)

    drop_boundary_parser = subparsers.add_parser(
        "drop-boundary", help="Reverse one jump cut by merging the two segments straddling it"
    )
    drop_boundary_parser.add_argument("keep_segments_json", help="Path to a keep-segments JSON file")
    drop_boundary_parser.add_argument("boundary_index", type=int, help="0-based boundary index to reverse")
    drop_boundary_parser.add_argument("output_json", help="Path to write the merged segment list to")
    drop_boundary_parser.set_defaults(func=_cmd_drop_boundary)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
