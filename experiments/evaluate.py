"""Scores a detector against the hand-made labels, the same way for every detector.

One file so that the free motion signal, the local vision model and the cloud one are
never compared on differently-computed numbers - which is the usual way a comparison
like this quietly answers the wrong question.

Reports AUC plus precision/recall at each threshold, and reports the two kinds of
negative apart: "dead" windows (inventory and shopping, a signal that cannot separate
these separates nothing) and "passed" windows (everything else the human read and did
not pick, where a false positive may be the detector finding something the human
missed rather than the detector being wrong).

    python experiments/evaluate.py --labels labels.json --scores motion.json --name движение
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def auc(pairs: list[tuple[float, int]]) -> float:
    """Probability a random positive outranks a random negative; ties count as half.

    Computed by counting pairs rather than by trapezoid over a curve: with sixty
    windows the curve is coarse enough that its area depends on how the steps are
    drawn, and the pair count has no such freedom.
    """
    positives = [score for score, label in pairs if label == 1]
    negatives = [score for score, label in pairs if label == 0]
    if not positives or not negatives:
        return float("nan")
    wins = 0.0
    for p in positives:
        for n in negatives:
            wins += 1.0 if p > n else 0.5 if p == n else 0.0
    return wins / (len(positives) * len(negatives))


def at_threshold(pairs: list[tuple[float, int]], threshold: float) -> dict:
    predicted = [(score >= threshold, label) for score, label in pairs]
    tp = sum(1 for flag, label in predicted if flag and label == 1)
    fp = sum(1 for flag, label in predicted if flag and label == 0)
    fn = sum(1 for flag, label in predicted if not flag and label == 1)
    return {
        "threshold": round(threshold, 4),
        "precision": round(tp / (tp + fp), 3) if tp + fp else 0.0,
        "recall": round(tp / (tp + fn), 3) if tp + fn else 0.0,
        "kept": tp + fp,
    }


def evaluate(labels: list[dict], scores: dict[tuple[str, float], float], name: str) -> dict:
    rows = []
    missing = 0
    for row in labels:
        key = (row["stem"], round(row["start"], 1))
        if key not in scores:
            missing += 1
            continue
        rows.append({"kind": row["kind"], "label": row["label"], "score": scores[key]})

    pairs = [(r["score"], r["label"]) for r in rows]
    dead = [(r["score"], r["label"]) for r in rows if r["kind"] in ("clip", "dead")]
    passed = [(r["score"], r["label"]) for r in rows if r["kind"] in ("clip", "passed")]

    candidates = sorted({round(score, 4) for score, _ in pairs})
    sweep = [at_threshold(pairs, t) for t in candidates]

    return {
        "name": name,
        "windows": len(rows),
        "missing": missing,
        "positives": sum(1 for _, label in pairs if label == 1),
        "auc_all": round(auc(pairs), 3),
        "auc_vs_dead": round(auc(dead), 3),
        "auc_vs_passed": round(auc(passed), 3),
        "sweep": sweep,
    }


def load_scores(path: str, field: str) -> dict[tuple[str, float], float]:
    """(stem, start) -> score, from either a verdict file or a motion profile."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    out: dict[tuple[str, float], float] = {}
    for row in data:
        value = row.get(field)
        if value is None and "verdict" in row:
            value = row["verdict"].get(field)
        if value is None:
            continue
        try:
            out[(row["stem"], round(float(row["start"]), 1))] = float(value)
        except (TypeError, ValueError):
            continue
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels", required=True)
    parser.add_argument("--scores", required=True)
    parser.add_argument("--field", default="score")
    parser.add_argument("--name", default="сигнал")
    parser.add_argument("--out")
    args = parser.parse_args()

    labels = json.loads(Path(args.labels).read_text(encoding="utf-8"))
    report = evaluate(labels, load_scores(args.scores, args.field), args.name)

    print(f"{report['name']}: {report['windows']} окон "
          f"({report['positives']} положительных), пропущено {report['missing']}")
    print(f"  AUC всего {report['auc_all']}  против dead {report['auc_vs_dead']}  "
          f"против passed {report['auc_vs_passed']}")
    print(f"  {'порог':>8} {'точность':>9} {'полнота':>8} {'оставлено':>10}")
    for step in report["sweep"]:
        print(f"  {step['threshold']:>8} {step['precision']:>9} "
              f"{step['recall']:>8} {step['kept']:>10}")
    if args.out:
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1),
                                  encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
