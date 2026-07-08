from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCHEMA_VERSION = 1
DEFAULT_OUT_PATH = "work/_profile/style_profile.json"
TOP_N = 10


def load_analytics_cache(cache_path: str) -> list[dict]:
    """Reads youtube_analytics.py's own JSON cache. No network call, no OAuth
    of its own - the API pull stays entirely in youtube_analytics.py; this is
    a pure transform over its already-cached output (STYLE-01)."""
    path = Path(cache_path)
    if not path.exists():
        print(f"[warn] analytics cache not found at {cache_path}; deriving an empty style profile", file=sys.stderr)
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as error:
        print(f"[warn] could not read analytics cache ({error}); deriving an empty style profile", file=sys.stderr)
        return []


def _performance_signal(record: dict) -> float:
    # average_view_percentage is the strongest "this specific cut resonated"
    # signal when present; view_count is a reasonable fallback for channels
    # without retention data (e.g. Analytics API was unreachable - see
    # youtube_analytics.py's fail-open comment).
    if record.get("average_view_percentage") is not None:
        return float(record["average_view_percentage"])
    if record.get("view_count") is not None:
        return float(record["view_count"])
    return 0.0


def derive_profile(records: list[dict]) -> dict:
    """Derives a structured, concrete few-shot style profile from real
    per-video performance records (STYLE-02). Every example carries an
    actual title string plus its real performance signal - never a prose
    description of "the creator's style" (PITFALL 5). Fails open to a
    valid, empty, correctly-shaped profile when given no records."""
    ranked = sorted(
        (record for record in records if record.get("title")),
        key=_performance_signal,
        reverse=True,
    )

    naming_examples = [
        {"title": record["title"], "signal": _performance_signal(record)}
        for record in ranked[:TOP_N]
    ]

    moment_examples = [
        {"title": record["title"], "signal": _performance_signal(record)}
        for record in ranked[:TOP_N]
    ]

    return {
        "schema_version": SCHEMA_VERSION,
        "naming_examples": naming_examples,
        "moment_examples": moment_examples,
    }


def format_naming_examples_block(profile: dict, limit: int = TOP_N) -> str:
    """Renders a profile's naming_examples as a fixed, ranked few-shot text
    block for prompt injection (TAGS-03) - one numbered line per example,
    highest performance signal first, in the shape `{i}. "{title}" (signal:
    {signal})`. Fails open to the empty string when naming_examples is
    missing or empty - the caller (SKILL.md step 5) checks for an empty
    string, it must never raise on a missing key or empty list."""
    examples = profile.get("naming_examples") or []
    if not examples:
        return ""
    lines = [
        f'{i}. "{example["title"]}" (signal: {example["signal"]})'
        for i, example in enumerate(examples[:limit], start=1)
    ]
    return "\n".join(lines)


def write_profile(profile: dict, out_path: str | None = None) -> str:
    """Writes the profile as JSON to a gitignored cache location, defaulting
    to work/_profile/style_profile.json (STYLE-03) - this artifact contains
    real per-channel titles, so its only legitimate destination is the
    gitignored side of the tree (PITFALL 4 - the project's prior incident
    was exactly this kind of leak landing in a tracked file)."""
    target = Path(out_path) if out_path else Path(DEFAULT_OUT_PATH)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(target)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Derive a structured, concrete few-shot creator style profile "
        "(naming + moment-selection examples) from the youtube_analytics.py cache"
    )
    parser.add_argument("cache_path", help="Path to youtube_analytics.py's performance JSON cache")
    parser.add_argument("--out", default=DEFAULT_OUT_PATH, help="Output path (default: gitignored work/_profile/)")
    args = parser.parse_args()

    records = load_analytics_cache(args.cache_path)
    profile = derive_profile(records)
    output_path = write_profile(profile, args.out)
    print(output_path)


if __name__ == "__main__":
    main()
