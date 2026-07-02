from __future__ import annotations

import argparse
import dataclasses
import json
from pathlib import Path


@dataclasses.dataclass
class Chunk:
    index: int
    start: float
    end: float
    segments: list[dict]


def split_into_chunks(segments: list[dict], chunk_minutes: int) -> list[Chunk]:
    if chunk_minutes <= 0:
        raise ValueError("chunk_minutes must be > 0")
    if not segments:
        return []

    window_seconds = chunk_minutes * 60
    chunks: list[Chunk] = []
    current_segments: list[dict] = []
    current_window_start = 0.0
    window_index = 0

    for segment in segments:
        while segment["start"] >= current_window_start + window_seconds:
            if current_segments:
                chunks.append(
                    Chunk(
                        index=window_index,
                        start=current_segments[0]["start"],
                        end=current_segments[-1]["end"],
                        segments=current_segments,
                    )
                )
                window_index += 1
                current_segments = []
            current_window_start += window_seconds
        current_segments.append(segment)

    if current_segments:
        chunks.append(
            Chunk(
                index=window_index,
                start=current_segments[0]["start"],
                end=current_segments[-1]["end"],
                segments=current_segments,
            )
        )

    return chunks


def write_chunks(chunks: list[Chunk], output_dir: str) -> list[str]:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    written_paths = []
    for chunk in chunks:
        file_path = output_path / f"chunk_{chunk.index:04d}.json"
        file_path.write_text(
            json.dumps(dataclasses.asdict(chunk), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        written_paths.append(str(file_path))
    return written_paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Split a cached transcript into analysis chunks")
    parser.add_argument("transcript_json", help="Path to a transcript JSON produced by transcribe.py")
    parser.add_argument("output_dir", help="Directory to write chunk_NNNN.json files into")
    parser.add_argument("--chunk-minutes", type=int, default=35)
    args = parser.parse_args()

    transcript = json.loads(Path(args.transcript_json).read_text(encoding="utf-8"))
    chunks = split_into_chunks(transcript["segments"], args.chunk_minutes)
    paths = write_chunks(chunks, args.output_dir)
    for path in paths:
        print(path)


if __name__ == "__main__":
    main()
