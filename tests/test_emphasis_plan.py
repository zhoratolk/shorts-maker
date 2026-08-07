from __future__ import annotations

from scripts.emphasis_plan import plan_emphasis_moves


def test_empty_clip_duration_returns_empty():
    assert plan_emphasis_moves(10.0, 10.0) == []


def test_no_signals_returns_empty():
    assert plan_emphasis_moves(0.0, 20.0) == []


def test_punch_zoom_at_becomes_a_candidate():
    moves = plan_emphasis_moves(0.0, 20.0, punch_zoom_at=5.0)
    assert moves == [{"at": 5.0, "duration": 0.6, "kind": "punch", "target": "action"}]


def test_energy_spike_rebased_to_clip_relative():
    spikes = [{"start": 105.0, "end": 105.4}]
    moves = plan_emphasis_moves(100.0, 120.0, energy_spikes=spikes)
    assert moves == [{"at": 5.0, "duration": 0.6, "kind": "punch", "target": "action"}]


def test_energy_spike_outside_clip_window_dropped():
    spikes = [{"start": 50.0, "end": 50.4}]
    moves = plan_emphasis_moves(100.0, 120.0, energy_spikes=spikes)
    assert moves == []


def test_punch_beats_nearby_energy_spike_by_priority():
    spikes = [{"start": 5.5, "end": 5.9}]
    moves = plan_emphasis_moves(0.0, 20.0, punch_zoom_at=5.0, energy_spikes=spikes, min_interval=2.0)
    assert len(moves) == 1
    assert moves[0]["at"] == 5.0


def test_far_apart_signals_both_kept():
    spikes = [{"start": 15.0, "end": 15.4}]
    moves = plan_emphasis_moves(0.0, 20.0, punch_zoom_at=5.0, energy_spikes=spikes, min_interval=3.0)
    assert [m["at"] for m in moves] == [5.0, 15.0]


def test_max_moves_caps_output_keeping_highest_priority():
    spikes = [
        {"start": 3.0, "end": 3.4},
        {"start": 9.0, "end": 9.4},
        {"start": 15.0, "end": 15.4},
    ]
    moves = plan_emphasis_moves(
        0.0, 20.0, energy_spikes=spikes, min_interval=1.0, max_moves=2,
    )
    assert len(moves) == 2
    # earliest-first among equal-priority energy spikes
    assert [m["at"] for m in moves] == [3.0, 9.0]


def test_no_move_lands_in_the_final_min_interval_window():
    moves = plan_emphasis_moves(0.0, 20.0, punch_zoom_at=19.0, min_interval=3.0)
    assert moves == []


def test_result_sorted_chronologically_regardless_of_priority():
    spikes = [{"start": 2.0, "end": 2.4}]
    moves = plan_emphasis_moves(0.0, 20.0, punch_zoom_at=10.0, energy_spikes=spikes, min_interval=1.0)
    assert [m["at"] for m in moves] == [2.0, 10.0]


def test_kind_controls_move_duration_and_default_kind_is_punch():
    moves = plan_emphasis_moves(0.0, 20.0, punch_zoom_at=5.0, kind="zoom")
    assert moves[0]["kind"] == "zoom"
    assert moves[0]["duration"] == 1.0


def test_target_passed_through():
    moves = plan_emphasis_moves(0.0, 20.0, punch_zoom_at=5.0, target="plate")
    assert moves[0]["target"] == "plate"


def test_negative_punch_zoom_at_outside_clip_ignored():
    moves = plan_emphasis_moves(0.0, 20.0, punch_zoom_at=-1.0)
    assert moves == []


def test_punch_zoom_at_past_clip_end_ignored():
    moves = plan_emphasis_moves(0.0, 20.0, punch_zoom_at=25.0)
    assert moves == []
