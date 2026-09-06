"""The join files a later pass superseded, and the artefacts that go with them."""

from deploy.prune import derived_paths, superseded


def test_superseded_keeps_only_the_newest_join_of_a_session():
    names = [
        "2026-09-05 16-09-34-joined-3.mkv",
        "2026-09-05 16-09-34-joined-11.mkv",
        "2026-09-05 16-09-34-joined-18.mkv",
    ]
    # 11 beats 3 on the number, not on the string: a plain sort would have kept -3.
    assert superseded(names) == [
        "2026-09-05 16-09-34-joined-3.mkv",
        "2026-09-05 16-09-34-joined-11.mkv",
    ]


def test_superseded_keeps_each_session_separately():
    names = [
        "2026-09-05 16-09-34-joined-3.mkv",
        "2026-09-05 16-09-34-joined-18.mkv",
        "2026-09-06 15-30-19-joined-12.mkv",
    ]
    assert superseded(names) == ["2026-09-05 16-09-34-joined-3.mkv"]


def test_superseded_leaves_a_lone_join_and_an_unjoined_recording_alone():
    names = [
        "2026-09-06 15-30-19-joined-12.mkv",
        "2026-08-12 14-00-00.mkv",
    ]
    assert superseded(names) == []


def test_derived_paths_cover_every_artefact_ingest_writes():
    paths = derived_paths("2026-09-05 16-09-34-joined-3", "/srv/shorts-maker", "/srv/media")
    # Separators come from the host os.path, so this reads the parts rather than a
    # whole path: the tests run on Windows and the pruning runs on Linux.
    joined = "\n".join(paths).replace("\\", "/")
    # A transcript left behind points a moment search at a video that is gone, and a
    # stale .ingested marker stops the stem from ever being ingested again if it comes
    # back - so both have to go with the join itself.
    assert "2026-09-05 16-09-34-joined-3.json" in joined
    assert "_pauses.json" in joined
    assert "_energy_spikes.json" in joined
    assert "/srv/shorts-maker/work/2026-09-05 16-09-34-joined-3" in joined
    assert ".ingested" in joined
