import builtins

import pytest

from scripts.transitions import (
    TRANSITION_TYPES,
    TransitionError,
    analyze_motion_at_boundary,
    analyze_similarity_at_boundary,
)


def test_transition_types_has_exactly_six_members():
    assert len(TRANSITION_TYPES) == 6


def test_transition_types_contains_expected_values():
    assert TRANSITION_TYPES == {"cut", "crossfade", "whip_pan", "mask_wipe", "glitch", "match_cut"}


def test_transition_error_subclasses_value_error():
    assert issubclass(TransitionError, ValueError)


def _block_import(monkeypatch, blocked_name):
    """Forces `import {blocked_name}` to raise ImportError deterministically,
    without requiring the real package to actually be absent from the venv -
    the fail-open lazy-import shape (diarize.py:72-78) must degrade to None
    even in an environment where cv2/librosa happen to be installed.
    """
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == blocked_name:
            raise ImportError(f"simulated missing {blocked_name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)


def test_analyze_motion_returns_none_when_cv2_missing(monkeypatch):
    _block_import(monkeypatch, "cv2")

    assert analyze_motion_at_boundary("a.jpg", "b.jpg") is None


def test_analyze_similarity_returns_none_when_cv2_missing(monkeypatch):
    _block_import(monkeypatch, "cv2")

    assert analyze_similarity_at_boundary("a.jpg", "b.jpg") is None


def test_analyze_motion_returns_none_when_frame_unreadable(tmp_path):
    pytest.importorskip("cv2")
    missing_path = str(tmp_path / "does_not_exist.jpg")

    assert analyze_motion_at_boundary(missing_path, missing_path) is None


def test_analyze_similarity_returns_none_when_frame_unreadable(tmp_path):
    pytest.importorskip("cv2")
    missing_path = str(tmp_path / "does_not_exist.jpg")

    assert analyze_similarity_at_boundary(missing_path, missing_path) is None


def _make_shifted_square_frame(square_x):
    import numpy as np

    frame = np.zeros((64, 64, 3), dtype=np.uint8)
    frame[10:30, square_x:square_x + 20] = (255, 255, 255)
    return frame


def test_analyze_motion_identical_frames_near_zero_shifted_frames_higher(tmp_path):
    cv2 = pytest.importorskip("cv2")
    pytest.importorskip("numpy")

    frame_a = _make_shifted_square_frame(square_x=5)
    frame_b = _make_shifted_square_frame(square_x=35)

    frame_a_path = str(tmp_path / "a.jpg")
    frame_b_path = str(tmp_path / "b.jpg")
    cv2.imwrite(frame_a_path, frame_a)
    cv2.imwrite(frame_b_path, frame_b)

    motion_same = analyze_motion_at_boundary(frame_a_path, frame_a_path)
    motion_shifted = analyze_motion_at_boundary(frame_a_path, frame_b_path)

    assert motion_same is not None and motion_same < 0.01
    assert motion_shifted is not None and motion_shifted > motion_same


def test_analyze_similarity_identical_frames_high_differing_colors_lower(tmp_path):
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")

    frame_blue = np.zeros((32, 32, 3), dtype=np.uint8)
    frame_blue[:, :] = (200, 30, 20)
    frame_red = np.zeros((32, 32, 3), dtype=np.uint8)
    frame_red[:, :] = (10, 20, 220)

    blue_path = str(tmp_path / "blue.jpg")
    red_path = str(tmp_path / "red.jpg")
    cv2.imwrite(blue_path, frame_blue)
    cv2.imwrite(red_path, frame_red)

    similarity_same = analyze_similarity_at_boundary(blue_path, blue_path)
    similarity_diff = analyze_similarity_at_boundary(blue_path, red_path)

    assert similarity_same is not None and similarity_same > 0.99
    assert similarity_diff is not None and similarity_diff < similarity_same
