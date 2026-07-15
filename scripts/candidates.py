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
    # 1-5, set by candidate-finding subagents only when speaker-labeled
    # segments are available (config.diarization.enabled); None otherwise.
    coherence: int | None = None
    # Free-form gameplay/theme description (D-01), set only once step 5's
    # trim decision marks this candidate sub_threshold.
    tag: str | None = None
    # True once step 5's tightest reasonable trim is still below
    # config.clip.min_seconds.
    sub_threshold: bool = False
    # Set by the same-session grouping pass; None means ungrouped.
    group_id: int | None = None
    # True only when sub_threshold and no group formed this run (D-03).
    unmatched: bool = False


def format_timecode(total_seconds: float) -> str:
    if total_seconds < 0:
        raise ValueError("total_seconds must be >= 0")
    total_seconds = int(total_seconds)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def compute_moment_budget(
    source_seconds: float, rate_per_hour: float = 3.0, minimum: int = 1
) -> int:
    """Phase 10 global top-N budget for auto-select mode ("сделай топ моменты
    по твоему выбору"): how many standalone shorts to render from a WHOLE
    recording = rate_per_hour * source_hours, rounded, never below `minimum`
    when there is any footage. This is a global cap, not per-hour-of-output:
    a 3h recording at rate 3 yields 9 total, drawn from anywhere across those
    3 hours (even all from the last 10 minutes if those were the best). Returns
    0 only for empty/zero-length input.
    """
    if source_seconds <= 0:
        return 0
    hours = source_seconds / 3600.0
    return max(minimum, round(rate_per_hour * hours))


def select_top_moments(
    candidates: list[dict], budget: int, *, score_key: str = "score"
) -> list[dict]:
    """Keep the top `budget` candidates by score (desc), tie-broken by earlier
    start then original order for determinism. A candidate missing a score is
    treated as 0 (sorts last). budget <= 0 or no candidates returns []. The kept
    subset is returned in chronological order so downstream numbering/output
    stays timeline-ordered. Operates on plain dicts (candidates.json rows), so
    SKILL.md can call it via a `python -c` one-liner after assigning scores.
    """
    if budget <= 0 or not candidates:
        return []
    indexed = list(enumerate(candidates))
    indexed.sort(
        key=lambda pair: (
            -float(pair[1].get(score_key, 0) or 0),
            pair[1].get("start", 0.0),
            pair[0],
        )
    )
    kept = [candidate for _, candidate in indexed[:budget]]
    kept.sort(key=lambda candidate: candidate.get("start", 0.0))
    return kept


def merge_candidates(chunks_candidates: list[list[dict]]) -> list[Candidate]:
    flattened: list[dict] = []
    for chunk_candidates in chunks_candidates:
        flattened.extend(chunk_candidates)

    flattened.sort(key=lambda item: item["start"])

    return [
        Candidate(
            id=index + 1,
            start=item["start"],
            end=item["end"],
            reason=item["reason"],
            coherence=item.get("coherence"),
            tag=item.get("tag"),
            sub_threshold=item.get("sub_threshold", False),
            group_id=item.get("group_id"),
            unmatched=item.get("unmatched", False),
        )
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
        line = f"{candidate.id}. `{start_tc}` - `{end_tc}` — {candidate.reason}"
        if candidate.coherence is not None:
            line += f" (целостность: {candidate.coherence}/5)"
        lines.append(line)
    return "\n".join(lines) + "\n"


def append_compilation_sections_markdown(path: str, groups: list[dict], unmatched: list[dict]) -> None:
    # Dict-based (not Candidate-typed) so this round-trips trivially through a
    # JSON file when called from SKILL.md via a `python -c` one-liner (mirrors
    # style_profile.format_naming_examples_block's invocation style) — no
    # dataclass reconstruction needed at the call site.
    if not groups and not unmatched:
        return

    lines: list[str] = []
    if groups:
        lines.append("")
        lines.append("## Sub-Threshold Compilations")
        lines.append("")
        for group in groups:
            member_ids = ", ".join(f"#{member.get('id', '?')}" for member in group["members"])
            lines.append(
                f"- Candidates {member_ids} grouped into compilation: "
                f"{group.get('title', '(untitled compilation)')}"
            )

    if unmatched:
        lines.append("")
        lines.append("## Unmatched Sub-Threshold")
        lines.append("")
        for candidate in unmatched:
            start_tc = format_timecode(candidate["start"])
            end_tc = format_timecode(candidate["end"])
            reason = candidate.get("reason", "(no reason given)")
            tag = candidate.get("tag", "(untagged)")
            lines.append(f"- `{start_tc}` - `{end_tc}` — {reason} (tag: {tag})")

    existing = Path(path).read_text(encoding="utf-8")
    Path(path).write_text(existing + "\n".join(lines) + "\n", encoding="utf-8")


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
