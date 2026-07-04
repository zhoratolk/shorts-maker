from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

# Punctuation Whisper attaches to word boundaries (commas, periods, quotes,
# dashes, ellipses) - stripped from displayed captions because a comma/period
# sitting alone in a 3-4 word burst reads as visual noise, not a sentence.
# Internal characters (apostrophes/hyphens inside a word) are left alone.
_PUNCTUATION_CHARS = ",.!?:;\"'«»„–—…()[]{}"
_STRIP_PUNCTUATION_RE = re.compile(
    rf"^[{re.escape(_PUNCTUATION_CHARS)}\s]+|[{re.escape(_PUNCTUATION_CHARS)}\s]+$"
)


def strip_display_punctuation(word: str) -> str:
    return _STRIP_PUNCTUATION_RE.sub("", word)


def group_words_into_cues(words: list[dict], max_words: int = 4, strip_punctuation: bool = True) -> list[dict]:
    cues = []
    for i in range(0, len(words), max_words):
        group = words[i : i + max_words]
        if strip_punctuation:
            group = [{**word, "word": strip_display_punctuation(word["word"])} for word in group]
        cues.append(
            {
                "start": group[0]["start"],
                "end": group[-1]["end"],
                "text": " ".join(word["word"].strip() for word in group if word["word"].strip()),
                "words": group,
            }
        )
    return cues


def format_srt_timestamp(seconds: float) -> str:
    total_ms = round(seconds * 1000)
    hours, remainder_ms = divmod(total_ms, 3_600_000)
    minutes, remainder_ms = divmod(remainder_ms, 60_000)
    secs, ms = divmod(remainder_ms, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def render_srt(cues: list[dict]) -> str:
    lines = []
    for index, cue in enumerate(cues, start=1):
        lines.append(str(index))
        lines.append(f"{format_srt_timestamp(cue['start'])} --> {format_srt_timestamp(cue['end'])}")
        lines.append(cue["text"])
        lines.append("")
    return "\n".join(lines) + ("\n" if lines else "")


def parse_srt_timestamp(timestamp: str) -> float:
    hours, minutes, rest = timestamp.split(":")
    seconds, ms = rest.split(",")
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(ms) / 1000


def parse_srt(text: str) -> list[dict]:
    cues = []
    for block in text.strip().split("\n\n"):
        lines = block.splitlines()
        if len(lines) < 3:
            continue
        start_str, end_str = lines[1].split(" --> ")
        cues.append(
            {
                "start": parse_srt_timestamp(start_str),
                "end": parse_srt_timestamp(end_str),
                "text": "\n".join(lines[2:]),
            }
        )
    return cues


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Group clip-relative word timestamps into short synced subtitle cues"
    )
    parser.add_argument("words_json", help="Path to a JSON file with a list of {word, start, end} objects")
    parser.add_argument("output_srt", help="Path to write the rendered .srt file to")
    parser.add_argument("--max-words", type=int, default=4, help="Max words per subtitle cue")
    parser.add_argument(
        "--strip-punctuation", action=argparse.BooleanOptionalAction, default=True,
        help="Strip leading/trailing punctuation from displayed caption words (default: on)",
    )
    args = parser.parse_args()

    words = json.loads(Path(args.words_json).read_text(encoding="utf-8"))
    cues = group_words_into_cues(words, max_words=args.max_words, strip_punctuation=args.strip_punctuation)
    Path(args.output_srt).write_text(render_srt(cues), encoding="utf-8")
    print(f"{len(cues)} cues written to {args.output_srt}")


if __name__ == "__main__":
    main()
