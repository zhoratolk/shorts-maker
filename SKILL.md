---
name: make-shorts
description: Turn a long gameplay/stream recording into vertical (9:16) short clips using local Whisper transcription and semantic moment-finding. No watermarks, no time limits. Invoke as /make-shorts <path-to-video>.
---

# make-shorts

## Prerequisites

Before the first run, make sure the environment is ready:

```bash
python scripts/setup.py
```

This checks/installs ffmpeg (via winget) and the Python dependencies, and reports whether a CUDA GPU was detected.

Make sure `config.yaml` exists (copy `config.example.yaml` if not) and read it before starting — every step below is governed by it.

## Pipeline

Given a video path `<video>` and the loaded `config.yaml`:

### 1. Transcribe (cached)

```bash
python scripts/transcribe.py "<video>" transcripts --model <whisper.model> --device <whisper.device> --language <whisper.language>
```

This prints the path to the cached transcript JSON (`transcripts/<video_stem>.json`). If the file already existed, transcription is skipped — do not re-run Whisper on a video that already has a cached transcript.

### 2. Split into chunks

```bash
python scripts/chunker.py transcripts/<video_stem>.json work/<video_stem>/chunks --chunk-minutes <analysis.chunk_minutes>
```

This writes one `chunk_NNNN.json` file per window into `work/<video_stem>/chunks/`.

### 3. Find candidates (pass 1)

For each `chunk_NNNN.json` file, produce a `work/<video_stem>/candidates/candidates_chunk_NNNN.json` file containing a JSON list of objects `{"start": <seconds>, "end": <seconds>, "reason": "<short reason>"}` for every strong moment found in that chunk's segments (jokes, reactions, stories — judged from the text itself, not audio energy).

- If `config.analysis.use_subagents` is `true` (default): dispatch one Agent (subagent_type: general-purpose) per chunk file, **in parallel in a single message**, each instructed to read its assigned chunk JSON and write its own `candidates_chunk_NNNN.json` file with that format. Do not have subagents talk to each other — they work independently on disjoint time windows.
- If `config.analysis.use_subagents` is `false`: read every chunk file yourself, sequentially, and write the candidate files directly without dispatching agents.
- If `config.content.allow_mature` is `false`, instruct the search (subagent prompt or your own pass) to skip any moment that is primarily profanity or sexual/adult humor rather than including it — only surface it as a candidate if it stands on its own without that material. If `true` (default), keep such moments as candidates normally; step 5 below flags them in the generated metadata instead of filtering them here.
- Treat any phrase in `config.analysis.hype_phrases` — and other language in the same register (streamer/audience hype, meme call-outs, exaggerated reactions) — as a strong positive signal for a candidate moment, even when the surrounding content alone wouldn't stand out.

Once every chunk has a candidates file, merge them:

```bash
python scripts/candidates.py work/<video_stem>/candidates work/<video_stem>/CANDIDATES.md work/<video_stem>/candidates.json
```

### 4. User approval

- If `config.analysis.require_approval` is `true` (default): show the user `work/<video_stem>/CANDIDATES.md` and ask which candidate IDs to proceed with. Only the approved subset continues to step 5.
- If `config.analysis.require_approval` is `false`: proceed with every candidate in `work/<video_stem>/candidates.json`.

### 5. Refine (pass 2)

For each approved candidate, re-read that moment's transcript window (from the chunk file(s) covering its time range) and decide:

- **Exact trim points** — adjust `start`/`end` to fall on natural speech pauses, not mid-word/mid-phrase, and keep the final duration within `config.clip.min_seconds`–`config.clip.max_seconds`.
- **Crop style** — determined by `config.crop.mode`:
  - If `config.crop.mode` is a concrete value (`zoom`, `pad`, or `original-16:9`), use that same value for every clip in this run — do not vary it per clip.
  - If `config.crop.mode` is `auto`, choose per clip among all three documented options: `zoom` (visually dynamic moment, crop in tight), `pad` (dialogue/joke-driven moment where the visual matters less, reserve room for captions), or `original-16:9` (a moment where the full frame matters and cropping would cut off something relevant — keep the whole 16:9 frame, letterboxed).
  - Never write `auto` into `PLAN.json` — it must always be a concrete resolved value.
- If `config.facecam.enabled` is `true`, let the facecam overlay inform (not override) the crop_style choice above — e.g. prefer `pad` or `original-16:9` so the overlay stays in frame, rather than a `zoom` that might crop it out. `facecam.mode` and `facecam.region` describe where the overlay sits, for this judgment call only — `render.py` does not crop to those pixel coordinates; it only ever applies the resolved crop_style (a center crop for `zoom`, or a full-frame letterbox for `pad`/`original-16:9`).
- If `config.subtitles.enabled` is `true`, build the clip's subtitles from **word-level** timestamps, not whole segments, so captions appear a few words at a time in sync with speech:
  1. Collect every `words` entry (`{"word", "start", "end"}`) from the transcript segments covering this clip's time range. Transcript timestamps are **absolute** (full source video); `render.py` seeks with `-ss` before `-i`, so each rendered clip's internal timeline starts at 0 — subtract this clip's `start` time from every word's `start`/`end` before writing anything, otherwise the subtitles will be timed for a point past the end of the rendered clip and never appear. Drop/clip any word that falls outside `[0, end-start]` after the shift.
  2. **Correct obviously mis-transcribed words** (Whisper garbles words, especially on fast/profane/slang speech). Read each word in context of its neighbors and fix it only when the intended word is unambiguous from context — a real word standing in for a nonsense token, an obvious one-letter slip, a homophone that doesn't fit the sentence. Do not rewrite unclear or ambiguous phrases you can't confidently reconstruct — leave those as Whisper transcribed them rather than guessing. This is a light proofreading pass, not a rewrite: keep every correction minimal and keep the original word's timestamps.
  3. Write the corrected, clip-relative word list to `work/<video_stem>/subtitles/<clip_filename_stem>_words.json` as a JSON list of `{"word", "start", "end"}` objects, then group them into short synced cues and render the `.srt`:
     ```bash
     python scripts/subtitles.py work/<video_stem>/subtitles/<clip_filename_stem>_words.json work/<video_stem>/subtitles/<clip_filename_stem>.srt --max-words <subtitles.words_per_cue>
     ```
  Reference the resulting `.srt` path as `subtitles_path` in the plan entry below.

- **Title and filename** — decide a short (2-3 word) title describing the clip's content (e.g. "Boss Rage Quit"), then run:
  ```bash
  python scripts/naming.py "<video_stem>" <1-based clip index> "<title>"
  ```
  to get the filesystem-safe filename (e.g. `mystream-0001-boss-rage-quit.mp4`) to use as `output_filename` below. The video stem prefix keeps clips from different source videos from colliding in the shared `config.output_dir`. Index clips sequentially in the order they appear in `PLAN.json`, starting at 1.
- **Per-platform metadata** — if `config.metadata.enabled` is `true`, for each platform in `config.metadata.platforms` produce:
  - `youtube`: `{"title": ..., "description": ..., "tags": [...]}` (tags as a plain list, not hashtags).
  - `tiktok` / `instagram`: `{"caption": "..."}` — a hook as the caption's first line, hashtags inline in the text.

  Write the metadata text in `config.metadata.language` (or, when it's `auto`, the same language as the transcript itself) — the same handling as `whisper.language` above, just applied to the generated text instead of the transcription.

  If `config.content.allow_mature` is `true` and this clip contains profanity or sexual/adult themes, add a clear content warning so the human uploader remembers to mark it accordingly on each platform: prepend `⚠️ 18+` to the `youtube.title`, add a short note (e.g. "Содержит ненормативную лексику / контент 18+") to `youtube.description`, and include the same warning in the `tiktok`/`instagram` captions. Skip this entirely for clips that don't contain such material, even when the config allows it.

  Write the combined per-platform object (keyed by platform name) to a JSON file, then render it:
  ```bash
  python scripts/metadata.py work/<video_stem>/metadata_data/<clip_filename_stem>.json work/<video_stem>/metadata/<clip_filename_stem>.txt
  ```
  where `<clip_filename_stem>` is the `output_filename` from the step above without its extension (e.g. `mystream-0001-boss-rage-quit`). Record the rendered path as `metadata_path` in the plan entry below. Skip this entirely when `config.metadata.enabled` is `false`.

Write the merged results to `work/<video_stem>/PLAN.json`: a JSON list of objects:
```json
{
  "start": 123.4,
  "end": 156.2,
  "crop_style": "zoom",
  "subtitles_path": "work/<video_stem>/subtitles/mystream-0001-boss-rage-quit.srt",
  "output_filename": "mystream-0001-boss-rage-quit.mp4",
  "metadata_path": "work/<video_stem>/metadata/mystream-0001-boss-rage-quit.txt"
}
```
(`subtitles_path` and `metadata_path` are each omitted entirely when the corresponding feature is disabled.)

### 6. Render

```bash
python scripts/render.py "<video>" work/<video_stem>/PLAN.json "<config.output_dir>" --fade-seconds <config.clip.fade_seconds> --sub-font "<config.subtitles.font>" --sub-size <config.subtitles.size> --sub-color <config.subtitles.color> --sub-outline-color <config.subtitles.outline> --sub-highlight-color <config.subtitles.highlight_color> --sub-position <config.subtitles.position> --sub-words-per-cue <config.subtitles.words_per_cue>
```

This probes the source video once, then renders every entry in `PLAN.json` into `config.output_dir`, printing each output path. Each clip fades video and audio to black/silence over the last `config.clip.fade_seconds` seconds (default 0.5s) — the fade only starts once the last word has fully finished (extending a bit into unused source footage past the clip's end when available), it does not overlap or cut into speech. When a clip has `subtitles_path` set, the `--sub-*` flags style the burned-in captions (font/size/colors/position); the `--sub-position bottom` default keeps a safe margin from the very bottom of the frame so captions don't sit under TikTok/Reels/Shorts' own UI buttons.

## Library-wide search

Because every transcript is cached under `transcripts/`, steps 2-5 can be re-run against any subset of already-transcribed videos to search for moments across the whole archive, not just the video just processed — skip step 1 for videos that are already cached.
