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
    pad_seconds: float = 0.2,
    onset_seconds: float = 0.0,
    clip_duration: float | None = None,
    max_spans: int | None = None,
) -> list[tuple[float, float]]:
    """Finds profane word spans in a clip-relative Whisper word list.

    words: {"word","start","end"} entries already in clip-relative,
    post-jumpcut-remap seconds (the caller runs jumpcuts.remap_words first
    - see 07-RESEARCH.md Pattern 2; this function never reimplements that
    remap, so a word dropped by a jump cut is simply absent here).

    onset_seconds delays a span's start by that many seconds into the word
    (no pad_seconds subtraction on that side), so the word's own onset
    plays clean and only the remainder is masked. Empirically, <= ~0.12s
    preserves STT-defeat; 0.20/0.28 let faster-whisper recover the word
    from its onset + context. If onset_seconds >= the word's own duration
    (degenerate case), the whole word is masked (start = word start) rather
    than producing an empty/inverted span. onset_seconds == 0 (default)
    reproduces the original pad_seconds-on-both-sides behavior exactly.

    pad_seconds is clamped against the immediate neighbor words: the padded
    end can never cross into the next word's own start, and (when
    onset_seconds == 0) the padded start can never cross into the previous
    word's own end. Without this, a flat pad_seconds tuned to compensate for
    Whisper's worst-case timestamp drift on one clip (Pitfall 2) overshoots
    on fast back-to-back speech elsewhere and the beep visibly eats into the
    next word instead of just covering the drift gap.

    Returns merged, padded (pad_seconds each side unless onset_seconds > 0
    shifts the start), neighbor- and clip-bound-clamped, 3-decimal-rounded
    (start, end) spans. If the number of merged spans exceeds max_spans,
    fails open: warns to stderr and returns [] rather than ever blocking a
    downstream render (Pitfall 5).
    """
    normalize_cfg = wordlist.get("normalize") or {}
    patterns = compile_patterns(wordlist)

    raw_spans: list[tuple[float, float]] = []
    for index, word in enumerate(words):
        token = normalize_word(word["word"].strip(".,!?:;\"'()"), normalize_cfg)
        if any(pattern.search(token) for pattern in patterns):
            if onset_seconds > 0:
                word_duration = word["end"] - word["start"]
                if onset_seconds >= word_duration:
                    start = word["start"]
                else:
                    start = word["start"] + onset_seconds
            else:
                start = max(0.0, word["start"] - pad_seconds)
                if index > 0:
                    start = max(start, min(words[index - 1]["end"], word["start"]))
            end = word["end"] + pad_seconds
            if index + 1 < len(words):
                end = max(word["end"], min(end, words[index + 1]["start"]))
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


_SUBTITLE_WORD_RE = re.compile(r"\w+", re.UNICODE)


def mask_token(token: str, keep_ratio: float = 0.4) -> str:
    """Partially masks a single word: keeps the leading keep_ratio fraction of
    the characters and replaces the rest with '*', preserving length so the
    word stays recognizable without being spelled out (e.g. keep_ratio=0.4:
    'хуй' -> 'х**', 'пидорас' -> 'пид****'). Always leaves at least one visible
    char and masks at least one char; a 1-char token is returned unchanged
    (nothing meaningful to mask).
    """
    length = len(token)
    if length <= 1:
        return token
    keep = max(1, round(length * keep_ratio))
    keep = min(keep, length - 1)  # always mask at least one trailing char
    return token[:keep] + "*" * (length - keep)


def _is_profane_token(token: str, patterns: list[re.Pattern], normalize_cfg: dict) -> bool:
    normalized = normalize_word(token.strip(".,!?:;\"'()"), normalize_cfg)
    return bool(normalized) and any(pattern.search(normalized) for pattern in patterns)


def mask_cues(cues: list[dict], wordlist: dict, keep_ratio: float = 0.4) -> list[dict]:
    """Masks profane words in subtitle cue text AND per-word karaoke tokens.

    The karaoke overlay in render.build_ass_content re-emits each
    cue["words"][i]["word"] independently of cue["text"], so masking only the
    joined text would leave the highlighted word spelled out - both layers must
    be masked. Uses the SAME wordlist/normalization as the audio mask
    (find_profane_spans) so a word bleeped in audio is also masked on screen.

    Fail-open: an empty wordlist (missing/malformed file) compiles to no
    patterns and returns the cues unchanged. Returns NEW cue dicts; input cues
    are never mutated.
    """
    normalize_cfg = wordlist.get("normalize") or {}
    patterns = compile_patterns(wordlist)
    if not patterns:
        return cues

    def mask_str(text: str) -> str:
        return _SUBTITLE_WORD_RE.sub(
            lambda match: mask_token(match.group(0), keep_ratio)
            if _is_profane_token(match.group(0), patterns, normalize_cfg)
            else match.group(0),
            text,
        )

    masked: list[dict] = []
    for cue in cues:
        new_cue = dict(cue)
        new_cue["text"] = mask_str(cue["text"])
        if "words" in cue:
            new_cue["words"] = [{**word, "word": mask_str(word["word"])} for word in cue["words"]]
        masked.append(new_cue)
    return masked


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Detect profane word spans in a clip-relative Whisper word list. "
        "Fail-open: a missing/malformed wordlist never blocks a downstream render."
    )
    parser.add_argument("words_json", help="Path to a JSON list of {word,start,end} (clip-relative seconds)")
    parser.add_argument(
        "--wordlist", default="data/profanity_wordlist.yaml", help="Path to the profanity wordlist YAML file"
    )
    parser.add_argument("--pad-seconds", type=float, default=0.2, help="Padding applied to each side of a span")
    parser.add_argument(
        "--onset-seconds",
        type=float,
        default=0.0,
        help="Delay a span's start this many seconds into the word (keep <= ~0.12 to preserve STT-defeat)",
    )
    parser.add_argument("--clip-duration", type=float, default=None, help="Clip duration in seconds, for clamping")
    parser.add_argument(
        "--max-spans", type=int, default=None, help="Fail-open cap on merged span count (see Pitfall 5)"
    )
    parser.add_argument(
        "--risk-rules", default=None,
        help="Also mask platform-risk phrases from this ruleset (data/monetization_rules.yaml). "
        "Their spans are merged into the output AND the matched words are starred out in the "
        "words file in place, since a burned-in caption is read as readily as the audio.",
    )
    parser.add_argument(
        "--risk-platform", default="youtube", help="Which platform's rules --risk-rules scores against"
    )
    parser.add_argument(
        "--risk-categories", default="age_restriction",
        help="Comma-separated rule categories to mask. Only categories that are a hard publishing "
        "problem belong here - advisory ones (hate_speech) are for the creator to judge, not to bleep.",
    )
    parser.add_argument("--keep-ratio", type=float, default=0.4, help="Fraction of a starred word left visible")
    args = parser.parse_args()

    words = json.loads(Path(args.words_json).read_text(encoding="utf-8"))
    wordlist = load_wordlist(args.wordlist)

    # Risky phrases are resolved BEFORE the profanity pass so both kinds of
    # mask land in one list: a clip has exactly one set of spans to bleep, and
    # deciding it in one place is what stops one of them being forgotten.
    risk_spans: list[list[float]] = []
    if args.risk_rules:
        # This is the one place a script reaches for a sibling module, so it is
        # also the one place `python scripts/profanity.py ...` can fail on the
        # import: running a file directly puts scripts/ on sys.path, not the
        # repo root, and `scripts` is then not a package. Tests never saw it -
        # pytest sets pythonpath=["."]. Put the repo root on the path first.
        repo_root = str(Path(__file__).resolve().parent.parent)
        if repo_root not in sys.path:
            sys.path.insert(0, repo_root)
        from scripts.monetization_risk import censor_words, find_risky_spans, load_rules

        risk_spans, hit_indices = find_risky_spans(
            words,
            load_rules(args.risk_rules),
            platform=args.risk_platform,
            categories=tuple(c.strip() for c in args.risk_categories.split(",") if c.strip()),
            pad_seconds=args.pad_seconds,
        )
        if hit_indices:
            censor_words(words, hit_indices, keep_ratio=args.keep_ratio)
            Path(args.words_json).write_text(
                json.dumps(words, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            starred = ", ".join(words[i]["word"].strip() for i in hit_indices)
            print(f"[risk] masked in audio and captions: {starred}", file=sys.stderr)

    spans = find_profane_spans(
        words,
        wordlist,
        pad_seconds=args.pad_seconds,
        onset_seconds=args.onset_seconds,
        clip_duration=args.clip_duration,
        max_spans=args.max_spans,
    )
    spans = sorted([list(span) for span in spans] + risk_spans)

    print(json.dumps(spans, ensure_ascii=False))
    print(args.words_json)


if __name__ == "__main__":
    main()
