"""Removes the join files the watcher superseded, and everything derived from them.

The watcher joins a session's parts every time it wakes up, so a stream that was still
being recorded gets joined once per pass: `...-joined-3.mkv`, then `-joined-5`, `-joined-7`,
up to the final `-joined-18`. Each one is a complete copy of everything recorded so far,
so a four hour session leaves nine files adding up to 133 GB where 25 GB is the whole
recording. On 2026-09-06 that had grown to 400 GB of joins for 60 GB of actual footage and
the volume was at 70%.

Only the newest join of a session is kept - it contains every part the earlier ones did.
Nothing here touches the recordings in `recordings/`: those are the only copy of a stream,
and deleting them stays a decision a person makes. Superseded joins are not - they are
duplicates by construction.

The artefacts ingest built from a superseded join go with it: its transcript, its pause and
energy files, its chunk/frame directory under work/, and its `.ingested` marker. Leaving
those behind would keep a moment search pointed at a stem whose video no longer exists.

Usage:
    python3 deploy/prune.py            # report only
    python3 deploy/prune.py --apply    # delete
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys

# "<first part stem>-joined-<N>.<ext>", the name session.py gives a join. The number is
# the part count, so a bigger one is always a superset of a smaller one from the same
# session - that is what makes dropping the smaller ones safe without probing them.
JOINED = re.compile(r"^(?P<stem>.+)-joined-(?P<count>\d+)$")

DEFAULT_ROOT = os.environ.get("SHORTS_ROOT", "/srv/shorts-maker")
DEFAULT_MEDIA = os.environ.get("SHORTS_MEDIA", "/srv/media")


def superseded(names: list[str]) -> list[str]:
    """The join file names that a later join of the same session already contains.

    A session with a single join keeps it. A session whose parts never needed joining
    has no `-joined-` in its name at all and never appears here.
    """
    newest: dict[str, int] = {}
    for name in names:
        match = JOINED.match(os.path.splitext(name)[0])
        if not match:
            continue
        stem, count = match["stem"], int(match["count"])
        newest[stem] = max(newest.get(stem, 0), count)

    doomed = []
    for name in names:
        match = JOINED.match(os.path.splitext(name)[0])
        if not match:
            continue
        if int(match["count"]) < newest[match["stem"]]:
            doomed.append(name)
    return doomed


def derived_paths(stem: str, root: str, media: str) -> list[str]:
    """Everything ingest wrote for one join, whether or not it exists."""
    transcripts = os.path.join(media, "clips", "transcripts")
    return [
        os.path.join(transcripts, f"{stem}.json"),
        os.path.join(transcripts, f"{stem}_pauses.json"),
        os.path.join(transcripts, f"{stem}_energy_spikes.json"),
        os.path.join(root, "work", stem),
        os.path.join(root, "work", "_auto", f"{stem}.ingested"),
    ]


def size_of(path: str) -> int:
    if os.path.isdir(path):
        total = 0
        for directory, _, files in os.walk(path):
            for name in files:
                try:
                    total += os.path.getsize(os.path.join(directory, name))
                except OSError:
                    pass
        return total
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def remove(path: str) -> None:
    if os.path.isdir(path):
        shutil.rmtree(path)
    else:
        os.unlink(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=DEFAULT_ROOT)
    parser.add_argument("--media", default=DEFAULT_MEDIA)
    parser.add_argument("--apply", action="store_true",
                        help="delete instead of listing what would be deleted")
    args = parser.parse_args(argv)

    sources = os.path.join(args.media, "clips", "sources")
    if not os.path.isdir(sources):
        print(f"no join directory at {sources}, nothing to do")
        return 0

    names = sorted(name for name in os.listdir(sources)
                   if os.path.isfile(os.path.join(sources, name)))
    doomed = superseded(names)
    if not doomed:
        print("every session's newest join is the only one left, nothing to prune")
        return 0

    freed = 0
    for name in doomed:
        stem = os.path.splitext(name)[0]
        targets = [os.path.join(sources, name)] + derived_paths(stem, args.root, args.media)
        for target in targets:
            if not os.path.exists(target):
                continue
            bytes_here = size_of(target)
            freed += bytes_here
            print(f"{'removing' if args.apply else 'would remove'} "
                  f"{target} ({bytes_here / 1024 ** 3:.2f} GB)")
            if args.apply:
                try:
                    remove(target)
                except OSError as error:
                    print(f"  could not remove: {error}", file=sys.stderr)

    print(f"{'freed' if args.apply else 'would free'} {freed / 1024 ** 3:.1f} GB "
          f"across {len(doomed)} superseded join(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
