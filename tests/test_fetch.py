"""Naming a downloaded VOD the way OBS names a recording.

The name is not cosmetic: session.py reads the moment a recording began out of the
filename and orders the parts of a session by it. A file named anything else is invisible
to that ordering, and a file with the wrong time sorts into the wrong place.
"""

from __future__ import annotations

import datetime as dt
import json
import os

import pytest

from scripts.fetch import (
    DEFAULT_SUFFIX,
    FetchError,
    fetch,
    probe,
    started_at,
    target_name,
)


class FakeResult:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


NOW = dt.datetime(2026, 8, 27, 12, 0, 0)


class TestWhenTheRecordingBegan:
    def test_a_real_timestamp_wins(self):
        started = dt.datetime(2026, 8, 25, 19, 30, 15)
        assert started_at({"timestamp": started.timestamp()}, NOW) == started

    def test_release_timestamp_is_accepted_too(self):
        started = dt.datetime(2026, 8, 25, 19, 30, 15)
        assert started_at({"release_timestamp": started.timestamp()}, NOW) == started

    def test_an_upload_date_at_least_keeps_the_day_right(self):
        assert started_at({"upload_date": "20260825"}, NOW) == dt.datetime(2026, 8, 25)

    def test_nothing_usable_falls_back_to_now(self):
        """Not to zero or to the epoch: a recording dated 1970 sorts before every real
        one and would be joined to the wrong session."""
        assert started_at({}, NOW) == NOW
        assert started_at({"timestamp": 0}, NOW) == NOW
        assert started_at({"upload_date": "не дата"}, NOW) == NOW


class TestTheNameSessionCanRead:
    def test_it_is_obs_format(self):
        started = dt.datetime(2026, 8, 25, 19, 30, 15)
        assert target_name({"timestamp": started.timestamp()}) == "2026-08-25 19-30-15.mkv"

    def test_session_py_can_parse_what_this_produces(self):
        """The contract in one assertion: the regex that orders a session's parts has to
        match this name, or the download is invisible to everything downstream."""
        from deploy.session import TIMESTAMP, started_at as session_started_at

        started = dt.datetime(2026, 8, 25, 19, 30, 15)
        name = target_name({"timestamp": started.timestamp()})

        assert TIMESTAMP.search(name)
        assert session_started_at(name) == started

    def test_the_suffix_is_one_session_py_accepts(self):
        from deploy.session import VIDEO_SUFFIXES

        assert DEFAULT_SUFFIX in VIDEO_SUFFIXES


class TestReadingTheVod:
    def test_a_refusal_is_reported_with_what_yt_dlp_said(self):
        def runner(cmd, **kwargs):
            return FakeResult(stderr="ERROR: video unavailable", returncode=1)

        with pytest.raises(FetchError, match="video unavailable"):
            probe("https://twitch.tv/videos/1", runner=runner)

    def test_junk_instead_of_json_is_not_silently_swallowed(self):
        def runner(cmd, **kwargs):
            return FakeResult(stdout="<html>", returncode=0)

        with pytest.raises(FetchError, match="not JSON"):
            probe("https://twitch.tv/videos/1", runner=runner)

    def test_it_does_not_download_anything(self):
        seen = []

        def runner(cmd, **kwargs):
            seen.append(cmd)
            return FakeResult(stdout="{}")

        probe("https://twitch.tv/videos/1", runner=runner)
        assert "--dump-single-json" in seen[0]


class TestTheDownloadItself:
    @pytest.fixture
    def into(self, tmp_path):
        return str(tmp_path)

    def _runner(self, into, name, calls):
        info = {"timestamp": dt.datetime(2026, 8, 25, 19, 30, 15).timestamp(),
                "title": "стрим", "duration": 7200}

        def runner(cmd, **kwargs):
            calls.append(cmd)
            if "--dump-single-json" in cmd:
                return FakeResult(stdout=json.dumps(info))
            target = cmd[cmd.index("-o") + 1]
            with open(target, "wb") as f:
                f.write(b"video")
            return FakeResult()

        return runner

    def test_it_lands_under_the_obs_name(self, into):
        calls = []
        path = fetch("https://twitch.tv/videos/1", into,
                     runner=self._runner(into, None, calls))

        assert os.path.basename(path) == "2026-08-25 19-30-15.mkv"
        assert os.path.exists(path)

    def test_the_file_is_unlisted_while_it_downloads(self, into):
        """A half-downloaded file carrying its final name is a file the watcher will
        eventually decide is finished and transcribe."""
        calls = []
        seen_during = {}

        info = {"timestamp": dt.datetime(2026, 8, 25, 19, 30, 15).timestamp()}

        def runner(cmd, **kwargs):
            calls.append(cmd)
            if "--dump-single-json" in cmd:
                return FakeResult(stdout=json.dumps(info))
            target = cmd[cmd.index("-o") + 1]
            with open(target, "wb") as f:
                f.write(b"video")
            seen_during["listing"] = sorted(os.listdir(into))
            return FakeResult()

        fetch("https://twitch.tv/videos/1", into, runner=runner)

        assert seen_during["listing"] == [".fetching-2026-08-25 19-30-15.mkv"]
        assert sorted(os.listdir(into)) == ["2026-08-25 19-30-15.mkv"]

    def test_a_recording_already_here_is_not_downloaded_again(self, into):
        calls = []
        fetch("https://twitch.tv/videos/1", into, runner=self._runner(into, None, calls))
        before = len(calls)

        fetch("https://twitch.tv/videos/1", into, runner=self._runner(into, None, calls))

        # One more probe to work out the name, and no second download.
        assert len(calls) == before + 1

    def test_a_failed_download_leaves_no_recording_behind(self, into):
        info = {"timestamp": dt.datetime(2026, 8, 25, 19, 30, 15).timestamp()}

        def runner(cmd, **kwargs):
            if "--dump-single-json" in cmd:
                return FakeResult(stdout=json.dumps(info))
            return FakeResult(returncode=1)

        with pytest.raises(FetchError):
            fetch("https://twitch.tv/videos/1", into, runner=runner)

        assert os.listdir(into) == []

    def test_an_explicit_name_overrides_the_generated_one(self, into):
        calls = []
        path = fetch("https://twitch.tv/videos/1", into, name="свой.mkv",
                     runner=self._runner(into, None, calls))

        assert os.path.basename(path) == "свой.mkv"
