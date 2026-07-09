"""Boundary-analysis signal layer for context-driven transitions (TRANS-01).

Computes independent, unit-testable analysis signals at a jumpcut boundary
(end of segment A / start of segment B): dense optical-flow motion, audio
onset strength, and a histogram-similarity match-cut proxy. Each analysis
function is lazy-imported and fail-open - it returns None (not a raised
exception) when its optional dependency (cv2/librosa) is unavailable or the
input is unreadable/inconclusive - so this module, and the whole transitions
feature, stays importable and disable-able without cv2/librosa installed.
The decision layer that turns these signals into a chosen transition type is
a later plan (04-04); this module only produces the raw signals.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


# Canonical transition-type enum consumed by the classifier (04-04) and the
# render fold (04-05); the render layer validates any transition-type string
# against this exact set before using it to key into a filter-string
# dispatch table (04-PATTERNS.md, 04-RESEARCH.md Security Domain V5).
TRANSITION_TYPES = frozenset({"cut", "crossfade", "whip_pan", "mask_wipe", "glitch", "match_cut"})


class TransitionError(ValueError):
    pass


def analyze_motion_at_boundary(frame_a_path: str, frame_b_path: str) -> float | None:
    """Dense optical-flow magnitude between two boundary frames (Farneback) -
    a proxy for how much on-screen motion happens right at the cut. Returns
    None (fail-open) if cv2 is unavailable or either frame is unreadable, so
    the caller treats the boundary as inconclusive (TRANS-03 fallback).
    """
    try:
        import cv2
    except ImportError:
        return None

    frame_a = cv2.imread(frame_a_path, cv2.IMREAD_GRAYSCALE)
    frame_b = cv2.imread(frame_b_path, cv2.IMREAD_GRAYSCALE)
    if frame_a is None or frame_b is None:
        return None

    flow = cv2.calcOpticalFlowFarneback(frame_a, frame_b, None, 0.5, 3, 15, 3, 5, 1.2, 0)
    magnitude, _ = cv2.cartToPolar(flow[..., 0], flow[..., 1])
    return float(magnitude.mean())


def analyze_similarity_at_boundary(frame_a_path: str, frame_b_path: str) -> float | None:
    """Histogram-correlation similarity between two boundary frames - a cheap
    match-cut proxy (visually continuous shots correlate near 1.0), avoiding
    a `scenedetect` dependency that would pull in plain opencv-python
    alongside opencv-python-headless (04-RESEARCH.md Anti-Patterns). Returns
    None (fail-open) if cv2 is unavailable or either frame is unreadable.
    """
    try:
        import cv2
    except ImportError:
        return None

    frame_a = cv2.imread(frame_a_path)
    frame_b = cv2.imread(frame_b_path)
    if frame_a is None or frame_b is None:
        return None

    hist_a = cv2.calcHist([frame_a], [0, 1, 2], None, [8, 8, 8], [0, 256, 0, 256, 0, 256])
    hist_b = cv2.calcHist([frame_b], [0, 1, 2], None, [8, 8, 8], [0, 256, 0, 256, 0, 256])
    cv2.normalize(hist_a, hist_a)
    cv2.normalize(hist_b, hist_b)
    return float(cv2.compareHist(hist_a, hist_b, cv2.HISTCMP_CORREL))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyze clip-boundary motion/audio/similarity signals for context-driven transitions"
    )
    parser.parse_args()
    print(json.dumps({"transition_types": sorted(TRANSITION_TYPES)}))


if __name__ == "__main__":
    main()
