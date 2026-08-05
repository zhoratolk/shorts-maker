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
    bin_dirs = [str(bin_dir) for bin_dir in Path(nvidia.__path__[0]).glob("*/bin")]
    for bin_dir in bin_dirs:
        os.add_dll_directory(bin_dir)
    # ctranslate2 (>=4.x) resolves cublas64_12.dll via a plain LoadLibrary that
    # searches PATH, not the add_dll_directory user dirs above — so add_dll_directory
    # alone is not enough on Windows. Prepend the same bin dirs to PATH too.
    if bin_dirs:
        os.environ["PATH"] = os.pathsep.join(bin_dirs) + os.pathsep + os.environ.get("PATH", "")


def transcript_cache_path(video_path: str, transcripts_dir: str) -> str:
    stem = Path(video_path).stem
    return str(Path(transcripts_dir) / f"{stem}.json")


def is_cached(video_path: str, transcripts_dir: str) -> bool:
    return Path(transcript_cache_path(video_path, transcripts_dir)).exists()


def split_segments_on_gaps(segments: list[dict], max_gap_seconds: float = 0.8) -> list[dict]:
    """Re-split segments wherever speech pauses, using the word timestamps.

    Batched inference returns very coarse segments (~50s vs ~6s unbatched) because it
    groups whole VAD speech regions. Downstream that hurts anything keyed off segment
    boundaries — diarization labels one speaker per segment, so a long segment spanning
    two voices collapses to a single label and the coherence signal degrades. The word
    timestamps are unaffected by batching, so restore the granularity from them.
    """
    out: list[dict] = []
    for segment in segments:
        words = segment.get("words") or []
        if len(words) < 2:
            out.append(segment)
            continue

        groups: list[list[dict]] = [[words[0]]]
        for previous, word in zip(words, words[1:]):
            if word["start"] - previous["end"] > max_gap_seconds:
                groups.append([])
            groups[-1].append(word)

        if len(groups) == 1:
            out.append(segment)
            continue

        for group in groups:
            out.append(
                {
                    "start": group[0]["start"],
                    "end": group[-1]["end"],
                    "text": "".join(word["word"] for word in group).strip(),
                    "words": group,
                }
            )
    return out


def transcribe_video(
    video_path: str,
    transcripts_dir: str,
    model,
    language: str = "auto",
    beam_size: int = 5,
    vad_filter: bool = False,
    batch_size: int = 0,
) -> dict:
    cache_path = Path(transcript_cache_path(video_path, transcripts_dir))
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))

    cache_path.parent.mkdir(parents=True, exist_ok=True)

    whisper_language = None if language == "auto" else language
    transcribe_kwargs = {
        "language": whisper_language,
        "word_timestamps": True,
        # Greedy decoding is not cheaper here — beam_size 1 and 5 both measure ~x7 on
        # this GPU — but greedy loses content, so there is nothing to trade away.
        "beam_size": beam_size,
        # Off by default. VAD is the only way to get batched inference (faster-whisper
        # raises "No clip timestamps found" without it) and that is 4x faster, but it
        # costs ~9 points of word recall against a no-VAD reference: the drops are short
        # interjections, which on this channel are often the punchline. Turn it on with
        # --vad --batch-size N when throughput matters more than completeness.
        "vad_filter": vad_filter,
    }
    if vad_filter:
        # Softer than Silero's defaults: the stock threshold of 0.5 drops ~24% of the
        # words on this mic (quiet interjections read as non-speech), while 0.2 with
        # generous padding costs ~5%.
        transcribe_kwargs["vad_parameters"] = {
            "threshold": 0.2,
            "min_speech_duration_ms": 0,
            "speech_pad_ms": 600,
        }
    if batch_size > 0:
        transcribe_kwargs["batch_size"] = batch_size
    segments_iter, info = model.transcribe(video_path, **transcribe_kwargs)

    segments = [
        {
            "start": segment.start,
            "end": segment.end,
            "text": segment.text,
            "words": [
                {"word": word.word, "start": word.start, "end": word.end}
                for word in (segment.words or [])
            ],
        }
        for segment in segments_iter
    ]
    if batch_size > 0:
        segments = split_segments_on_gaps(segments)
    result = {
        "video_path": video_path,
        "language": info.language,
        "duration": info.duration,
        "segments": segments,
    }
    cache_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def load_whisper_model(
    model_size: str,
    device: str,
    compute_type: str = "auto",
    batch_size: int = 0,
):
    _register_nvidia_dll_dirs()

    from faster_whisper import WhisperModel

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from scripts.setup import check_gpu

    resolved_device = check_gpu() if device == "auto" else device
    if compute_type == "auto":
        # int8_float16 over plain float16 on CUDA: the GTX 1650 (TU117) has no tensor
        # cores, so float16 buys little speed while medium still eats 3 of its 4 GB —
        # quantized weights roughly halve that and leave room for batched inference.
        compute_type = "int8_float16" if resolved_device == "cuda" else "int8"

    def build_and_warm_up(device: str, compute_type: str):
        model = WhisperModel(model_size, device=device, compute_type=compute_type)
        if device == "cuda":
            # ctranslate2 loads its CUDA runtime libraries (cuBLAS/cuDNN) lazily on the
            # first inference, not at construction — a missing DLL only surfaces here,
            # so warm up with a throwaway silent buffer to catch it before real work starts.
            import numpy as np

            segments, _ = model.transcribe(np.zeros(16000, dtype="float32"), language=None)
            next(segments, None)
        if batch_size > 0:
            from faster_whisper import BatchedInferencePipeline

            return BatchedInferencePipeline(model=model)
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
    parser.add_argument("--compute-type", default="auto")
    parser.add_argument("--beam-size", type=int, default=5)
    parser.add_argument(
        "--batch-size", type=int, default=0, help="0 disables batched inference; needs --vad"
    )
    parser.add_argument("--vad", dest="vad_filter", action="store_true", default=False)
    args = parser.parse_args()

    if is_cached(args.video_path, args.transcripts_dir):
        print(transcript_cache_path(args.video_path, args.transcripts_dir))
        return

    model = load_whisper_model(args.model, args.device, args.compute_type, args.batch_size)
    transcribe_video(
        args.video_path,
        args.transcripts_dir,
        model,
        args.language,
        beam_size=args.beam_size,
        vad_filter=args.vad_filter,
        batch_size=args.batch_size,
    )
    print(transcript_cache_path(args.video_path, args.transcripts_dir))


if __name__ == "__main__":
    main()
