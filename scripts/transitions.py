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


def analyze_audio_onset_at_boundary(audio_window_path: str) -> float | None:
    """Spectral-flux onset-strength peak within a short audio window around a
    boundary - a sharp transient scores higher than a steady/near-silent
    window. librosa is named explicitly in TRANS-01's own requirement text,
    so it's used here rather than audio_energy.py's ebur128 spike detector
    (which can't distinguish a transient attack from a sustained loud
    passage - 04-RESEARCH.md Alternatives Considered). Returns None
    (fail-open) if librosa is unavailable.
    """
    try:
        import librosa
    except ImportError:
        return None

    y, sr = librosa.load(audio_window_path, sr=None)
    onset_env = librosa.onset.onset_strength(y=y, sr=sr)
    return float(onset_env.max())


def extract_audio_window(
    video_path: str, center_time: float, duration: float, output_path: str, runner=subprocess.run
) -> str:
    """Slices a short mono wav centered on center_time via ffmpeg (-ss before
    -i for fast seek), the input analyze_audio_onset_at_boundary consumes.
    Builds the ffmpeg call as an argument list (never a shell string -
    T-04-INJ-A mitigation) and clamps the window start at 0.0 so a boundary
    near the start of the video doesn't request a negative timestamp.
    """
    start = max(0.0, center_time - duration / 2)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg", "-y",
        "-ss", str(start),
        "-i", video_path,
        "-t", str(duration),
        "-vn", "-ac", "1",
        output_path,
    ]
    result = runner(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise TransitionError(f"ffmpeg failed extracting audio window at {center_time}s: {result.stderr}")
    return output_path


def compute_signal_threshold(scores: list[float | None], percentile: float) -> float | None:
    """The adaptive per-video "strong signal" cutoff (D-02, 04-RESEARCH.md
    Pitfall 4): the given percentile of THIS video's own boundary-score
    distribution, not a fixed magic number - a score only counts as "strong"
    relative to how this particular video's boundaries actually scored.
    Drops None entries (inconclusive boundaries don't skew the distribution)
    and returns None when nothing is left to compute a percentile from -
    callers (classify_transition) treat a None threshold as inconclusive and
    fall back to "cut" (TRANS-03).

    Uses the same linear-interpolation percentile definition as
    numpy.percentile's default, implemented with stdlib only so this module
    stays importable without numpy/opencv/librosa (module import-safety
    contract, 04-03).
    """
    valid = sorted(score for score in scores if score is not None)
    if not valid:
        return None
    if len(valid) == 1:
        return valid[0]

    rank = (percentile / 100) * (len(valid) - 1)
    lower_index = int(rank)
    upper_index = min(lower_index + 1, len(valid) - 1)
    fraction = rank - lower_index
    return valid[lower_index] + (valid[upper_index] - valid[lower_index]) * fraction


def classify_transition(
    motion: float | None,
    audio: float | None,
    similarity: float | None,
    motion_threshold: float | None,
    audio_threshold: float | None,
    match_cut_similarity: float,
) -> str:
    """Maps the three boundary signals to exactly one member of
    TRANSITION_TYPES. This is a conservative, empirical, tunable decision
    tree (D-01/D-02) - D-04 explicitly leaves the exact signal-to-type
    assignment to the planner's discretion, so a materially different
    mapping is still "correct" as long as the conservative bias (weak or
    inconclusive signals default to "cut") is honored.

    Decision order (each branch below is only reached if every branch above
    it did not match, so the whole tree is mutually exclusive and every
    return value is a literal TRANSITION_TYPES member):

      0. motion, audio, motion_threshold, or audio_threshold is None ->
         "cut" (TRANS-03). Similarity is deliberately NOT included in this
         guard - it only ever adds a match_cut override below, it never
         gates the base decision, so a missing similarity score simply
         disables that override rather than forcing "cut".
      1. similarity >= match_cut_similarity -> "match_cut". Visual
         continuity wins outright regardless of motion/audio strength.
      2. strong motion AND strong audio -> "crossfade" (big combined
         signal on both channels).
      3. strong motion (regardless of audio, since case 2 already handled
         strong+strong) -> "whip_pan" (motion-led, no matching audio hit).
      4. moderate motion (>= half the strong threshold, but below it) AND
         strong audio -> "glitch" (an audio-led impact without enough
         motion for a full whip pan).
      5. moderate motion, audio not strong -> "mask_wipe" (a
         moderate-strength, visually discontinuous scene change - by this
         point similarity, if present, already scored below
         match_cut_similarity per step 1 not triggering).
      6. everything else (motion below the moderate floor) -> "cut" (D-01
         conservative default - a boundary with no more than weak motion
         never gets a fancy transition, no matter what audio is doing).
    """
    if motion is None or audio is None or motion_threshold is None or audio_threshold is None:
        return "cut"

    if similarity is not None and similarity >= match_cut_similarity:
        return "match_cut"

    strong_motion = motion >= motion_threshold
    strong_audio = audio >= audio_threshold
    moderate_motion = motion >= motion_threshold / 2

    if strong_motion and strong_audio:
        return "crossfade"
    if strong_motion:
        return "whip_pan"
    if moderate_motion and strong_audio:
        return "glitch"
    if moderate_motion:
        return "mask_wipe"
    return "cut"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyze clip-boundary motion/audio/similarity signals for context-driven transitions"
    )
    parser.parse_args()
    print(json.dumps({"transition_types": sorted(TRANSITION_TYPES)}))


if __name__ == "__main__":
    main()
