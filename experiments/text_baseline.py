"""Signals that cost nothing because the transcript is already on disk.

Before asking whether a vision model earns its keep, the honest comparison is not
against nothing - it is against what the pipeline already has. The words in a window
are free, and some of them are plausibly predictive: people talk faster when something
is happening, swear when it goes wrong, and laugh when it is funny.

Each feature is reported on its own. Nothing is fitted or combined: sixty-one windows
cannot support choosing weights, and a weighted blend picked by looking at these same
sixty-one would score well here and mean nothing.

    python experiments/text_baseline.py --labels labels.json --out text_scores.json
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

LAUGHTER = re.compile(r"\b(ха+х*|хех|ахах\w*|ржу|угар\w*|лол)\b", re.IGNORECASE)
# Hype in the streamer/audience register, the same idea as config.analysis.hype_phrases.
HYPE = re.compile(r"\b(го\s+клип|клипани|база|имба|жиза|пиздец|ахуе\w+|охуе\w+|"
                  r"нихуя|ебать|блять|бля)\b", re.IGNORECASE)
QUESTION = re.compile(r"[?]")


def features(text: str, duration: float) -> dict[str, float]:
    words = text.split()
    count = len(words)
    per_second = count / duration if duration else 0.0
    swearing = len(HYPE.findall(text))
    return {
        "words_per_second": round(per_second, 4),
        "word_count": float(count),
        "laughter": float(len(LAUGHTER.findall(text))),
        "hype_hits": float(swearing),
        "hype_rate": round(swearing / count, 4) if count else 0.0,
        "questions": float(len(QUESTION.findall(text))),
        # Longest gap between words is not available from the joined text, so the
        # crude stand-in is how much of the window carries speech at all.
        "density": round(min(1.0, per_second / 3.0), 4),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    rows = json.loads(Path(args.labels).read_text(encoding="utf-8"))
    scored = []
    for row in rows:
        duration = float(row["end"]) - float(row["start"])
        scored.append({"stem": row["stem"], "start": row["start"],
                       **features(row.get("text", ""), duration)})
    Path(args.out).write_text(json.dumps(scored, ensure_ascii=False), encoding="utf-8")
    print(f"{len(scored)} окон, признаки: {', '.join(features('', 1.0))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
