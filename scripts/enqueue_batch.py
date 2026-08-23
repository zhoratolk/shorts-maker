"""Put a finished batch on the publish grid in one command.

The last hand-assembled step in the pipeline. `enqueue()` is a Python function
with seven optional arguments, so every batch used to need a throwaway script
that read the plan, dug the title/description/tags out of the metadata JSON,
computed source_duration, remembered moment_tag, remembered the poster path,
and remembered to interleave the loop clips. Forget any one of those and
nothing errors - the clip just publishes with a piece missing, which is the
same silent-omission failure the render flags had.

Reads the plan and the metadata the pipeline already wrote, so there is nothing
to pass by hand and nothing to forget.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Running this file directly puts scripts/ on sys.path, not the repo root, so
# `scripts` is not importable as a package - and SKILL.md documents running it
# exactly that way. Put the repo root first, before the sibling imports below.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.config import Config, load_config
from scripts.publish_queue import enqueue, interleave_loops, load_queue, save_queue
from scripts.render_batch import is_loop_entry


class EnqueueBatchError(RuntimeError):
    pass


def clip_stem(entry: dict) -> str:
    return Path(entry["output_filename"]).stem


def metadata_json_path(plan_path: str, entry: dict) -> Path:
    """Per-clip metadata JSON, written next to the plan by step 5."""
    return Path(plan_path).parent / "metadata_data" / f"{clip_stem(entry)}.json"


def clip_duration(entry: dict) -> float:
    """The clip's own length in seconds, before cold open and outro card.

    A compilation sums its members' segments; a jump-cut clip sums the kept
    segments; anything else is end - start.
    """
    members = entry.get("segments")
    if members:
        return round(sum(float(end) - float(start) for start, end in members), 2)
    keep = entry.get("keep_segments")
    if keep:
        return round(sum(float(end) - float(start) for start, end in keep), 2)
    return round(float(entry["end"]) - float(entry["start"]), 2)


def load_youtube_metadata(plan_path: str, entry: dict) -> dict:
    path = metadata_json_path(plan_path, entry)
    if not path.exists():
        raise EnqueueBatchError(f"no metadata for {clip_stem(entry)}: {path} is missing")
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    youtube = data.get("youtube")
    if not youtube:
        raise EnqueueBatchError(f"{path} has no 'youtube' block")
    return youtube


def batch_order(entries: list[dict]) -> list[dict]:
    """Publish order for the batch: loop clips spread evenly through the rest.

    Loop clips are rendered in their own pass, so a batch arrives as "all the
    regular ones, then all the loops" - enqueuing in arrival order puts every
    looping clip back to back on the grid.
    """
    return interleave_loops(entries, is_loop_entry)


def enqueue_batch(
    config: Config,
    plan_path: str,
    output_dir: str,
    *,
    skip_missing: bool = True,
) -> list[dict]:
    """Enqueues every clip of one plan, in publish order. Returns the queue
    entries that were added (an already-queued clip_id is skipped by enqueue's
    own idempotency and is not reported as added)."""
    entries = json.loads(Path(plan_path).read_text(encoding="utf-8-sig"))
    queue = load_queue(config.publish.queue_path)
    known = {entry["clip_id"] for entry in queue["entries"]}

    added: list[dict] = []
    for entry in batch_order(entries):
        stem = clip_stem(entry)
        video_path = Path(output_dir) / entry["output_filename"]
        if not video_path.exists():
            message = f"{stem}: rendered clip not found at {video_path}"
            if not skip_missing:
                raise EnqueueBatchError(message)
            print(f"[warn] skipped, {message}", file=sys.stderr)
            continue

        youtube = load_youtube_metadata(plan_path, entry)
        row = enqueue(
            queue,
            clip_id=stem,
            video_path=str(video_path),
            metadata_path=str(Path(output_dir) / f"{stem}.txt"),
            title=youtube["title"],
            description=youtube["description"],
            tags=youtube.get("tags", []),
            moment_tag=entry.get("moment_tag"),
            source_duration=clip_duration(entry),
        )
        if stem not in known:
            added.append(row)
            marker = "ЛУП" if is_loop_entry(entry) else "   "
            poster = "+обложка" if row.get("thumbnail_path") else "БЕЗ ОБЛОЖКИ"
            print(f"seq={row['seq']:>4} {marker} {poster:12} {stem}")

    save_queue(queue, config.publish.queue_path)
    return added


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Enqueue a rendered batch onto the publish grid, reading titles, "
        "tags, durations, moment tags and posters from what the pipeline already wrote.",
    )
    parser.add_argument("plan_json", help="The batch's PLAN.json (loop entries included)")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    parser.add_argument("--output-dir", default=None, help="Override config.output_dir")
    parser.add_argument(
        "--strict", action="store_true",
        help="Fail on a plan entry whose rendered clip is missing instead of skipping it",
    )
    parser.add_argument(
        "--local-only", action="store_true",
        help="Stop after writing the local queue instead of uploading the batch to YouTube",
    )
    parser.add_argument("--client-secret", default="client_secret.json", help="OAuth client secret JSON path")
    parser.add_argument("--token", default="upload_token.json", help="Cached upload-scoped OAuth token JSON path")
    args = parser.parse_args()

    config = load_config(args.config)
    added = enqueue_batch(
        config,
        args.plan_json,
        args.output_dir or config.output_dir,
        skip_missing=not args.strict,
    )

    queued = sum(1 for entry in load_queue(config.publish.queue_path)["entries"] if entry["status"] == "queued")
    print(f"\n{len(added)} clips enqueued, {queued} now waiting for a slot")
    if not config.publish.enabled:
        print("publish.enabled is false - nothing will upload until it is turned on")


if __name__ == "__main__":
    main()
