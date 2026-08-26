"""Downloads a stream VOD into the recordings folder the watcher already watches.

The pipeline has always taken a path to a file, which meant a VOD had to be fetched by
hand and dropped into the share. This closes that gap without changing anything
downstream: what lands here is an ordinary recording, named the way OBS names one, and
the watcher picks it up on its next pass like any other.

The name matters more than it looks. session.py reads the moment a recording began out
of its filename - not out of mtime, which is when writing *finished* - and uses it to
order the parts of a session. A file named anything else is invisible to that ordering,
so the VOD's own start time is what goes into the name, and only a VOD that reports no
start time falls back to now.

Written to a temporary name and renamed at the end. A half-downloaded file that already
carries its final name is a file the watcher will eventually decide is finished.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys

# What session.py accepts. Anything else would download fine and then be ignored by
# everything after it, which is the most confusing possible outcome.
DEFAULT_SUFFIX = ".mkv"

# OBS's filename template, which session.py's TIMESTAMP regex parses.
NAME_FORMAT = "%Y-%m-%d %H-%M-%S"


class FetchError(Exception):
    pass


def probe(url: str, runner=subprocess.run) -> dict:
    """The VOD's metadata, without downloading a byte of it."""
    result = runner(
        ["yt-dlp", "--dump-single-json", "--no-warnings", "--no-playlist", url],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise FetchError(f"yt-dlp could not read {url}: {result.stderr.strip()[-400:]}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise FetchError(f"yt-dlp returned something that is not JSON: {e}") from e


def started_at(info: dict, now: dt.datetime | None = None) -> dt.datetime:
    """When the stream began, as well as the source is willing to say.

    Twitch and YouTube both carry a real unix timestamp for a VOD; some sources give
    only the upload date, which at least keeps recordings from the same day in order.
    """
    stamp = info.get("timestamp") or info.get("release_timestamp")
    if isinstance(stamp, (int, float)) and stamp > 0:
        return dt.datetime.fromtimestamp(stamp)

    date = info.get("upload_date")
    if isinstance(date, str) and len(date) == 8 and date.isdigit():
        return dt.datetime.strptime(date, "%Y%m%d")

    return now or dt.datetime.now()


def target_name(info: dict, suffix: str = DEFAULT_SUFFIX, now: dt.datetime | None = None) -> str:
    return started_at(info, now).strftime(NAME_FORMAT) + suffix


def fetch(url: str, into: str, suffix: str = DEFAULT_SUFFIX, name: str | None = None,
          runner=subprocess.run) -> str:
    """Downloads the VOD and returns the path it landed on."""
    info = probe(url, runner=runner)
    name = name or target_name(info, suffix)
    final = os.path.join(into, name)

    if os.path.exists(final):
        print(f"[skip] {name} is already here", file=sys.stderr)
        return final

    os.makedirs(into, exist_ok=True)
    # A dot-prefixed working name: session.py globs by suffix, and this way a download in
    # flight is not merely unfinished but unlisted.
    partial = os.path.join(into, f".fetching-{name}")

    title = info.get("title") or url
    duration = info.get("duration")
    if duration:
        print(f"[fetch] {title} — {duration / 3600:.1f} ч", file=sys.stderr)
    else:
        print(f"[fetch] {title}", file=sys.stderr)

    result = runner(
        [
            "yt-dlp", "--no-playlist", "--no-warnings",
            # Merged into one file rather than left as separate streams: everything
            # downstream opens exactly one path.
            "--merge-output-format", suffix.lstrip("."),
            "--retries", "10", "--fragment-retries", "10",
            # Resumes a partial file instead of starting a three-hour download again.
            "--continue",
            "-o", partial, url,
        ],
    )
    if result.returncode != 0:
        raise FetchError(f"yt-dlp failed on {url} (exit {result.returncode})")

    # yt-dlp may have added its own extension to the working name when remuxing.
    actual = partial if os.path.exists(partial) else _find_partial(into, name)
    if actual is None:
        raise FetchError(f"yt-dlp reported success but wrote nothing for {name}")

    os.replace(actual, final)
    print(f"[done] {final}", file=sys.stderr)
    return final


def _find_partial(into: str, name: str) -> str | None:
    prefix = f".fetching-{name}"
    for entry in sorted(os.listdir(into)):
        if entry.startswith(prefix):
            return os.path.join(into, entry)
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Download a stream VOD into the recordings folder."
    )
    parser.add_argument("url", help="Twitch/YouTube/etc. VOD link")
    parser.add_argument("--into", default="/media/recordings",
                        help="where the recording should land")
    parser.add_argument("--suffix", default=DEFAULT_SUFFIX,
                        help="container for the merged file")
    parser.add_argument("--name", help="override the generated filename entirely")
    args = parser.parse_args(argv)

    try:
        print(fetch(args.url, args.into, args.suffix, args.name))
    except FetchError as e:
        print(f"fetch failed: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
