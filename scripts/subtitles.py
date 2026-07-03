from __future__ import annotations

import argparse
import json
from pathlib import Path


def group_words_into_cues(words: list[dict], max_words: int = 4) -> list[dict]:
    cues = []
    for i in range(0, len(words), max_words):
        group = words[i : i + max_words]
        cues.append(
            {
                "start": group[0]["start"],
                "end": group[-1]["end"],
                "text": " ".join(word["word"].strip() for word in group),
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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Group clip-relative word timestamps into short synced subtitle cues"
    )
    parser.add_argument("words_json", help="Path to a JSON file with a list of {word, start, end} objects")
    parser.add_argument("output_srt", help="Path to write the rendered .srt file to")
    parser.add_argument("--max-words", type=int, default=4, help="Max words per subtitle cue")
    args = parser.parse_args()

    words = json.loads(Path(args.words_json).read_text(encoding="utf-8"))
    cues = group_words_into_cues(words, max_words=args.max_words)
    Path(args.output_srt).write_text(render_srt(cues), encoding="utf-8")
    print(f"{len(cues)} cues written to {args.output_srt}")


if __name__ == "__main__":
    main()
