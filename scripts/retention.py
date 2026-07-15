"""Audience-retention analysis: pull the per-video retention CURVE (where
inside each clip viewers drop off, not just the average %), distil it into
actionable shape metrics, and roll those up into an insights file the
make-shorts skill reads back during auto-select scoring - so the pipeline
learns from its own published clips (which hook strengths / clip lengths
actually hold viewers) instead of guessing every run.

The aggregate average-view-% signal already lives in youtube_analytics.py;
this module is strictly the moment-by-moment curve (elapsedVideoTimeRatio x
audienceWatchRatio) and the learning loop built on top of it.

Pure functions (analyze_curve/summarize_retention/render/classify) take
plain data and are fully unit-tested; the API fetch and main() are the only
network-touching parts. All real-channel output lands under work/ (gitignored
privacy boundary) - never committed.
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

# The retention curve is a single Analytics query per video: the
# elapsedVideoTimeRatio dimension buckets the clip into ~100 equal slices
# (0.00..1.00) and audienceWatchRatio is the fraction of viewers still
# watching at each slice (1.0 = everyone who started is still here).
# elapsedVideoTimeRatio CANNOT be batched across videos (unlike the
# aggregate metrics in youtube_analytics.py) - it needs one video== filter,
# so one request per video.
CURVE_DIMENSION = "elapsedVideoTimeRatio"
CURVE_METRIC = "audienceWatchRatio"

# A single inter-slice drop this large (in watch-ratio) is a "cliff" - a spot
# where a noticeable chunk of the remaining audience left at once. Tunable via
# analyze_curve(cliff_threshold=...).
DEFAULT_CLIFF_THRESHOLD = 0.05

# If viewers are still mostly present at the end of the clip, the clip could
# likely have run longer (there was appetite left); if they've mostly left
# well before the end, it dragged. These bound the "length signal" verdict.
LONGER_OK_END_RATIO = 0.7
TOO_LONG_END_RATIO = 0.35


def fetch_retention_curve(
    analytics_service,
    channel_id: str,
    video_id: str,
    start_date: str,
    end_date: str,
) -> list[tuple[float, float]]:
    """One reports.query for a single video's retention curve. Returns
    [(elapsed_ratio, watch_ratio), ...] sorted by elapsed_ratio. An empty
    list means the video has no retention data yet (too new / too few views
    for YouTube to compute a curve) - callers treat that as "skip", not an
    error.
    """
    response = analytics_service.reports().query(
        ids=f"channel=={channel_id}",
        startDate=start_date,
        endDate=end_date,
        metrics=CURVE_METRIC,
        dimensions=CURVE_DIMENSION,
        filters=f"video=={video_id}",
        maxResults=200,
    ).execute()

    curve = [(float(row[0]), float(row[1])) for row in response.get("rows", [])]
    curve.sort(key=lambda point: point[0])
    return curve


def _watch_at(curve: list[tuple[float, float]], target_elapsed: float) -> float:
    """Watch-ratio of the curve point nearest target_elapsed."""
    return min(curve, key=lambda point: abs(point[0] - target_elapsed))[1]


def analyze_curve(
    curve: list[tuple[float, float]],
    *,
    cliff_threshold: float = DEFAULT_CLIFF_THRESHOLD,
) -> dict:
    """Reduces a retention curve to actionable shape metrics:

    - intro_retention: watch-ratio right after the start (~5% in) - the hook
      test; how many viewers survive the first moment.
    - end_retention: watch-ratio near the very end - did anyone make it.
    - average_watch: mean watch-ratio across the whole curve.
    - biggest_drop: {at, delta} - the single steepest inter-slice decline and
      where (elapsed_ratio) it happens; the prime "fix this spot" pointer.
    - cliffs: every elapsed_ratio where the step decline exceeded
      cliff_threshold, earliest first.
    - length_signal: "could_be_longer" | "too_long" | "ok" (see verdict bands).

    Empty/one-point curves return a zeroed record with length_signal="unknown"
    so downstream aggregation can simply skip them.
    """
    if len(curve) < 2:
        return {
            "intro_retention": None,
            "end_retention": None,
            "average_watch": None,
            "biggest_drop": None,
            "cliffs": [],
            "length_signal": "unknown",
            "points": len(curve),
        }

    intro_retention = _watch_at(curve, 0.05)
    end_retention = curve[-1][1]
    average_watch = statistics.fmean(point[1] for point in curve)

    biggest_drop = {"at": None, "delta": 0.0}
    cliffs: list[float] = []
    for (prev_elapsed, prev_watch), (elapsed, watch) in zip(curve, curve[1:]):
        delta = prev_watch - watch  # positive = viewers left over this slice
        if delta > biggest_drop["delta"]:
            biggest_drop = {"at": round(elapsed, 4), "delta": round(delta, 4)}
        if delta > cliff_threshold:
            cliffs.append(round(elapsed, 4))

    if end_retention >= LONGER_OK_END_RATIO:
        length_signal = "could_be_longer"
    elif end_retention <= TOO_LONG_END_RATIO:
        length_signal = "too_long"
    else:
        length_signal = "ok"

    return {
        "intro_retention": round(intro_retention, 4),
        "end_retention": round(end_retention, 4),
        "average_watch": round(average_watch, 4),
        "biggest_drop": biggest_drop if biggest_drop["at"] is not None else None,
        "cliffs": cliffs,
        "length_signal": length_signal,
        "points": len(curve),
    }


def _mean_or_none(values: list[float]) -> float | None:
    usable = [value for value in values if value is not None]
    return round(statistics.fmean(usable), 4) if usable else None


def summarize_retention(records: list[dict]) -> dict:
    """Rolls per-clip analyses into channel-level learning signals.

    Each record: {"video_id", optional "title", optional "tag", optional
    "duration", "analysis": <analyze_curve output>}. Records whose analysis
    is "unknown" (no curve) are ignored.

    Returns:
    - clips_analyzed: how many usable curves fed the summary.
    - mean_intro_retention / mean_average_watch: channel-wide hook & body
      strength.
    - length_signal_counts: tally of per-clip length verdicts (is the channel
      systematically over- or under-running).
    - common_cliff_zone: which fifth of the clip (0-20%, 20-40%, ...) most
      often contains a cliff - the recurring drop-off zone to design around.
    - by_tag: per moment-tag mean intro/average, when records carry tags -
      the "which kinds of moments hold viewers" ranking that biases
      auto-select. Absent when no record has a tag.
    """
    usable = [record for record in records if record["analysis"]["length_signal"] != "unknown"]
    if not usable:
        return {
            "clips_analyzed": 0,
            "mean_intro_retention": None,
            "mean_average_watch": None,
            "length_signal_counts": {},
            "common_cliff_zone": None,
            "by_tag": {},
        }

    length_counts: dict[str, int] = {}
    for record in usable:
        signal = record["analysis"]["length_signal"]
        length_counts[signal] = length_counts.get(signal, 0) + 1

    # Bucket every cliff into fifths of the clip and find the most common zone.
    zone_counts: dict[str, int] = {}
    for record in usable:
        for cliff in record["analysis"]["cliffs"]:
            fifth = min(int(cliff * 5), 4)  # clamp the 1.0 edge into the last bucket
            zone = f"{fifth * 20}-{fifth * 20 + 20}%"
            zone_counts[zone] = zone_counts.get(zone, 0) + 1
    common_cliff_zone = max(zone_counts, key=zone_counts.get) if zone_counts else None

    by_tag: dict[str, dict] = {}
    tagged = [record for record in usable if record.get("tag")]
    if tagged:
        tags = sorted({record["tag"] for record in tagged})
        for tag in tags:
            group = [record for record in tagged if record["tag"] == tag]
            by_tag[tag] = {
                "clips": len(group),
                "mean_intro_retention": _mean_or_none([r["analysis"]["intro_retention"] for r in group]),
                "mean_average_watch": _mean_or_none([r["analysis"]["average_watch"] for r in group]),
            }

    return {
        "clips_analyzed": len(usable),
        "mean_intro_retention": _mean_or_none([r["analysis"]["intro_retention"] for r in usable]),
        "mean_average_watch": _mean_or_none([r["analysis"]["average_watch"] for r in usable]),
        "length_signal_counts": length_counts,
        "common_cliff_zone": common_cliff_zone,
        "by_tag": by_tag,
    }


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.0f}%"


def render_retention_markdown(records: list[dict], summary: dict) -> str:
    """Human-readable digest: a channel-level takeaway block plus a per-clip
    table of the shape metrics, sorted worst-hook-first so the clips bleeding
    viewers earliest surface at the top.
    """
    lines = ["# Retention analysis", ""]

    if summary["clips_analyzed"] == 0:
        lines.append("No clips had retention data yet (too new or too few views).")
        return "\n".join(lines) + "\n"

    lines.append(f"Clips analyzed: **{summary['clips_analyzed']}**")
    lines.append(f"- Mean intro retention (hook): **{_pct(summary['mean_intro_retention'])}**")
    lines.append(f"- Mean average watch: **{_pct(summary['mean_average_watch'])}**")
    if summary["common_cliff_zone"]:
        lines.append(f"- Most common drop-off zone: **{summary['common_cliff_zone']}** of clip length")
    if summary["length_signal_counts"]:
        counts = ", ".join(f"{signal}: {count}" for signal, count in summary["length_signal_counts"].items())
        lines.append(f"- Length verdicts: {counts}")

    if summary["by_tag"]:
        lines.append("")
        lines.append("## By moment tag (best-holding first)")
        ranked = sorted(
            summary["by_tag"].items(),
            key=lambda item: item[1]["mean_average_watch"] or 0.0,
            reverse=True,
        )
        for tag, stats in ranked:
            lines.append(
                f"- **{tag}** ({stats['clips']} clips): intro {_pct(stats['mean_intro_retention'])}, "
                f"avg watch {_pct(stats['mean_average_watch'])}"
            )

    lines.append("")
    lines.append("## Per clip (worst hook first)")

    def hook_key(record: dict) -> float:
        intro = record["analysis"]["intro_retention"]
        return intro if intro is not None else 2.0  # unknowns sink to the bottom

    for record in sorted(records, key=hook_key):
        analysis = record["analysis"]
        if analysis["length_signal"] == "unknown":
            continue
        title = record.get("title") or record["video_id"]
        drop = analysis["biggest_drop"]
        drop_text = f"biggest drop {_pct(drop['delta'])} at {_pct(drop['at'])}" if drop else "no notable drop"
        lines.append(
            f"- **{title}** — hook {_pct(analysis['intro_retention'])}, "
            f"avg {_pct(analysis['average_watch'])}, end {_pct(analysis['end_retention'])}, "
            f"{drop_text} ({analysis['length_signal']})"
        )

    return "\n".join(lines) + "\n"


def write_retention_insights(summary: dict, path: str) -> None:
    """Writes the summary as JSON for the make-shorts skill to read back
    during auto-select scoring. Parent dirs are created; this lands under
    work/ in normal use (gitignored - real-channel derived).
    """
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_tag_map(publish_queue_path: str) -> dict[str, dict]:
    """Best-effort map video_id -> {tag, duration} from a publish queue file,
    so retention can be attributed to moment types. Missing file or absent
    fields degrade to an empty map (curve-shape signals still work)."""
    queue_file = Path(publish_queue_path)
    if not queue_file.exists():
        return {}
    try:
        queue = json.loads(queue_file.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}
    tag_map: dict[str, dict] = {}
    for entry in queue.get("entries", []):
        video_id = entry.get("video_id")
        if not video_id:
            continue
        tag_map[video_id] = {"tag": entry.get("moment_tag"), "duration": entry.get("source_duration")}
    return tag_map


def build_records(
    analytics_service,
    channel_id: str,
    videos: list[dict],
    start_date: str,
    end_date: str,
    tag_map: dict[str, dict] | None = None,
) -> list[dict]:
    """Fetches + analyzes one curve per video, attaching tag/duration from
    tag_map when present. `videos` is [{"video_id", "title"?}, ...] (the same
    shape youtube_analytics.list_uploaded_videos returns)."""
    tag_map = tag_map or {}
    records = []
    for video in videos:
        video_id = video["video_id"]
        curve = fetch_retention_curve(analytics_service, channel_id, video_id, start_date, end_date)
        extra = tag_map.get(video_id, {})
        records.append(
            {
                "video_id": video_id,
                "title": video.get("title"),
                "tag": extra.get("tag"),
                "duration": extra.get("duration"),
                "analysis": analyze_curve(curve),
            }
        )
    return records


def main() -> None:
    from scripts import youtube_analytics

    parser = argparse.ArgumentParser(
        description="Fetch per-video audience-retention curves, analyze where viewers drop off, and "
        "write a learning-insights JSON (for make-shorts auto-select) plus a markdown digest."
    )
    parser.add_argument("insights_path", help="Path to write the retention-insights JSON (use a work/ path)")
    parser.add_argument("--markdown", default=None, help="Optional path to also write the human-readable digest")
    parser.add_argument("--publish-queue", default=None, help="Publish queue JSON to attribute retention to moment tags")
    parser.add_argument("--client-secret", default="client_secret.json", help="OAuth client secret JSON path")
    parser.add_argument("--token", default="token.json", help="Cached OAuth token JSON path")
    parser.add_argument("--start-date", default=youtube_analytics.EPOCH_START_DATE, help="YYYY-MM-DD")
    parser.add_argument("--end-date", default=None, help="YYYY-MM-DD (default: today)")
    args = parser.parse_args()

    end_date = args.end_date or youtube_analytics.default_end_date()
    credentials = youtube_analytics.load_credentials(args.client_secret, args.token)
    data_service, analytics_service = youtube_analytics.build_services(credentials)
    channel = youtube_analytics.get_own_channel(data_service)
    videos = youtube_analytics.list_uploaded_videos(data_service, channel["uploads_playlist_id"])

    tag_map = _load_tag_map(args.publish_queue) if args.publish_queue else {}
    records = build_records(
        analytics_service, channel["channel_id"], videos, args.start_date, end_date, tag_map
    )
    summary = summarize_retention(records)
    write_retention_insights(summary, args.insights_path)
    print(f"{summary['clips_analyzed']} clips analyzed, insights written to {args.insights_path}")

    if args.markdown:
        Path(args.markdown).parent.mkdir(parents=True, exist_ok=True)
        Path(args.markdown).write_text(render_retention_markdown(records, summary), encoding="utf-8")
        print(f"digest written to {args.markdown}")


if __name__ == "__main__":
    main()
