#!/usr/bin/env python3
"""Watch windows of a recording with a local vision-language model.

Prototype, not a stage: it takes windows, hands the model frames plus the words said
inside each, and returns a short structured verdict. Nothing here writes to a plan.

Why windows and not the recording. A vision model does not stream video - it is handed a
fixed number of stills and told when each was taken. The frames are what cost: in the
Qwen-VL family one token covers a 28x28 block, so a 448-wide 16:9 frame is 16x9 = 144
tokens. Twenty seconds at 2 fps is 40 frames, under 6k tokens. A two-hour recording at
1 fps is 7200 frames and over a million, which is not a budgeting problem but an
impossibility on one card. So the model only looks at windows something cheaper chose.

Why the transcript goes in with the frames. The model reads text better than it hears
speech, and the speech is already transcribed to a higher standard than it could manage.
The frames say a car went into the sky; the transcript says the streamer had just
promised the route was safe.

    python watch_window.py --video vod.mkv --start 1830 --end 1852 --dry-run
    python watch_window.py --video vod.mkv --windows labels.json --out verdicts.json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# One token per 28x28 pixels, after the 2x2 merge the Qwen vision tower does. Close
# enough to budget with; measure on the real processor before trusting it to the token.
PIXELS_PER_TOKEN_SIDE = 28

PROMPT = """Ты смотришь короткий фрагмент записи стрима. Тебе даны кадры с отметками
времени и расшифровка речи внутри этого же окна.

Ответь строго одним JSON-объектом, без markdown и без пояснений вокруг:

{{
  "scene": "<action|menu|inventory|map|idle>",
  "visual": "что происходит на экране, одно-два предложения",
  "event": "самое заметное событие или null, если ничего не произошло",
  "event_at": <секунда события с точностью до десятых, или null>,
  "unspoken": <true, если на экране произошло что-то, чего нет в расшифровке>,
  "clipworthy": <0-5, насколько это тянет на самостоятельный вертикальный клип>,
  "why": "почему именно такая оценка, одно предложение",
  "index_line": "одна фраза для поиска этого момента позже, как его вспомнил бы человек"
}}

Правила:
- "scene": "action" - идёт игра, что-то происходит в мире. "menu"/"inventory"/"map" -
  открыт интерфейс, магазин, ящики, карта: игра на паузе, люди обсуждают закупку.
  "idle" - персонажи стоят, ничего не происходит.
- "event_at" - абсолютная секунда записи, бери её из отметок на кадрах.
- "index_line" пиши так, как о моменте потом сказали бы вслух: "слил мид",
  "машина улетела в небо", "проиграл боту в шахматы".
- Если кадры и расшифровка расходятся, верь кадрам: расшифровка могла потерять крик.
- Не выдумывай названий предметов и способностей игры, если не уверен.

Расшифровка окна:
{transcript}
"""


def extract_frames(video: str, start: float, end: float, fps: float, size: int,
                   out_dir: Path) -> list[tuple[float, Path]]:
    """Still frames from [start, end), evenly spaced, scaled to fit `size`.

    -ss before -i so ffmpeg seeks rather than decodes its way to the window; on a
    four-hour recording that is the difference between a second and a minute.
    """
    pattern = str(out_dir / "f%04d.jpg")
    command = [
        "ffmpeg", "-nostdin", "-loglevel", "error",
        "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", video,
        "-vf", f"fps={fps},scale='min({size},iw)':-2",
        "-q:v", "3", pattern,
    ]
    subprocess.run(command, check=True)

    frames = sorted(out_dir.glob("f*.jpg"))
    # Frame n was taken at start + n/fps. ffmpeg numbers from 1.
    return [(start + i / fps, path) for i, path in enumerate(frames)]


def frame_size(path: Path) -> tuple[int, int]:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    )
    width, height = result.stdout.strip().split(",")[:2]
    return int(width), int(height)


def token_estimate(frames: int, width: int, height: int) -> int:
    """Image tokens for `frames` frames of this actual size.

    Measured from the frame that came out of ffmpeg, not from --size. The scale filter
    constrains the width only, so a 448 request on 16:9 footage yields 448x252 - 16x9 =
    144 tokens, not the 256 a square frame would cost. Estimating from the requested
    side overstated every window by 1.8x, which is the safe direction to be wrong in
    and still the wrong number to plan a pipeline with.
    """
    return frames * (width // PIXELS_PER_TOKEN_SIDE) * (height // PIXELS_PER_TOKEN_SIDE)


def build_messages(frames: list[tuple[float, Path]], transcript: str) -> list[dict]:
    """Frames interleaved with their timestamps, then the instructions.

    The timestamp goes in as text immediately before its frame rather than in one list
    at the end: the model has to associate a picture with a moment, and the association
    it makes reliably is the one sitting next to the picture.
    """
    content: list[dict] = []
    for at, path in frames:
        content.append({"type": "text", "text": f"[t={at:.1f}s]"})
        # A plain path, not a file:// URI. The loader in transformers takes local paths
        # and http(s) URLs; whether it accepts file:// depends on the version, and a
        # prototype should not fail on its packaging.
        content.append({"type": "image", "path": str(path)})
    content.append({"type": "text", "text": PROMPT.format(transcript=transcript or "(тишина)")})
    return [{"role": "user", "content": content}]


def parse_verdict(text: str) -> dict:
    """The first parseable JSON object in the answer, or the raw text under an error key.

    Scanned with raw_decode from each opening brace rather than matched with a regex.
    `\\{.*\\}` under DOTALL is greedy: it spans from the first brace to the LAST one, so
    a model that echoes the schema before answering - which local models do - hands back
    a span that is two objects glued together and parses as neither. That reads as a
    refusal to answer when the answer was there.
    """
    decoder = json.JSONDecoder()
    for index, character in enumerate(text):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return {"error": "no JSON in the answer", "raw": text[:400]}


class Watcher:
    """Holds the model open across windows.

    One window per process meant reloading eight gigabytes of weights per window, so
    sixty windows measured the loader sixty times and the model once. Any timing taken
    that way is a timing of the disk.
    """

    def __init__(self, model_id: str, max_new_tokens: int):
        import torch
        from transformers import AutoModelForImageTextToText, AutoProcessor

        self.max_new_tokens = max_new_tokens
        self.processor = AutoProcessor.from_pretrained(model_id)
        # Pinned to card 0 of what this process can see rather than "auto". auto
        # silently spills layers to CPU when they do not fit, turning a seconds-long
        # inference into a minutes-long one - and then the measurement says the
        # approach is too slow when what was measured was the offload.
        # sdpa rather than the default: the fused path compiles a triton kernel at
        # first use, and the pipeline image has no C compiler ("Failed to find C
        # compiler"). sdpa is built into torch and needs nothing at runtime.
        self.model = AutoModelForImageTextToText.from_pretrained(
            model_id, dtype=torch.bfloat16, device_map={"": 0},
            attn_implementation="sdpa",
        )
        self.torch = torch

    def watch(self, messages: list[dict]) -> str:
        inputs = self.processor.apply_chat_template(
            messages, add_generation_prompt=True, tokenize=True,
            return_dict=True, return_tensors="pt",
        ).to(self.model.device)
        # Greedy on purpose. This answer is read by code, and a temperature that makes
        # the prose nicer also makes the field names creative.
        generated = self.model.generate(
            **inputs, max_new_tokens=self.max_new_tokens, do_sample=False
        )
        answer = generated[0][inputs["input_ids"].shape[1]:]
        return self.processor.decode(answer, skip_special_tokens=True)

    def peak_vram_gb(self) -> float:
        return round(self.torch.cuda.max_memory_allocated() / 1024 ** 3, 2)


def windows_from(args) -> list[dict]:
    if args.windows:
        rows = json.loads(Path(args.windows).read_text(encoding="utf-8"))
        return [dict(row) for row in rows]
    return [{"start": args.start, "end": args.end,
             "text": Path(args.transcript).read_text(encoding="utf-8") if args.transcript else ""}]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--video", help="single-window mode, or the default for --windows")
    parser.add_argument("--video-dir", help="--windows mode: directory holding <stem>.mkv")
    parser.add_argument("--start", type=float)
    parser.add_argument("--end", type=float)
    parser.add_argument("--windows", help="JSON list of {stem?,start,end,text}")
    parser.add_argument("--out", help="--windows mode: where to write the verdicts")
    parser.add_argument("--fps", type=float, default=2.0)
    parser.add_argument("--size", type=int, default=448,
                        help="longest frame side; halving it quarters the token cost")
    parser.add_argument("--max-frames", type=int, default=48)
    parser.add_argument("--transcript", help="single-window mode: file with the words")
    parser.add_argument("--model", default="Qwen/Qwen3-VL-4B-Instruct")
    parser.add_argument("--max-new-tokens", type=int, default=512)
    parser.add_argument("--keep-frames", metavar="DIR",
                        help="write the frames here instead of a temp dir - the point of "
                             "a calibration run is seeing what the model saw")
    parser.add_argument("--dry-run", action="store_true",
                        help="extract frames and print the cost, load nothing")
    args = parser.parse_args()

    rows = windows_from(args)
    watcher = None
    results = []

    for index, row in enumerate(rows, start=1):
        video = args.video
        if args.video_dir and row.get("stem"):
            video = str(Path(args.video_dir) / f"{row['stem']}.mkv")
        if not video:
            print("нет пути к видео", file=sys.stderr)
            return 1

        if args.keep_frames:
            directory = Path(args.keep_frames) / f"w{index:03d}"
            directory.mkdir(parents=True, exist_ok=True)
            context = None
        else:
            context = tempfile.TemporaryDirectory(prefix="watch-window-")
            directory = Path(context.name)

        try:
            frames = extract_frames(video, row["start"], row["end"],
                                    args.fps, args.size, directory)
            if not frames:
                print(f"окно {index}: ffmpeg не дал кадров", file=sys.stderr)
                continue
            if len(frames) > args.max_frames:
                # Thinned evenly rather than truncated: the end of a window is where
                # the punchline is, and cutting the tail throws away the reason to look.
                step = len(frames) / args.max_frames
                frames = [frames[int(i * step)] for i in range(args.max_frames)]

            width, height = frame_size(frames[0][1])
            tokens = token_estimate(len(frames), width, height)
            if args.dry_run:
                print(f"окно {index}: {len(frames)} кадров {width}x{height}, "
                      f"~{tokens} токенов", file=sys.stderr)
                continue

            if watcher is None:
                began = time.time()
                watcher = Watcher(args.model, args.max_new_tokens)
                print(f"модель загружена за {time.time() - began:.0f} с", file=sys.stderr)

            began = time.time()
            answer = watcher.watch(build_messages(frames, row.get("text", "")))
            elapsed = time.time() - began
            verdict = parse_verdict(answer)
            results.append({**{k: v for k, v in row.items() if k != "text"},
                            "verdict": verdict, "seconds": round(elapsed, 1),
                            "frames": len(frames), "image_tokens": tokens})
            print(f"окно {index}/{len(rows)} {row['start']:.0f}s "
                  f"{elapsed:.1f}с clipworthy={verdict.get('clipworthy')} "
                  f"scene={verdict.get('scene')}", file=sys.stderr)
        finally:
            if context is not None:
                context.cleanup()

    if watcher is not None:
        print(f"пик VRAM {watcher.peak_vram_gb()} ГБ", file=sys.stderr)
    if args.out:
        Path(args.out).write_text(json.dumps(results, ensure_ascii=False, indent=1),
                                  encoding="utf-8")
    elif results:
        print(json.dumps(results[0]["verdict"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
