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

## Project layout

- `scripts/` — the deterministic building blocks (config loading, transcript chunking, candidate merging, ffmpeg rendering, dependency setup) — each has a Python API and a CLI wrapper.
- `SKILL.md` — the Claude Code skill that orchestrates the above plus the semantic analysis passes.
- `transcripts/` — cached Whisper output per video (gitignored).
- `work/<video>/` — per-video working files: chunked transcript, candidate list, render plan (gitignored).
