# Codebase Concerns

**Analysis Date:** 2026-07-07

## Security: OAuth Credentials on Disk (Local Exposure Risk)

**Live secrets present in working directory:**
- `client_secret.json` (repo root) — contains a real Google OAuth client_id + client_secret
  (`GOCSPX-...`) for a project named `shorts-maker-501522`.
- `token.json` (repo root) — contains a live YouTube OAuth access/refresh token pair with
  `youtube.readonly` and `yt-analytics.readonly` scopes, tied to the same client.
- Both files are correctly listed in `.gitignore` (verified: `client_secret.json`, `token.json` are
  present in `.gitignore` at repo root, and `git ls-files` confirms neither is tracked). **Git
  history is clean of these files** — no evidence they were ever committed.
- Risk is local-disk exposure, not git leakage: anyone with filesystem access to `D:\shorts-maker`
  (this machine, a backup, a zip sent to someone) gets a working refresh token scoped to the
  channel's Analytics data. Read-only scopes limit blast radius (no upload/delete capability), but
  the tokens should still be treated as sensitive and not archived/shared as part of the project
  directory.
- `scripts/youtube_analytics.py:250-251` defaults `--client-secret`/`--token` args to these exact
  filenames in the repo root, reinforcing the pattern of storing OAuth material alongside code
  rather than in a dedicated (also-gitignored) secrets directory outside the repo tree.
- **Recommendation:** no code change strictly required (gitignore already correct), but consider
  moving both files outside the repo root (e.g. `~/.config/shorts-maker/`) to reduce accidental
  inclusion in zips/backups of the project folder, and rotate the current token/client_secret if
  this directory has ever been shared or synced anywhere.

## Security: Personal Channel Data in Docs — Verified Clean

- `docs/viral-clips-ru.md` was scrubbed in commit `443c46e` ("strip personal channel data from
  docs"): a section that previously named specific clip titles and view/comment counts from one
  channel was replaced with a generic pointer to the local, gitignored analytics JSON cache
  (`scripts/youtube_analytics.py` output).
- **Current tracked content verified clean**: read the full file (134 lines) — no channel name,
  video titles, view counts, or other per-user identifying data present. Only generic research
  content and external source links remain.
- No other tracked file was found to reference concrete channel/video/user data.
- Git history for `docs/viral-clips-ru.md` (`git log --oneline`) shows the scrub commit as the
  latest change to the file — no further personal data reintroduced in later commits.

## Stray Untracked Junk Files in Repo Root

**Still present, confirmed via `git status` and `ls`:**
- `nul` — 25-byte file, content is a stray Windows console codepage message
  (`Active code page: 65001`). Classic Windows shell redirection artifact (a command was likely
  run with `> nul` on PowerShell/cmd, which on Windows creates a literal file named `nul` instead
  of discarding output as it would on a real `NUL` device in cmd.exe).
- `tmp_out.txt`, `tmp_out2.txt`, `tmp_out4.txt`, `tmp_out5.txt`, `tmp_out6.txt` — debug output
  dumps from development/testing, containing raw Whisper transcript fragments (Russian stream
  speech, e.g. `tmp_out.txt`) and candidate-clip timestamp lists (e.g. `tmp_out2.txt`, filenames +
  start/end seconds matching real recorded stream files like
  `2026-07-05-merged-stream-0002-otvratitelnoe-lobbi.mp4`).
- All six files are untracked (not in `.gitignore`, not committed) — confirmed via
  `git status` and `git ls-files`. They pose no git-history risk but are working-directory clutter
  left over from ad-hoc debugging/manual test runs, and contain what is effectively raw personal
  stream transcript content sitting in the repo root outside of the intended `work/` (gitignored)
  output directory.
- **Fix approach:** delete all six files; consider adding `nul` and `tmp_out*.txt` to `.gitignore`
  as a safety net against future recurrence from ad-hoc PowerShell redirection during debugging.

## Tech Debt

**Bare instance-level `--client-secret`/`--token` defaults in `youtube_analytics.py`:**
- Files: `scripts/youtube_analytics.py:250-251`
- Issue: CLI defaults point at repo-root filenames for OAuth material (see Security section
  above). No environment-variable or config-driven override is wired through `config.yaml`/
  `scripts/config.py`, so the secure path (custom location) requires remembering to pass
  `--client-secret`/`--token` flags manually every invocation.
- Fix approach: read default paths from `config.yaml` (already has a `config.py` loader) or an
  env var, falling back to repo-root only if unset, and document the recommended external location
  in `README.md`.

**Bare `except Exception` blocks:**
- Files: `scripts/transcribe.py:96`, `scripts/youtube_analytics.py:233`
- Issue: broad exception catches. In `youtube_analytics.py:233-239` this is intentional and
  documented (fails open on Analytics API network blocks, keeping Data API stats) — acceptable as
  designed. `transcribe.py:96` was not fully inspected here; verify it doesn't silently swallow
  unrelated failures (e.g. disk-full, corrupt model cache) that a caller would want surfaced.

## Fragile Areas

**`render.py` is by far the largest module (607 lines):**
- Files: `scripts/render.py`
- Why fragile: concentrates ffmpeg command construction, crop math, probing, and rendering in one
  file — the largest in `scripts/` by a wide margin (next largest is `config.py` at 308 lines).
  Any ffmpeg CLI/version behavior change or crop-mode edge case has a large single-file blast
  radius.
- Safe modification: the `subprocess.run` injection pattern (`runner=subprocess.run` default arg)
  used consistently across `render.py`, `audio_energy.py`, `frames.py`, `diarize.py`, `silence.py`,
  `setup.py` is good for testability — new code touching ffmpeg/ffprobe calls should follow the
  same injectable-runner pattern already established, and add tests via the same mocking approach
  used in the existing `tests/test_render.py`.

## Test Coverage Gaps

**Not independently verified in this pass** — a full read of `tests/` against `scripts/` line
counts wasn't performed as part of this concerns-only audit. `render.py` (607 lines, most complex
module) and `youtube_analytics.py` (269 lines, network-calling, only unit-testable via mocked
`data_service`/`analytics_service`) are the two highest-risk-of-undertested modules by size/
complexity and warrant explicit verification that `tests/test_render.py` and
`tests/test_youtube_analytics.py` exercise their edge cases (crop modes, ffmpeg failures, Analytics
API network-block fallback path).

---

*Concerns audit: 2026-07-07*
