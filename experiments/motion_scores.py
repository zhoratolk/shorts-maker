"""Turns motion profiles into one score per labelled window, so the free signal can be
scored by the same evaluator as everything else.

The profile is on a fixed 20-second grid over the whole recording; the labels are
25-second windows that start wherever the moment starts. A window's score is the mean
over every profile bucket it touches - weighted by how much of the bucket it touches,
because a window that clips two seconds off a bucket should not inherit all of it.

    python experiments/motion_scores.py --labels labels.json \\
        --profile "stem=motion_0905.json" --profile "stem2=motion_0906.json" --out motion_scores.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def window_score(buckets: list[dict], start: float, end: float, width: float) -> float | None:
    """Overlap-weighted mean of the profile over [start, end)."""
    total = weight = 0.0
    for bucket in buckets:
        low, high = bucket["at"], bucket["at"] + width
        overlap = min(end, high) - max(start, low)
        if overlap <= 0:
            continue
        total += bucket["mean_diff"] * overlap
        weight += overlap
    return round(total / weight, 4) if weight else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels", required=True)
    parser.add_argument("--profile", action="append", required=True,
                        metavar="STEM=PATH", help="можно повторять")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    profiles: dict[str, tuple[list[dict], float]] = {}
    for pair in args.profile:
        stem, _, path = pair.partition("=")
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        profiles[stem] = (data["windows"], float(data["window"]))

    rows = json.loads(Path(args.labels).read_text(encoding="utf-8"))
    scored, missing = [], 0
    for row in rows:
        if row["stem"] not in profiles:
            missing += 1
            continue
        buckets, width = profiles[row["stem"]]
        score = window_score(buckets, row["start"], row["end"], width)
        if score is None:
            missing += 1
            continue
        scored.append({"stem": row["stem"], "start": row["start"], "score": score})

    Path(args.out).write_text(json.dumps(scored, ensure_ascii=False), encoding="utf-8")
    print(f"{len(scored)} окон озвучено, {missing} без профиля")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
