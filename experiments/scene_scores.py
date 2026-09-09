"""Turns the `scene` field of a verdict file into a number the evaluator can rank.

Separate from the clipworthy score on purpose: they answer different questions and
deserve separate numbers. "Is this a shop screen" is nearly a lookup; "is this worth
clipping" is a judgement. Reporting one number for both hides which of the two the model
is actually good at.

    python experiments/scene_scores.py --verdicts vlm_eval.json --out scene_scores.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

# Only "action" counts as live. "idle" is the game running with nothing happening, which
# is not a shop screen but is not a moment either.
LIVE = {"action"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verdicts", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    rows = json.loads(Path(args.verdicts).read_text(encoding="utf-8"))
    scored, unparsed = [], 0
    counts: dict[str, int] = {}
    for row in rows:
        scene = (row.get("verdict") or {}).get("scene")
        scene = scene.strip().lower() if isinstance(scene, str) else "unparsed"
        counts[scene] = counts.get(scene, 0) + 1
        if scene == "unparsed":
            unparsed += 1
        scored.append({"stem": row["stem"], "start": row["start"],
                       "score": 1.0 if scene in LIVE else 0.0})

    Path(args.out).write_text(json.dumps(scored, ensure_ascii=False), encoding="utf-8")
    print(f"{len(scored)} окон, без разбора {unparsed}; " +
          ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
