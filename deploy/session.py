"""Turns a folder of OBS split files back into the recordings they came from.

OBS writes a long stream as a chain of ~15 minute files, and every later stage - the
transcript, the moment search, the timestamps in a plan - assumes one file per session.
Stitching them by hand is the step that has been done manually until now, and it is the
step with the sharpest edge on it: the sources are the only copy of a stream, and a
concat that silently dropped a part looks exactly like a concat that worked.

So nothing here deletes anything. It writes the joined file, checks it against the sum of
its parts, and refuses to hand it on if the numbers disagree. Removing the originals stays
a human decision made after looking at the result.

Only the standard library plus ffmpeg/ffprobe, which the image already carries.
"""

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time

# OBS's default filename template, and the one this recorder uses: "2026-08-25 14-30-00".
TIMESTAMP = re.compile(r"(\d{4})-(\d{2})-(\d{2})[ _](\d{2})-(\d{2})-(\d{2})")

VIDEO_SUFFIXES = (".mkv", ".mp4", ".flv", ".mov", ".ts")

# How far apart two parts may be and still be one recording. OBS closes one file and opens
# the next in well under a second, so this is generous on purpose: what it must not do is
# swallow the gap between two genuinely separate streams, which is minutes at least.
MAX_GAP_SECONDS = 90

# Concatenating without re-encoding copies packets, so the result is the sum of its parts
# to within a frame. A tolerance wider than this would stop the check from catching the
# failure it exists for: a part that was quietly left out.
DURATION_TOLERANCE_SECONDS = 2.0
SIZE_TOLERANCE_FRACTION = 0.01


class SessionError(Exception):
    pass


def started_at(name: str) -> dt.datetime | None:
    """When the recording in this file began, read from its name.

    Falls back to None rather than to the file's mtime: mtime is when writing *finished*,
    and mixing the two would order the parts of a session wrongly.
    """
    match = TIMESTAMP.search(os.path.basename(name))
    if not match:
        return None
    try:
        return dt.datetime(*(int(part) for part in match.groups()))
    except ValueError:
        return None


def probe_duration(path: str) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", path],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise SessionError(f"ffprobe could not read {path}: {result.stderr.strip()}")
    try:
        return float(json.loads(result.stdout)["format"]["duration"])
    except (KeyError, ValueError, json.JSONDecodeError) as e:
        raise SessionError(f"ffprobe gave no duration for {path}: {e}") from e


def group_sessions(parts: list[tuple[str, dt.datetime, float]],
                   max_gap: float = MAX_GAP_SECONDS) -> list[list[str]]:
    """Splits (path, started_at, duration) into one list of paths per recording.

    Two parts belong together when the second begins about where the first ended. Judged
    on the clock rather than on the filenames being adjacent, because a folder holds
    several nights at once and "the next file alphabetically" is the wrong answer as soon
    as one session ends and another starts an hour later.
    """
    ordered = sorted(parts, key=lambda part: part[1])
    sessions: list[list[str]] = []
    ends_at: dt.datetime | None = None

    for path, begins, duration in ordered:
        if ends_at is not None and (begins - ends_at).total_seconds() <= max_gap:
            sessions[-1].append(path)
        else:
            sessions.append([path])
        ends_at = begins + dt.timedelta(seconds=duration)
    return sessions


def totals_agree(joined_duration: float, joined_size: int,
                 part_durations: list[float], part_sizes: list[int]) -> list[str]:
    """What is wrong with the joined file, or nothing.

    Both numbers are checked because they fail differently: a dropped part shows up in
    both, while a stream that stopped being copied part-way through shows up in the size
    long before the duration notices.
    """
    problems = []
    expected_duration = sum(part_durations)
    if abs(joined_duration - expected_duration) > DURATION_TOLERANCE_SECONDS:
        problems.append(
            f"joined file is {joined_duration:.1f}s, the parts add up to "
            f"{expected_duration:.1f}s"
        )
    expected_size = sum(part_sizes)
    if expected_size and abs(joined_size - expected_size) / expected_size > SIZE_TOLERANCE_FRACTION:
        problems.append(
            f"joined file is {joined_size / 1024 ** 3:.2f} GB, the parts add up to "
            f"{expected_size / 1024 ** 3:.2f} GB"
        )
    return problems


def session_name(paths: list[str]) -> str:
    """The joined file's name: the first part's, with the part count if there was one."""
    stem, suffix = os.path.splitext(os.path.basename(paths[0]))
    if len(paths) == 1:
        return stem + suffix
    return f"{stem}-joined-{len(paths)}{suffix}"


def write_concat_list(paths: list[str], list_path: str) -> None:
    """ffmpeg's concat demuxer list. Single quotes in a path are escaped its way."""
    with open(list_path, "w", encoding="utf-8") as f:
        for path in paths:
            escaped = os.path.abspath(path).replace("'", "'\\''")
            f.write(f"file '{escaped}'\n")


def already_joined(paths: list[str], destination: str) -> bool:
    """Whether a file left from an earlier run can be trusted.

    Existence is not enough, and assuming it was is how this module could have defeated
    its own purpose: a join that failed its check is deliberately left on disk to be
    looked at, and a run that was killed part-way leaves a truncated file behind. Either
    one, taken on faith by the next pass, is a recording with a piece missing handed on as
    finished - the exact outcome everything here exists to prevent, made worse by the
    originals being deleted afterwards.
    """
    if not os.path.exists(destination):
        return False
    try:
        problems = totals_agree(
            probe_duration(destination), os.path.getsize(destination),
            [probe_duration(path) for path in paths],
            [os.path.getsize(path) for path in paths],
        )
    except SessionError:
        # Unreadable by ffprobe, which a truncated file usually is. Not trusted.
        return False
    return not problems


def join(paths: list[str], destination: str) -> str:
    """Concatenates the parts without re-encoding and checks the result.

    Stream copy rather than a re-encode: these are 4-8 GB of already-encoded video, the
    parts came out of one encoder so their streams match, and re-encoding would cost hours
    and a generation of quality for nothing.
    """
    if len(paths) == 1:
        return paths[0]

    os.makedirs(os.path.dirname(destination), exist_ok=True)
    # Built beside the destination and moved onto it only once it has passed, because
    # ffmpeg's -y truncates its output before it reads a single byte of input. Writing
    # straight to the destination meant a rebuild destroyed whatever was already there
    # before finding out whether it could produce a replacement - so one part being
    # briefly unreadable (a backup holding it open, an antivirus scan) turned yesterday's
    # good joined file into a stub, and the "kept for inspection" copy this raises about
    # was overwritten by the next run before anybody could look at it.
    partial = destination + ".part"
    list_path = destination + ".txt"
    write_concat_list(paths, list_path)
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-f", "concat", "-safe", "0", "-i", list_path, "-c", "copy", partial],
            capture_output=True, text=True, check=False,
        )
        if result.returncode != 0:
            raise SessionError(f"ffmpeg concat failed: {result.stderr.strip()[:400]}")
    finally:
        try:
            os.unlink(list_path)
        except OSError:
            pass

    problems = totals_agree(
        probe_duration(partial), os.path.getsize(partial),
        [probe_duration(path) for path in paths],
        [os.path.getsize(path) for path in paths],
    )
    if problems:
        # Left on disk deliberately, so the mismatch can be looked at rather than guessed
        # about. The sources are untouched either way, so nothing has been lost yet.
        raise SessionError(
            "the joined file does not match its parts, so it is not being used: "
            + "; ".join(problems) + f" (kept at {partial} for inspection)"
        )
    os.replace(partial, destination)
    return destination


def settled(path: str, now: float, quiet_seconds: float) -> bool:
    """Whether a file has stopped growing.

    A recording still being written looks exactly like a finished one, and reading it
    would transcribe a stream that has not finished happening.
    """
    try:
        return now - os.path.getmtime(path) >= quiet_seconds
    except OSError:
        return False


def find_parts(directory: str, now: float,
               quiet_seconds: float) -> list[tuple[str, dt.datetime, float]]:
    parts = []
    for name in sorted(os.listdir(directory)):
        path = os.path.join(directory, name)
        if not name.lower().endswith(VIDEO_SUFFIXES) or not os.path.isfile(path):
            continue
        if not settled(path, now, quiet_seconds):
            continue
        begins = started_at(name)
        if begins is None:
            # Anything not named by the recorder was dropped in by hand. It is a session
            # of one, and its real start time is unknowable, so it is ordered by when it
            # was last written instead.
            begins = dt.datetime.fromtimestamp(os.path.getmtime(path))
        try:
            duration = probe_duration(path)
        except SessionError as e:
            # One unreadable file - a zero-byte leftover, a copy that was interrupted -
            # used to take the whole pass with it: the error came out of here, main never
            # reached the manifest, and every other session that was ready went unwritten
            # too. Skipping it costs that one recording and saves the rest.
            print(f"[warn] skipping {name}: {e}", file=sys.stderr)
            continue
        parts.append((path, begins, duration))
    return parts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Join OBS split recordings into sessions.")
    parser.add_argument("directory", help="where the recorder writes")
    parser.add_argument("--into", required=True, help="where joined files go")
    parser.add_argument("--quiet-minutes", type=float, default=10.0,
                        help="how long a file must be untouched before it counts as done")
    parser.add_argument("--list", action="store_true",
                        help="print the sessions that would be joined and stop")
    parser.add_argument("--manifest",
                        help="write one usable recording path per line here")
    args = parser.parse_args(argv)

    parts = find_parts(args.directory, time.time(), args.quiet_minutes * 60)
    sessions = group_sessions(parts)
    ready = []

    for session in sessions:
        destination = os.path.join(args.into, session_name(session))
        if args.list:
            print(f"{len(session)} part(s) -> {destination}")
            continue
        try:
            # A session of one part is used where it lies, so what comes back here is
            # sometimes the joined file and sometimes the original. Whichever it is, it is
            # the path the rest of the pipeline should be given.
            if len(session) == 1:
                ready.append(session[0])
            elif already_joined(session, destination):
                ready.append(destination)
            else:
                ready.append(join(session, destination))
        except SessionError as e:
            print(f"session starting {os.path.basename(session[0])}: {e}", file=sys.stderr)

    # Written to a file rather than printed, because stdout is not ours alone: this runs
    # inside a container whose base image greets every start with a licence notice, and a
    # caller parsing that would treat the greeting as a recording.
    if args.manifest:
        # dirname of a bare filename is "", and makedirs("") raises - so a perfectly
        # ordinary `--manifest sessions.txt` from a cron job with a working directory
        # brought the whole pass down at the last step.
        manifest_dir = os.path.dirname(args.manifest)
        if manifest_dir:
            os.makedirs(manifest_dir, exist_ok=True)
        with open(args.manifest, "w", encoding="utf-8") as f:
            for path in ready:
                f.write(path + "\n")

    for path in ready:
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
