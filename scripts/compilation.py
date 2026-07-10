"""Mechanical grouping-validation and PLAN.json compilation-entry builder for
sub-threshold highlight compilations (COMP-01/02/03). Claude has already
decided WHICH sub-threshold candidates belong in a group (D-02, semantic
similarity judgment) and their strongest-first order (D-04) before anything
in this module runs - this module only validates the mechanical constraints
(group size >= 2, same video_stem, length ceiling) and assembles the
PLAN.json "compilation" entry shape. No tag-similarity matching, no
string/fuzzy comparison of tag text lives here - see project Anti-Pattern
"Encoding semantic judgment in Python".
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


class CompilationError(ValueError):
    pass


MIN_GROUP_SIZE = 2


def _member_duration(member: dict) -> float:
    keep_segments = member.get("keep_segments")
    if keep_segments:
        return sum(seg_end - seg_start for seg_start, seg_end in keep_segments)
    return member["end"] - member["start"]


def build_compilation_entry(
    members: list[dict],
    compilation_max_seconds: float,
    crop_style: str,
    boundary_transitions: list[str] | None = None,
    punch_zoom_at: float | None = None,
    subtitles_path: str | None = None,
    metadata_path: str | None = None,
    output_filename: str | None = None,
) -> dict:
    """Validates a caller-supplied, already strongest-first-ordered (D-04)
    group of sub-threshold candidates and builds the PLAN.json "compilation"
    entry. Raises CompilationError on any mechanical violation - too few
    members (COMP-02), members spanning more than one video_stem (COMP-03),
    a group that can't fit even 2 members under compilation_max_seconds
    (D-05), or a boundary_transitions list whose length doesn't match the
    flattened segment count. Never silently produces a broken entry.
    """
    if len(members) < MIN_GROUP_SIZE:
        raise CompilationError(
            f"a compilation group needs >= {MIN_GROUP_SIZE} members, got {len(members)}"
        )

    video_stems = {member["video_stem"] for member in members}
    if len(video_stems) > 1:
        raise CompilationError(
            f"all group members must share one video_stem, got {sorted(video_stems)}"
        )

    # Length-ceiling capping (D-04/D-05): walk members in the given
    # strongest-first order, accumulating each member's own duration. Stop
    # at the first member that would push the running total over the cap -
    # drop it and every member after it. Never skip ahead looking for a
    # smaller later member that might still fit; strongest-first order must
    # be preserved literally.
    fitted: list[dict] = []
    running_total = 0.0
    for member in members:
        duration = _member_duration(member)
        if running_total + duration > compilation_max_seconds:
            break
        fitted.append(member)
        running_total += duration

    if len(fitted) < MIN_GROUP_SIZE:
        raise CompilationError(
            f"capping at compilation_max_seconds={compilation_max_seconds} leaves "
            f"{len(fitted)} member(s), a compilation group needs >= {MIN_GROUP_SIZE}"
        )

    flattened_segment_count = sum(
        len(member["keep_segments"]) if member.get("keep_segments") else 1 for member in fitted
    )

    if boundary_transitions is not None:
        expected_length = flattened_segment_count - 1
        # boundary_transitions is computed pre-cap by SKILL.md step 5b bullet 5
        # (against the full uncapped flattened segment list), before this
        # function's own length-ceiling capping above ever runs. Capping only
        # ever drops a contiguous trailing run of members under D-04's literal
        # strongest-first ordering, so the pre-cap list's own prefix is exactly
        # the boundaries that survive - truncate down to reconcile, but never
        # pad, so a genuinely too-short list still raises below (CR-01).
        if len(boundary_transitions) > expected_length:
            boundary_transitions = boundary_transitions[:expected_length]
        if len(boundary_transitions) != expected_length:
            raise CompilationError(
                f"boundary_transitions must have length {expected_length} "
                f"(flattened segment count {flattened_segment_count} - 1), "
                f"got {len(boundary_transitions)}"
            )

    segments = []
    for member in fitted:
        segment = {"start": member["start"], "end": member["end"]}
        if member.get("keep_segments"):
            segment["keep_segments"] = member["keep_segments"]
        segments.append(segment)

    entry: dict = {"type": "compilation", "segments": segments, "crop_style": crop_style}
    if boundary_transitions is not None:
        entry["boundary_transitions"] = boundary_transitions
    if punch_zoom_at is not None:
        entry["punch_zoom_at"] = punch_zoom_at
    if subtitles_path is not None:
        entry["subtitles_path"] = subtitles_path
    if metadata_path is not None:
        entry["metadata_path"] = metadata_path
    if output_filename is not None:
        entry["output_filename"] = output_filename
    return entry


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate a sub-threshold candidate group and build its PLAN.json 'compilation' entry"
    )
    parser.add_argument(
        "members_json",
        help="Path to a JSON list of member dicts (video_stem, start, end, optional keep_segments)",
    )
    parser.add_argument("compilation_max_seconds", type=float, help="Length ceiling for the compilation")
    parser.add_argument("crop_style", help="Crop style for the compilation clip")
    parser.add_argument("output_json", help="Path to write the built PLAN.json 'compilation' entry to")
    parser.add_argument(
        "--boundary-transitions-json", default=None,
        help="Path to a JSON list of per-boundary transition types",
    )
    parser.add_argument("--punch-zoom-at", type=float, default=None)
    parser.add_argument("--subtitles-path", default=None)
    parser.add_argument("--metadata-path", default=None)
    parser.add_argument("--output-filename", default=None)
    args = parser.parse_args()

    members = json.loads(Path(args.members_json).read_text(encoding="utf-8"))
    boundary_transitions = None
    if args.boundary_transitions_json is not None:
        boundary_transitions = json.loads(Path(args.boundary_transitions_json).read_text(encoding="utf-8"))

    entry = build_compilation_entry(
        members,
        args.compilation_max_seconds,
        args.crop_style,
        boundary_transitions=boundary_transitions,
        punch_zoom_at=args.punch_zoom_at,
        subtitles_path=args.subtitles_path,
        metadata_path=args.metadata_path,
        output_filename=args.output_filename,
    )
    Path(args.output_json).write_text(json.dumps(entry, indent=2), encoding="utf-8")
    print(args.output_json)


if __name__ == "__main__":
    main()
