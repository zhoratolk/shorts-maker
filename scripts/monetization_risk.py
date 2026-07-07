from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

_SEVERITY_RANK = {"none": 0, "low": 1, "medium": 2, "high": 3}
_CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}

_EMPTY_RULES: dict = {"updated": "unknown", "youtube": {}, "tiktok": {}, "instagram": {}}


def load_rules(rules_path: str) -> dict:
    """Loads the per-platform monetization ruleset from YAML.

    Fail-open: a missing/unreadable/malformed rules file warns to stderr and
    returns an empty-but-valid ruleset (no categories, updated="unknown")
    instead of raising - the flag is additive, not a hard dependency of the
    pipeline (see .planning/research/PITFALLS.md Pitfall 2, CONVENTIONS fail-open tier).
    """
    try:
        raw_text = Path(rules_path).read_text(encoding="utf-8")
        rules = yaml.safe_load(raw_text) or {}
    except Exception as error:
        print(
            f"[warn] could not load monetization rules from {rules_path} ({error}); "
            "continuing with an empty ruleset (risk_level will be 'none')",
            file=sys.stderr,
        )
        return dict(_EMPTY_RULES)
    rules.setdefault("updated", "unknown")
    return rules


def _empty_risk(platform: str, last_checked: str) -> dict:
    return {
        "platform": platform,
        "risk_level": "none",
        "flags": [],
        "flagged_spans": [],
        "confidence": "low",
        "last_checked": last_checked,
    }


def score_transcript(text: str, platform: str, rules: dict) -> dict:
    """Scores a transcript against one platform's rule table.

    Matching is case-insensitive substring/word-boundary against each
    category's keyword list. risk_level is the max severity of any matched
    category (none when nothing matched). confidence reflects the matched
    rule's own declared confidence. This is advisory-only framing - "possible
    risk factors detected", never a claim the platform will actually act on
    it, and it never returns a pass/fail boolean.

    Never raises on normal input.
    """
    last_checked = rules.get("updated", "unknown")
    platform_rules = rules.get(platform) or {}
    if not text or not platform_rules:
        return _empty_risk(platform, last_checked)

    lowered = text.lower()
    matched_flags: list[str] = []
    flagged_spans: list[dict] = []
    best_severity = "none"
    best_confidence = "low"

    for category, spec in platform_rules.items():
        keywords = spec.get("keywords") or []
        severity = spec.get("severity", "low")
        confidence = spec.get("confidence", "low")
        for keyword in keywords:
            pattern = re.compile(re.escape(keyword.lower()))
            for match in pattern.finditer(lowered):
                matched_flags.append(category)
                flagged_spans.append(
                    {"start": match.start(), "end": match.end(), "reason": category, "matched_text": keyword}
                )
                if _SEVERITY_RANK.get(severity, 0) > _SEVERITY_RANK.get(best_severity, 0):
                    best_severity = severity
                if _CONFIDENCE_RANK.get(confidence, 0) > _CONFIDENCE_RANK.get(best_confidence, 0):
                    best_confidence = confidence

    # De-duplicate flags while keeping first-seen order (multiple keyword
    # hits in the same category should surface once in the flags list).
    seen: set[str] = set()
    unique_flags = []
    for flag in matched_flags:
        if flag not in seen:
            seen.add(flag)
            unique_flags.append(flag)

    return {
        "platform": platform,
        "risk_level": best_severity,
        "flags": unique_flags,
        "flagged_spans": flagged_spans,
        "confidence": best_confidence if unique_flags else "low",
        "last_checked": last_checked,
    }


def score_all_platforms(text: str, rules: dict) -> dict:
    """Scores a transcript against every platform present in the ruleset."""
    platforms = [key for key in rules.keys() if key != "updated"]
    return {platform: score_transcript(text, platform, rules) for platform in platforms}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Score a transcript against the per-platform monetization-risk ruleset. "
        "Advisory only - never blocks export."
    )
    parser.add_argument("transcript_path", help="Path to a transcript .txt or .json file")
    parser.add_argument(
        "--rules", default="data/monetization_rules.yaml", help="Path to the monetization rules YAML file"
    )
    parser.add_argument(
        "--platform", default="all", help="Platform to score against, or 'all' for every ruleset platform"
    )
    args = parser.parse_args()

    raw_text = Path(args.transcript_path).read_text(encoding="utf-8")
    try:
        data = json.loads(raw_text)
        text = data.get("text") if isinstance(data, dict) else raw_text
        if isinstance(data, dict) and "segments" in data and not text:
            text = " ".join(segment.get("text", "") for segment in data["segments"])
    except json.JSONDecodeError:
        text = raw_text

    rules = load_rules(args.rules)

    if args.platform == "all":
        result: dict = score_all_platforms(text, rules)
    else:
        result = score_transcript(text, args.platform, rules)

    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(args.transcript_path)


if __name__ == "__main__":
    main()
