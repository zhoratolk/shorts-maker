from __future__ import annotations

import argparse
import json
from pathlib import Path


def transcript_cache_path(video_path: str, transcripts_dir: str) -> str:
    stem = Path(video_path).stem
    return str(Path(transcripts_dir) / f"{stem}.json")


def is_cached(video_path: str, transcripts_dir: str) -> bool:
    return Path(transcript_cache_path(video_path, transcripts_dir)).exists()


def transcribe_video(
    video_path: str,
    transcripts_dir: str,
    model,
    language: str = "auto",
) -> dict:
    cache_path = Path(transcript_cache_path(video_path, transcripts_dir))
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))

    cache_path.parent.mkdir(parents=True, exist_ok=True)

    whisper_language = None if language == "auto" else language
    segments_iter, info = model.transcribe(video_path, language=whisper_language, word_timestamps=True)

    segments = [
        {"start": segment.start, "end": segment.end, "text": segment.text}
        for segment in segments_iter
    ]
    result = {
        "video_path": video_path,
        "language": info.language,
        "duration": info.duration,
        "segments": segments,
    }
    cache_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def load_whisper_model(model_size: str, device: str):
    from faster_whisper import WhisperModel

    from scripts.setup import check_gpu

    resolved_device = check_gpu() if device == "auto" else device
    compute_type = "float16" if resolved_device == "cuda" else "int8"

    try:
        return WhisperModel(model_size, device=resolved_device, compute_type=compute_type)
    except Exception as error:
        # ctranslate2/CUDA can fail with several different exception types on OOM;
        # catch broadly here since this is a best-effort fallback, not error handling
        # for a known failure mode.
        if resolved_device != "cuda":
            raise
        print(f"[warn] failed to load Whisper model on GPU ({error}); falling back to CPU")
        return WhisperModel(model_size, device="cpu", compute_type="int8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Transcribe a video with faster-whisper (cached)")
    parser.add_argument("video_path")
    parser.add_argument("transcripts_dir")
    parser.add_argument("--model", default="medium")
    parser.add_argument("--device", default="auto")
    parser.add_argument("--language", default="auto")
    args = parser.parse_args()

    if is_cached(args.video_path, args.transcripts_dir):
        print(transcript_cache_path(args.video_path, args.transcripts_dir))
        return

    model = load_whisper_model(args.model, args.device)
    transcribe_video(args.video_path, args.transcripts_dir, model, args.language)
    print(transcript_cache_path(args.video_path, args.transcripts_dir))


if __name__ == "__main__":
    main()
