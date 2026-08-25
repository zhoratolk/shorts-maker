"""Putting a stream's parts back together, and refusing to when they don't add up.

The sources are the only copy of a recording, so the interesting behaviour here is not
the concatenation - ffmpeg does that - but the two ways it can go wrong quietly: parts
grouped into the wrong session, and a joined file that is missing one of them. Both look
like success from the outside, which is why they are checked rather than assumed.
"""

import datetime as dt
import os
import pathlib
import tempfile

import pytest

from deploy import session


def part(name: str, begins: str, duration: float):
    return (name, dt.datetime.fromisoformat(begins), duration)


class TestReadingWhenARecordingStarted:
    def test_the_recorder_format_is_understood(self):
        assert session.started_at("2026-08-25 14-30-00.mkv") == dt.datetime(2026, 8, 25, 14, 30, 0)

    def test_a_full_path_is_fine(self):
        got = session.started_at("/media/recordings/2026-08-25 14-30-00.mkv")

        assert got == dt.datetime(2026, 8, 25, 14, 30, 0)

    def test_underscores_instead_of_a_space(self):
        assert session.started_at("2026-08-25_14-30-00.mkv") == dt.datetime(2026, 8, 25, 14, 30)

    def test_a_name_of_somebody_own_is_not_guessed_at(self):
        """Returning something plausible here would order a hand-dropped file into the
        middle of a real session."""
        assert session.started_at("gameplay-final-v2.mkv") is None

    def test_an_impossible_date_is_not_a_crash(self):
        assert session.started_at("2026-13-45 99-99-99.mkv") is None


class TestGroupingPartsIntoSessions:
    def test_parts_that_run_on_from_each_other_are_one_session(self):
        parts = [
            part("a.mkv", "2026-08-25T14:00:00", 900),
            part("b.mkv", "2026-08-25T14:15:00", 900),
            part("c.mkv", "2026-08-25T14:30:00", 600),
        ]

        assert session.group_sessions(parts) == [["a.mkv", "b.mkv", "c.mkv"]]

    def test_a_gap_of_hours_starts_a_new_session(self):
        """The folder holds several nights at once, so this is the case that matters."""
        parts = [
            part("night1.mkv", "2026-08-25T14:00:00", 900),
            part("night2.mkv", "2026-08-25T20:00:00", 900),
        ]

        assert session.group_sessions(parts) == [["night1.mkv"], ["night2.mkv"]]

    def test_the_small_gap_between_obs_files_does_not_split_them(self):
        parts = [
            part("a.mkv", "2026-08-25T14:00:00", 900.0),
            part("b.mkv", "2026-08-25T14:15:03", 900.0),
        ]

        assert session.group_sessions(parts) == [["a.mkv", "b.mkv"]]

    def test_parts_are_ordered_by_when_they_started_not_by_name(self):
        """A hand-dropped file sorts anywhere alphabetically; putting it in the wrong
        place inside a session would shift every timestamp after it."""
        parts = [
            part("zebra.mkv", "2026-08-25T14:00:00", 900),
            part("alpha.mkv", "2026-08-25T14:15:00", 900),
        ]

        assert session.group_sessions(parts) == [["zebra.mkv", "alpha.mkv"]]

    def test_nothing_to_group(self):
        assert session.group_sessions([]) == []

    def test_a_lone_recording_is_a_session_of_one(self):
        assert session.group_sessions([part("a.mkv", "2026-08-25T14:00:00", 900)]) == [["a.mkv"]]


class TestCheckingTheJoinedFile:
    def test_matching_totals_pass(self):
        assert session.totals_agree(1800.0, 2000, [900.0, 900.0], [1000, 1000]) == []

    def test_a_dropped_part_is_caught(self):
        """The failure this exists for: ffmpeg exits 0 and the file plays fine, it is
        simply an hour short, and nothing downstream can tell."""
        problems = session.totals_agree(900.0, 1000, [900.0, 900.0], [1000, 1000])

        assert len(problems) == 2
        assert "1800" in problems[0]

    def test_a_truncated_copy_shows_up_in_the_size_first(self):
        problems = session.totals_agree(1800.0, 1200, [900.0, 900.0], [1000, 1000])

        assert len(problems) == 1
        assert "GB" in problems[0]

    def test_a_frame_of_rounding_is_not_a_problem(self):
        assert session.totals_agree(1800.04, 2000, [900.0, 900.02], [1000, 1000]) == []

    def test_empty_parts_do_not_divide_by_zero(self):
        assert session.totals_agree(0.0, 0, [], []) == []


class TestNaming:
    def test_a_single_file_keeps_its_name(self):
        assert session.session_name(["/rec/2026-08-25 14-00-00.mkv"]) == "2026-08-25 14-00-00.mkv"

    def test_a_joined_session_says_how_many_parts_went_in(self):
        got = session.session_name(["/rec/2026-08-25 14-00-00.mkv", "/rec/2026-08-25 14-15-00.mkv"])

        assert got == "2026-08-25 14-00-00-joined-2.mkv"


class TestNothingIsReadWhileItIsStillBeingWritten:
    @pytest.fixture
    def recording(self):
        directory = pathlib.Path(tempfile.mkdtemp())
        path = directory / "2026-08-25 14-00-00.mkv"
        path.write_bytes(b"x")
        return path

    def test_a_file_still_growing_is_not_ready(self, recording):
        """OBS is still writing it; transcribing now would read a stream that has not
        finished happening."""
        now = os.path.getmtime(recording) + 60

        assert not session.settled(str(recording), now, quiet_seconds=600)

    def test_a_file_untouched_for_a_while_is_ready(self, recording):
        now = os.path.getmtime(recording) + 3600

        assert session.settled(str(recording), now, quiet_seconds=600)

    def test_a_file_that_vanished_is_not_ready(self):
        assert not session.settled("/nope/recording.mkv", now=0.0, quiet_seconds=1)


class TestTheConcatList:
    def test_each_part_is_listed_in_order(self):
        directory = pathlib.Path(tempfile.mkdtemp())
        list_path = directory / "list.txt"

        session.write_concat_list(["/rec/a.mkv", "/rec/b.mkv"], str(list_path))

        lines = list_path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2
        assert lines[0].startswith("file '") and lines[0].endswith("a.mkv'")

    def test_a_quote_in_a_path_is_escaped_the_way_ffmpeg_wants(self):
        """Unescaped, ffmpeg reads the rest of the name as syntax and cannot find the
        file - which on a concat list means one part silently missing."""
        directory = pathlib.Path(tempfile.mkdtemp())
        list_path = directory / "list.txt"

        session.write_concat_list(["/rec/it's here.mkv"], str(list_path))

        assert "'\\''" in list_path.read_text(encoding="utf-8")


class TestJoining:
    def test_a_session_of_one_is_used_where_it_lies(self):
        """No copy, no re-encode, no second 8 GB on the disk for nothing."""
        assert session.join(["/rec/only.mkv"], "/out/only.mkv") == "/rec/only.mkv"


class TestTheInterpreterTheSubStepsRunUnder:
    """Naming only the Windows virtualenv layout meant ingest could not run anywhere else,
    which is how it failed the first time it was asked to run in a container."""

    def test_a_posix_virtualenv_is_found(self, monkeypatch):
        from scripts import ingest

        root = pathlib.Path(tempfile.mkdtemp())
        (root / ".venv" / "bin").mkdir(parents=True)
        (root / ".venv" / "bin" / "python").write_text("#!/bin/sh\n", encoding="utf-8")
        monkeypatch.setattr(ingest, "REPO_ROOT", root)

        assert ingest._interpreter().endswith(os.path.join("bin", "python"))

    def test_a_windows_virtualenv_is_found(self, monkeypatch):
        from scripts import ingest

        root = pathlib.Path(tempfile.mkdtemp())
        (root / ".venv" / "Scripts").mkdir(parents=True)
        (root / ".venv" / "Scripts" / "python.exe").write_bytes(b"MZ")
        monkeypatch.setattr(ingest, "REPO_ROOT", root)

        assert ingest._interpreter().endswith("python.exe")

    def test_without_a_virtualenv_the_running_interpreter_is_used(self, monkeypatch):
        """The container case: the dependencies are installed system-wide and there is no
        .venv to find, so insisting on one would leave nothing to run."""
        import sys

        from scripts import ingest

        monkeypatch.setattr(ingest, "REPO_ROOT", pathlib.Path(tempfile.mkdtemp()))

        assert ingest._interpreter() == sys.executable


class TestTheManifest:
    """What the unattended pass actually reads.

    It used to glob the joined-files directory, which meant a recording that arrived as a
    single part - most of them - was never picked up at all, because a session of one is
    used where it lies and no joined file is ever written for it.
    """

    def _fake_parts(self, monkeypatch, parts):
        monkeypatch.setattr(session, "find_parts", lambda directory, now, quiet: parts)

    def test_a_single_part_recording_is_listed_where_it_lies(self, monkeypatch):
        directory = pathlib.Path(tempfile.mkdtemp())
        manifest = directory / "_auto" / "sessions.txt"
        self._fake_parts(monkeypatch, [
            ("/media/recordings/2026-08-25 14-00-00.mkv",
             dt.datetime(2026, 8, 25, 14, 0), 900.0),
        ])

        session.main(["/media/recordings", "--into", "/media/clips/sources",
                      "--manifest", str(manifest)])

        assert manifest.read_text(encoding="utf-8").strip() == \
            "/media/recordings/2026-08-25 14-00-00.mkv"

    def test_a_joined_session_is_listed_at_its_joined_path(self, monkeypatch):
        directory = pathlib.Path(tempfile.mkdtemp())
        manifest = directory / "sessions.txt"
        joined = directory / "2026-08-25 14-00-00-joined-2.mkv"
        joined.write_bytes(b"already here")
        self._fake_parts(monkeypatch, [
            ("/rec/2026-08-25 14-00-00.mkv", dt.datetime(2026, 8, 25, 14, 0), 900.0),
            ("/rec/2026-08-25 14-15-00.mkv", dt.datetime(2026, 8, 25, 14, 15), 900.0),
        ])

        session.main(["/rec", "--into", str(directory), "--manifest", str(manifest)])

        assert manifest.read_text(encoding="utf-8").strip() == str(joined)

    def test_a_session_that_could_not_be_joined_is_left_out(self, monkeypatch):
        """Better to skip it than to hand the next stage a file that does not match its
        parts - and it stays on disk, so the mismatch can be looked at."""
        directory = pathlib.Path(tempfile.mkdtemp())
        manifest = directory / "sessions.txt"
        self._fake_parts(monkeypatch, [
            ("/rec/a.mkv", dt.datetime(2026, 8, 25, 14, 0), 900.0),
            ("/rec/b.mkv", dt.datetime(2026, 8, 25, 14, 15), 900.0),
        ])
        monkeypatch.setattr(session, "join",
                            lambda paths, dest: (_ for _ in ()).throw(session.SessionError("nope")))

        session.main(["/rec", "--into", str(directory), "--manifest", str(manifest)])

        assert manifest.read_text(encoding="utf-8") == ""

    def test_nothing_ready_writes_an_empty_manifest_rather_than_leaving_a_stale_one(self, monkeypatch):
        directory = pathlib.Path(tempfile.mkdtemp())
        manifest = directory / "sessions.txt"
        manifest.write_text("/rec/from-last-time.mkv\n", encoding="utf-8")
        self._fake_parts(monkeypatch, [])

        session.main(["/rec", "--into", str(directory), "--manifest", str(manifest)])

        assert manifest.read_text(encoding="utf-8") == ""
