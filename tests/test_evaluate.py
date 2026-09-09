"""The scoring used to compare every detector against the same labels."""

import math

from experiments.evaluate import at_threshold, auc, evaluate


def test_auc_is_one_when_every_positive_outranks_every_negative():
    assert auc([(0.9, 1), (0.8, 1), (0.2, 0), (0.1, 0)]) == 1.0


def test_auc_is_zero_when_the_order_is_exactly_backwards():
    assert auc([(0.1, 1), (0.2, 0)]) == 0.0


def test_ties_count_as_half_so_a_constant_signal_scores_chance():
    # A detector that returns the same number for everything separates nothing, and
    # must score 0.5 rather than 1.0 - which is what happens if ties count as wins.
    assert auc([(1.0, 1), (1.0, 0), (1.0, 1), (1.0, 0)]) == 0.5


def test_auc_is_nan_without_both_classes():
    assert math.isnan(auc([(1.0, 1), (2.0, 1)]))


def test_at_threshold_counts_precision_and_recall():
    pairs = [(5.0, 1), (4.0, 1), (4.0, 0), (1.0, 0)]
    step = at_threshold(pairs, 4.0)
    assert step["kept"] == 3
    assert step["recall"] == 1.0
    assert step["precision"] == round(2 / 3, 3)


def test_evaluate_splits_the_two_kinds_of_negative():
    labels = [
        {"stem": "s", "start": 0.0, "label": 1, "kind": "clip"},
        {"stem": "s", "start": 10.0, "label": 0, "kind": "dead"},
        {"stem": "s", "start": 20.0, "label": 0, "kind": "passed"},
    ]
    # Separates the positive from the dead window perfectly, not at all from the
    # passed one. One number would hide that; two show it.
    scores = {("s", 0.0): 5.0, ("s", 10.0): 1.0, ("s", 20.0): 5.0}
    report = evaluate(labels, scores, "тест")
    assert report["auc_vs_dead"] == 1.0
    assert report["auc_vs_passed"] == 0.5


def test_evaluate_counts_windows_it_had_no_score_for():
    labels = [
        {"stem": "s", "start": 0.0, "label": 1, "kind": "clip"},
        {"stem": "s", "start": 10.0, "label": 0, "kind": "dead"},
    ]
    report = evaluate(labels, {("s", 0.0): 1.0}, "тест")
    assert report["missing"] == 1
    assert report["windows"] == 1


# --- motion profile -> per-window score --------------------------------------

def test_window_score_weights_buckets_by_how_much_they_overlap():
    from experiments.motion_scores import window_score

    buckets = [{"at": 0.0, "mean_diff": 10.0}, {"at": 20.0, "mean_diff": 0.0}]
    # [15, 25) takes 5s of the first bucket and 5s of the second: an even split.
    assert window_score(buckets, 15.0, 25.0, 20.0) == 5.0
    # [0, 20) is exactly the first bucket and must not be diluted by the second.
    assert window_score(buckets, 0.0, 20.0, 20.0) == 10.0


def test_window_score_is_none_outside_the_profile():
    from experiments.motion_scores import window_score

    assert window_score([{"at": 0.0, "mean_diff": 3.0}], 100.0, 120.0, 20.0) is None
