from __future__ import annotations

import argparse
import dataclasses
import json
from pathlib import Path


@dataclasses.dataclass
class Candidate:
    id: int
    start: float
    end: float
    reason: str


def format_timecode(total_seconds: float) -> str:
    if total_seconds < 0:
        raise ValueError("total_seconds must be >= 0")
    total_seconds = int(total_seconds)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def merge_candidates(chunks_candidates: list[list[dict]]) -> list[Candidate]:
    flattened: list[dict] = []
    for chunk_candidates in chunks_candidates:
        flattened.extend(chunk_candidates)

    flattened.sort(key=lambda item: item["start"])

    return [
        Candidate(id=index + 1, start=item["start"], end=item["end"], reason=item["reason"])
        for index, item in enumerate(flattened)
    ]


def merge_candidate_files(candidates_dir: str) -> list[Candidate]:
    files = sorted(Path(candidates_dir).glob("*.json"))
    chunks_candidates = [json.loads(file.read_text(encoding="utf-8")) for file in files]
    return merge_candidates(chunks_candidates)


def render_candidates_markdown(candidates: list[Candidate]) -> str:
    if not candidates:
        return "# Candidates\n\nNo candidates found.\n"

    lines = ["# Candidates", ""]
    for candidate in candidates:
        start_tc = format_timecode(candidate.start)
        end_tc = format_timecode(candidate.end)
        lines.append(f"{candidate.id}. `{start_tc}` - `{end_tc}` — {candidate.reason}")
    return "\n".join(lines) + "\n"


def write_candidates_json(candidates: list[Candidate], path: str) -> None:
    Path(path).write_text(
        json.dumps([dataclasses.asdict(candidate) for candidate in candidates], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge per-chunk candidate files into CANDIDATES.md")
    parser.add_argument("candidates_dir", help="Directory containing candidates_chunk_NNNN.json files")
    parser.add_argument("output_markdown", help="Path to write CANDIDATES.md to")
    parser.add_argument("output_json", help="Path to write the machine-readable candidates.json to")
    args = parser.parse_args()

    candidates = merge_candidate_files(args.candidates_dir)
    Path(args.output_markdown).write_text(render_candidates_markdown(candidates), encoding="utf-8")
    write_candidates_json(candidates, args.output_json)
    print(f"{len(candidates)} candidates written to {args.output_markdown}")


if __name__ == "__main__":
    main()
