import subprocess

from scripts.setup import (
    check_ffmpeg,
    check_gpu,
    check_python_deps,
    install_ffmpeg,
    install_python_deps,
)


def test_check_ffmpeg_found(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "C:/ffmpeg/ffmpeg.exe")
    assert check_ffmpeg() is True


def test_check_ffmpeg_missing(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    assert check_ffmpeg() is False


def test_check_gpu_returns_cuda_when_nvidia_smi_succeeds():
    class FakeResult:
        returncode = 0

    def fake_runner(command, capture_output, check):
        return FakeResult()

    assert check_gpu(runner=fake_runner) == "cuda"


def test_check_gpu_returns_cpu_when_nvidia_smi_missing():
    def fake_runner(command, capture_output, check):
        raise FileNotFoundError()

    assert check_gpu(runner=fake_runner) == "cpu"


def test_check_gpu_returns_cpu_when_nvidia_smi_errors():
    def fake_runner(command, capture_output, check):
        raise subprocess.CalledProcessError(1, command)

    assert check_gpu(runner=fake_runner) == "cpu"


def test_check_python_deps_reports_missing_module():
    missing = check_python_deps(module_names=("os", "definitely_not_a_real_module_xyz"))
    assert missing == ["definitely_not_a_real_module_xyz"]


def test_check_python_deps_empty_when_all_present():
    missing = check_python_deps(module_names=("os", "sys"))
    assert missing == []


def test_install_ffmpeg_calls_winget():
    captured = {}

    def fake_runner(command, check):
        captured["command"] = command

    install_ffmpeg(runner=fake_runner)

    assert captured["command"] == ["winget", "install", "-e", "--id", "Gyan.FFmpeg"]


def test_install_python_deps_maps_module_names_to_packages():
    captured = {}

    def fake_runner(command, check):
        captured["command"] = command

    install_python_deps(["yaml", "faster_whisper"], runner=fake_runner)

    assert captured["command"][-2:] == ["pyyaml", "faster-whisper"]
