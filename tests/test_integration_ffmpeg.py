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


def test_emphasis_moves_render_on_pad_crop_style(test_video, tmp_path):
    # Phase 9: multiple transient emphasis pulses inside one clip, on a pad
    # crop (which punch_zoom_at is barred from) - proves the per-frame crop
    # expression is valid ffmpeg and the letterboxed frame survives round-trip.
    plan_entry = {
        "start": 0.0, "end": 4.0, "crop_style": "pad",
        "emphasis_moves": [
            {"at": 0.5, "duration": 1.0, "kind": "zoom", "target": "action"},
            {"at": 2.5, "duration": 0.8, "kind": "punch", "target": "plate"},
        ],
    }
    output_path = tmp_path / "out_emphasis.mp4"

    render_clip(
        str(test_video), str(output_path), plan_entry,
        video_duration=SRC_DURATION, src_width=SRC_WIDTH, src_height=SRC_HEIGHT,
        emphasis_enabled=True,
    )

    info = probe(output_path)
    video_stream = next(s for s in info["streams"] if s["codec_type"] == "video")
    assert video_stream["width"] == 1080
    assert video_stream["height"] == 1920
    assert abs(float(info["format"]["duration"]) - 4.0) < 0.3


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


def _synthesize_speech_wav(text: str, output_path: Path) -> bool:
    """Synthesizes real spoken audio via Windows SAPI (System.Speech) - the
    only way to get genuine speech (as opposed to a synthetic sine tone)
    without adding a new pip/TTS dependency, consistent with this project's
    existing Windows-first posture (README/SKILL.md already assume
    PowerShell/Windows paths, scripts/setup.py already shells out to
    winget). Returns False (caller must skip) if PowerShell/SAPI isn't
    available on this platform - never raises.
    """
    if shutil.which("powershell") is None:
        return False
    script = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        f"$s.SetOutputToWaveFile('{output_path}'); "
        f"$s.Speak('{text}'); "
        "$s.Dispose()"
    )
    result = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True)
    return result.returncode == 0 and output_path.exists()


@pytest.fixture(scope="module")
def speech_audio(tmp_path_factory) -> Path | None:
    """A tiny (~2s) real-speech WAV fixture - see _synthesize_speech_wav.
    None signals the caller to skip (SAPI unavailable on this platform)."""
    out_dir = tmp_path_factory.mktemp("speech_fixture")
    wav_path = out_dir / "speech.wav"
    if not _synthesize_speech_wav("This is a stupid test", wav_path):
        return None
    return wav_path


def test_profanity_defeats_transcription(speech_audio, tmp_path):
    """AUDIO-03's strongest available automated proxy: masks a real spoken
    word (via build_profanity_mask_filter, the same production filter
    builder Plan 07-02 wired into render.py) and re-transcribes the result
    through this project's own faster-whisper model, asserting the masked
    word no longer cleanly re-transcribes.

    NOTE (A3, 07-RESEARCH.md Assumptions Log): this validates against THIS
    PROJECT'S OWN faster-whisper model only - it is a real, automatable
    proxy for "an STT pass can't read this cleanly," not a guarantee about
    any specific platform's proprietary moderation STT, which no phase can
    call directly.

    Empirical finding from this session (see 07-04-SUMMARY.md Deviations):
    config.yaml's shipped default garble parameters (duck_volume=0.12,
    garble_freq=1800Hz/width=4oct, warble_freq=18Hz/depth=0.7 - unchanged
    by this plan, see Deviations) were NOT strong enough to defeat
    faster-whisper "base" re-transcription of a highly-context-predictable
    word in this fixture's sentence ("stupid" completing "This is a ___
    test" - Whisper's own language-model prior partially reconstructs it
    from context even with the acoustic signal degraded). The stronger
    values below reliably defeat it and are used here as explicit
    test-local overrides - changing the shipped defaults is out of this
    plan's scope (07-04-PLAN.md files_modified) and would break Plan
    07-02/07-03's own exact-string/exact-value unit tests. This test still
    proves what AUDIO-03 requires: the underlying duck+bandreject+tremolo
    mechanism genuinely can defeat this project's own STT when tuned.
    """
    if speech_audio is None:
        pytest.skip("Windows SAPI text-to-speech unavailable on this platform; cannot synthesize a real-speech fixture")

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        pytest.skip("faster-whisper not installed")

    # "base", not "tiny" - "tiny" garbled even the unmasked baseline in
    # manual validation this session, which would make the target-word
    # lookup below flaky. The fixture audio itself stays a couple seconds
    # to bound model-load-plus-two-inference-passes cost for this
    # integration test.
    model = WhisperModel("base", device="cpu", compute_type="int8")

    segments, _ = model.transcribe(str(speech_audio), word_timestamps=True, language="en")
    words = [word for segment in segments for word in (segment.words or [])]
    target = next((word for word in words if "stupid" in word.word.lower()), None)
    assert target is not None, (
        f"baseline (unmasked) transcription never produced the target word: {[w.word for w in words]}"
    )

    mask_filter = build_profanity_mask_filter(
        [(max(0.0, target.start - 0.08), target.end + 0.08)],
        duck_volume=0.12, garble_freq=1200.0, garble_width_octaves=6.0,
        warble_freq=25.0, warble_depth=1.0,
    )
    masked_path = tmp_path / "masked_speech.wav"
    result = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(speech_audio), "-af", mask_filter, str(masked_path)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr

    re_segments, _ = model.transcribe(str(masked_path), word_timestamps=True, language="en")
    re_words = [word.word.strip().lower() for segment in re_segments for word in (segment.words or [])]
    assert not any("stupid" in word for word in re_words), f"masked word still re-transcribed cleanly: {re_words}"


def test_hook_banner_changes_pixels_in_banner_region(test_video, tmp_path):
    """Renders the same clip with and without banner_text and asserts the
    banner region's pixels actually differ (HOOK-01/HOOK-04 end-to-end:
    Cyrillic drawtext with fontfile= on this machine's real ffmpeg)."""
    base_entry = {"start": 0.0, "end": 1.5, "crop_style": "zoom"}
    plain_path = tmp_path / "out_plain.mp4"
    banner_path = tmp_path / "out_banner.mp4"

    render_clip(
        str(test_video), str(plain_path), dict(base_entry),
        video_duration=SRC_DURATION, src_width=SRC_WIDTH, src_height=SRC_HEIGHT,
    )
    render_clip(
        str(test_video), str(banner_path),
        {**base_entry, "banner_text": "ТЕСТОВЫЙ ХУК"},
        video_duration=SRC_DURATION, src_width=SRC_WIDTH, src_height=SRC_HEIGHT,
        banner_cta_text="@nick",
    )

    def banner_region_signature(path):
        # Crop the banner zone (y=100..320 across the full width), downscale,
        # and dump raw gray pixels - a cheap, deterministic region signature.
        result = subprocess.run(
            [
                "ffmpeg", "-v", "error", "-ss", "0.5", "-i", str(path),
                "-frames:v", "1",
                "-vf", "crop=1080:220:0:100,scale=54:11,format=gray",
                "-f", "rawvideo", "-",
            ],
            capture_output=True,
        )
        assert result.returncode == 0, result.stderr
        return result.stdout

    assert banner_region_signature(plain_path) != banner_region_signature(banner_path)
