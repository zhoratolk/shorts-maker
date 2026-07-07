# External Integrations

**Analysis Date:** 2026-07-07

## APIs & External Services

**Speech-to-Text (local, no network):**
- Whisper via `faster-whisper` (CTranslate2 backend) - fully local model inference, no API calls, no network dependency at runtime
  - Client: `faster_whisper.WhisperModel`, loaded in `scripts/transcribe.py::load_whisper_model`
  - Model sizes: `tiny | base | small | medium | large-v3` (config: `whisper.model` in `config.yaml`)
  - Device selection: `auto | cuda | cpu` (config: `whisper.device`); `auto` resolves via `scripts/setup.py::check_gpu` (`nvidia-smi` probe)
  - Model weights are downloaded/cached by `faster-whisper` on first use (HuggingFace Hub under the hood) but inference itself is offline
  - Transcript cache: JSON file per video at `<transcripts_dir>/<video_stem>.json` (`scripts/transcribe.py::transcript_cache_path`) — transcription runs at most once per video ever

**Speaker Diarization (local model, HuggingFace-gated):**
- `pyannote/speaker-diarization-3.1` (+ dependency `pyannote/segmentation-3.0`) via `pyannote.audio`
  - Client: `pyannote.audio.Pipeline.from_pretrained(...)`, `scripts/diarize.py::load_diarization_pipeline`
  - Auth: HuggingFace access token, env var `HF_TOKEN` (or `--hf-token` CLI flag), read-scope token type `hf_...`
  - Gating: requires accepting model terms on huggingface.co for BOTH `pyannote/speaker-diarization-3.1` and `pyannote/segmentation-3.0` individually (per-model gate, not account-wide) — a missing/invalid token or unaccepted terms surfaces as a 403/gated-repo error
  - Fail-open design: if `diarization.enabled` is off, no network/token is touched at all
  - Device: `auto | cuda | cpu`, moved onto `torch.device("cuda")` when resolved to GPU (`scripts/diarize.py::load_diarization_pipeline`)
  - Runs against a temp 16kHz mono WAV extracted via ffmpeg (`scripts/diarize.py::extract_audio_wav`), not the original video

**YouTube Data API v3 + YouTube Analytics API v2 (OAuth, optional, read-only):**
- Used only by `scripts/youtube_analytics.py` — pulls the channel's own video performance for grounding candidate-finding in real numbers
- Scopes (both read-only, no upload/edit/delete capability):
  - `https://www.googleapis.com/auth/youtube.readonly` (`DATA_API_SCOPE`)
  - `https://www.googleapis.com/auth/yt-analytics.readonly` (`ANALYTICS_API_SCOPE`)
- Auth flow: `google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file(...).run_local_server(port=0)` — opens a local browser consent flow on first run only (`scripts/youtube_analytics.py::load_credentials`)
  - Credential file: `client_secret.json` (OAuth "Desktop app" client, downloaded from Google Cloud Console, gitignored)
  - Token cache: `token.json` (gitignored) — refreshed silently via `google.auth.transport.requests.Request()` when expired but a refresh token exists; otherwise re-runs the consent flow
  - Testing-mode app note (from README): Google expires a testing-mode refresh token after 7 days of inactivity — occasional re-consent may be needed unless the OAuth app is published
- API clients built via `googleapiclient.discovery.build("youtube", "v3", ...)` and `build("youtubeAnalytics", "v2", ...)` (`scripts/youtube_analytics.py::build_services`)
- Endpoints used:
  - `channels().list(part="contentDetails", mine=True)` — resolve own channel + uploads playlist (`get_own_channel`)
  - `playlistItems().list(...)` — paginate the uploads playlist for video id/title/publish date (`list_uploaded_videos`)
  - `videos().list(part="statistics", id=...)` — lifetime view/like/comment counts, chunked 50 ids/request (`fetch_video_statistics`, `MAX_VIDEO_IDS_PER_REQUEST`)
  - `youtubeAnalytics.reports().query(..., metrics="views,averageViewDuration,averageViewPercentage", dimensions="video")` — retention metrics (`fetch_analytics_for_videos`)
  - `youtubeAnalytics.reports().query(..., dimensions="video,insightTrafficSourceType")` — traffic-source breakdown, e.g. `YT_SHORTS`/`YT_SEARCH`/`SUBSCRIBER` (`fetch_traffic_sources_for_videos`)
- Fail-open behavior: the Analytics half (`youtubeAnalytics.googleapis.com`) is wrapped in try/except separately from the Data API half — some ISPs block that host specifically (TLS handshake timeout observed directly per code comment); on failure it prints a `[warn]` and continues with view/like/comment counts only (`scripts/youtube_analytics.py::fetch_channel_performance`)
- Output: local JSON cache, e.g. `<output_dir>/analytics/channel_performance.json` — no database, just a flat file
- Not automated/scheduled — invoked manually per README instructions

**Claude Code / Anthropic (orchestration layer, not a library dependency):**
- The pipeline is designed to run as a Claude Code skill: `SKILL.md` at repo root is copied to `.claude/skills/make-shorts/SKILL.md` in the target project and invoked as `/make-shorts <video>`
- Claude Code itself reads the cached transcript JSON and performs the semantic "find viral moments" and metadata-writing passes (referencing `docs/viral-clips-ru.md`, `docs/metadata-writing-ru.md`, `docs/register-ru.md`) — this is prompt-driven orchestration, not an SDK/API call from within the Python scripts
- Optional: `claude-in-chrome` browser extension can be used ad hoc (outside these scripts) to browse a user's logged-in YouTube Studio analytics pages

## Data Storage

**Databases:**
- None. No SQL/NoSQL database anywhere in the codebase.

**File Storage:**
- Local filesystem only:
  - `<output_dir>/transcripts/<video_stem>.json` - cached Whisper transcripts (persistent, reused across runs)
  - `work/<video>/` - per-video working files: chunked transcript, candidate list (`CANDIDATES.md`), render plan JSON (gitignored, ephemeral per-run state)
  - `<output_dir>/` - final rendered `.mp4` clips + per-clip `.txt` metadata files (title/description/tags/captions)
  - `<output_dir>/analytics/channel_performance.json` - YouTube analytics cache (example path from README)

**Caching:**
- Transcript cache: `scripts/transcribe.py::is_cached` / `transcript_cache_path` — skip re-transcription if the JSON file already exists for that video stem
- OAuth token cache: `token.json` (YouTube integration)
- No in-memory or distributed cache (Redis, etc.)

## Authentication & Identity

**Auth Provider:**
- Google OAuth 2.0 (Desktop app flow) - only for the optional `scripts/youtube_analytics.py` integration; see `client_secret.json`/`token.json` above. No user auth system for the pipeline itself (single-user local tool).
- HuggingFace token (`HF_TOKEN`) - not OAuth, a static personal access token used as a Bearer credential for gated model downloads (pyannote diarization only)

## Monitoring & Observability

**Error Tracking:**
- None (no Sentry/similar). Errors surface as Python exceptions or printed `[warn]`/`[error]` messages to stdout/stderr.

**Logs:**
- Plain `print()` statements to stdout/stderr for warnings and status (e.g. GPU fallback warning in `scripts/transcribe.py`, Analytics API unreachable warning in `scripts/youtube_analytics.py`). No structured logging framework.

## CI/CD & Deployment

**Hosting:**
- None — this is a local CLI tool, not a deployed service.

**CI Pipeline:**
- None detected in the repo (no `.github/workflows`, no CI config files found).

## Environment Configuration

**Required env vars:**
- `HF_TOKEN` - only required if `diarization.enabled: true` in `config.yaml`; otherwise unused

**Secrets location:**
- `client_secret.json` (repo root, gitignored) - Google OAuth client secret
- `token.json` (repo root, gitignored) - cached Google OAuth token
- `HF_TOKEN` - process environment variable (set via `setx`/`$env:HF_TOKEN`), never written to a file by this codebase
- `config.yaml` (gitignored) - user's local paths (`input_dir`/`output_dir`), not itself secret but excluded from version control since it's machine-specific

## Webhooks & Callbacks

**Incoming:**
- None

**Outgoing:**
- None — the OAuth flow's local redirect (`run_local_server(port=0)`) is a one-time interactive browser consent step, not a persistent webhook endpoint

---

*Integration audit: 2026-07-07*
