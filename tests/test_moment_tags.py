"""The closed moment-tag vocabulary and the table that folds old values into it."""

import pytest

from scripts.moment_tags import ALIASES, MOMENT_TAGS, canonical_tag


def test_a_vocabulary_tag_maps_to_itself():
    assert canonical_tag("aphorism") == "aphorism"


def test_case_and_spacing_do_not_make_a_new_tag():
    # A closed list grows an eighteenth member the day "Rage-Rant" is treated
    # as something other than "rage-rant".
    assert canonical_tag("  Rage-Rant  ") == "rage-rant"
    assert canonical_tag("САМОИРОНИЯ") == "self-deprecation"


def test_the_same_class_in_two_languages_lands_in_one_bucket():
    # This split was the whole problem: 7 + 1 + 2 + 1 clips of one kind,
    # recorded as four unrelated tags, none of which looked significant.
    for written in ("self-deprecating", "self-deprecation",
                    "самоирония", "самоирония по статистике"):
        assert canonical_tag(written) == "self-deprecation"


def test_an_invented_tag_is_rejected_rather_than_guessed():
    assert canonical_tag("шутка про кота") is None
    assert canonical_tag("") is None
    assert canonical_tag(None) is None


@pytest.mark.parametrize("alias,tag", sorted(ALIASES.items()))
def test_every_alias_points_at_a_real_vocabulary_entry(alias, tag):
    # An alias pointing at a tag that no longer exists silently drops its
    # clips out of the statistics, which is the failure this file prevents.
    assert tag in MOMENT_TAGS, f"{alias!r} points at {tag!r}, which is not a tag"


def test_no_alias_shadows_a_vocabulary_tag():
    # An alias named after a real tag would be unreachable, and reading it in
    # the table would tell you the opposite of what happens.
    assert not set(ALIASES) & set(MOMENT_TAGS)


def test_the_vocabulary_stays_small_enough_to_carry_statistics():
    # 295 tagged clips over 17 buckets averages 17 apiece. Doubling the list
    # halves that and puts the distribution back where it started.
    assert 10 <= len(MOMENT_TAGS) <= 20
