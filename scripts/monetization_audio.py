from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys

_SEVERITY_RANK = {"none": 0, "low": 1, "medium": 2, "high": 3}
_FPCALC_DURATION_RE = re.compile(r"^DURATION=(\d+)", re.MULTILINE)
_FPCALC_FINGERPRINT_RE = re.compile(r"^FINGERPRINT=(\S+)", re.MULTILINE)

# A fingerprint match alone is a heuristic hint, never certainty a platform
# will act on - always framed as "likely licensed audio" (PITFALLS.md Pitfall 2).
_DEFAULT_SEVERITY = "medium"


def generate_fingerprint(audio_path: str, runner=subprocess.run) -> dict | None:
    """Runs the local Chromaprint `fpcalc` binary and parses its duration +
    fingerprint. Purely local - no network call here (STACK.md: fingerprint
    generation is local, AcoustID lookup is the optional network half).

    Fails open: a missing binary or any subprocess failure prints a
    `[warn] ...` and returns None rather than raising, matching the
    CONVENTIONS fail-open tier used by audio_energy.py/diarize.py.
    """
    try:
        result = runner(["fpcalc", audio_path], capture_output=True, text=True, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError) as error:
        print(
            f"[warn] fpcalc unavailable ({error}); continuing with no audio-fingerprint flag this run",
            file=sys.stderr,
        )
        return None

    duration_match = _FPCALC_DURATION_RE.search(result.stdout)
    fingerprint_match = _FPCALC_FINGERPRINT_RE.search(result.stdout)
    if not duration_match or not fingerprint_match:
        print(f"[warn] could not parse fpcalc output for {audio_path}; skipping audio-fingerprint flag", file=sys.stderr)
        return None

    return {"duration": int(duration_match.group(1)), "fingerprint": fingerprint_match.group(1)}


def lookup_fingerprint(fingerprint: dict, api_key: str | None = None) -> dict | None:
    """Optional AcoustID network lookup - the ONLY network egress in this
    plan, off unless explicitly enabled by the caller. Fails open on any
    network error: a lookup failure just means "no confirmed match this
    run", never a pipeline abort.
    """
    if not api_key:
        print("[warn] no AcoustID API key provided; skipping network lookup, local fingerprint only", file=sys.stderr)
        return None
    try:
        import acoustid  # lazy import: optional dependency (CONVENTIONS lazy-import pattern)

        matches = list(
            acoustid.lookup(api_key, fingerprint["fingerprint"], fingerprint["duration"])
        )
    except Exception as error:
        print(f"[warn] AcoustID lookup failed ({error}); continuing with no confirmed match", file=sys.stderr)
        return None

    if not matches:
        return None
    return {"category": "copyrighted_audio", "confidence": "high"}


def to_risk_flag(match: dict, last_checked: str) -> dict:
    """Builds the advisory copyright-risk flag from a positive match, using
    the same field vocabulary (category/confidence/last_checked) Plan 01's
    keyword flags use, so the two merge cleanly (MONET-03)."""
    return {
        "category": match.get("category", "copyrighted_audio"),
        "confidence": match.get("confidence", "medium"),
        "last_checked": last_checked,
        "severity": match.get("severity", _DEFAULT_SEVERITY),
    }


def merge_audio_flag(risk_dict: dict, audio_flag: dict | None) -> dict:
    """Merges an audio-fingerprint copyright flag into an existing per-
    platform risk dict (Plan 01's shape) without dropping keyword flags,
    raising risk_level to the max of the two severities. A None audio_flag
    (no binary / no match / fail-open path) returns the risk dict unchanged.
    """
    if audio_flag is None:
        return risk_dict

    category = audio_flag["category"]
    flags = list(risk_dict.get("flags", []))
    if category not in flags:
        flags.append(category)

    flagged_spans = list(risk_dict.get("flagged_spans", []))
    flagged_spans.append({"start": None, "end": None, "reason": category, "matched_text": None})

    current_level = risk_dict.get("risk_level", "none")
    audio_severity = audio_flag.get("severity", _DEFAULT_SEVERITY)
    risk_level = audio_severity if _SEVERITY_RANK.get(audio_severity, 0) > _SEVERITY_RANK.get(current_level, 0) else current_level

    return {
        **risk_dict,
        "flags": flags,
        "flagged_spans": flagged_spans,
        "risk_level": risk_level,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fingerprint a clip's audio locally (Chromaprint/fpcalc) and produce an "
        "advisory copyrighted-audio flag. Advisory only - never blocks export."
    )
    parser.add_argument("audio_path", help="Path to the clip's audio/video file")
    parser.add_argument("--enable-lookup", action="store_true", help="Also perform the optional AcoustID network lookup")
    parser.add_argument("--acoustid-api-key", default=None, help="AcoustID API key (required if --enable-lookup is set)")
    parser.add_argument("--last-checked", default="unknown", help="Date stamp to attach to the produced flag")
    args = parser.parse_args()

    fingerprint = generate_fingerprint(args.audio_path)
    match = None
    if fingerprint and args.enable_lookup:
        match = lookup_fingerprint(fingerprint, api_key=args.acoustid_api_key)

    flag = to_risk_flag(match, args.last_checked) if match else None
    print(json.dumps(flag, ensure_ascii=False, indent=2))
    print(args.audio_path)


if __name__ == "__main__":
    main()
