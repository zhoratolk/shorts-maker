from __future__ import annotations

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
