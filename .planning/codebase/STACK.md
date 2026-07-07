# Technology Stack

**Analysis Date:** 2026-07-07

## Languages

**Primary:**
- Python 3.11/3.12 (recommended; 3.13 works if a prebuilt `ctranslate2` wheel exists) - all of `scripts/*.py` and `tests/*.py`

**Secondary:**
- YAML - configuration (`config.yaml`, `config.example.yaml`)
- ASS (Advanced SubStation Alpha) - generated subtitle files, built in-memory by `scripts/render.py::build_ass_content`
- Markdown - `SKILL.md` (the Claude Code skill orchestration script, not source code) and `docs/*.md`

## Runtime

**Environment:**
- Windows-first (setup script uses `winget`, DLL loading workaround via `os.add_dll_directory` is Windows-only); code guards Windows-specific behavior with `sys.platform == "win32"` checks (`scripts/transcribe.py:_register_nvidia_dll_dirs`)
- No web server / long-running process — this is a CLI/batch pipeline invoked per-video via a Claude Code skill (`SKILL.md`) that shells out to the scripts below

**Package Manager:**
- pip + `venv` (`.venv/`)
- Lockfile: none (plain `requirements.txt`/`requirements-dev.txt` with `>=` version floors, no pinned lockfile)

## Frameworks

**Core:**
- `faster-whisper>=1.0.0` (CTranslate2-backed Whisper reimplementation) - local speech-to-text transcription, `scripts/transcribe.py`
- `pyannote.audio>=3.1` (optional) - speaker diarization, `scripts/diarize.py`
- `google-api-python-client>=2.100`, `google-auth-oauthlib>=1.2`, `google-auth-httplib2>=0.2` (optional) - YouTube Data/Analytics API access, `scripts/youtube_analytics.py`
- `PyYAML>=6.0` - config file parsing, `scripts/config.py`

**Testing:**
- `pytest>=7.4.0` (`requirements-dev.txt`) - all tests under `tests/`
- Custom pytest marker `integration` (defined in `pyproject.toml`) for real-ffmpeg smoke tests that skip themselves when ffmpeg/ffprobe aren't on PATH (`tests/test_integration_ffmpeg.py`)

**Build/Dev:**
- No bundler/transpiler — plain Python scripts, no build step
- `scripts/setup.py` - dependency-check/installer script (ffmpeg via winget, missing pip packages, GPU detection via `nvidia-smi`)

## Key Dependencies

**Critical:**
- `ffmpeg` / `ffprobe` (external binary, not a pip package) - required for audio extraction, clip rendering, subtitle burn-in, denoise/loudnorm, cropping; must be on `PATH`. Installed via `winget install -e --id Gyan.FFmpeg` (`scripts/setup.py::install_ffmpeg`)
- `faster-whisper` - transcription backbone; internally depends on `ctranslate2` (native wheel, platform/Python-version sensitive — see README troubleshooting)
- `nvidia-cublas-cu12`, `nvidia-cudnn-cu12` (optional, not in requirements.txt, mentioned in README) - CUDA runtime DLLs for actual GPU transcription; `scripts/transcribe.py::_register_nvidia_dll_dirs` registers their `bin/` dirs via `os.add_dll_directory` since Windows' loader ignores `PATH` for `LoadLibraryEx`

**Infrastructure:**
- `pyyaml` - `scripts/config.py::load_config` (dataclass-based config with validation in `_validate`)
- `pyannote.audio` + `torch` (transitive) - only imported lazily inside `scripts/diarize.py::load_diarization_pipeline`, so the base install works without it when diarization is disabled

## Configuration

**Environment:**
- `HF_TOKEN` env var - HuggingFace access token for pyannote diarization models (read via `os.environ.get("HF_TOKEN")` in `scripts/diarize.py`); set via `setx HF_TOKEN "hf_..."` per README
- `config.yaml` (gitignored, user-local) copied from `config.example.yaml` - drives `input_dir`, `output_dir`, whisper model/device/language, analysis chunking, clip length, crop mode, facecam, subtitles, diarization, audio_energy, metadata platforms, audio denoise/loudnorm, effects, jumpcuts, visual detection
- `client_secret.json` (gitignored) - Google OAuth desktop-app client secret for `scripts/youtube_analytics.py`
- `token.json` (gitignored) - cached OAuth refresh/access token written by `scripts/youtube_analytics.py::load_credentials`

**Build:**
- `pyproject.toml` - pytest-only config (`[tool.pytest.ini_options]`): sets `pythonpath = ["."]`, `testpaths = ["tests"]`, registers the `integration` marker. No `[build-system]`/packaging metadata — this project is not distributed as an installable package.

## Platform Requirements

**Development:**
- Windows with `winget` available
- Python 3.11/3.12 (3.13 conditionally supported)
- `ffmpeg`/`ffprobe` on `PATH`
- Claude Code CLI (orchestrates the pipeline via `SKILL.md`, installed as `.claude/skills/make-shorts/SKILL.md` in the project)
- Optional NVIDIA GPU + driver (`nvidia-smi`) for faster transcription; CUDA runtime wheels needed for actual GPU execution, not just detection

**Production:**
- No production/server deployment — runs entirely on the local machine as a developer/creator tool; outputs (rendered clips, transcripts, cache) are local files under `config.output_dir` and `work/`

---

*Stack analysis: 2026-07-07*
