"""The same windows, the same prompt, a hosted model instead of the local one.

Exists so the local-versus-cloud question is answered by a measurement rather than by
whichever option was written up more persuasively. It imports the prompt and the answer
parser from watch_window rather than restating them: two copies of a prompt drift, and a
comparison between two drifted prompts measures the drift.

The key is read from a .env file by name and never printed. Frames leave the machine on
this path - they are stills from the owner's own recording, sent to the API the owner
asked for, and that is the whole reason this is a separate file from the local one.

    python experiments/cloud_window.py --windows labels.json --video-dir /srv/media/... \\
        --out cloud.json --model google/gemini-2.5-flash
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

# Imported as a sibling rather than through the package: this file also runs from
# inside the pipeline container, which mounts work/ but not experiments/.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from sweep_scene import SCENE_PROMPT, normalise
from watch_window import PROMPT, extract_frames, parse_verdict

ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"


def read_key(env_file: str, name: str) -> str:
    """The API key, by name, out of a .env file. Never returned to a log."""
    for line in Path(env_file).read_text(encoding="utf-8").splitlines():
        key, _, value = line.partition("=")
        if key.strip() == name:
            return value.strip().strip('"').strip("'")
    raise SystemExit(f"{name} нет в {env_file}")


def data_url(path: Path) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(path.read_bytes()).decode()


def build_content(frames: list[tuple[float, Path]], transcript: str,
                  scene_only: bool = False) -> list[dict]:
    """The full verdict, or just the one-word scene question.

    The narrow question exists to be run over a whole recording rather than over windows
    somebody already chose, so it must not carry the full schema: the schema is most of
    the prompt and all of the output.
    """
    if scene_only:
        return [{"type": "image_url", "image_url": {"url": data_url(frames[0][1])}},
                {"type": "text", "text": SCENE_PROMPT}]
    content: list[dict] = []
    for at, path in frames:
        content.append({"type": "text", "text": f"[t={at:.1f}s]"})
        content.append({"type": "image_url", "image_url": {"url": data_url(path)}})
    content.append({"type": "text",
                    "text": PROMPT.format(transcript=transcript or "(тишина)")})
    return content


def ask(key: str, model: str, content: list[dict], max_tokens: int) -> tuple[str, dict]:
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "max_tokens": max_tokens,
        # Greedy for the same reason the local run is: this answer is read by code.
        "temperature": 0,
        "usage": {"include": True},
    }).encode()
    request = urllib.request.Request(
        ENDPOINT, data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        payload = json.loads(response.read())
    text = payload["choices"][0]["message"]["content"]
    return text, payload.get("usage", {})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--windows", required=True)
    parser.add_argument("--video-dir", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--model", default="google/gemini-2.5-flash")
    parser.add_argument("--env-file", default="/d/shortmaker-business/.env")
    parser.add_argument("--key-name", default="OPENROUTER_API_KEY")
    parser.add_argument("--fps", type=float, default=2.0)
    parser.add_argument("--size", type=int, default=448)
    parser.add_argument("--max-frames", type=int, default=48)
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--limit", type=int, default=None, help="первые N окон")
    parser.add_argument("--scene-only", action="store_true",
                        help="один кадр и один вопрос вместо полного вердикта")
    args = parser.parse_args()

    key = read_key(args.env_file, args.key_name)
    rows = json.loads(Path(args.windows).read_text(encoding="utf-8"))
    if args.limit:
        rows = rows[: args.limit]

    results, spent = [], 0.0
    for index, row in enumerate(rows, start=1):
        video = str(Path(args.video_dir) / f"{row['stem']}.mkv")
        with tempfile.TemporaryDirectory(prefix="cloud-window-") as tmp:
            frames = extract_frames(video, row["start"], row["end"],
                                    args.fps, args.size, Path(tmp))
            if len(frames) > args.max_frames:
                step = len(frames) / args.max_frames
                frames = [frames[int(i * step)] for i in range(args.max_frames)]
            content = build_content(frames, row.get("text", ""), args.scene_only)
            began = time.time()
            try:
                answer, usage = ask(key, args.model, content, args.max_tokens)
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as error:
                detail = ""
                if isinstance(error, urllib.error.HTTPError):
                    detail = error.read()[:300].decode("utf-8", "replace")
                print(f"окно {index}: {error} {detail}", file=sys.stderr)
                continue
            elapsed = time.time() - began

        # The narrow question answers with a bare word, not an object, so it must not
        # go through the JSON parser - which would report every correct answer as a
        # failure to answer.
        verdict = ({"scene": normalise(answer)} if args.scene_only
                   else parse_verdict(answer))
        cost = float(usage.get("cost", 0.0) or 0.0)
        spent += cost
        results.append({**{k: v for k, v in row.items() if k != "text"},
                        "verdict": verdict, "seconds": round(elapsed, 1),
                        "frames": len(frames), "usage": usage})
        # Written after every window, not once at the end: a crash on window 193 of
        # 215 otherwise throws away 192 paid-for answers.
        Path(args.out).write_text(json.dumps(results, ensure_ascii=False, indent=1),
                                  encoding="utf-8")
        print(f"окно {index}/{len(rows)} {row['start']:.0f}s {elapsed:.1f}с "
              f"clipworthy={verdict.get('clipworthy')} scene={verdict.get('scene')} "
              f"${cost:.5f}", file=sys.stderr)

    Path(args.out).write_text(json.dumps(results, ensure_ascii=False, indent=1),
                              encoding="utf-8")
    print(f"{len(results)} окон, суммарно ${spent:.4f}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
