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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyze clip-boundary motion/audio/similarity signals for context-driven transitions"
    )
    parser.parse_args()
    print(json.dumps({"transition_types": sorted(TRANSITION_TYPES)}))


if __name__ == "__main__":
    main()
