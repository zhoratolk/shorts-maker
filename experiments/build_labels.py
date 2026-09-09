"""The evaluation set: windows a human already judged, positive and negative.

Nothing here can be measured without labels, and the labels exist already - they were
made by hand, twice, on two full recordings. Every window that became a clip is a
positive. Everything that was read and passed over is a negative, and that judgement is
real evidence: both recordings were gone through end to end, not sampled.

Negatives come in two kinds and are kept apart on purpose:

  "dead"    - drawn from a span known to be inventory management and shopping (05.09,
              roughly 8400-12600 s). If a signal cannot separate these, it separates
              nothing.
  "passed"  - drawn uniformly from everywhere else that is not a positive. Harder and
              noisier: a window here may well contain something worth clipping that the
              human missed, so a detector penalised on these is being penalised partly
              for finding what the human did not. Reported separately for that reason.

    python experiments/build_labels.py --out experiments/data/labels.json
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

TRANSCRIPTS = "/srv/media/clips/transcripts"
WORK = "/srv/shorts-maker/work"

SESSIONS = {
    "2026-09-05 16-09-34-joined-18": {"duration": 15725.0, "dead": (8400.0, 12600.0)},
    "2026-09-06 15-30-19-joined-12": {"duration": 9905.0, "dead": None},
}

WINDOW = 25.0
EDGE = 90.0          # nothing from the very start or end of a recording
DEAD_NEGATIVES = 20
PASSED_NEGATIVES = 25
SEED = 20260909


def load_words(stem: str) -> list[dict]:
    data = json.loads(Path(f"{TRANSCRIPTS}/{stem}.json").read_text(encoding="utf-8"))
    return [w for segment in data["segments"] for w in segment.get("words", [])]


def text_in(words: list[dict], start: float, end: float) -> str:
    return " ".join(w["word"].strip() for w in words if start <= w["start"] < end)


def positives(stem: str) -> list[tuple[float, float]]:
    """The chosen moments, as windows the same width as every other window.

    Centred on the moment rather than taken as its raw span. The spans in a plan run
    31 s on average against the 25 s of a sampled negative, and a wider window holds
    more words by construction - which made raw word count look like a strong detector
    (AUC 0.855) when part of what it detected was the label being longer. Equal widths
    remove the question instead of arguing about it.
    """
    plan = json.loads(Path(f"{WORK}/{stem}/PLAN.json").read_text(encoding="utf-8"))
    windows = []
    for entry in plan:
        middle = (float(entry["start"]) + float(entry["end"])) / 2
        windows.append((round(middle - WINDOW / 2, 1), round(middle + WINDOW / 2, 1)))
    return windows


def overlaps(a: tuple[float, float], spans: list[tuple[float, float]]) -> bool:
    return any(a[0] < end and start < a[1] for start, end in spans)


def sample_negatives(rng: random.Random, taken: list[tuple[float, float]],
                     low: float, high: float, count: int) -> list[tuple[float, float]]:
    """Windows inside [low, high) that touch nothing already taken."""
    chosen: list[tuple[float, float]] = []
    for _ in range(count * 200):
        if len(chosen) == count:
            break
        start = round(rng.uniform(low, high - WINDOW), 1)
        window = (start, start + WINDOW)
        if overlaps(window, taken) or overlaps(window, chosen):
            continue
        chosen.append(window)
    return sorted(chosen)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    rng = random.Random(SEED)
    rows: list[dict] = []

    for stem, meta in SESSIONS.items():
        words = load_words(stem)
        chosen = positives(stem)
        for start, end in chosen:
            rows.append({"stem": stem, "start": start, "end": end,
                         "label": 1, "kind": "clip",
                         "text": text_in(words, start, end)})

        taken = list(chosen)
        if meta["dead"]:
            low, high = meta["dead"]
            for start, end in sample_negatives(rng, taken, low, high, DEAD_NEGATIVES):
                rows.append({"stem": stem, "start": start, "end": end,
                             "label": 0, "kind": "dead",
                             "text": text_in(words, start, end)})
                taken.append((start, end))

        for start, end in sample_negatives(
            rng, taken, EDGE, meta["duration"] - EDGE,
            PASSED_NEGATIVES // len(SESSIONS) + PASSED_NEGATIVES % len(SESSIONS),
        ):
            rows.append({"stem": stem, "start": start, "end": end,
                         "label": 0, "kind": "passed",
                         "text": text_in(words, start, end)})
            taken.append((start, end))

    rows.sort(key=lambda r: (r["stem"], r["start"]))
    Path(args.out).write_text(json.dumps(rows, ensure_ascii=False, indent=1),
                              encoding="utf-8")
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["kind"]] = counts.get(row["kind"], 0) + 1
    print(f"{len(rows)} окон: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
