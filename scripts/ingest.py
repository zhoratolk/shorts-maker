"""Mechanically runs the pipeline's deterministic front half in one command:
transcribe, pause detection, diarization, audio-energy spikes, chunking, and
per-chunk frame pre-extraction (SKILL.md steps 1/1b/1c/1d/2 plus the frame
extraction step 3's visual pass otherwise repeats per chunk). Every gate and
value is read from config.yaml, the same way work/_render.py already does for
the render step. None of this requires judgment - it exists so the orchestrator
calls this once and starts real work at step 3 (candidate finding).

Usage:
    python scripts/ingest.py "<video path>"
    (reads ./config.yaml by default; pass --config to override)
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON = str(REPO_ROOT / ".venv" / "Scripts" / "python.exe")


def video_stem(video_path: str) -> str:
    return Path(video_path).stem


def build_transcribe_command(video_path: str, transcripts_dir: str, whisper_cfg: dict) -> list[str]:
    return [
        PYTHON, "scripts/transcribe.py", video_path, transcripts_dir,
        "--model", str(whisper_cfg.get("model", "medium")),
        "--device", str(whisper_cfg.get("device", "auto")),
        "--language", str(whisper_cfg.get("language", "auto")),
    ]


def build_silence_command(video_path: str, jumpcuts_cfg: dict) -> list[str]:
    return [
        PYTHON, "scripts/silence.py", video_path,
        "--min-duration", str(jumpcuts_cfg.get("detect_min_seconds", 0.15)),
    ]


def build_diarize_command(video_path: str, transcripts_dir: str, diarization_cfg: dict) -> list[str]:
    cmd = [PYTHON, "scripts/diarize.py", video_path, transcripts_dir]
    if diarization_cfg.get("num_speakers") is not None:
        cmd += ["--num-speakers", str(diarization_cfg["num_speakers"])]
        return cmd
    if diarization_cfg.get("min_speakers") is not None:
        cmd += ["--min-speakers", str(diarization_cfg["min_speakers"])]
    if diarization_cfg.get("max_speakers") is not None:
        cmd += ["--max-speakers", str(diarization_cfg["max_speakers"])]
    return cmd


def build_audio_energy_command(video_path: str, audio_energy_cfg: dict) -> list[str]:
    return [
        PYTHON, "scripts/audio_energy.py", video_path,
        "--threshold-db", str(audio_energy_cfg.get("threshold_db", 6.0)),
        "--floor-lufs", str(audio_energy_cfg.get("floor_lufs", -35.0)),
        "--baseline-window-seconds", str(audio_energy_cfg.get("baseline_window_seconds", 20.0)),
        "--min-duration", str(audio_energy_cfg.get("min_duration", 0.3)),
        "--merge-gap-seconds", str(audio_energy_cfg.get("merge_gap_seconds", 1.0)),
    ]


def build_chunk_command(transcript_path: str, chunks_dir: str, analysis_cfg: dict) -> list[str]:
    return [
        PYTHON, "scripts/chunker.py", transcript_path, chunks_dir,
        "--chunk-minutes", str(analysis_cfg.get("chunk_minutes", 35)),
    ]


def build_frames_command(
    video_path: str, chunk_start: float, chunk_end: float, frames_dir: str, visual_cfg: dict
) -> list[str]:
    return [
        PYTHON, "scripts/frames.py", video_path,
        str(chunk_start), str(chunk_end), frames_dir,
        "--interval-seconds", str(visual_cfg.get("frame_interval_seconds", 120.0)),
        "--prefix", "frame",
    ]


def run_ingest(video_path: str, config: dict, repo_root: Path, runner=subprocess.run) -> dict:
    """Runs SKILL.md steps 1/1b/1c/1d/2 plus per-chunk frame pre-extraction,
    gated exactly like the orchestrator prose documents. Raises on a
    hard-required step failing (transcribe, chunk); fails open (records a
    warning, keeps going) on the steps SKILL.md already marks fail-open
    (diarize, audio-energy, frame extraction).
    """
    stem = video_stem(video_path)
    output_dir = Path(config["output_dir"])
    transcripts_dir = output_dir / "transcripts"
    transcript_path = transcripts_dir / f"{stem}.json"
    pauses_path = transcripts_dir / f"{stem}_pauses.json"
    energy_path = transcripts_dir / f"{stem}_energy_spikes.json"
    chunks_dir = repo_root / "work" / stem / "chunks"
    frames_root = repo_root / "work" / stem / "frames"

    summary: dict = {
        "video_stem": stem,
        "transcript_path": str(transcript_path),
        "pauses_path": None,
        "diarized": False,
        "energy_path": None,
        "chunks_dir": str(chunks_dir),
        "chunk_paths": [],
        "warnings": [],
    }

    result = runner(
        build_transcribe_command(video_path, str(transcripts_dir), config.get("whisper", {})),
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"transcribe failed: {result.stderr.strip()}")

    jumpcuts_cfg = config.get("jumpcuts", {})
    if jumpcuts_cfg.get("enabled"):
        if not pauses_path.exists():
            result = runner(build_silence_command(video_path, jumpcuts_cfg), capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(f"pause detection failed: {result.stderr.strip()}")
            pauses_path.parent.mkdir(parents=True, exist_ok=True)
            pauses_path.write_text(result.stdout, encoding="utf-8")
        summary["pauses_path"] = str(pauses_path)

    diarization_cfg = config.get("diarization", {})
    if diarization_cfg.get("enabled"):
        result = runner(
            build_diarize_command(video_path, str(transcripts_dir), diarization_cfg),
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            summary["warnings"].append(
                f"diarization failed, continuing without speaker labels: {result.stderr.strip()[-300:]}"
            )
        else:
            summary["diarized"] = True

    audio_energy_cfg = config.get("audio_energy", {})
    if audio_energy_cfg.get("enabled"):
        if energy_path.exists():
            summary["energy_path"] = str(energy_path)
        else:
            result = runner(build_audio_energy_command(video_path, audio_energy_cfg), capture_output=True, text=True)
            if result.returncode != 0:
                summary["warnings"].append(
                    f"audio-energy detection failed, continuing without spikes: {result.stderr.strip()[-300:]}"
                )
            else:
                energy_path.parent.mkdir(parents=True, exist_ok=True)
                energy_path.write_text(result.stdout, encoding="utf-8")
                summary["energy_path"] = str(energy_path)

    result = runner(
        build_chunk_command(str(transcript_path), str(chunks_dir), config.get("analysis", {})),
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"chunking failed: {result.stderr.strip()}")
    chunk_paths = sorted(Path(p) for p in result.stdout.splitlines() if p.strip())
    summary["chunk_paths"] = [str(p) for p in chunk_paths]

    visual_cfg = config.get("visual", {})
    if visual_cfg.get("enabled"):
        for chunk_path in chunk_paths:
            chunk = json.loads(chunk_path.read_text(encoding="utf-8"))
            frames_dir = frames_root / chunk_path.stem
            if frames_dir.exists() and any(frames_dir.glob("frame_*.jpg")):
                continue
            result = runner(
                build_frames_command(video_path, chunk["start"], chunk["end"], str(frames_dir), visual_cfg),
                capture_output=True, text=True,
            )
            if result.returncode != 0:
                summary["warnings"].append(
                    f"frame extraction failed for {chunk_path.name}: {result.stderr.strip()[-300:]}"
                )

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("video_path")
    parser.add_argument("--config", default=str(REPO_ROOT / "config.yaml"))
    args = parser.parse_args()

    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))

    def cwd_runner(cmd, **kwargs):
        return subprocess.run(cmd, cwd=str(REPO_ROOT), **kwargs)

    summary = run_ingest(args.video_path, config, REPO_ROOT, runner=cwd_runner)

    for warning in summary["warnings"]:
        print(f"[warn] {warning}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
