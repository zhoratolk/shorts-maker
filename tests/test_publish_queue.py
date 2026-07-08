from scripts.publish_queue import VALID_STATUSES


def test_valid_statuses_contains_exactly_six_states():
    assert VALID_STATUSES == frozenset(
        {"queued", "uploading", "scheduled", "published", "killed", "paused"}
    )
