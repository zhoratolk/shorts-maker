"""Finds the stretches of a recording where nothing clippable can happen.

A four-hour session is not uniformly interesting, and the uninteresting part is not
scattered - it comes in blocks. On 2026-09-05, seventy of two hundred and sixty-two
minutes were two chunks of back-to-back shopping and inventory sorting. Those seventy
minutes still had to be read end to end to find nothing in them, and reading is the
scarce resource in this pipeline: the GPU is idle while a human (or a model) goes
through a transcript.

This finds those blocks from the transcript alone, with a regular expression, in
milliseconds.

Why not from the picture. That was the obvious idea and it was measured first: sample
frames across the recording and ask a vision model whether the screen shows a shop, an
inventory or a map. It does not work here, and the reason is specific rather than
technical - in Barotrauma the crew keeps an inventory panel open during combat as
readily as during shopping, so 47% of frames in the LIVE part of the recording show an
interface. Screen contents carry almost no information about whether the session is in
a dead stretch (AUC 0.55 raw, 0.59 smoothed over eighteen minutes).

What the players are TALKING about carries almost all of it. The same eighteen minutes
of smoothing over the share of shopping vocabulary separates the same spans at AUC
0.966. A dead zone in a co-op game is a conversational state, not a visual one.

The vocabulary is game-specific and deliberately so - see VOCABULARIES. It was written
by reading one Barotrauma session, which means it is fitted to that game and needs
checking against a new recording before being trusted on one.

**Span edges are soft by five to nine minutes**, because eighteen minutes of smoothing is
what makes the detection reliable and blurs the boundary by the same amount. Checked by
hand on 2026-09-05: the core of every flagged span is real trading, and the first and
last few minutes of one are ordinary play that happened to sit next to it. So this is a
tool for deciding what to read LAST, not for cutting spans out of a recording - skipping
a flagged span outright throws away a few live minutes at each end.

    python scripts/dead_zones.py transcript.json
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

# Sampled in two-minute buckets: short enough that a span boundary lands within a
# minute or so, long enough that one passing mention of money does not make a bucket.
STEP_SECONDS = 120.0

# Smoothed over nine buckets - eighteen minutes. A dead zone is defined by lasting:
# a single bucket of shop talk is a crew deciding something mid-dive, while eighteen
# minutes of it is the session having stopped. Measured over 1, 3, 5, 7 and 9 buckets;
# the separation rises monotonically (0.879, 0.929, 0.945, 0.960, 0.966) and flattens.
SMOOTH_BUCKETS = 9

# At this share of shopping words, 34 of 35 dead buckets are caught for 14 false
# positives out of 97 live ones. Raising it to 0.030 trades recall (77%) for precision
# (3% false). The lower value is the right default: this gates what gets READ, and a
# false positive costs a skipped minute while a false negative costs nothing at all.
DEFAULT_THRESHOLD = 0.020

VOCABULARIES = {
    # Barotrauma: buying, selling, crafting, hauling crates, upgrading the sub.
    "barotrauma": re.compile(
        r"куп|прода|ящик|крафт|переработ|пушк|снаряд|стерж|закуп|ресурс|"
        r"инвентар|рюкзак|прокач|улучш|деньг|тысяч|стоит|торгаш", re.IGNORECASE),
}


def bucket_ratios(words: list[dict], pattern: re.Pattern,
                  step: float = STEP_SECONDS) -> list[tuple[float, float]]:
    """(bucket start, share of words matching the vocabulary) over the recording."""
    counts: dict[int, list[int]] = {}
    for word in words:
        index = int(float(word["start"]) // step)
        entry = counts.setdefault(index, [0, 0])
        entry[0] += 1
        if pattern.search(word["word"]):
            entry[1] += 1
    return [(index * step, hits / total if total else 0.0)
            for index, (total, hits) in sorted(counts.items())]


def smoothed(series: list[tuple[float, float]], buckets: int) -> list[tuple[float, float]]:
    """Centred moving average, shortened at the ends rather than padded.

    Padding with zeros would make the first and last buckets of every recording look
    livelier than they are, which is exactly where a session's shopping usually sits.
    """
    out = []
    half = buckets // 2
    for i, (at, _) in enumerate(series):
        low, high = max(0, i - half), min(len(series), i + half + 1)
        out.append((at, sum(v for _, v in series[low:high]) / (high - low)))
    return out


def merge_spans(marked: list[float], step: float, gap: float = 1.5) -> list[tuple[float, float]]:
    """Adjacent flagged buckets joined into spans; a single gap does not split one."""
    spans: list[list[float]] = []
    for at in marked:
        if spans and at - spans[-1][1] <= step * gap:
            spans[-1][1] = at
        else:
            spans.append([at, at])
    return [(low, high + step) for low, high in spans]


def dead_spans(words: list[dict], game: str = "barotrauma",
               step: float = STEP_SECONDS, buckets: int = SMOOTH_BUCKETS,
               threshold: float = DEFAULT_THRESHOLD) -> list[tuple[float, float]]:
    """Spans of the recording where the crew is shopping rather than playing."""
    pattern = VOCABULARIES.get(game)
    if pattern is None:
        raise ValueError(f"нет словаря для игры {game!r}: есть {', '.join(VOCABULARIES)}")
    series = smoothed(bucket_ratios(words, pattern, step), buckets)
    return merge_spans([at for at, value in series if value >= threshold], step)


def words_of(transcript_path: str) -> list[dict]:
    data = json.loads(Path(transcript_path).read_text(encoding="utf-8"))
    return [word for segment in data["segments"] for word in segment.get("words", [])]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("transcript")
    parser.add_argument("--game", default="barotrauma")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    spans = dead_spans(words_of(args.transcript), args.game, threshold=args.threshold)
    if args.json:
        print(json.dumps([{"start": a, "end": b} for a, b in spans], ensure_ascii=False))
        return 0
    if not spans:
        print("мёртвых зон не найдено")
        return 0
    total = sum(b - a for a, b in spans)
    for a, b in spans:
        print(f"{a / 60:7.1f}-{b / 60:6.1f} мин  ({(b - a) / 60:4.1f} мин)")
    print(f"итого {total / 60:.0f} мин можно не читать")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
