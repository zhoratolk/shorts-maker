import json
import sys
import types
from pathlib import Path

from scripts import transcribe as transcribe_module
from scripts.transcribe import (
    is_cached,
    load_whisper_model,
    split_segments_on_gaps,
    transcribe_video,
    transcript_cache_path,
)


def test_transcript_cache_path_uses_video_stem():
    path = transcript_cache_path("F:/Запись/2025-11-02 17-32-40.mp4", "transcripts")
    assert path == str(Path("transcripts") / "2025-11-02 17-32-40.json")


def test_is_cached_false_when_missing(tmp_path):
    assert is_cached(str(tmp_path / "video.mp4"), str(tmp_path / "transcripts")) is False


def test_is_cached_true_when_present(tmp_path):
    transcripts_dir = tmp_path / "transcripts"
    transcripts_dir.mkdir()
    (transcripts_dir / "video.json").write_text("{}", encoding="utf-8")

    assert is_cached(str(tmp_path / "video.mp4"), str(transcripts_dir)) is True


class FakeWord:
    def __init__(self, word, start, end):
        self.word = word
        self.start = start
        self.end = end


class FakeSegment:
    def __init__(self, start, end, text, words=None):
        self.start = start
        self.end = end
        self.text = text
        self.words = words or []


class FakeInfo:
    def __init__(self, language, duration):
        self.language = language
        self.duration = duration


class FakeModel:
    def __init__(self):
        self.kwargs = None

    def transcribe(self, video_path, **kwargs):
        self.kwargs = kwargs
        segments = [
            FakeSegment(0.0, 2.0, "hello", [FakeWord("hello", 0.0, 2.0)]),
            FakeSegment(2.0, 4.0, "world", [FakeWord("world", 2.0, 4.0)]),
        ]
        return iter(segments), FakeInfo("en", 4.0)


def test_transcribe_video_writes_cache(tmp_path):
    video_path = str(tmp_path / "video.mp4")
    transcripts_dir = str(tmp_path / "transcripts")

    model = FakeModel()
    result = transcribe_video(video_path, transcripts_dir, model)

    assert model.kwargs["beam_size"] == 5
    # VAD and batching are opt-in: both cost word recall, see transcribe_video's comment
    assert model.kwargs["vad_filter"] is False
    assert "vad_parameters" not in model.kwargs
    assert "batch_size" not in model.kwargs
    assert result == {
        "video_path": video_path,
        "language": "en",
        "duration": 4.0,
        "segments": [
            {
                "start": 0.0, "end": 2.0, "text": "hello",
                "words": [{"word": "hello", "start": 0.0, "end": 2.0}],
            },
            {
                "start": 2.0, "end": 4.0, "text": "world",
                "words": [{"word": "world", "start": 2.0, "end": 4.0}],
            },
        ],
    }
    cache_file = Path(transcripts_dir) / "video.json"
    assert json.loads(cache_file.read_text(encoding="utf-8")) == result


def test_transcribe_video_forwards_vad_and_batching_when_asked(tmp_path):
    model = FakeModel()

    transcribe_video(
        str(tmp_path / "video.mp4"),
        str(tmp_path / "transcripts"),
        model,
        vad_filter=True,
        batch_size=8,
    )

    assert model.kwargs["vad_filter"] is True
    assert model.kwargs["vad_parameters"] == {
        "threshold": 0.2,
        "min_speech_duration_ms": 0,
        "speech_pad_ms": 600,
    }
    assert model.kwargs["batch_size"] == 8


def test_transcribe_video_uses_cache_when_present(tmp_path):
    video_path = str(tmp_path / "video.mp4")
    transcripts_dir = tmp_path / "transcripts"
    transcripts_dir.mkdir()
    cached_content = {"video_path": video_path, "language": "ru", "duration": 1.0, "segments": []}
    (transcripts_dir / "video.json").write_text(json.dumps(cached_content), encoding="utf-8")

    class ExplodingModel:
        def transcribe(self, *args, **kwargs):
            raise AssertionError("should not be called when cache exists")

    result = transcribe_video(video_path, str(transcripts_dir), ExplodingModel())

    assert result == cached_content


def test_load_whisper_model_resolves_auto_device(monkeypatch):
    captured = {}

    class FakeWhisperModel:
        def __init__(self, model_size, device, compute_type):
            captured["model_size"] = model_size
            captured["device"] = device
            captured["compute_type"] = compute_type

        def transcribe(self, audio, language):
            return iter([]), None

    fake_module = types.ModuleType("faster_whisper")
    fake_module.WhisperModel = FakeWhisperModel
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_module)
    monkeypatch.setattr("scripts.setup.check_gpu", lambda: "cuda")

    load_whisper_model("medium", "auto")

    assert captured == {"model_size": "medium", "device": "cuda", "compute_type": "int8_float16"}


def test_load_whisper_model_respects_explicit_device(monkeypatch):
    captured = {}

    class FakeWhisperModel:
        def __init__(self, model_size, device, compute_type):
            captured["device"] = device
            captured["compute_type"] = compute_type

    fake_module = types.ModuleType("faster_whisper")
    fake_module.WhisperModel = FakeWhisperModel
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_module)

    load_whisper_model("small", "cpu")

    assert captured == {"device": "cpu", "compute_type": "int8"}


def test_load_whisper_model_falls_back_to_cpu_on_gpu_failure(monkeypatch, capsys):
    calls = []

    class FakeWhisperModel:
        def __init__(self, model_size, device, compute_type):
            calls.append({"model_size": model_size, "device": device, "compute_type": compute_type})

        def transcribe(self, audio, language):
            raise RuntimeError("CUDA out of memory")

    fake_module = types.ModuleType("faster_whisper")
    fake_module.WhisperModel = FakeWhisperModel
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_module)
    monkeypatch.setattr("scripts.setup.check_gpu", lambda: "cuda")

    load_whisper_model("medium", "auto")

    assert calls == [
        {"model_size": "medium", "device": "cuda", "compute_type": "int8_float16"},
        {"model_size": "medium", "device": "cpu", "compute_type": "int8"},
    ]
    assert "falling back to CPU" in capsys.readouterr().out


def test_load_whisper_model_reraises_when_already_on_cpu(monkeypatch):
    class FakeWhisperModel:
        def __init__(self, model_size, device, compute_type):
            raise RuntimeError("out of memory")

    fake_module = types.ModuleType("faster_whisper")
    fake_module.WhisperModel = FakeWhisperModel
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_module)

    try:
        load_whisper_model("medium", "cpu")
        raise AssertionError("expected RuntimeError to propagate")
    except RuntimeError as error:
        assert "out of memory" in str(error)


def test_load_whisper_model_respects_explicit_compute_type(monkeypatch):
    captured = {}

    class FakeWhisperModel:
        def __init__(self, model_size, device, compute_type):
            captured["compute_type"] = compute_type

    fake_module = types.ModuleType("faster_whisper")
    fake_module.WhisperModel = FakeWhisperModel
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_module)

    load_whisper_model("small", "cpu", compute_type="float32")

    assert captured == {"compute_type": "float32"}


def test_load_whisper_model_wraps_in_batched_pipeline(monkeypatch):
    class FakeWhisperModel:
        def __init__(self, model_size, device, compute_type):
            pass

    class FakeBatchedPipeline:
        def __init__(self, model):
            self.model = model

    fake_module = types.ModuleType("faster_whisper")
    fake_module.WhisperModel = FakeWhisperModel
    fake_module.BatchedInferencePipeline = FakeBatchedPipeline
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_module)

    plain = load_whisper_model("small", "cpu", batch_size=0)
    batched = load_whisper_model("small", "cpu", batch_size=8)

    assert isinstance(plain, FakeWhisperModel)
    assert isinstance(batched, FakeBatchedPipeline)


def test_split_segments_on_gaps_splits_at_long_pause():
    segments = [
        {
            "start": 0.0,
            "end": 10.0,
            "text": "раз два три",
            "words": [
                {"word": "раз", "start": 0.0, "end": 0.5},
                {"word": " два", "start": 0.7, "end": 1.2},
                {"word": " три", "start": 9.0, "end": 10.0},
            ],
        }
    ]

    out = split_segments_on_gaps(segments, max_gap_seconds=0.8)

    assert [(s["start"], s["end"], s["text"]) for s in out] == [
        (0.0, 1.2, "раз два"),
        (9.0, 10.0, "три"),
    ]


def test_split_segments_on_gaps_keeps_tight_segment_intact():
    segments = [
        {
            "start": 0.0,
            "end": 1.2,
            "text": "раз два",
            "words": [
                {"word": "раз", "start": 0.0, "end": 0.5},
                {"word": " два", "start": 0.7, "end": 1.2},
            ],
        }
    ]

    assert split_segments_on_gaps(segments) == segments


def test_split_segments_on_gaps_passes_through_wordless_segment():
    segments = [{"start": 0.0, "end": 2.0, "text": "нет слов", "words": []}]

    assert split_segments_on_gaps(segments) == segments


def test_register_nvidia_dll_dirs_skips_on_non_windows(monkeypatch):
    monkeypatch.setattr(transcribe_module.sys, "platform", "linux")
    calls = []
    monkeypatch.setattr(transcribe_module.os, "add_dll_directory", lambda p: calls.append(p), raising=False)

    transcribe_module._register_nvidia_dll_dirs()

    assert calls == []


def test_register_nvidia_dll_dirs_skips_when_nvidia_not_installed(monkeypatch):
    monkeypatch.setattr(transcribe_module.sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "nvidia", None)
    calls = []
    monkeypatch.setattr(transcribe_module.os, "add_dll_directory", lambda p: calls.append(p), raising=False)

    transcribe_module._register_nvidia_dll_dirs()

    assert calls == []


def test_register_nvidia_dll_dirs_registers_each_bin_dir(monkeypatch, tmp_path):
    (tmp_path / "cublas" / "bin").mkdir(parents=True)
    (tmp_path / "cudnn" / "bin").mkdir(parents=True)

    fake_nvidia = types.ModuleType("nvidia")
    fake_nvidia.__path__ = [str(tmp_path)]
    monkeypatch.setattr(transcribe_module.sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "nvidia", fake_nvidia)
    calls = []
    monkeypatch.setattr(transcribe_module.os, "add_dll_directory", lambda p: calls.append(p), raising=False)

    transcribe_module._register_nvidia_dll_dirs()

    assert sorted(calls) == sorted(
        [str(tmp_path / "cublas" / "bin"), str(tmp_path / "cudnn" / "bin")]
    )
