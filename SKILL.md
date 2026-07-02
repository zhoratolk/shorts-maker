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
- If `config.subtitles.enabled` is `true`, generate an `.srt` file for the clip's exact window under `work/<video_stem>/subtitles/` from the transcript segments, and reference it in the plan entry. Transcript segments carry **absolute** timestamps from the full source video, but `render.py` seeks with `-ss` before `-i`, so each rendered clip's internal timeline starts at 0, not at the clip's `start` offset. Before writing the `.srt`, subtract this clip's `start` time from every segment's start/end so the subtitle timestamps are clip-relative (starting at/near 0) — otherwise the subtitles will be timed for a point far past the end of the rendered clip and never appear.

Write the merged results to `work/<video_stem>/PLAN.json`: a JSON list of objects:
```json
{
  "start": 123.4,
  "end": 156.2,
  "crop_style": "zoom",
  "subtitles_path": "work/<video_stem>/subtitles/clip_0001.srt",
  "output_filename": "<video_stem>_clip01.mp4"
}
```
(`subtitles_path` is omitted entirely when subtitles are disabled.)

### 6. Render

```bash
python scripts/render.py "<video>" work/<video_stem>/PLAN.json "<config.output_dir>"
```

This probes the source video once, then renders every entry in `PLAN.json` into `config.output_dir`, printing each output path.

## Library-wide search

Because every transcript is cached under `transcripts/`, steps 2-5 can be re-run against any subset of already-transcribed videos to search for moments across the whole archive, not just the video just processed — skip step 1 for videos that are already cached.
