from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def is_diarized(transcript: dict) -> bool:
    segments = transcript.get("segments") or []
    return bool(segments) and all("speaker" in segment for segment in segments)


def label_speakers_by_first_appearance(turns: list[dict]) -> dict[str, str]:
    order: list[str] = []
    for turn in sorted(turns, key=lambda item: item["start"]):
        if turn["speaker"] not in order:
            order.append(turn["speaker"])
    return {raw: f"Голос {index + 1}" for index, raw in enumerate(order)}


def _overlap_seconds(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def assign_speaker_to_segment(segment: dict, turns: list[dict]) -> str | None:
    if not turns:
        return None

    best_speaker = None
    best_overlap = 0.0
    for turn in turns:
        overlap = _overlap_seconds(segment["start"], segment["end"], turn["start"], turn["end"])
        if overlap > best_overlap:
            best_overlap = overlap
            best_speaker = turn["speaker"]

    if best_speaker is not None:
        return best_speaker

    # Segment falls in a gap between diarized turns (e.g. brief cross-talk the
    # pipeline didn't attribute) - fall back to whichever turn is nearest in
    # time rather than leaving the segment unlabeled.
    midpoint = (segment["start"] + segment["end"]) / 2
    nearest = min(turns, key=lambda turn: min(abs(midpoint - turn["start"]), abs(midpoint - turn["end"])))
    return nearest["speaker"]


def attach_speakers_to_segments(segments: list[dict], turns: list[dict]) -> list[dict]:
    labeled = []
    for segment in segments:
        speaker = assign_speaker_to_segment(segment, turns)
        labeled.append({**segment, "speaker": speaker})
    return labeled


def extract_audio_wav(video_path: str, output_wav_path: str, runner=subprocess.run) -> None:
    runner(
        [
            "ffmpeg", "-y", "-i", video_path,
            "-vn", "-ac", "1", "-ar", "16000",
            output_wav_path,
        ],
        check=True,
        capture_output=True,
    )


def load_diarization_pipeline(hf_token: str, device: str = "auto"):
    from pyannote.audio import Pipeline

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from scripts.setup import check_gpu

    # pyannote.audio >=4 renamed use_auth_token= to token=; support both so an
    # environment with the older 3.x still works.
    try:
        pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1", token=hf_token)
    except TypeError:
        pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1", use_auth_token=hf_token)

    resolved_device = check_gpu() if device == "auto" else device
    if resolved_device == "cuda":
        import torch

        pipeline.to(torch.device("cuda"))
    return pipeline


def load_waveform(audio_path: str) -> dict:
    # pyannote.audio >=4 reads files through torchcodec, which needs FFmpeg
    # *shared* DLLs (versions 4-7) on Windows - a static ffmpeg 8 build can't
    # feed it. We already extract a plain 16 kHz mono wav ourselves, so hand
    # the pipeline a waveform dict and skip torchcodec entirely.
    import soundfile
    import torch

    data, sample_rate = soundfile.read(audio_path, dtype="float32", always_2d=True)
    waveform = torch.from_numpy(data.T)  # (channel, time)
    return {"waveform": waveform, "sample_rate": sample_rate}


def run_diarization_pipeline(
    pipeline,
    audio_path: str,
    num_speakers: int | None = None,
    min_speakers: int | None = None,
    max_speakers: int | None = None,
) -> list[dict]:
    kwargs: dict = {}
    if num_speakers is not None:
        kwargs["num_speakers"] = num_speakers
    else:
        if min_speakers is not None:
            kwargs["min_speakers"] = min_speakers
        if max_speakers is not None:
            kwargs["max_speakers"] = max_speakers

    diarization = pipeline(load_waveform(audio_path), **kwargs)

    # pyannote.audio >=4 wraps the Annotation in a DiarizeOutput dataclass;
    # 3.x returns the Annotation directly.
    if not hasattr(diarization, "itertracks"):
        diarization = diarization.speaker_diarization

    turns = [
        {"start": turn.start, "end": turn.end, "speaker": speaker}
        for turn, _, speaker in diarization.itertracks(yield_label=True)
    ]
    turns.sort(key=lambda item: item["start"])
    return turns


def diarize_transcript(
    video_path: str,
    transcript_path: str,
    pipeline,
    num_speakers: int | None = None,
    min_speakers: int | None = None,
    max_speakers: int | None = None,
) -> dict:
    transcript = json.loads(Path(transcript_path).read_text(encoding="utf-8"))
    if is_diarized(transcript):
        return transcript

    with tempfile.TemporaryDirectory() as tmp_dir:
        wav_path = str(Path(tmp_dir) / "audio.wav")
        extract_audio_wav(video_path, wav_path)
        raw_turns = run_diarization_pipeline(pipeline, wav_path, num_speakers, min_speakers, max_speakers)

    labels = label_speakers_by_first_appearance(raw_turns)
    turns = [{**turn, "speaker": labels[turn["speaker"]]} for turn in raw_turns]

    transcript["segments"] = attach_speakers_to_segments(transcript["segments"], turns)
    Path(transcript_path).write_text(json.dumps(transcript, ensure_ascii=False, indent=2), encoding="utf-8")
    return transcript


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Label speakers in a cached transcript JSON using pyannote.audio diarization"
    )
    parser.add_argument("video_path", help="Path to the source video/audio file")
    parser.add_argument("transcripts_dir", help="Directory containing the cached transcript JSON")
    parser.add_argument(
        "--hf-token", default=os.environ.get("HF_TOKEN"),
        help="HuggingFace access token (defaults to $HF_TOKEN); must have accepted "
        "pyannote/speaker-diarization-3.1 + pyannote/segmentation-3.0 model terms",
    )
    parser.add_argument("--device", choices=["auto", "cuda", "cpu"], default="auto")
    parser.add_argument("--num-speakers", type=int, default=None)
    parser.add_argument("--min-speakers", type=int, default=None)
    parser.add_argument("--max-speakers", type=int, default=None)
    args = parser.parse_args()

    if not args.hf_token:
        parser.error("HuggingFace token required: pass --hf-token or set $HF_TOKEN")

    stem = Path(args.video_path).stem
    transcript_path = str(Path(args.transcripts_dir) / f"{stem}.json")
    if not Path(transcript_path).exists():
        parser.error(f"no cached transcript found at {transcript_path} - run scripts/transcribe.py first")

    pipeline = load_diarization_pipeline(args.hf_token, args.device)
    diarize_transcript(
        args.video_path, transcript_path, pipeline,
        num_speakers=args.num_speakers, min_speakers=args.min_speakers, max_speakers=args.max_speakers,
    )
    print(transcript_path)


if __name__ == "__main__":
    main()
