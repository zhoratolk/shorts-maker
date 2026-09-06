"""Moves a finished session's recording off the server and onto F:, then drops
the 15-minute parts it was built from.

The server has ~1 TB and fills at 20-50 GB per stream. Once a session's clips
are rendered, the recording is no longer working data - it is an archive, and
the archive belongs on the desktop's big disk where there is room for it.

What actually moves is the joined file, not the parts. They are the same footage:
session.py builds the join with a stream copy and refuses to hand it on unless
its duration and size match the sum of the parts, so keeping both is holding one
recording twice. This checks that agreement again before touching anything - the
parts are the only copy of a stream, and being wrong here is unrecoverable.

Two halves, because the two disks are on different machines:

    python3 deploy/archive.py plan            # on the server: what is safe to move
    python deploy/archive.py pull --apply     # on the desktop: copy, verify, drop

A recording the recorder wrote in one piece has no parts and no join; it moves
as itself, and the same copy-verify-then-delete order applies.

`plan` names a session only when its join verifies against its parts AND at
least one rendered clip carries its stem - "after we made the clip" is the whole
trigger. Everything else is left alone and said out loud.

`pull` copies the join, re-probes the local copy, and only then asks the server
to delete the parts. Nothing is deleted before the copy has been checked where
it landed, and a session whose local copy disagrees is reported and skipped.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DEFAULT_MEDIA = os.environ.get("SHORTS_MEDIA", "/srv/media")
DEFAULT_HOST = os.environ.get("SHORTS_HOST", "zhora@192.168.1.72")
DEFAULT_ARCHIVE = os.environ.get("SHORTS_ARCHIVE", r"F:\Запись\Архив")
DEFAULT_ROOT = os.environ.get("SHORTS_ROOT", "/srv/shorts-maker")

# The identity and known_hosts are named explicitly: the desktop user's profile
# is a Cyrillic path, and ssh from Git Bash cannot read it ("Could not create
# directory '/c/Users/\306\356\360\340/.ssh'"). The 8.3 short name works.
SSH_KEY = os.environ.get("SHORTS_SSH_KEY", "/c/Users/5611~1/.ssh/id_ed25519")
SSH_HOSTS = os.environ.get("SHORTS_SSH_HOSTS", "/c/Users/5611~1/.ssh/known_hosts")


def ssh_command(*args: str) -> list[str]:
    return ["ssh", "-i", SSH_KEY, "-o", f"UserKnownHostsFile={SSH_HOSTS}",
            DEFAULT_HOST, *args]


# --------------------------------------------------------------------------
# plan - runs on the server
# --------------------------------------------------------------------------

def is_clipped(stem: str, clips: list[str]) -> bool:
    """Whether any rendered clip came out of this recording.

    Clip filenames carry the stem through naming.slugify, so the spaces in
    "2026-09-05 16-09-34-joined-18" are dashes by the time they reach a
    filename. Comparing the raw stem matched nothing and made every
    already-clipped session look unclipped - which is the safe direction to be
    wrong in, but it meant the command never moved anything.
    """
    from scripts.naming import slugify

    prefix = slugify(stem)
    return any(clip.startswith(prefix) and clip.endswith(".mp4") for clip in clips)


def build_plan(media: str, quiet_seconds: float = 600.0) -> dict:
    """Sessions whose join is verified, clipped, and therefore safe to move."""
    import time

    from deploy.session import (find_parts, group_sessions, probe_duration,
                                session_name, totals_agree)

    recordings = os.path.join(media, "recordings")
    sources = os.path.join(media, "clips", "sources")
    clips = os.listdir(media + "/clips")

    sessions, skipped = [], []
    parts = find_parts(recordings, time.time(), quiet_seconds)
    for paths in group_sessions(parts):
        name = session_name(paths)
        stem = os.path.splitext(name)[0]

        # A recording that came out of the recorder in one piece was never
        # joined, so the file in recordings/ IS the recording and it is what
        # moves. This used to be skipped as "no join to verify", which had the
        # check backwards: what is being verified is the copy that lands on F:,
        # against the file it was copied from - and that file exists either way.
        # The join case only differs in which file is the source.
        if len(paths) == 1:
            joined = paths[0]
        else:
            joined = os.path.join(sources, name)
            if not os.path.exists(joined):
                skipped.append({"stem": stem, "why": "no joined file in clips/sources"})
                continue
        if not is_clipped(stem, clips):
            skipped.append({"stem": stem, "why": "no rendered clip carries this stem yet"})
            continue

        problems = totals_agree(
            probe_duration(joined), os.path.getsize(joined),
            [probe_duration(path) for path in paths],
            [os.path.getsize(path) for path in paths],
        )
        if problems:
            skipped.append({"stem": stem, "why": "; ".join(problems)})
            continue

        sessions.append({
            "stem": stem,
            "joined": joined,
            "size": os.path.getsize(joined),
            "duration": round(probe_duration(joined), 3),
            "parts": paths,
            "parts_size": sum(os.path.getsize(path) for path in paths),
        })
    return {"sessions": sessions, "skipped": skipped}


# --------------------------------------------------------------------------
# pull - runs on the desktop
# --------------------------------------------------------------------------

def local_duration(path: str) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", path],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe could not read {path}: {result.stderr.strip()}")
    return float(json.loads(result.stdout)["format"]["duration"])


def pull(archive_dir: str, root: str, apply: bool) -> int:
    plan_json = subprocess.run(
        ssh_command(f"cd {root} && python3 deploy/archive.py plan"),
        capture_output=True, text=True, check=False,
    )
    if plan_json.returncode != 0:
        print(plan_json.stderr.strip(), file=sys.stderr)
        return 1
    plan = json.loads(plan_json.stdout)

    for entry in plan["skipped"]:
        print(f"  пропуск {entry['stem']}: {entry['why']}")
    if not plan["sessions"]:
        print("нечего переносить")
        return 0

    os.makedirs(archive_dir, exist_ok=True)
    moved = 0
    for session in plan["sessions"]:
        name = os.path.basename(session["joined"])
        destination = os.path.join(archive_dir, name)
        gigabytes = session["size"] / 1024 ** 3
        parts_gigabytes = session["parts_size"] / 1024 ** 3
        if session["parts"] == [session["joined"]]:
            print(f"{session['stem']}: {gigabytes:.1f} ГБ на F: — запись переезжает целиком")
        else:
            print(f"{session['stem']}: {gigabytes:.1f} ГБ на F:, "
                  f"{len(session['parts'])} кусков ({parts_gigabytes:.1f} ГБ) с сервера")
        if not apply:
            continue

        if not os.path.exists(destination) or os.path.getsize(destination) != session["size"]:
            copy = subprocess.run(
                ["scp", "-i", SSH_KEY, "-o", f"UserKnownHostsFile={SSH_HOSTS}",
                 f"{DEFAULT_HOST}:{session['joined']}", destination],
                check=False,
            )
            if copy.returncode != 0:
                print("  копирование не удалось, куски оставлены на месте", file=sys.stderr)
                continue

        # Checked where it landed, not where it came from: a copy that was cut
        # short is exactly the failure that would otherwise cost the recording.
        size = os.path.getsize(destination)
        if size != session["size"]:
            print(f"  копия {size} Б против {session['size']} Б на сервере - куски оставлены",
                  file=sys.stderr)
            continue
        if abs(local_duration(destination) - session["duration"]) > 2.0:
            print("  длительность копии не сходится - куски оставлены", file=sys.stderr)
            continue

        quoted = " ".join("'" + path.replace("'", "'\\''") + "'" for path in session["parts"])
        drop = subprocess.run(ssh_command(f"rm -f {quoted}"), check=False)
        if drop.returncode != 0:
            print("  копия на месте, но куски удалить не вышло", file=sys.stderr)
            continue
        moved += 1
        print(f"  перенесено, {len(session['parts'])} кусков удалено")

    print(f"\n{'перенесено' if apply else 'к переносу'} сессий: "
          f"{moved if apply else len(plan['sessions'])}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    plan_parser = sub.add_parser("plan", help="на сервере: что можно переносить (JSON)")
    plan_parser.add_argument("--media", default=DEFAULT_MEDIA)

    pull_parser = sub.add_parser("pull", help="на десктопе: перенести на F: и убрать куски")
    pull_parser.add_argument("--archive-dir", default=DEFAULT_ARCHIVE)
    pull_parser.add_argument("--root", default=DEFAULT_ROOT)
    pull_parser.add_argument("--apply", action="store_true",
                             help="без него только показывает, что было бы перенесено")

    args = parser.parse_args(argv)
    if args.command == "plan":
        print(json.dumps(build_plan(args.media), ensure_ascii=False))
        return 0
    return pull(args.archive_dir, args.root, args.apply)


if __name__ == "__main__":
    raise SystemExit(main())
