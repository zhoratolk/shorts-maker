from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

_EMPTY_WORDLIST: dict = {"updated": "unknown", "normalize": {}, "ru": [], "en": []}


def load_wordlist(path: str) -> dict:
    """Loads the RU+EN profanity wordlist from YAML.

    Fail-open: a missing/unreadable/malformed wordlist file warns to stderr
    and returns an empty-but-valid wordlist (updated="unknown", no stems)
    instead of raising - masking is additive, never a hard dependency of
    the pipeline (D-04, mirrors scripts/monetization_risk.py::load_rules).
    """
    try:
        raw_text = Path(path).read_text(encoding="utf-8")
        data = yaml.safe_load(raw_text) or {}
    except Exception as error:
        print(
            f"[warn] could not load profanity wordlist from {path} ({error}); "
            "continuing with an empty wordlist (no masking will be applied)",
            file=sys.stderr,
        )
        return dict(_EMPTY_WORDLIST)
    data.setdefault("updated", "unknown")
    return data


def normalize_word(word: str, normalize_cfg: dict) -> str:
    """Case-folds, applies leetspeak substitutions, strips user-typed
    censor characters, then collapses runs of 3+ identical characters to
    one - this normalization (not literal-spelling enumeration) is what
    makes common obfuscated spellings tractable (D-02).
    """
    text = word.lower()
    for src, dst in (normalize_cfg.get("substitutions") or {}).items():
        text = text.replace(src, dst)
    strip_chars = normalize_cfg.get("strip_chars", "")
    if strip_chars:
        text = re.sub(f"[{re.escape(strip_chars)}]", "", text)
    if normalize_cfg.get("collapse_repeats", False):
        text = re.sub(r"(.)\1{2,}", r"\1", text)
    return text


def compile_patterns(wordlist: dict) -> list[re.Pattern]:
    """Compiles one word-boundary stem regex per wordlist root.

    Every root is re.escape()d before compiling - a wordlist data-file
    value is never treated as a raw regex fragment, so a malformed or
    malicious entry (e.g. "(a+)+") can never cause catastrophic
    backtracking (ASVS V5 / ReDoS guard).
    """
    roots = [entry["root"] for lang in ("ru", "en") for entry in (wordlist.get(lang) or [])]
    return [re.compile(rf"\b{re.escape(root)}\w*", re.IGNORECASE) for root in roots]


def find_profane_spans(
    words: list[dict],
    wordlist: dict,
    pad_seconds: float = 0.08,
    clip_duration: float | None = None,
    max_spans: int | None = None,
) -> list[tuple[float, float]]:
    """Finds profane word spans in a clip-relative Whisper word list.

    words: {"word","start","end"} entries already in clip-relative,
    post-jumpcut-remap seconds (the caller runs jumpcuts.remap_words first
    - see 07-RESEARCH.md Pattern 2; this function never reimplements that
    remap, so a word dropped by a jump cut is simply absent here).

    Returns merged, padded (pad_seconds each side), clip-bound-clamped,
    3-decimal-rounded (start, end) spans. Padding compensates for Whisper
    word-timestamp drift (Pitfall 2). If the number of merged spans exceeds
    max_spans, fails open: warns to stderr and returns [] rather than ever
    blocking a downstream render (Pitfall 5).
    """
    normalize_cfg = wordlist.get("normalize") or {}
    patterns = compile_patterns(wordlist)

    raw_spans: list[tuple[float, float]] = []
    for word in words:
        token = normalize_word(word["word"].strip(".,!?:;\"'()"), normalize_cfg)
        if any(pattern.search(token) for pattern in patterns):
            start = max(0.0, word["start"] - pad_seconds)
            end = word["end"] + pad_seconds
            if clip_duration is not None:
                end = min(end, clip_duration)
            raw_spans.append((round(start, 3), round(end, 3)))

    if not raw_spans:
        return []

    raw_spans.sort()
    merged = [raw_spans[0]]
    for start, end in raw_spans[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))

    if max_spans is not None and len(merged) > max_spans:
        print(
            f"[warn] {len(merged)} profanity spans exceeds cap of {max_spans}; "
            "skipping masking for this clip (no spans will be masked)",
            file=sys.stderr,
        )
        return []

    return merged


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Detect profane word spans in a clip-relative Whisper word list. "
        "Fail-open: a missing/malformed wordlist never blocks a downstream render."
    )
    parser.add_argument("words_json", help="Path to a JSON list of {word,start,end} (clip-relative seconds)")
    parser.add_argument(
        "--wordlist", default="data/profanity_wordlist.yaml", help="Path to the profanity wordlist YAML file"
    )
    parser.add_argument("--pad-seconds", type=float, default=0.08, help="Padding applied to each side of a span")
    parser.add_argument("--clip-duration", type=float, default=None, help="Clip duration in seconds, for clamping")
    parser.add_argument(
        "--max-spans", type=int, default=None, help="Fail-open cap on merged span count (see Pitfall 5)"
    )
    args = parser.parse_args()

    words = json.loads(Path(args.words_json).read_text(encoding="utf-8"))
    wordlist = load_wordlist(args.wordlist)
    spans = find_profane_spans(
        words, wordlist, pad_seconds=args.pad_seconds, clip_duration=args.clip_duration, max_spans=args.max_spans
    )

    print(json.dumps(spans, ensure_ascii=False))
    print(args.words_json)


if __name__ == "__main__":
    main()
