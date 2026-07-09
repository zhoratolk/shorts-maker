from scripts.transitions import TRANSITION_TYPES, TransitionError


def test_transition_types_has_exactly_six_members():
    assert len(TRANSITION_TYPES) == 6


def test_transition_types_contains_expected_values():
    assert TRANSITION_TYPES == {"cut", "crossfade", "whip_pan", "mask_wipe", "glitch", "match_cut"}


def test_transition_error_subclasses_value_error():
    assert issubclass(TransitionError, ValueError)
