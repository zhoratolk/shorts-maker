"""Which finished sessions the archive command considers already clipped."""

from deploy.archive import is_clipped


def test_is_clipped_matches_the_slugified_stem():
    # The recording's stem has spaces; the clip filename has none, because it
    # went through naming.slugify. Matching the raw stem found nothing.
    clips = ["2026-09-05-16-09-34-joined-18-0001-tri-vzryva-v-ebalo.mp4"]
    assert is_clipped("2026-09-05 16-09-34-joined-18", clips)


def test_is_clipped_ignores_a_different_session():
    clips = ["2026-09-06-15-30-19-joined-12-0001-cvety-na-pokhorony.mp4"]
    assert not is_clipped("2026-09-05 16-09-34-joined-18", clips)


def test_is_clipped_ignores_posters_and_metadata():
    # A poster is written next to every clip, and it is not evidence that the
    # render finished - only the .mp4 is.
    clips = [
        "2026-09-05-16-09-34-joined-18-0001-tri-vzryva-v-ebalo.thumb.jpg",
        "2026-09-05-16-09-34-joined-18-0001-tri-vzryva-v-ebalo.txt",
    ]
    assert not is_clipped("2026-09-05 16-09-34-joined-18", clips)


def test_is_clipped_is_false_with_no_clips_at_all():
    assert not is_clipped("2026-09-05 16-09-34-joined-18", [])
