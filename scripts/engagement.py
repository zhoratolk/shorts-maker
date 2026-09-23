"""How many viewers keep watching past the first seconds, and what that tracks.

The completion rate is not what decides how far a Short travels. This is:
YouTube's `engagedViews / views` - the "Реакция зрителей" bar in Studio, viewers
who kept watching versus viewers who swiped away. Measured 2026-09-10 over 228
published clips, it sits at a median of 43.7% on this channel and correlates
+0.35 with views: the clips that stalled at 100-250 views ran 17-24%, the ones
that reached 900+ ran 42-53% - inside the same batch, on the same day, in the
same game. The algorithm samples a clip on a small audience and only pushes what
holds, so this ratio is upstream of the view count rather than a summary of it.

Publish slot explains none of it (42-46% in every hour of the grid), and neither
do clip length, opening brightness, opening loudness or time-to-first-word. What
tracks it is the game, the kind of moment, and - the open question this script
exists to answer - whether the clip's first spoken line stands on its own or
leans on context the viewer has not seen. That last one is recorded by hand as
`opening` on each plan entry and carried into the publish queue; it is a
hypothesis until enough labelled clips have published to compare the two groups.

    python scripts/engagement.py --publish-queue work/_publish/queue.json
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path

# Below this a clip has not been shown to enough people for the ratio to mean
# anything: a handful of views can put it anywhere between 0 and 100%.
MIN_VIEWS = 80


def ratio_rows(engagement: dict[str, dict], entries: list[dict],
               min_views: int = MIN_VIEWS) -> list[dict]:
    """Joins per-video {views, engaged} onto queue entries, keeping only the
    clips with enough views for the ratio to carry information."""
    by_video = {entry["video_id"]: entry for entry in entries if entry.get("video_id")}
    rows = []
    for video_id, metrics in engagement.items():
        entry = by_video.get(video_id)
        views = metrics.get("views") or 0
        if entry is None or views < min_views:
            continue
        rows.append({
            "video_id": video_id,
            "views": views,
            "ratio": 100.0 * (metrics.get("engaged") or 0) / views,
            "opening": entry.get("opening"),
            "moment_tag": entry.get("moment_tag"),
            "game": (entry.get("tags") or [""])[0].lower().strip() or None,
        })
    return rows


def group_medians(rows: list[dict], field: str, min_group: int = 5) -> list[tuple]:
    """(value, count, median ratio) per distinct value of `field`, biggest
    median first, skipping groups too small to read anything into."""
    groups: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        if row.get(field) is not None:
            groups[row[field]].append(row["ratio"])
    out = [(value, len(values), statistics.median(values))
           for value, values in groups.items() if len(values) >= min_group]
    return sorted(out, key=lambda item: -item[2])


def fetch_engagement(analytics_service, channel_id: str, video_ids: list[str],
                     start_date: str, end_date: str) -> dict[str, dict]:
    """views + engagedViews per video, in one request per 200 ids."""
    from scripts.youtube_analytics import chunk_video_ids

    out: dict[str, dict] = {}
    for chunk in chunk_video_ids(video_ids, 200):
        response = analytics_service.reports().query(
            ids=f"channel=={channel_id}",
            startDate=start_date,
            endDate=end_date,
            metrics="views,engagedViews,averageViewPercentage",
            dimensions="video",
            filters=f"video=={','.join(chunk)}",
            maxResults=len(chunk),
        ).execute()
        for video_id, views, engaged, percentage in response.get("rows", []):
            out[video_id] = {"views": views, "engaged": engaged, "pct": percentage}
    return out


def render(rows: list[dict]) -> str:
    lines = [f"Клипов с {MIN_VIEWS}+ просмотров: {len(rows)}"]
    if rows:
        ratios = sorted(row["ratio"] for row in rows)
        lines.append(f"Медиана доли досмотревших дальше первых секунд: "
                     f"{statistics.median(ratios):.1f}%")
    for field, title in (("opening", "по типу начала"),
                         ("game", "по игре"),
                         ("moment_tag", "по тегу момента")):
        groups = group_medians(rows, field)
        if not groups:
            continue
        lines.append(f"\n{title}:")
        for value, count, median in groups:
            lines.append(f"  {value:18} n={count:3d} {median:5.1f}%")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    from scripts.youtube_auth import DEFAULT_TOKEN_PATH

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--publish-queue", default="work/_publish/queue.json")
    parser.add_argument("--client-secret", default="client_secret.json")
    parser.add_argument("--token", default=DEFAULT_TOKEN_PATH)
    parser.add_argument("--start-date", default="2026-07-01")
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--cache", default="work/_analytics/engagement.json",
                        help="Where the raw per-video numbers are written")
    args = parser.parse_args(argv)

    from scripts.youtube_analytics import (build_services, default_end_date,
                                           get_own_channel, load_credentials)

    entries = json.loads(Path(args.publish_queue).read_text(encoding="utf-8"))["entries"]
    video_ids = [entry["video_id"] for entry in entries if entry.get("video_id")]
    if not video_ids:
        print("в очереди нет опубликованных клипов")
        return 0

    credentials = load_credentials(args.client_secret, args.token)
    data_service, analytics_service, _reporting = build_services(credentials)
    channel_id = get_own_channel(data_service)["channel_id"]
    engagement = fetch_engagement(analytics_service, channel_id, video_ids,
                                  args.start_date, args.end_date or default_end_date())

    cache = Path(args.cache)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(engagement, ensure_ascii=False, indent=1), encoding="utf-8")
    print(render(ratio_rows(engagement, entries)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
