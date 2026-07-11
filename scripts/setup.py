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


def ffmpeg_install_command(platform: str = sys.platform) -> list[str] | None:
    """Best-effort ffmpeg install command for this OS, or None when no
    supported package manager is available (user installs manually)."""
    if platform == "win32":
        return ["winget", "install", "-e", "--id", "Gyan.FFmpeg"]
    if platform == "darwin":
        return ["brew", "install", "ffmpeg"] if shutil.which("brew") else None
    # Linux/other: apt is the only one common enough to guess at.
    if shutil.which("apt-get"):
        return ["sudo", "apt-get", "install", "-y", "ffmpeg"]
    return None


def fpcalc_install_hint(platform: str = sys.platform) -> str:
    if platform == "win32":
        return "winget install -e --id Chromaprint.Chromaprint"
    if platform == "darwin":
        return "brew install chromaprint"
    return "sudo apt-get install libchromaprint-tools (or your distro's chromaprint package)"


def install_ffmpeg(runner=subprocess.run) -> None:
    command = ffmpeg_install_command()
    if command is None:
        print(
            "[skip] no supported package manager found for this OS — install ffmpeg "
            "manually (https://ffmpeg.org/download.html) and make sure it's on PATH"
        )
        return
    runner(command, check=True)


def install_python_deps(missing: list[str], runner=subprocess.run) -> None:
    packages = [PACKAGE_NAMES[name] for name in missing]
    runner([sys.executable, "-m", "pip", "install", *packages], check=True)


def main() -> None:
    print("Checking dependencies...")

    if check_ffmpeg():
        print("[ok] ffmpeg found")
    else:
        command = ffmpeg_install_command()
        if command is not None and prompt_yes_no(
            f"ffmpeg not found. Install via `{' '.join(command)}` now? [y/N] "
        ):
            install_ffmpeg()
        else:
            print(
                "[skip] ffmpeg not installed — rendering will fail until it is "
                "(https://ffmpeg.org/download.html)"
            )

    if check_fpcalc():
        print("[ok] fpcalc (Chromaprint) found")
    else:
        print(
            "[skip] fpcalc not found — audio-fingerprint monetization flagging will stay "
            f"disabled until Chromaprint is installed (e.g. `{fpcalc_install_hint()}`); "
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
