from __future__ import annotations

import shutil
import subprocess
import sys

PACKAGE_NAMES = {"yaml": "pyyaml", "faster_whisper": "faster-whisper"}


def prompt_yes_no(question: str) -> bool:
    try:
        return input(question).strip().lower() == "y"
    except EOFError:
        # non-interactive environment (e.g. CI, piped stdin) - default to "no"
        return False


def check_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def check_fpcalc() -> bool:
    return shutil.which("fpcalc") is not None


def check_gpu(runner=subprocess.run) -> str:
    try:
        runner(["nvidia-smi"], capture_output=True, check=True)
        return "cuda"
    except (FileNotFoundError, subprocess.CalledProcessError):
        return "cpu"


def check_python_deps(module_names: tuple[str, ...] = ("yaml", "faster_whisper")) -> list[str]:
    missing = []
    for module_name in module_names:
        try:
            __import__(module_name)
        except ImportError:
            missing.append(module_name)
    return missing


def install_ffmpeg(runner=subprocess.run) -> None:
    runner(["winget", "install", "-e", "--id", "Gyan.FFmpeg"], check=True)


def install_python_deps(missing: list[str], runner=subprocess.run) -> None:
    packages = [PACKAGE_NAMES[name] for name in missing]
    runner([sys.executable, "-m", "pip", "install", *packages], check=True)


def main() -> None:
    print("Checking dependencies...")

    if check_ffmpeg():
        print("[ok] ffmpeg found")
    else:
        if prompt_yes_no("ffmpeg not found. Install via winget now? [y/N] "):
            install_ffmpeg()
        else:
            print("[skip] ffmpeg not installed — rendering will fail until it is")

    if check_fpcalc():
        print("[ok] fpcalc (Chromaprint) found")
    else:
        print(
            "[skip] fpcalc not found — audio-fingerprint monetization flagging will stay "
            "disabled until Chromaprint is installed (e.g. `winget install -e --id Chromaprint.Chromaprint`); "
            "everything else works without it"
        )

    missing_deps = check_python_deps()
    if not missing_deps:
        print("[ok] python dependencies found")
    else:
        print(f"Missing python packages: {', '.join(missing_deps)}")
        if prompt_yes_no("Install them now? [y/N] "):
            install_python_deps(missing_deps)
        else:
            print("[skip] missing packages not installed — the pipeline will fail until they are")

    if sys.version_info[:2] >= (3, 13):
        print(
            "[warn] Python 3.13+ detected — faster-whisper/ctranslate2 may not have prebuilt "
            "wheels yet on this platform. If installation fails, create a venv with Python 3.11 or "
            "3.12 instead."
        )

    print(f"[info] GPU detected: {check_gpu()}")


if __name__ == "__main__":
    main()
