from scripts.youtube_analytics import (
    chunk_video_ids,
    fetch_analytics_for_videos,
    fetch_traffic_sources_for_videos,
    fetch_video_statistics,
    get_own_channel,
    list_uploaded_videos,
    merge_performance_records,
)


class FakeChannelsService:
    def __init__(self, response):
        self.response = response
        self.list_kwargs = None

    def channels(self):
        return self

    def list(self, **kwargs):
        self.list_kwargs = kwargs
        return self

    def execute(self):
        return self.response


class FakePlaylistItemsService:
    def __init__(self, pages):
        self.pages = list(pages)
        self.calls = []

    def playlistItems(self):
        return self

    def list(self, **kwargs):
        self.calls.append(kwargs)
        self._current = self.pages.pop(0)
        return self

    def execute(self):
        return self._current


class FakeVideosService:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def videos(self):
        return self

    def list(self, **kwargs):
        self.calls.append(kwargs)
        self._current = self.responses.pop(0)
        return self

    def execute(self):
        return self._current


class FakeAnalyticsService:
    def __init__(self, response):
        self.response = response
        self.query_kwargs = None

    def reports(self):
        return self

    def query(self, **kwargs):
        self.query_kwargs = kwargs
        return self

    def execute(self):
        return self.response


def test_chunk_video_ids_splits_by_size():
    assert chunk_video_ids(["a", "b", "c", "d", "e"], chunk_size=2) == [["a", "b"], ["c", "d"], ["e"]]


def test_chunk_video_ids_empty_input():
    assert chunk_video_ids([]) == []


def test_get_own_channel_extracts_id_and_uploads_playlist():
    service = FakeChannelsService(
        {"items": [{"id": "UC123", "contentDetails": {"relatedPlaylists": {"uploads": "UU123"}}}]}
    )

    result = get_own_channel(service)

    assert result == {"channel_id": "UC123", "uploads_playlist_id": "UU123"}
    assert service.list_kwargs == {"part": "contentDetails", "mine": True}


def test_list_uploaded_videos_single_page():
    service = FakePlaylistItemsService(
        [
            {
                "items": [
                    {
                        "snippet": {
                            "resourceId": {"videoId": "vid1"},
                            "title": "Первый",
                            "publishedAt": "2026-07-05T10:00:00Z",
                        }
                    }
                ]
            }
        ]
    )

    videos = list_uploaded_videos(service, "UU123")

    assert videos == [{"video_id": "vid1", "title": "Первый", "published_at": "2026-07-05T10:00:00Z"}]


def test_list_uploaded_videos_paginates_until_no_next_page_token():
    service = FakePlaylistItemsService(
        [
            {
                "items": [
                    {"snippet": {"resourceId": {"videoId": "vid1"}, "title": "A", "publishedAt": "t1"}},
                ],
                "nextPageToken": "PAGE2",
            },
            {
                "items": [
                    {"snippet": {"resourceId": {"videoId": "vid2"}, "title": "B", "publishedAt": "t2"}},
                ],
            },
        ]
    )

    videos = list_uploaded_videos(service, "UU123")

    assert [v["video_id"] for v in videos] == ["vid1", "vid2"]
    assert service.calls[1]["pageToken"] == "PAGE2"
    assert "pageToken" not in service.calls[0]


def test_fetch_video_statistics_parses_and_chunks(monkeypatch):
    service = FakeVideosService(
        [
            {"items": [{"id": "vid1", "statistics": {"viewCount": "786", "likeCount": "10", "commentCount": "0"}}]},
        ]
    )

    stats = fetch_video_statistics(service, ["vid1"])

    assert stats == {"vid1": {"view_count": 786, "like_count": 10, "comment_count": 0}}


def test_fetch_video_statistics_handles_missing_optional_counts():
    service = FakeVideosService([{"items": [{"id": "vid1", "statistics": {"viewCount": "5"}}]}])

    stats = fetch_video_statistics(service, ["vid1"])

    assert stats == {"vid1": {"view_count": 5, "like_count": None, "comment_count": None}}


def test_fetch_video_statistics_issues_one_request_per_chunk_of_50():
    ids = [f"vid{i}" for i in range(60)]
    service = FakeVideosService([{"items": []}, {"items": []}])

    fetch_video_statistics(service, ids)

    assert len(service.calls) == 2
    assert service.calls[0]["id"].count(",") == 49
    assert service.calls[1]["id"].count(",") == 9


def test_fetch_analytics_for_videos_returns_empty_dict_for_no_ids():
    assert fetch_analytics_for_videos(FakeAnalyticsService({}), "UC123", [], "2026-01-01", "2026-07-01") == {}


def test_fetch_analytics_for_videos_parses_rows():
    service = FakeAnalyticsService({"rows": [["vid1", 786, 12.5, 43.3], ["vid2", 455, 19.0, 65.5]]})

    result = fetch_analytics_for_videos(service, "UC123", ["vid1", "vid2"], "2026-01-01", "2026-07-01")

    assert result == {
        "vid1": {"views_in_range": 786, "average_view_duration": 12.5, "average_view_percentage": 43.3},
        "vid2": {"views_in_range": 455, "average_view_duration": 19.0, "average_view_percentage": 65.5},
    }
    assert service.query_kwargs["filters"] == "video==vid1,vid2"
    assert service.query_kwargs["dimensions"] == "video"


def test_fetch_analytics_for_videos_missing_row_simply_absent():
    service = FakeAnalyticsService({"rows": [["vid1", 786, 12.5, 43.3]]})

    result = fetch_analytics_for_videos(service, "UC123", ["vid1", "vid2"], "2026-01-01", "2026-07-01")

    assert "vid2" not in result


def test_fetch_traffic_sources_for_videos_groups_by_video():
    service = FakeAnalyticsService(
        {
            "rows": [
                ["vid1", "YT_SHORTS", 775],
                ["vid1", "SUBSCRIBER", 11],
                ["vid2", "YT_SEARCH", 5],
            ]
        }
    )

    result = fetch_traffic_sources_for_videos(service, "UC123", ["vid1", "vid2"], "2026-01-01", "2026-07-01")

    assert result == {"vid1": {"YT_SHORTS": 775, "SUBSCRIBER": 11}, "vid2": {"YT_SEARCH": 5}}


def test_fetch_traffic_sources_for_videos_empty_ids():
    assert fetch_traffic_sources_for_videos(FakeAnalyticsService({}), "UC123", [], "2026-01-01", "2026-07-01") == {}


def test_merge_performance_records_combines_all_sources():
    videos = [{"video_id": "vid1", "title": "Клип", "published_at": "2026-07-05T10:00:00Z"}]
    statistics = {"vid1": {"view_count": 786, "like_count": 10, "comment_count": 0}}
    analytics = {"vid1": {"views_in_range": 786, "average_view_duration": 12.5, "average_view_percentage": 43.3}}
    traffic = {"vid1": {"YT_SHORTS": 775}}

    merged = merge_performance_records(videos, statistics, analytics, traffic)

    assert merged == [
        {
            "video_id": "vid1",
            "title": "Клип",
            "published_at": "2026-07-05T10:00:00Z",
            "view_count": 786,
            "like_count": 10,
            "comment_count": 0,
            "views_in_range": 786,
            "average_view_duration": 12.5,
            "average_view_percentage": 43.3,
            "traffic_sources": {"YT_SHORTS": 775},
        }
    ]


def test_merge_performance_records_fills_gaps_for_video_with_no_data_yet():
    videos = [{"video_id": "vid2", "title": "Свежий", "published_at": "2026-07-06T00:00:00Z"}]

    merged = merge_performance_records(videos, statistics={}, analytics={}, traffic_sources={})

    assert merged == [
        {
            "video_id": "vid2",
            "title": "Свежий",
            "published_at": "2026-07-06T00:00:00Z",
            "view_count": None,
            "like_count": None,
            "comment_count": None,
            "views_in_range": None,
            "average_view_duration": None,
            "average_view_percentage": None,
            "traffic_sources": {},
        }
    ]
