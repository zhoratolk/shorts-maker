import json
import os
from pathlib import Path

import pytest

from scripts.ingest import (
    build_audio_energy_command,
    build_chunk_command,
    build_diarize_command,
    build_frames_command,
    build_silence_command,
    build_transcribe_command,
    run_ingest,
    speech_source,
    video_stem,
)


class FakeResult:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_video_stem():
    assert video_stem("F:/rec/2026-07-20_merged_stream.mkv") == "2026-07-20_merged_stream"


def test_build_transcribe_command_uses_whisper_config():
    cmd = build_transcribe_command("in.mkv", "out/transcripts", {"model": "small", "device": "cpu", "language": "ru"})

    assert cmd[2:4] == ["in.mkv", "out/transcripts"]
    assert "--model" in cmd and cmd[cmd.index("--model") + 1] == "small"
    assert "--device" in cmd and cmd[cmd.index("--device") + 1] == "cpu"
    assert "--language" in cmd and cmd[cmd.index("--language") + 1] == "ru"


def test_build_silence_command_defaults():
    cmd = build_silence_command("in.mkv", {})

    assert cmd[2] == "in.mkv"
    assert cmd[-2:] == ["--min-duration", "0.15"]


def test_build_diarize_command_fixed_speaker_count_omits_min_max():
    cmd = build_diarize_command("in.mkv", "out/transcripts", {"num_speakers": 3, "min_speakers": 1, "max_speakers": 5})

    assert "--num-speakers" in cmd
    assert cmd[cmd.index("--num-speakers") + 1] == "3"
    assert "--min-speakers" not in cmd
    assert "--max-speakers" not in cmd


def test_build_diarize_command_range_when_no_fixed_count():
    cmd = build_diarize_command("in.mkv", "out/transcripts", {"min_speakers": 2, "max_speakers": 4})

    assert "--num-speakers" not in cmd
    assert cmd[cmd.index("--min-speakers") + 1] == "2"
    assert cmd[cmd.index("--max-speakers") + 1] == "4"


def test_build_audio_energy_command_defaults():
    cmd = build_audio_energy_command("in.mkv", {})

    assert cmd[2] == "in.mkv"
    assert "--threshold-db" in cmd


def test_build_chunk_command():
    cmd = build_chunk_command("t.json", "chunks", {"chunk_minutes": 20})

    assert cmd[2:4] == ["t.json", "chunks"]
    assert cmd[-1] == "20"


def test_build_frames_command():
    cmd = build_frames_command("in.mkv", 0.0, 120.0, "frames/chunk_0000", {"frame_interval_seconds": 60.0})

    assert cmd[2:6] == ["in.mkv", "0.0", "120.0", "frames/chunk_0000"]
    assert cmd[-3:] == ["--interval-seconds", "60.0", "--prefix"] or cmd[-1] == "frame"


def test_run_ingest_happy_path_all_features_enabled(tmp_path):
    output_dir = tmp_path / "out"
    (output_dir / "transcripts").mkdir(parents=True)
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    calls = []

    def fake_runner(cmd, **kwargs):
        # ingest probes the recording for a second audio track before it starts, so it
        # can warn when one is there and nothing was told which to listen to.
        if cmd[0] == "ffprobe":
            return FakeResult(stdout="0")
        calls.append(cmd)
        if "transcribe.py" in cmd[1]:
            transcript = {"segments": [{"start": 0.0, "end": 5.0, "words": []}]}
            (output_dir / "transcripts" / "vid.json").write_text(json.dumps(transcript), encoding="utf-8")
            return FakeResult(stdout=str(output_dir / "transcripts" / "vid.json"))
        if "silence.py" in cmd[1]:
            return FakeResult(stdout="[]")
        if "diarize.py" in cmd[1]:
            return FakeResult(stdout="")
        if "audio_energy.py" in cmd[1]:
            return FakeResult(stdout="[]")
        if "chunker.py" in cmd[1]:
            chunks_dir = repo_root / "work" / "vid" / "chunks"
            chunks_dir.mkdir(parents=True, exist_ok=True)
            chunk_path = chunks_dir / "chunk_0000.json"
            chunk_path.write_text(json.dumps({"index": 0, "start": 0.0, "end": 5.0, "segments": []}), encoding="utf-8")
            return FakeResult(stdout=str(chunk_path))
        if "frames.py" in cmd[1]:
            frames_dir = repo_root / "work" / "vid" / "frames" / "chunk_0000"
            frames_dir.mkdir(parents=True, exist_ok=True)
            (frames_dir / "frame_000.jpg").write_bytes(b"")
            return FakeResult(stdout=str(frames_dir / "frame_000.jpg"))
        raise AssertionError(f"unexpected command: {cmd}")

    config = {
        "output_dir": str(output_dir),
        "whisper": {"model": "medium", "device": "auto", "language": "auto"},
        "jumpcuts": {"enabled": True, "detect_min_seconds": 0.15},
        "diarization": {"enabled": True},
        "audio_energy": {"enabled": True},
        "analysis": {"chunk_minutes": 35},
        "visual": {"enabled": True, "frame_interval_seconds": 120.0},
    }

    summary = run_ingest("vid.mkv", config, repo_root, runner=fake_runner)

    assert summary["video_stem"] == "vid"
    assert summary["pauses_path"] is not None
    assert summary["diarized"] is True
    assert summary["energy_path"] is not None
    assert len(summary["chunk_paths"]) == 1
    assert summary["warnings"] == []
    assert any("frames.py" in c[1] for c in calls)


def test_run_ingest_skips_optional_steps_when_disabled(tmp_path):
    output_dir = tmp_path / "out"
    (output_dir / "transcripts").mkdir(parents=True)
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    def fake_runner(cmd, **kwargs):
        # ingest probes the recording for a second audio track before it starts, so it
        # can warn when one is there and nothing was told which to listen to.
        if cmd[0] == "ffprobe":
            return FakeResult(stdout="0")
        if "transcribe.py" in cmd[1]:
            transcript = {"segments": [{"start": 0.0, "end": 5.0, "words": []}]}
            (output_dir / "transcripts" / "vid.json").write_text(json.dumps(transcript), encoding="utf-8")
            return FakeResult(stdout=str(output_dir / "transcripts" / "vid.json"))
        if "chunker.py" in cmd[1]:
            chunks_dir = repo_root / "work" / "vid" / "chunks"
            chunks_dir.mkdir(parents=True, exist_ok=True)
            chunk_path = chunks_dir / "chunk_0000.json"
            chunk_path.write_text(json.dumps({"index": 0, "start": 0.0, "end": 5.0, "segments": []}), encoding="utf-8")
            return FakeResult(stdout=str(chunk_path))
        raise AssertionError(f"unexpected command when features disabled: {cmd}")

    config = {
        "output_dir": str(output_dir),
        "whisper": {},
        "jumpcuts": {"enabled": False},
        "diarization": {"enabled": False},
        "audio_energy": {"enabled": False},
        "analysis": {"chunk_minutes": 35},
        "visual": {"enabled": False},
    }

    summary = run_ingest("vid.mkv", config, repo_root, runner=fake_runner)

    assert summary["pauses_path"] is None
    assert summary["diarized"] is False
    assert summary["energy_path"] is None


def test_run_ingest_skips_cached_pauses_and_energy(tmp_path):
    output_dir = tmp_path / "out"
    transcripts_dir = output_dir / "transcripts"
    transcripts_dir.mkdir(parents=True)
    (transcripts_dir / "vid_pauses.json").write_text("[]", encoding="utf-8")
    (transcripts_dir / "vid_energy_spikes.json").write_text("[]", encoding="utf-8")
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    def fake_runner(cmd, **kwargs):
        # ingest probes the recording for a second audio track before it starts, so it
        # can warn when one is there and nothing was told which to listen to.
        if cmd[0] == "ffprobe":
            return FakeResult(stdout="0")
        assert "silence.py" not in cmd[1]
        assert "audio_energy.py" not in cmd[1]
        if "transcribe.py" in cmd[1]:
            transcript = {"segments": [{"start": 0.0, "end": 5.0, "words": []}]}
            (transcripts_dir / "vid.json").write_text(json.dumps(transcript), encoding="utf-8")
            return FakeResult(stdout=str(transcripts_dir / "vid.json"))
        if "diarize.py" in cmd[1]:
            return FakeResult(stdout="")
        if "chunker.py" in cmd[1]:
            chunks_dir = repo_root / "work" / "vid" / "chunks"
            chunks_dir.mkdir(parents=True, exist_ok=True)
            chunk_path = chunks_dir / "chunk_0000.json"
            chunk_path.write_text(json.dumps({"index": 0, "start": 0.0, "end": 5.0, "segments": []}), encoding="utf-8")
            return FakeResult(stdout=str(chunk_path))
        raise AssertionError(f"unexpected command: {cmd}")

    config = {
        "output_dir": str(output_dir),
        "whisper": {},
        "jumpcuts": {"enabled": True},
        "diarization": {"enabled": True},
        "audio_energy": {"enabled": True},
        "analysis": {"chunk_minutes": 35},
        "visual": {"enabled": False},
    }

    summary = run_ingest("vid.mkv", config, repo_root, runner=fake_runner)

    assert summary["pauses_path"] == str(transcripts_dir / "vid_pauses.json")
    assert summary["energy_path"] == str(transcripts_dir / "vid_energy_spikes.json")


def test_run_ingest_fails_open_on_diarize_error(tmp_path):
    output_dir = tmp_path / "out"
    (output_dir / "transcripts").mkdir(parents=True)
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    def fake_runner(cmd, **kwargs):
        # ingest probes the recording for a second audio track before it starts, so it
        # can warn when one is there and nothing was told which to listen to.
        if cmd[0] == "ffprobe":
            return FakeResult(stdout="0")
        if "transcribe.py" in cmd[1]:
            transcript = {"segments": [{"start": 0.0, "end": 5.0, "words": []}]}
            (output_dir / "transcripts" / "vid.json").write_text(json.dumps(transcript), encoding="utf-8")
            return FakeResult(stdout=str(output_dir / "transcripts" / "vid.json"))
        if "diarize.py" in cmd[1]:
            return FakeResult(returncode=1, stderr="HF_TOKEN missing")
        if "chunker.py" in cmd[1]:
            chunks_dir = repo_root / "work" / "vid" / "chunks"
            chunks_dir.mkdir(parents=True, exist_ok=True)
            chunk_path = chunks_dir / "chunk_0000.json"
            chunk_path.write_text(json.dumps({"index": 0, "start": 0.0, "end": 5.0, "segments": []}), encoding="utf-8")
            return FakeResult(stdout=str(chunk_path))
        raise AssertionError(f"unexpected command: {cmd}")

    config = {
        "output_dir": str(output_dir),
        "whisper": {},
        "jumpcuts": {"enabled": False},
        "diarization": {"enabled": True},
        "audio_energy": {"enabled": False},
        "analysis": {"chunk_minutes": 35},
        "visual": {"enabled": False},
    }

    summary = run_ingest("vid.mkv", config, repo_root, runner=fake_runner)

    assert summary["diarized"] is False
    assert any("diarization failed" in w for w in summary["warnings"])


def test_run_ingest_raises_on_transcribe_failure(tmp_path):
    output_dir = tmp_path / "out"
    (output_dir / "transcripts").mkdir(parents=True)
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    def fake_runner(cmd, **kwargs):
        # ingest probes the recording for a second audio track before it starts, so it
        # can warn when one is there and nothing was told which to listen to.
        if cmd[0] == "ffprobe":
            return FakeResult(stdout="0")
        return FakeResult(returncode=1, stderr="ffmpeg not found")

    config = {
        "output_dir": str(output_dir),
        "whisper": {},
        "jumpcuts": {"enabled": False},
        "diarization": {"enabled": False},
        "audio_energy": {"enabled": False},
        "analysis": {"chunk_minutes": 35},
        "visual": {"enabled": False},
    }

    try:
        run_ingest("vid.mkv", config, repo_root, runner=fake_runner)
        assert False, "expected RuntimeError"
    except RuntimeError as error:
        assert "transcribe failed" in str(error)


def test_run_ingest_skips_frame_extraction_when_frames_already_exist(tmp_path):
    output_dir = tmp_path / "out"
    (output_dir / "transcripts").mkdir(parents=True)
    repo_root = tmp_path / "repo"
    frames_dir = repo_root / "work" / "vid" / "frames" / "chunk_0000"
    frames_dir.mkdir(parents=True)
    (frames_dir / "frame_000.jpg").write_bytes(b"")

    def fake_runner(cmd, **kwargs):
        # ingest probes the recording for a second audio track before it starts, so it
        # can warn when one is there and nothing was told which to listen to.
        if cmd[0] == "ffprobe":
            return FakeResult(stdout="0")
        assert "frames.py" not in cmd[1]
        if "transcribe.py" in cmd[1]:
            transcript = {"segments": [{"start": 0.0, "end": 5.0, "words": []}]}
            (output_dir / "transcripts" / "vid.json").write_text(json.dumps(transcript), encoding="utf-8")
            return FakeResult(stdout=str(output_dir / "transcripts" / "vid.json"))
        if "chunker.py" in cmd[1]:
            chunks_dir = repo_root / "work" / "vid" / "chunks"
            chunks_dir.mkdir(parents=True, exist_ok=True)
            chunk_path = chunks_dir / "chunk_0000.json"
            chunk_path.write_text(json.dumps({"index": 0, "start": 0.0, "end": 5.0, "segments": []}), encoding="utf-8")
            return FakeResult(stdout=str(chunk_path))
        raise AssertionError(f"unexpected command: {cmd}")

    config = {
        "output_dir": str(output_dir),
        "whisper": {},
        "jumpcuts": {"enabled": False},
        "diarization": {"enabled": False},
        "audio_energy": {"enabled": False},
        "analysis": {"chunk_minutes": 35},
        "visual": {"enabled": True, "frame_interval_seconds": 120.0},
    }

    summary = run_ingest("vid.mkv", config, repo_root, runner=fake_runner)

    assert summary["warnings"] == []


def test_run_ingest_surfaces_a_repetition_loop_the_subprocess_only_printed(tmp_path):
    """A Whisper repetition loop is the one transcription failure that looks like success.

    transcribe.py detects it and warns on stderr - which run_ingest captures and, on a
    zero exit code, never looks at. The loops are also written into the transcript, and
    that is the copy that survives being run as a subprocess.
    """
    output_dir = tmp_path / "out"
    (output_dir / "transcripts").mkdir(parents=True)
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    def fake_runner(cmd, **kwargs):
        # ingest probes the recording for a second audio track before it starts, so it
        # can warn when one is there and nothing was told which to listen to.
        if cmd[0] == "ffprobe":
            return FakeResult(stdout="0")
        if "transcribe.py" in cmd[1]:
            transcript = {
                "segments": [{"start": 0.0, "end": 5.0, "words": []}],
                "repetition_loops": [
                    {"start": 754.0, "end": 900.0, "text": "Вечный файт", "count": 41}
                ],
            }
            (output_dir / "transcripts" / "vid.json").write_text(
                json.dumps(transcript, ensure_ascii=False), encoding="utf-8"
            )
            # Exactly what the real script does: warns on stderr, exits zero.
            return FakeResult(stdout="", stderr="[warn] transcript repeats")
        if "chunker.py" in cmd[1]:
            chunks_dir = repo_root / "work" / "vid" / "chunks"
            chunks_dir.mkdir(parents=True, exist_ok=True)
            chunk_path = chunks_dir / "chunk_0000.json"
            chunk_path.write_text(
                json.dumps({"index": 0, "start": 0.0, "end": 5.0, "segments": []}), encoding="utf-8"
            )
            return FakeResult(stdout=str(chunk_path))
        raise AssertionError(f"unexpected command: {cmd}")

    config = {
        "output_dir": str(output_dir),
        "whisper": {"model": "medium", "device": "auto", "language": "auto"},
        "jumpcuts": {"enabled": False},
        "diarization": {"enabled": False},
        "audio_energy": {"enabled": False},
        "analysis": {"chunk_minutes": 35},
        "visual": {"enabled": False},
    }

    summary = run_ingest("vid.mkv", config, repo_root, runner=fake_runner)

    assert len(summary["warnings"]) == 1
    assert "Вечный файт" in summary["warnings"][0]
    assert "41" in summary["warnings"][0]


class TestWhichTrackTheAnalysisListensTo:
    """One mixed track is the OBS default and must keep behaving exactly as before.
    A mic on its own track is the reason this exists: every analysis step should hear
    the mic alone, while rendering keeps cutting from the recording so clips still
    carry game audio.
    """

    def _probe(self, count):
        def runner(cmd, **kwargs):
            if cmd[0] == "ffprobe":
                return FakeResult(stdout="\n".join(str(i) for i in range(count)))
            return FakeResult()
        return runner

    def test_unset_leaves_the_recording_alone(self, tmp_path):
        config = {"audio": {"speech_track": None}}
        assert speech_source("rec.mkv", config, tmp_path, self._probe(1)) == "rec.mkv"

    def test_no_audio_section_at_all_is_the_same_as_unset(self, tmp_path):
        assert speech_source("rec.mkv", {}, tmp_path, self._probe(1)) == "rec.mkv"

    def test_a_configured_track_is_extracted_next_to_the_recordings_work(self, tmp_path):
        calls = []

        def runner(cmd, **kwargs):
            calls.append(cmd)
            if cmd[0] == "ffprobe":
                return FakeResult(stdout="0\n1")
            open(cmd[-1], "wb").write(b"wav")
            return FakeResult()

        path = speech_source("rec.mkv", {"audio": {"speech_track": 1}}, tmp_path, runner)

        assert "-map" in calls[1] and "0:a:1" in calls[1]
        assert os.path.exists(path)

    def test_the_wav_keeps_the_recordings_stem(self, tmp_path):
        """Not cosmetic. The transcript cache, the pause file and the diarisation output
        are all named from the stem of the path they are handed, so a wav named anything
        else would give every recording in the project the same cache path."""

        def runner(cmd, **kwargs):
            if cmd[0] == "ffprobe":
                return FakeResult(stdout="0\n1")
            open(cmd[-1], "wb").write(b"wav")
            return FakeResult()

        path = speech_source("/rec/2026-08-27 02-59-25.mkv",
                                    {"audio": {"speech_track": 1}}, tmp_path, runner)

        assert Path(path).stem == video_stem("/rec/2026-08-27 02-59-25.mkv")

    def test_a_track_that_is_not_there_refuses_rather_than_falling_back(self, tmp_path):
        """Falling back to the mixed track would produce a transcript that looks entirely
        normal and describes the wrong audio - the failure nobody catches."""
        with pytest.raises(RuntimeError, match="which has 1"):
            speech_source("rec.mkv", {"audio": {"speech_track": 1}}, tmp_path, self._probe(1))

    def test_an_extraction_that_fails_leaves_no_half_written_wav(self, tmp_path):
        def runner(cmd, **kwargs):
            if cmd[0] == "ffprobe":
                return FakeResult(stdout="0\n1")
            open(cmd[-1], "wb").write(b"half")
            return FakeResult(stderr="boom", returncode=1)

        with pytest.raises(RuntimeError, match="boom"):
            speech_source("rec.mkv", {"audio": {"speech_track": 1}}, tmp_path, runner)

        assert not (tmp_path / "work" / "rec" / "rec.wav").exists()

    def test_an_already_extracted_wav_is_not_extracted_again(self, tmp_path):
        calls = []

        def runner(cmd, **kwargs):
            calls.append(cmd)
            if cmd[0] == "ffprobe":
                return FakeResult(stdout="0\n1")
            open(cmd[-1], "wb").write(b"wav")
            return FakeResult()

        config = {"audio": {"speech_track": 1}}
        speech_source("rec.mkv", config, tmp_path, runner)
        before = len(calls)
        speech_source("rec.mkv", config, tmp_path, runner)

        assert len(calls) == before + 1  # the probe, and no second extraction

    def test_a_second_track_nobody_configured_is_reported(self, tmp_path):
        """The quiet version of this going wrong: ffmpeg maps every audio stream,
        ebur128 measures each one, and audio_energy reads both sets off one stderr as
        though they were a single timeline. Nothing fails - the spikes are just a blend
        of game audio and voice."""
        output_dir = tmp_path / "out"

        def fake_runner(cmd, **kwargs):
            if cmd[0] == "ffprobe":
                return FakeResult(stdout="0\n1")
            if "transcribe.py" in cmd[1]:
                (output_dir / "transcripts").mkdir(parents=True, exist_ok=True)
                (output_dir / "transcripts" / "vid.json").write_text(
                    json.dumps({"segments": []}), encoding="utf-8")
                return FakeResult(stdout="")
            if "chunker.py" in cmd[1]:
                return FakeResult(stdout="")
            return FakeResult(stdout="")

        summary = run_ingest("vid.mkv", {"output_dir": str(output_dir)}, tmp_path, fake_runner)

        assert any("2 audio tracks" in w and "speech_track" in w for w in summary["warnings"])

    def test_no_such_warning_for_an_ordinary_single_track_recording(self, tmp_path):
        output_dir = tmp_path / "out"

        def fake_runner(cmd, **kwargs):
            if cmd[0] == "ffprobe":
                return FakeResult(stdout="0")
            if "transcribe.py" in cmd[1]:
                (output_dir / "transcripts").mkdir(parents=True, exist_ok=True)
                (output_dir / "transcripts" / "vid.json").write_text(
                    json.dumps({"segments": []}), encoding="utf-8")
            return FakeResult(stdout="")

        summary = run_ingest("vid.mkv", {"output_dir": str(output_dir)}, tmp_path, fake_runner)

        assert not any("audio tracks" in w for w in summary["warnings"])
