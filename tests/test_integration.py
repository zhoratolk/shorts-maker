import json
from pathlib import Path

from scripts.candidates import merge_candidate_files, render_candidates_markdown, write_candidates_json
from scripts.chunker import split_into_chunks, write_chunks
from scripts.render import render_clip


def test_full_pipeline_on_synthetic_transcript(tmp_path):
    segments = [
        {"start": 0.0, "end": 3.0, "text": "intro"},
        {"start": 65.0, "end": 70.0, "text": "a really funny joke about the boss fight"},
        {"start": 130.0, "end": 134.0, "text": "another great reaction moment"},
    ]

    # Step 1: chunk the synthetic transcript (1-minute windows)
    chunks = split_into_chunks(segments, chunk_minutes=1)
    chunk_paths = write_chunks(chunks, str(tmp_path / "chunks"))
    assert len(chunk_paths) == 3

    # Step 2: simulate per-chunk subagent output — one candidate for chunks 1 and 2, none for chunk 0
    candidates_dir = tmp_path / "candidates"
    candidates_dir.mkdir()
    (candidates_dir / "candidates_chunk_0000.json").write_text(json.dumps([]), encoding="utf-8")
    (candidates_dir / "candidates_chunk_0001.json").write_text(
        json.dumps([{"start": 65.0, "end": 70.0, "reason": "funny joke about the boss fight"}]),
        encoding="utf-8",
    )
    (candidates_dir / "candidates_chunk_0002.json").write_text(
        json.dumps([{"start": 130.0, "end": 134.0, "reason": "great reaction moment"}]),
        encoding="utf-8",
    )

    # Step 3: merge into CANDIDATES.md + candidates.json
    candidates = merge_candidate_files(str(candidates_dir))
    assert len(candidates) == 2
    markdown = render_candidates_markdown(candidates)
    assert "funny joke about the boss fight" in markdown
    assert "great reaction moment" in markdown

    candidates_json_path = tmp_path / "candidates.json"
    write_candidates_json(candidates, str(candidates_json_path))

    # Step 4: simulate approval of both, and a refine pass producing PLAN.json
    plan = [
        {"start": 64.5, "end": 71.0, "crop_style": "zoom", "output_filename": "clip_0001.mp4"},
        {"start": 129.5, "end": 135.0, "crop_style": "pad", "output_filename": "clip_0002.mp4"},
    ]

    # Step 5: render each plan entry against a fake ffmpeg runner
    rendered_commands = []

    class FakeResult:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_runner(command, capture_output, text):
        rendered_commands.append(command)
        return FakeResult()

    for entry in plan:
        render_clip(
            "video.mp4", entry["output_filename"], entry,
            video_duration=200.0, src_width=1920, src_height=1080,
            runner=fake_runner,
        )

    assert len(rendered_commands) == 2
    assert rendered_commands[0][-1] == "clip_0001.mp4"
    assert rendered_commands[1][-1] == "clip_0002.mp4"
