from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.config import METADATA_PLATFORMS


def render_risk_subblock(risk: dict) -> str:
    """Renders the advisory monetization-risk sub-block for one platform.

    Framed explicitly as advisory ("possible risk factors detected"), never
    as a certainty like "will be demonetized" - the ruleset can be wrong in
    either direction (see .planning/research/PITFALLS.md Pitfall 2). The
    last-checked date makes ruleset staleness visible to the creator.
    """
    flags = ", ".join(risk.get("flags") or []) or "none"
    return (
        "Monetization risk (advisory):\n"
        f"  Level: {risk.get('risk_level', 'none')}\n"
        f"  Flags: {flags}\n"
        f"  Last checked: {risk.get('last_checked', 'unknown')}"
    )


def render_metadata_text(platforms_data: dict) -> str:
    unknown = set(platforms_data) - METADATA_PLATFORMS
    if unknown:
        raise ValueError(f"unknown platform(s) in metadata: {sorted(unknown)}")

    sections = []
    for platform in sorted(platforms_data):
        fields = platforms_data[platform]
        header = f"=== {platform.upper()} ==="
        if platform == "youtube":
            body = (
                f"Title: {fields['title']}\n\n"
                f"Description:\n{fields['description']}\n\n"
                f"Tags: {', '.join(fields['tags'])}"
            )
        else:
            body = fields["caption"]
        if "risk" in fields:
            body = f"{body}\n\n{render_risk_subblock(fields['risk'])}"
        sections.append(f"{header}\n{body}")

    return "\n\n".join(sections) + "\n"


def write_metadata_file(platforms_data: dict, path: str) -> None:
    Path(path).write_text(render_metadata_text(platforms_data), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render per-platform clip metadata (title/description/tags/caption) into one text file"
    )
    parser.add_argument("platforms_data_json", help="Path to a JSON file with the per-platform metadata fields")
    parser.add_argument("output_path", help="Path to write the rendered metadata text file to")
    args = parser.parse_args()

    platforms_data = json.loads(Path(args.platforms_data_json).read_text(encoding="utf-8"))
    write_metadata_file(platforms_data, args.output_path)
    print(f"metadata written to {args.output_path}")


if __name__ == "__main__":
    main()
