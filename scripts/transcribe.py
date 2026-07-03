from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _register_nvidia_dll_dirs() -> None:
    # On Windows, ctranslate2 loads CUDA runtime DLLs (cuBLAS/cuDNN) via LoadLibraryEx,
    # which ignores PATH under the default search flags. If the pip packages
    # nvidia-cublas-cu12/nvidia-cudnn-cu12 are installed, register their bin/
    # directories explicitly so GPU inference works without any manual setup.
    if sys.platform != "win32":
        return
    try:
        import nvidia
    except ImportError:
        return
    for bin_dir in Path(nvidia.__path__[0]).glob("*/bin"):
        os.add_dll_directory(str(bin_dir))


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
    _register_nvidia_dll_dirs()

    from faster_whisper import WhisperModel

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from scripts.setup import check_gpu

    resolved_device = check_gpu() if device == "auto" else device
    compute_type = "float16" if resolved_device == "cuda" else "int8"

    def build_and_warm_up(device: str, compute_type: str):
        model = WhisperModel(model_size, device=device, compute_type=compute_type)
        if device == "cuda":
            # ctranslate2 loads its CUDA runtime libraries (cuBLAS/cuDNN) lazily on the
            # first inference, not at construction — a missing DLL only surfaces here,
            # so warm up with a throwaway silent buffer to catch it before real work starts.
            import numpy as np

            segments, _ = model.transcribe(np.zeros(16000, dtype="float32"), language=None)
            next(segments, None)
        return model

    try:
        return build_and_warm_up(resolved_device, compute_type)
    except Exception as error:
        # ctranslate2/CUDA can fail with several different exception types on OOM or
        # missing runtime libraries; catch broadly here since this is a best-effort
        # fallback, not error handling for a known failure mode.
        if resolved_device != "cuda":
            raise
        print(f"[warn] failed to load Whisper model on GPU ({error}); falling back to CPU")
        return build_and_warm_up("cpu", "int8")


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
