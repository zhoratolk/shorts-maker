from __future__ import annotations

import argparse
import datetime
import json
from pathlib import Path

# Read-only scopes - this script never uploads/edits/deletes anything.
DATA_API_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"
ANALYTICS_API_SCOPE = "https://www.googleapis.com/auth/yt-analytics.readonly"
SCOPES = [DATA_API_SCOPE, ANALYTICS_API_SCOPE]

# videos.list's id filter accepts at most 50 ids per request.
MAX_VIDEO_IDS_PER_REQUEST = 50

# YouTube's own launch date - a safe "since the beginning" default so a
# first run captures every video's full lifetime history.
EPOCH_START_DATE = "2005-04-23"


def default_end_date() -> str:
    return datetime.date.today().isoformat()


def chunk_video_ids(video_ids: list[str], chunk_size: int = MAX_VIDEO_IDS_PER_REQUEST) -> list[list[str]]:
    return [video_ids[i : i + chunk_size] for i in range(0, len(video_ids), chunk_size)]


def load_credentials(client_secret_path: str, token_path: str, scopes: list[str] = SCOPES):
    """Loads cached OAuth credentials from token_path, refreshing an expired
    token or running the local-server consent flow (opens a browser, using
    client_secret_path's app credentials) when there's no usable token yet.
    Writes the resulting token back to token_path either way, so this is
    only interactive on the very first run (or after a revoke/expiry the
    refresh token itself can't recover from).
    """
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    credentials = None
    token_file = Path(token_path)
    if token_file.exists():
        credentials = Credentials.from_authorized_user_file(str(token_file), scopes)

    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(client_secret_path, scopes)
            credentials = flow.run_local_server(port=0)
        token_file.write_text(credentials.to_json(), encoding="utf-8")

    return credentials


def build_services(credentials):
    from googleapiclient.discovery import build

    data_service = build("youtube", "v3", credentials=credentials)
    analytics_service = build("youtubeAnalytics", "v2", credentials=credentials)
    return data_service, analytics_service


def get_own_channel(data_service) -> dict:
    """Returns {"channel_id", "uploads_playlist_id"} for the authenticated
    user's own channel - both needed by every other fetch below.
    """
    response = data_service.channels().list(part="contentDetails", mine=True).execute()
    item = response["items"][0]
    return {
        "channel_id": item["id"],
        "uploads_playlist_id": item["contentDetails"]["relatedPlaylists"]["uploads"],
    }


def list_uploaded_videos(data_service, playlist_id: str) -> list[dict]:
    """Paginates playlistItems.list for the channel's uploads playlist.
    Returns [{"video_id", "title", "published_at"}, ...] in playlist order
    (newest first).
    """
    videos = []
    page_token = None
    while True:
        request_kwargs = {"part": "snippet", "playlistId": playlist_id, "maxResults": 50}
        if page_token:
            request_kwargs["pageToken"] = page_token
        response = data_service.playlistItems().list(**request_kwargs).execute()
        for item in response.get("items", []):
            snippet = item["snippet"]
            videos.append(
                {
                    "video_id": snippet["resourceId"]["videoId"],
                    "title": snippet["title"],
                    "published_at": snippet["publishedAt"],
                }
            )
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    return videos


def fetch_video_statistics(data_service, video_ids: list[str]) -> dict[str, dict]:
    """videos.list statistics for every id, chunked to respect the API's
    50-ids-per-request limit. Returns {video_id: {"view_count", "like_count",
    "comment_count"}} - view_count is the platform's lifetime total, unlike
    the Analytics API metrics below which are scoped to a date range.
    """
    statistics_by_id: dict[str, dict] = {}
    for chunk in chunk_video_ids(video_ids):
        response = data_service.videos().list(part="statistics", id=",".join(chunk)).execute()
        for item in response.get("items", []):
            stats = item["statistics"]
            statistics_by_id[item["id"]] = {
                "view_count": int(stats["viewCount"]) if "viewCount" in stats else None,
                "like_count": int(stats["likeCount"]) if "likeCount" in stats else None,
                "comment_count": int(stats["commentCount"]) if "commentCount" in stats else None,
            }
    return statistics_by_id


def fetch_analytics_for_videos(
    analytics_service, channel_id: str, video_ids: list[str], start_date: str, end_date: str
) -> dict[str, dict]:
    """One reports.query call for up to ~500 videos at once (dimensions=video),
    returning average-view-duration/percentage - the retention/completion
    signal the Data API's statistics don't expose. Missing rows (video too
    new for analytics processing, or zero views in range) are simply absent
    from the response, not an error.
    """
    if not video_ids:
        return {}
    response = analytics_service.reports().query(
        ids=f"channel=={channel_id}",
        startDate=start_date,
        endDate=end_date,
        metrics="views,averageViewDuration,averageViewPercentage",
        dimensions="video",
        filters=f"video=={','.join(video_ids)}",
        maxResults=len(video_ids),
    ).execute()

    result = {}
    for row in response.get("rows", []):
        video_id, views_in_range, average_view_duration, average_view_percentage = row
        result[video_id] = {
            "views_in_range": views_in_range,
            "average_view_duration": average_view_duration,
            "average_view_percentage": average_view_percentage,
        }
    return result


def fetch_traffic_sources_for_videos(
    analytics_service, channel_id: str, video_ids: list[str], start_date: str, end_date: str
) -> dict[str, dict[str, int]]:
    """One reports.query call breaking down views per video by
    insightTrafficSourceType (e.g. YT_SHORTS, SUBSCRIBER, YT_SEARCH) -
    confirms whether a clip's views came from the Shorts feed algorithm
    picking it up vs. search/external/subscribers.
    """
    if not video_ids:
        return {}
    response = analytics_service.reports().query(
        ids=f"channel=={channel_id}",
        startDate=start_date,
        endDate=end_date,
        metrics="views",
        dimensions="video,insightTrafficSourceType",
        filters=f"video=={','.join(video_ids)}",
        maxResults=len(video_ids) * 20,
    ).execute()

    result: dict[str, dict[str, int]] = {}
    for row in response.get("rows", []):
        video_id, source_type, views = row
        result.setdefault(video_id, {})[source_type] = views
    return result


def merge_performance_records(
    videos: list[dict],
    statistics: dict[str, dict],
    analytics: dict[str, dict],
    traffic_sources: dict[str, dict[str, int]],
) -> list[dict]:
    """Combines playlist metadata + Data API stats + Analytics API metrics
    into one record per video, in the same order as `videos`.
    """
    empty_statistics = {"view_count": None, "like_count": None, "comment_count": None}
    empty_analytics = {"views_in_range": None, "average_view_duration": None, "average_view_percentage": None}

    merged = []
    for video in videos:
        video_id = video["video_id"]
        merged.append(
            {
                **video,
                **statistics.get(video_id, empty_statistics),
                **analytics.get(video_id, empty_analytics),
                "traffic_sources": traffic_sources.get(video_id, {}),
            }
        )
    return merged


def fetch_channel_performance(
    data_service, analytics_service, start_date: str = EPOCH_START_DATE, end_date: str | None = None
) -> list[dict]:
    end_date = end_date or default_end_date()
    channel = get_own_channel(data_service)
    videos = list_uploaded_videos(data_service, channel["uploads_playlist_id"])
    video_ids = [video["video_id"] for video in videos]

    statistics = fetch_video_statistics(data_service, video_ids)
    analytics = fetch_analytics_for_videos(analytics_service, channel["channel_id"], video_ids, start_date, end_date)
    traffic_sources = fetch_traffic_sources_for_videos(
        analytics_service, channel["channel_id"], video_ids, start_date, end_date
    )
    return merge_performance_records(videos, statistics, analytics, traffic_sources)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch this channel's own video performance (views, retention, traffic sources) "
        "via the YouTube Data + Analytics APIs, cached to a local JSON file"
    )
    parser.add_argument("output_path", help="Path to write the performance JSON cache to")
    parser.add_argument("--client-secret", default="client_secret.json", help="OAuth client secret JSON path")
    parser.add_argument("--token", default="token.json", help="Cached OAuth token JSON path")
    parser.add_argument("--start-date", default=EPOCH_START_DATE, help="YYYY-MM-DD (default: since YouTube existed)")
    parser.add_argument("--end-date", default=None, help="YYYY-MM-DD (default: today)")
    args = parser.parse_args()

    credentials = load_credentials(args.client_secret, args.token)
    data_service, analytics_service = build_services(credentials)
    records = fetch_channel_performance(
        data_service, analytics_service, start_date=args.start_date, end_date=args.end_date
    )

    output_path = Path(args.output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(records)} videos written to {output_path}")


if __name__ == "__main__":
    main()
