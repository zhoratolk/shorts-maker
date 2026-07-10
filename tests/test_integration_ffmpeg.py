"""Real-ffmpeg smoke tests - no mocked subprocess runner.

Unit tests elsewhere assert the exact ffmpeg command string; these actually
run it, so a broken filter_complex/expression syntax (which a string
assertion can't catch) fails here instead of only showing up on a real
multi-hour recording. Requires ffmpeg/ffprobe on PATH - skips entirely
otherwise. Marked `integration`: pytest -m "not integration" skips this file.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from scripts.frames import extract_frames
from scripts.jumpcuts import compute_keep_segments
from scripts.render import build_profanity_mask_filter, render_clip
from scripts.silence import find_pauses

FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not FFMPEG_AVAILABLE, reason="ffmpeg/ffprobe not found on PATH"),
]


def probe(path) -> dict:
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


SRC_WIDTH = 640
SRC_HEIGHT = 360
SRC_DURATION = 6.0  # 2s tone, 2s silent gap, 2s tone


@pytest.fixture(scope="module")
def test_video(tmp_path_factory) -> Path:
    """~6s synthetic video: a 2s tone, a 2s silent gap, then a 2s tone - real
    signal for jump-cut, silence-detection, denoise/loudnorm, and
    frame-extraction tests to work with, without needing a real recording.

    Deliberately small/low-fps/short: the `noise` grain filter is genuinely
    CPU-heavy per frame (that's real render.py cost, not a test bug) -
    keeping the source small keeps this file's total runtime reasonable
    while still exercising the real ffmpeg filter graphs end to end.
    Explicit yuv420p matters too - without it ffmpeg picked yuv444p here,
    which is ~3x the pixel data and made libx264 encode dramatically slower.
    """
    out_dir = tmp_path_factory.mktemp("integration_media")
    video_path = out_dir / "source.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", (
                "sine=frequency=440:duration=2[a1];"
                "aevalsrc=0:duration=2[s1];"
                "sine=frequency=440:duration=2[a2];"
                "[a1][s1][a2]concat=n=3:v=0:a=1"
            ),
            "-f", "lavfi", "-i", f"testsrc=size={SRC_WIDTH}x{SRC_HEIGHT}:duration={SRC_DURATION}:rate=15",
            "-shortest", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac",
            str(video_path), "-loglevel", "error",
        ],
        check=True,
    )
    return video_path


def test_vignette_and_grain_render_correct_dimensions(test_video, tmp_path):
    plan_entry = {"start": 0.0, "end": 1.5, "crop_style": "zoom"}
    output_path = tmp_path / "out_vignette.mp4"

    render_clip(
        str(test_video), str(output_path), plan_entry,
        video_duration=SRC_DURATION, src_width=SRC_WIDTH, src_height=SRC_HEIGHT,
        vignette=True, grain_strength=20,
    )

    info = probe(output_path)
    video_stream = next(s for s in info["streams"] if s["codec_type"] == "video")
    assert video_stream["width"] == 1080
    assert video_stream["height"] == 1920


def test_punch_zoom_renders_correct_dimensions(test_video, tmp_path):
    plan_entry = {"start": 0.0, "end": 2.0, "crop_style": "zoom", "punch_zoom_at": 0.5}
    output_path = tmp_path / "out_punchzoom.mp4"

    render_clip(
        str(test_video), str(output_path), plan_entry,
        video_duration=SRC_DURATION, src_width=SRC_WIDTH, src_height=SRC_HEIGHT,
    )

    info = probe(output_path)
    video_stream = next(s for s in info["streams"] if s["codec_type"] == "video")
    assert video_stream["width"] == 1080
    assert video_stream["height"] == 1920


def test_jumpcut_splices_out_silence_gap(test_video, tmp_path):
    # audio is 2s tone, 2s silence, 2s tone - cut [2, 4) out of [0, 6)
    plan_entry = {
        "start": 0.0, "end": SRC_DURATION, "crop_style": "zoom",
        "keep_segments": [[0.0, 2.0], [4.0, SRC_DURATION]],
    }
    output_path = tmp_path / "out_jumpcut.mp4"

    render_clip(
        str(test_video), str(output_path), plan_entry,
        video_duration=SRC_DURATION, src_width=SRC_WIDTH, src_height=SRC_HEIGHT,
    )

    info = probe(output_path)
    duration = float(info["format"]["duration"])
    assert 3.5 < duration < 4.5  # ~4s = 2+2, the 2s pause is gone


def test_combined_features_render_together(test_video, tmp_path):
    """jump cuts + punch-zoom + denoise + loudnorm + vignette + grain, all in
    one render_clip call - the exact combination verified manually during
    development, now pinned as a regression test."""
    plan_entry = {
        "start": 0.0, "end": SRC_DURATION, "crop_style": "zoom",
        "keep_segments": [[0.0, 2.0], [4.0, SRC_DURATION]],
        "punch_zoom_at": 0.5,
    }
    output_path = tmp_path / "out_combo.mp4"

    render_clip(
        str(test_video), str(output_path), plan_entry,
        video_duration=SRC_DURATION, src_width=SRC_WIDTH, src_height=SRC_HEIGHT,
        fade_seconds=0.3, denoise=True, loudnorm=True, vignette=True, grain_strength=15,
    )

    info = probe(output_path)
    video_stream = next(s for s in info["streams"] if s["codec_type"] == "video")
    assert video_stream["width"] == 1080
    assert video_stream["height"] == 1920
    duration = float(info["format"]["duration"])
    assert 3.5 < duration < 4.5


def test_forced_crossfade_transition_renders_playable_output(test_video, tmp_path):
    """Forces a boundary_transitions=['crossfade'] entry (no cv2/librosa
    involved - the type is picked directly, not via select_boundary_transitions)
    to exercise 04-05's xfade/acrossfade sequential-fold on a real ffmpeg
    binary. A string assertion on build_jumpcut_command's output can't catch
    a malformed xfade offset/filter syntax - only a real encode can."""
    # audio/video is 2s tone, 2s silent gap, 2s tone - the boundary between
    # [0, 2] and [4, 6] straddles that real 2s gap, far above the default
    # min_overlap_seconds (0.12s), so the fold path borrows real overlap.
    plan_entry = {
        "start": 0.0, "end": SRC_DURATION, "crop_style": "zoom",
        "keep_segments": [[0.0, 2.0], [4.0, SRC_DURATION]],
        "boundary_transitions": ["crossfade"],
    }
    output_path = tmp_path / "out_transition.mp4"

    command = render_clip(
        str(test_video), str(output_path), plan_entry,
        video_duration=SRC_DURATION, src_width=SRC_WIDTH, src_height=SRC_HEIGHT,
    )

    assert "-filter_complex" in command
    filter_complex = command[command.index("-filter_complex") + 1]
    assert "xfade=transition=fade" in filter_complex  # crossfade's xfade node, not a plain concat

    info = probe(output_path)
    video_stream = next(s for s in info["streams"] if s["codec_type"] == "video")
    audio_stream = next(s for s in info["streams"] if s["codec_type"] == "audio")
    assert video_stream["width"] == 1080
    assert video_stream["height"] == 1920
    assert audio_stream is not None  # acrossfade produced a playable audio stream


def test_compilation_of_non_contiguous_members_renders_playable_output(test_video, tmp_path):
    """Three separately-seeked, non-contiguous member windows drawn from the
    fixture's own 6s span - genuinely exercises independent per-member
    -ss/-i seeks (build_compilation_command) rather than one contiguous
    decode window. The 6s fixture is reused rather than adding a new,
    larger synthetic video, since what's under test - multiple independent
    inputs stitched together - doesn't require the members to be minutes
    apart, only non-contiguous."""
    plan_entry = {
        "type": "compilation",
        "crop_style": "zoom",
        "segments": [
            {"start": 0.0, "end": 1.0},
            {"start": 2.0, "end": 3.0},
            {"start": 4.5, "end": 5.5},
        ],
    }
    output_path = tmp_path / "out_compilation.mp4"

    command = render_clip(
        str(test_video), str(output_path), plan_entry,
        video_duration=SRC_DURATION, src_width=SRC_WIDTH, src_height=SRC_HEIGHT,
    )

    assert command.count("-i") == 3

    info = probe(output_path)
    video_stream = next(s for s in info["streams"] if s["codec_type"] == "video")
    audio_stream = next(s for s in info["streams"] if s["codec_type"] == "audio")
    assert video_stream["width"] == 1080
    assert video_stream["height"] == 1920
    assert audio_stream is not None  # playable output


def test_silence_detection_finds_real_pause(test_video):
    pauses = find_pauses(str(test_video), min_duration=0.3)

    assert len(pauses) >= 1
    assert any(1.5 < pause["start"] < 2.5 for pause in pauses)


def test_frame_extraction_writes_real_jpegs(test_video, tmp_path):
    output_dir = tmp_path / "frames"

    paths = extract_frames(str(test_video), [0.0, 3.0], str(output_dir), prefix="chunk")

    assert len(paths) == 2
    for path in paths:
        data = Path(path).read_bytes()
        assert len(data) > 0
        assert data[:2] == b"\xff\xd8"  # JPEG magic bytes


def test_full_pipeline_silence_detect_to_jumpcut_render(test_video, tmp_path):
    """The actual chain SKILL.md orchestrates: detect pauses, decide what to
    keep, render the spliced result - each step feeding the next for real."""
    pauses = find_pauses(str(test_video), min_duration=0.3)
    keep_segments = compute_keep_segments(0.0, SRC_DURATION, pauses, max_pause_seconds=0.5)
    assert len(keep_segments) == 2  # confirms the ~2s silence was detected and will be cut

    plan_entry = {"start": 0.0, "end": SRC_DURATION, "crop_style": "zoom", "keep_segments": keep_segments}
    output_path = tmp_path / "out_full_pipeline.mp4"

    render_clip(
        str(test_video), str(output_path), plan_entry,
        video_duration=SRC_DURATION, src_width=SRC_WIDTH, src_height=SRC_HEIGHT,
    )

    info = probe(output_path)
    duration = float(info["format"]["duration"])
    assert 3.5 < duration < 4.5


def measure_mean_volume(video_path, start: float, end: float, runner=subprocess.run) -> float:
    """Isolates [start, end) via atrim then reads its mean_volume off
    ffmpeg's volumedetect filter - the exact technique live-verified in
    07-RESEARCH.md Pattern 1 (baseline -21.1dB, ducked -33.3dB, outside the
    window unchanged). volumedetect prints its measurement to stderr at the
    default (info) log level, so this intentionally omits -loglevel error.
    Uses the project's injectable runner=subprocess.run shape (matches
    scripts/render.py::probe_video) rather than an inline subprocess call.
    """
    result = runner(
        ["ffmpeg", "-i", str(video_path), "-af", f"atrim=start={start}:end={end},volumedetect", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    match = re.search(r"mean_volume:\s*(-?[\d.]+)\s*dB", result.stderr)
    assert match, f"could not parse mean_volume from ffmpeg volumedetect output: {result.stderr}"
    return float(match.group(1))


def test_profanity_mask_measurably_ducks_loudness_inside_span(test_video, tmp_path):
    """AUDIO-02: a real ffmpeg render with profanity_spans set is measurably
    quieter inside the masked span than outside it - audio keeps flowing
    (not a hard silence cut), just ducked+garbled. Renders through
    render_clip (the real production path build_ffmpeg_command/
    build_profanity_mask_filter feed into, not just a string assertion -
    those already exist in tests/test_render.py) and measures with the
    exact volumedetect isolation technique live-verified in 07-RESEARCH.md
    Pattern 1."""
    plan_entry = {
        "start": 0.0, "end": 2.0, "crop_style": "zoom",
        "profanity_spans": [[0.5, 1.0]],
    }
    output_path = tmp_path / "out_profanity_mask.mp4"

    render_clip(
        str(test_video), str(output_path), plan_entry,
        video_duration=SRC_DURATION, src_width=SRC_WIDTH, src_height=SRC_HEIGHT,
    )

    # test_video's [0, 2) window is a plain 440Hz tone (see the fixture's own
    # docstring) - both windows below sit fully inside the masked [0.5, 1.0]
    # span or fully outside it, on the same tone so only the mask differs.
    inside_volume = measure_mean_volume(output_path, 0.6, 0.9)
    outside_volume = measure_mean_volume(output_path, 1.2, 1.8)

    assert inside_volume < outside_volume - 5.0, (
        f"masked span is not measurably quieter than outside it: "
        f"inside={inside_volume}dB outside={outside_volume}dB"
    )
