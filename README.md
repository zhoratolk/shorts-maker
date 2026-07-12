# shorts-maker

Turn long gameplay/stream recordings into vertical (9:16) short clips — fully local, free, no watermarks, no time limits. Runs as a Claude Code skill: local Whisper transcription + ffmpeg rendering do the mechanical work, Claude Code reads the transcript to find and trim the good moments. Optional speaker diarization (who's talking when) lets it also judge how sustained a monologue/dialogue's train of thought is, and optional audio-energy spike detection catches wordless hype moments (screams/laughs) the transcript alone would miss — both feed candidate-finding alongside a short-form-virality research doc ([docs/viral-clips-ru.md](docs/viral-clips-ru.md)).

## Requirements

- Windows, macOS, or Linux (developed and battle-tested on Windows; `scripts/setup.py` knows winget/brew/apt for installing ffmpeg, everything else is plain cross-platform Python + ffmpeg)
- [ffmpeg](https://ffmpeg.org/download.html) on `PATH` (`scripts/setup.py` offers to install it)
- Python 3.11 or 3.12 recommended; 3.13 also works as long as `pip install` finds a prebuilt `ctranslate2` wheel for your Python version — if it tries to build from source, switch to 3.11/3.12
- [Claude Code](https://claude.com/claude-code)
- Optional: an NVIDIA GPU for faster transcription — the driver alone (`nvidia-smi` working) is enough to be *detected*, but actually running on GPU needs the CUDA runtime too; see [Troubleshooting](#troubleshooting) if it silently falls back to CPU

> **Language note:** the pipeline itself is language-agnostic (Whisper auto-detects), but the bundled metadata/title-writing guidance (`docs/metadata-writing-ru.md`, `docs/register-ru.md`) and the default `hype_phrases` list are tuned for Russian-language streams. Everything works for other languages — swap `hype_phrases` for your language's equivalents in `config.yaml` (an English example is included in `config.example.yaml`) and titles/captions will simply be written without the Russian register rules.

## Setup

```bash
git clone <this-repo>
cd shorts-maker
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
python scripts/setup.py
```

`scripts/setup.py` checks for ffmpeg and Python dependencies, offers to install anything missing (via winget/brew/apt depending on OS), and reports whether it detected a CUDA GPU.

Optional features live behind pip extras so the base install stays small — install only what you enable in `config.yaml`:

```bash
pip install -e ".[diarization]"   # speaker diarization (pyannote.audio + torch, heavy)
pip install -e ".[transitions]"   # context-driven transitions (opencv, librosa)
pip install -e ".[publish]"       # YouTube analytics/publish queue, TikTok/Instagram publish
pip install -e ".[all]"           # everything
```

### Alternative: uv (faster, reproducible)

With [uv](https://docs.astral.sh/uv/) installed, one command replaces the venv + pip steps and installs the exact dependency versions pinned in `uv.lock`:

```bash
uv sync                # base install
uv sync --extra transitions --extra publish   # plus optional features
uv sync --all-extras   # everything (pulls torch — heavy)
```

Then either activate `.venv` as usual or prefix commands with `uv run` (e.g. `uv run pytest -m "not integration"`). If your Windows username contains non-ASCII characters and uv fails with a `ModuleNotFoundError` during interpreter discovery, point its cache at an ASCII path once: `setx UV_CACHE_DIR D:\uv-cache`.

Copy the example config and fill in your paths:

```bash
copy config.example.yaml config.yaml   # Windows
cp config.example.yaml config.yaml     # macOS/Linux
```

Edit `config.yaml` — see the comments in `config.example.yaml` for what each field does (recommended chunk size ranges, facecam mode cost tradeoffs, etc).

### Optional: speaker diarization

`diarization.enabled` (off by default in `config.example.yaml`) labels who's talking per transcript segment, which the candidate search then uses to score how sustained a monologue/dialogue's train of thought is (`coherence`, step 3). If you don't want it, leave it `false` — nothing else below is needed, and a missing/invalid token just makes that step skip itself (fail-open, doesn't break the rest of the pipeline).

To actually use it:

1. Install the extra package: `pip install pyannote.audio`
2. Create a free account at [huggingface.co/join](https://huggingface.co/join) if you don't have one.
3. Accept the model terms — a separate one-time click-through for **each** of these two model pages, while logged in (a token alone isn't enough without this step, it's a per-model gate, not an account-wide permission):
   - [huggingface.co/pyannote/speaker-diarization-3.1](https://huggingface.co/pyannote/speaker-diarization-3.1) → "Agree and access repository"
   - [huggingface.co/pyannote/segmentation-3.0](https://huggingface.co/pyannote/segmentation-3.0) → "Agree and access repository"
4. Create an access token at [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) → "New token" → type **Read** (write access isn't needed) → Create, then copy it (`hf_...`, shown only once).
5. Set it as `HF_TOKEN` so the skill can find it. Session-only (current terminal window):
   ```powershell
   $env:HF_TOKEN = "hf_..."
   ```
   Or persistent (survives new terminals/reboots, recommended — set once and forget it):
   ```powershell
   setx HF_TOKEN "hf_..."
   ```
   `setx` only takes effect in *new* terminal windows/processes started after you run it — close and reopen your terminal (or restart Claude Code) before the next `/make-shorts` run.

### Optional: audio-energy spike detection

`audio_energy.enabled` (off by default) finds sudden loudness jumps (screams, laughs, hype yells) relative to the stream's own recent volume, and feeds them into candidate-finding as their own signal — the same kind of signal production AI clipping tools use, and one that catches wordless moments a transcript search structurally can't (nothing was said, or Whisper mangled it). No extra dependency or token needed, just ffmpeg (already required). Tune sensitivity via `audio_energy.threshold_db` (how big a jump counts, in dB) and `audio_energy.floor_lufs` (ignore jumps that stay within near-silence) in `config.yaml` if it's over/under-triggering — see the comments in `config.example.yaml`.

## Making `/make-shorts` available in Claude Code

Nothing to set up — the skill ships tracked at `.claude/skills/make-shorts/SKILL.md`, which is exactly where Claude Code discovers project skills. Just always launch Claude Code from this repo's directory (`cd shorts-maker` and run `claude`) — that's what makes `/make-shorts` appear and lets the skill's relative script paths (`scripts/*.py`, `work/`) resolve.

## Usage

In Claude Code, from this project directory:

```
/make-shorts F:\Recordings\my-stream.mp4
```

Claude Code will transcribe (cached — only happens once per video ever), search the transcript for candidate moments, show you a list to approve, then render the approved clips into `config.output_dir`. When `metadata.enabled` is `true`, each rendered clip also gets a same-named `.txt` file with ready-to-post title/description/tags/captions for every configured platform.

## Grounding candidate-finding in your own channel's real performance (optional)

`docs/viral-clips-ru.md` is built from general short-form-video research — a reasonable default, but generic by nature. Two ways to check what's *actually* landing on your own channel instead of relying only on general research:

**Quick, no setup:** connect the [claude-in-chrome](https://claude.com/claude-code) browser extension, sign into it with your Anthropic account, then just ask Claude Code to open your YouTube Studio content/analytics pages — it browses using your logged-in session, so authenticated pages work without any separate API setup. Manual, ask-Claude-to-check, one video (or page) at a time.

**Whole-channel snapshot in one file:** `scripts/youtube_analytics.py` pulls every uploaded video's view count, average-view-duration/completion percentage, and traffic-source breakdown (Shorts feed vs. search vs. subscribers, etc.) into one local JSON via the YouTube Data + Analytics APIs — read-only, never uploads/edits/deletes anything. One-time setup:

1. Go to [console.cloud.google.com](https://console.cloud.google.com/), create a project (any name).
2. In that project, enable **YouTube Data API v3** and **YouTube Analytics API** (APIs & Services → Library → search each → Enable). Both are free, no billing account needed for this usage level.
3. APIs & Services → OAuth consent screen → External → fill the required fields (app name, your email) → add both scopes (`.../auth/youtube.readonly`, `.../auth/yt-analytics.readonly`) → add yourself under **Test users**. The app stays in "Testing" mode (fine for personal use) — note that Google expires a testing-mode refresh token after 7 days of inactivity, so you may need to re-consent occasionally if you don't run this often; publishing the app removes that limit but isn't necessary for solo use.
4. APIs & Services → Credentials → Create Credentials → OAuth client ID → Application type **Desktop app** → Create, then Download JSON. Save it as `client_secret.json` in this repo's root (gitignored — never commit it).
5. `pip install -e ".[publish]"`
6. Run it:
   ```bash
   python scripts/youtube_analytics.py "<config.output_dir>/analytics/channel_performance.json"
   ```
   The first run opens a browser for you to sign in and consent, then caches the token as `token.json` (also gitignored) — later runs are silent until that token needs refreshing. `--start-date`/`--end-date` (YYYY-MM-DD) narrow the window if you don't want full channel history.
7. Point Claude Code at the resulting JSON when you want candidate-finding/hook choices grounded in real numbers instead of (or alongside) `docs/viral-clips-ru.md`'s general research.

## Running the tests

```bash
pytest
```

This runs everything, including `tests/test_integration_ffmpeg.py` — real ffmpeg smoke tests (no mocked subprocess) that catch broken filter graphs a string assertion can't, at the cost of ~30-40s of real encoding. For the fast day-to-day loop:

```bash
pytest -m "not integration"
```

The integration file skips itself automatically if ffmpeg/ffprobe aren't on `PATH`.

## Troubleshooting

**`ModuleNotFoundError` / EOFError during `python scripts/setup.py`:** old clones may hit either issue — both are fixed as of this commit. If `setup.py` still asks `[y/N]` and hangs when run non-interactively (no terminal attached), it now defaults to "no" instead of crashing; install ffmpeg yourself (`winget install Gyan.FFmpeg` / `brew install ffmpeg` / `sudo apt-get install ffmpeg`) and re-run.

**GPU is detected but transcription still runs on CPU:** `scripts/setup.py`/`transcribe.py` only check that `nvidia-smi` works (i.e. a driver is installed), not that the CUDA runtime libraries `faster-whisper`'s backend (ctranslate2) actually needs are present. If `cublas64_12.dll` (or a cuDNN DLL) can't be loaded, `transcribe.py` prints a `[warn] failed to load Whisper model on GPU (...); falling back to CPU` line and keeps going — slower, but it won't crash the run. To get real GPU speed instead of the CPU fallback, install the CUDA runtime as Python wheels (no system-wide CUDA Toolkit install needed):

```bash
pip install nvidia-cublas-cu12 nvidia-cudnn-cu12
```

That's it — `transcribe.py` finds and registers those packages' DLL directories itself (Windows' DLL loader ignores `PATH` for this, so it uses `os.add_dll_directory` instead), no manual `PATH` editing needed.

**Video has no real speech, or is mostly game-audio-only:** Whisper hallucinates short filler transcriptions (repeated `"Okay."`, `"Thank you."`, etc.) on near-silent or non-speech audio instead of leaving segments empty. That's a known Whisper behavior, not a bug in this project — pick a source video that actually has voice commentary.

**`diarize.py` fails with a 403/gated-repo error:** you haven't accepted the model terms for `pyannote/speaker-diarization-3.1` and/or `pyannote/segmentation-3.0` on huggingface.co with the account that issued your `HF_TOKEN` — visit both model pages while logged in, click through the terms, and re-run.

**`youtube_analytics.py` prints `[warn] YouTube Analytics API unreachable` every run:** the Data API (view/like/comment counts) and Analytics API (retention/traffic sources) are separate services on separate hosts — some ISPs/networks block `youtubeanalytics.googleapis.com` specifically while `www.googleapis.com` works fine (observed directly: TLS handshake to that one host times out, `curl` to it hangs, `nslookup` resolves it fine). This is a network-level block outside the script's control, not a bug — it fails open and still writes view/like/comment counts, just without retention/traffic-source data. A VPN that routes around the block is the only fix if you need that data.

**Cyrillic (or other non-ASCII) text prints as `????`/mojibake in your terminal:** the transcript/config files themselves are correct UTF-8 (`ensure_ascii=False`) — this is only a terminal code page issue. Open the `.json`/`.txt` files in an editor, or on Windows run `chcp 65001` first, to see the text correctly.

## Project layout

- `scripts/` — the deterministic building blocks (config loading, transcript chunking, candidate merging, ffmpeg rendering, dependency setup) — each has a Python API and a CLI wrapper.
- `.claude/skills/make-shorts/SKILL.md` — the Claude Code skill that orchestrates the above plus the semantic analysis passes.
- `docs/` — reference material the skill reads during the semantic passes: [viral-clips-ru.md](docs/viral-clips-ru.md) (candidate-finding/trim lens), [metadata-writing-ru.md](docs/metadata-writing-ru.md) and [register-ru.md](docs/register-ru.md) (title/description/caption writing).
- `<output_dir>/transcripts/` — cached Whisper output per video, next to the rendered clips.
- `work/<video>/` — per-video working files: chunked transcript, candidate list, render plan (gitignored).

## License

[MIT](LICENSE)
