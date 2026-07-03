# shorts-maker

Turn long gameplay/stream recordings into vertical (9:16) short clips — fully local, free, no watermarks, no time limits. Runs as a Claude Code skill: local Whisper transcription + ffmpeg rendering do the mechanical work, Claude Code reads the transcript to find and trim the good moments.

## Requirements

- Windows with [winget](https://learn.microsoft.com/windows/package-manager/winget/) available
- Python 3.11 or 3.12 recommended; 3.13 also works as long as `pip install` finds a prebuilt `ctranslate2` wheel for your Python version — if it tries to build from source, switch to 3.11/3.12
- [Claude Code](https://claude.com/claude-code)
- Optional: an NVIDIA GPU for faster transcription — the driver alone (`nvidia-smi` working) is enough to be *detected*, but actually running on GPU needs the CUDA runtime too; see [Troubleshooting](#troubleshooting) if it silently falls back to CPU

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

## Making `/make-shorts` available in Claude Code

Claude Code discovers skills from `.claude/skills/<name>/SKILL.md` in the project it's running in — it will not pick up the bare `SKILL.md` at this repo's root on its own. Since that file's instructions invoke `scripts/*.py` and read/write `transcripts/`/`work/` using paths relative to this repo, the skill only works correctly when Claude Code's working directory is this repo. Set it up once:

```bash
mkdir .claude\skills\make-shorts
copy SKILL.md .claude\skills\make-shorts\SKILL.md
```

(On macOS/Linux: `mkdir -p .claude/skills/make-shorts && cp SKILL.md .claude/skills/make-shorts/SKILL.md`, or symlink it if you'd rather it stay in sync automatically.)

Then always launch Claude Code from this repo's directory (`cd shorts-maker` and run `claude`) — that's what makes `/make-shorts` appear and lets its relative script paths resolve.

## Usage

In Claude Code, from this project directory:

```
/make-shorts F:\Recordings\my-stream.mp4
```

Claude Code will transcribe (cached — only happens once per video ever), search the transcript for candidate moments, show you a list to approve, then render the approved clips into `config.output_dir`. When `metadata.enabled` is `true`, each rendered clip also gets a same-named `.txt` file with ready-to-post title/description/tags/captions for every configured platform.

## Running the tests

```bash
pytest
```

## Troubleshooting

**`ModuleNotFoundError` / EOFError during `python scripts/setup.py`:** old clones may hit either issue — both are fixed as of this commit. If `setup.py` still asks `[y/N]` and hangs when run non-interactively (no terminal attached), it now defaults to "no" instead of crashing; install ffmpeg yourself with `winget install Gyan.FFmpeg` and re-run.

**GPU is detected but transcription still runs on CPU:** `scripts/setup.py`/`transcribe.py` only check that `nvidia-smi` works (i.e. a driver is installed), not that the CUDA runtime libraries `faster-whisper`'s backend (ctranslate2) actually needs are present. If `cublas64_12.dll` (or a cuDNN DLL) can't be loaded, `transcribe.py` prints a `[warn] failed to load Whisper model on GPU (...); falling back to CPU` line and keeps going — slower, but it won't crash the run. To get real GPU speed instead of the CPU fallback, install the CUDA runtime as Python wheels (no system-wide CUDA Toolkit install needed):

```bash
pip install nvidia-cublas-cu12 nvidia-cudnn-cu12
```

That's it — `transcribe.py` finds and registers those packages' DLL directories itself (Windows' DLL loader ignores `PATH` for this, so it uses `os.add_dll_directory` instead), no manual `PATH` editing needed.

**Video has no real speech, or is mostly game-audio-only:** Whisper hallucinates short filler transcriptions (repeated `"Okay."`, `"Thank you."`, etc.) on near-silent or non-speech audio instead of leaving segments empty. That's a known Whisper behavior, not a bug in this project — pick a source video that actually has voice commentary.

**Cyrillic (or other non-ASCII) text prints as `????`/mojibake in your terminal:** the transcript/config files themselves are correct UTF-8 (`ensure_ascii=False`) — this is only a terminal code page issue. Open the `.json`/`.txt` files in an editor, or on Windows run `chcp 65001` first, to see the text correctly.

## Project layout

- `scripts/` — the deterministic building blocks (config loading, transcript chunking, candidate merging, ffmpeg rendering, dependency setup) — each has a Python API and a CLI wrapper.
- `SKILL.md` — the Claude Code skill that orchestrates the above plus the semantic analysis passes.
- `transcripts/` — cached Whisper output per video (gitignored).
- `work/<video>/` — per-video working files: chunked transcript, candidate list, render plan (gitignored).
