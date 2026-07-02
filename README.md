# shorts-maker

Turn long gameplay/stream recordings into vertical (9:16) short clips — fully local, free, no watermarks, no time limits. Runs as a Claude Code skill: local Whisper transcription + ffmpeg rendering do the mechanical work, Claude Code reads the transcript to find and trim the good moments.

## Requirements

- Windows with [winget](https://learn.microsoft.com/windows/package-manager/winget/) available
- Python 3.11 or 3.12 (faster-whisper/ctranslate2 may not yet have prebuilt wheels for 3.13 on all platforms)
- [Claude Code](https://claude.com/claude-code)
- Optional: an NVIDIA GPU for faster transcription

## Setup

```bash
git clone <this-repo>
cd shorts-maker
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt
python scripts/setup.py
```

`scripts/setup.py` checks for ffmpeg and Python dependencies, offers to install anything missing, and reports whether it detected a CUDA GPU.

Copy the example config and fill in your paths:

```bash
copy config.example.yaml config.yaml
```

Edit `config.yaml` — see the comments in `config.example.yaml` for what each field does (recommended chunk size ranges, facecam mode cost tradeoffs, etc).

## Usage

In Claude Code, from this project directory:

```
/make-shorts F:\Recordings\my-stream.mp4
```

Claude Code will transcribe (cached — only happens once per video ever), search the transcript for candidate moments, show you a list to approve, then render the approved clips into `config.output_dir`.

## Running the tests

```bash
pytest
```

## Project layout

- `scripts/` — the deterministic building blocks (config loading, transcript chunking, candidate merging, ffmpeg rendering, dependency setup) — each has a Python API and a CLI wrapper.
- `SKILL.md` — the Claude Code skill that orchestrates the above plus the semantic analysis passes.
- `transcripts/` — cached Whisper output per video (gitignored).
- `work/<video>/` — per-video working files: chunked transcript, candidate list, render plan (gitignored).
