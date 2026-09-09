"""Walks a whole recording and labels each sample frame live or dead.

This is the application the 61-window evaluation cannot measure. Judging whether a
window is clip-worthy is a hard, subjective call; deciding whether the screen is showing
a shop, an inventory or a map is nearly a lookup, and it is the decision that would save
the most: on 2026-09-05, seventy of two hundred and sixty-two minutes were two chunks of
back-to-back shopping that had to be read in full to find nothing in them.

One frame per sample point, one word out. The prompt is deliberately not the full verdict
schema - a question this narrow answers in a single token, and the whole point is that it
has to be cheap enough to run over hours rather than over windows somebody already chose.

    python experiments/sweep_scene.py --video vod.mkv --interval 120 --out scene.json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# Imported as a sibling rather than through the package: this file also runs from
# inside the pipeline container, which mounts work/ but not experiments/.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from watch_window import Watcher, frame_size, token_estimate

SCENE_PROMPT = """Один кадр из записи стрима. Что на экране?

Ответь ровно одним словом из списка, без пояснений:
action - идёт игра, персонажи в мире, что-то происходит
menu - открыто меню, магазин, окно закупки, экран улучшений
inventory - открыт инвентарь, ящики, перетаскивание предметов
map - карта, сонар, навигационный экран
idle - игра идёт, но ничего не происходит: стоят, ждут, чёрный экран

Слово:"""

LIVE = {"action"}


def duration_of(video: str) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", video],
        capture_output=True, text=True, check=True,
    )
    return float(result.stdout.strip())


def grab(video: str, at: float, size: int, path: Path) -> bool:
    command = [
        "ffmpeg", "-nostdin", "-loglevel", "error", "-y",
        "-ss", f"{at:.3f}", "-i", video, "-frames:v", "1",
        "-vf", f"scale='min({size},iw)':-2", "-q:v", "3", str(path),
    ]
    return subprocess.run(command).returncode == 0 and path.exists()


def normalise(answer: str | None) -> str:
    """The one word, or "unparsed". None is a real answer here: a hosted model can
    return an empty message, and letting that raise loses every result collected so
    far when the run is only saved at the end."""
    if not answer or not answer.strip():
        return "unparsed"
    word = answer.strip().lower().split()[0]
    word = "".join(c for c in word if c.isalpha())
    return word if word in {"action", "menu", "inventory", "map", "idle"} else "unparsed"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--interval", type=float, default=120.0)
    parser.add_argument("--size", type=int, default=448)
    parser.add_argument("--model", default="Qwen/Qwen3-VL-4B-Instruct")
    parser.add_argument("--start", type=float, default=0.0)
    parser.add_argument("--end", type=float, default=None)
    args = parser.parse_args()

    end = args.end if args.end is not None else duration_of(args.video)
    points = []
    at = args.start
    while at < end:
        points.append(round(at, 1))
        at += args.interval

    watcher = Watcher(args.model, max_new_tokens=8)
    results = []
    began_all = time.time()
    with tempfile.TemporaryDirectory(prefix="sweep-") as tmp:
        frame = Path(tmp) / "f.jpg"
        for index, at in enumerate(points, start=1):
            if frame.exists():
                frame.unlink()
            if not grab(args.video, at, args.size, frame):
                continue
            width, height = frame_size(frame)
            messages = [{"role": "user", "content": [
                {"type": "image", "path": str(frame)},
                {"type": "text", "text": SCENE_PROMPT},
            ]}]
            started = time.time()
            scene = normalise(watcher.watch(messages))
            results.append({"at": at, "scene": scene,
                            "seconds": round(time.time() - started, 2),
                            "image_tokens": token_estimate(1, width, height)})
            if index % 20 == 0 or index == len(points):
                print(f"{index}/{len(points)} кадров", file=sys.stderr)

    elapsed = time.time() - began_all
    counts: dict[str, int] = {}
    for row in results:
        counts[row["scene"]] = counts.get(row["scene"], 0) + 1
    Path(args.out).write_text(json.dumps({
        "video": args.video, "interval": args.interval,
        "wall_seconds": round(elapsed, 1), "counts": counts,
        "peak_vram_gb": watcher.peak_vram_gb(), "points": results,
    }, ensure_ascii=False), encoding="utf-8")
    print(f"{len(results)} кадров за {elapsed:.0f} с; " +
          ", ".join(f"{k} {v}" for k, v in sorted(counts.items())), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
