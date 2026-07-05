from scripts.audio_energy import (
    compute_rolling_baseline,
    detect_energy_spikes,
    find_energy_spikes,
    measure_momentary_loudness,
)


class FakeResult:
    def __init__(self, stderr: str, returncode: int = 0):
        self.stderr = stderr
        self.returncode = returncode
        self.stdout = ""


EBUR128_STDERR = """[Parsed_ebur128_0 @ 0000017] t: 0.099979   TARGET:-23 LUFS    M: -60.0 S: -60.0     I: -60.0 LUFS       LRA:   0.0 LU
[Parsed_ebur128_0 @ 0000017] t: 0.199979   TARGET:-23 LUFS    M: -59.5 S: -59.5     I: -59.5 LUFS       LRA:   0.0 LU
[Parsed_ebur128_0 @ 0000017] t: 0.299979   TARGET:-23 LUFS    M: -18.0 S: -20.0     I: -20.0 LUFS       LRA:   0.0 LU
"""


def test_measure_momentary_loudness_parses_time_series():
    points = measure_momentary_loudness("in.mp4", runner=lambda *a, **k: FakeResult(EBUR128_STDERR))

    assert points == [
        {"time": 0.099979, "momentary_lufs": -60.0},
        {"time": 0.199979, "momentary_lufs": -59.5},
        {"time": 0.299979, "momentary_lufs": -18.0},
    ]


def test_measure_momentary_loudness_empty_when_no_match():
    assert measure_momentary_loudness("in.mp4", runner=lambda *a, **k: FakeResult("nothing here")) == []


def test_compute_rolling_baseline_uses_trailing_median():
    points = [
        {"time": 0.0, "momentary_lufs": -40.0},
        {"time": 1.0, "momentary_lufs": -40.0},
        {"time": 2.0, "momentary_lufs": -40.0},
    ]

    assert compute_rolling_baseline(points, window_seconds=20.0) == [-40.0, -40.0, -40.0]


def test_compute_rolling_baseline_drops_points_outside_window():
    points = [
        {"time": 0.0, "momentary_lufs": -10.0},   # will fall outside the window by t=25
        {"time": 20.0, "momentary_lufs": -40.0},
        {"time": 25.0, "momentary_lufs": -40.0},
    ]

    baselines = compute_rolling_baseline(points, window_seconds=10.0)

    # at t=25, window is (15, 25] - only the two -40.0 points qualify
    assert baselines[2] == -40.0


def test_detect_energy_spikes_finds_a_sustained_jump():
    points = [
        {"time": 0.0, "momentary_lufs": -40.0},
        {"time": 0.5, "momentary_lufs": -40.0},
        {"time": 1.0, "momentary_lufs": -40.0},
        {"time": 1.5, "momentary_lufs": -20.0},
        {"time": 2.0, "momentary_lufs": -20.0},
        {"time": 2.5, "momentary_lufs": -40.0},
    ]

    spikes = detect_energy_spikes(points, threshold_db=6.0, floor_lufs=-35.0, min_duration=0.3)

    assert spikes == [{"start": 1.5, "end": 2.0, "reason": "audio energy spike"}]


def test_detect_energy_spikes_ignores_spike_below_floor():
    points = [
        {"time": 0.0, "momentary_lufs": -80.0},
        {"time": 0.5, "momentary_lufs": -80.0},
        {"time": 1.0, "momentary_lufs": -60.0},  # +20dB jump, but still below floor_lufs
    ]

    assert detect_energy_spikes(points, threshold_db=6.0, floor_lufs=-35.0) == []


def test_detect_energy_spikes_drops_too_short_blip():
    points = [
        {"time": 0.0, "momentary_lufs": -40.0},
        {"time": 0.1, "momentary_lufs": -10.0},
        {"time": 0.2, "momentary_lufs": -40.0},
    ]

    assert detect_energy_spikes(points, threshold_db=6.0, floor_lufs=-35.0, min_duration=0.3) == []


def test_detect_energy_spikes_merges_nearby_windows():
    # Two short loud bursts (3.0-3.5, 4.5-5.0) separated by a 1.0s quiet gap
    # (<= merge_gap_seconds) surrounded by enough quiet context that the
    # rolling median baseline isn't dragged up by the bursts themselves.
    times = [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0]
    vals = [-40, -40, -40, -40, -40, -40, -10, -10, -40, -10, -10, -40, -40]
    points = [{"time": t, "momentary_lufs": v} for t, v in zip(times, vals)]

    spikes = detect_energy_spikes(
        points, threshold_db=6.0, floor_lufs=-35.0, baseline_window_seconds=5.0,
        merge_gap_seconds=1.0, min_duration=0.3,
    )

    assert spikes == [{"start": 3.0, "end": 5.0, "reason": "audio energy spike"}]


def test_detect_energy_spikes_empty_input():
    assert detect_energy_spikes([]) == []


def test_find_energy_spikes_runs_measure_then_detect():
    spikes = find_energy_spikes(
        "in.mp4", runner=lambda *a, **k: FakeResult(EBUR128_STDERR),
        threshold_db=6.0, floor_lufs=-35.0, min_duration=0.0,
    )

    assert spikes == [{"start": 0.299979, "end": 0.299979, "reason": "audio energy spike"}]
