import requests

from scripts.youtube_analytics import (
    aggregate_reach_by_video,
    chunk_video_ids,
    download_report_csv,
    ensure_reach_job,
    fetch_analytics_for_videos,
    fetch_channel_performance,
    fetch_reach_by_video,
    fetch_traffic_sources_for_videos,
    fetch_video_statistics,
    get_own_channel,
    list_available_reach_reports,
    list_uploaded_videos,
    merge_performance_records,
    parse_reach_csv,
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


class FakeReportingService:
    """Mirrors the googleapiclient chained-resource shape for the pieces
    fetch_reach_by_video needs: jobs().list()/create() and
    jobs().reports().list() share one execute(), routed by which resource
    method was called last (mirrors FakeDataService's self._mode pattern).
    """

    def __init__(self, jobs_list_response=None, job_create_response=None, reports_list_response=None):
        self.jobs_list_response = jobs_list_response or {"jobs": []}
        self.job_create_response = job_create_response
        self.reports_list_response = reports_list_response or {"reports": []}
        self.create_calls = []
        self.reports_list_calls = []
        self._resource = None
        self._pending = None

    def jobs(self):
        self._resource = "jobs"
        return self

    def reports(self):
        self._resource = "reports"
        return self

    def list(self, **kwargs):
        if self._resource == "reports":
            self.reports_list_calls.append(kwargs)
            self._pending = "reports_list"
        else:
            self._pending = "jobs_list"
        return self

    def create(self, **kwargs):
        self.create_calls.append(kwargs)
        self._pending = "job_create"
        return self

    def execute(self):
        if self._pending == "jobs_list":
            return self.jobs_list_response
        if self._pending == "job_create":
            return self.job_create_response
        if self._pending == "reports_list":
            return self.reports_list_response
        raise AssertionError("execute() called with no pending request")


class FakeHttpResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, url, headers=None):
        self.calls.append((url, headers))
        return self.response


def test_ensure_reach_job_reuses_existing_job_for_same_report_type():
    service = FakeReportingService(
        jobs_list_response={"jobs": [{"id": "job1", "reportTypeId": "channel_reach_basic_a1"}]}
    )

    job_id = ensure_reach_job(service)

    assert job_id == "job1"
    assert service.create_calls == []


def test_ensure_reach_job_creates_when_none_exists():
    service = FakeReportingService(jobs_list_response={"jobs": []}, job_create_response={"id": "new-job"})

    job_id = ensure_reach_job(service)

    assert job_id == "new-job"
    assert service.create_calls == [{"body": {"reportTypeId": "channel_reach_basic_a1", "name": "shorts-maker-reach"}}]


def test_ensure_reach_job_ignores_jobs_for_other_report_types():
    service = FakeReportingService(
        jobs_list_response={"jobs": [{"id": "other-job", "reportTypeId": "channel_basic_a2"}]},
        job_create_response={"id": "new-reach-job"},
    )

    job_id = ensure_reach_job(service)

    assert job_id == "new-reach-job"


def test_list_available_reach_reports_returns_reports():
    service = FakeReportingService(reports_list_response={"reports": [{"id": "r1", "downloadUrl": "https://d1"}]})

    reports = list_available_reach_reports(service, "job1")

    assert reports == [{"id": "r1", "downloadUrl": "https://d1"}]
    assert service.reports_list_calls == [{"jobId": "job1"}]


def test_list_available_reach_reports_empty_when_none_yet():
    service = FakeReportingService(reports_list_response={"reports": []})

    assert list_available_reach_reports(service, "job1") == []


def test_download_report_csv_sends_bearer_token_and_returns_text():
    session = FakeSession(FakeHttpResponse("date,video_id\n2026-07-01,vid1\n"))

    text = download_report_csv("https://download", "tok123", session=session)

    assert text == "date,video_id\n2026-07-01,vid1\n"
    assert session.calls == [("https://download", {"Authorization": "Bearer tok123"})]


def test_parse_reach_csv_parses_rows():
    csv_text = (
        "date,channel_id,video_id,video_thumbnail_impressions,video_thumbnail_impressions_ctr\n"
        "2026-07-01,UC1,vid1,500,8.5\n"
        "2026-07-01,UC1,vid2,20,2.0\n"
    )

    rows = parse_reach_csv(csv_text)

    assert rows == [
        {"video_id": "vid1", "thumbnail_impressions": 500, "thumbnail_impressions_click_rate": 8.5},
        {"video_id": "vid2", "thumbnail_impressions": 20, "thumbnail_impressions_click_rate": 2.0},
    ]


def test_aggregate_reach_by_video_sums_impressions_and_weights_ctr():
    rows = [
        {"video_id": "vid1", "thumbnail_impressions": 100, "thumbnail_impressions_click_rate": 10.0},
        {"video_id": "vid1", "thumbnail_impressions": 300, "thumbnail_impressions_click_rate": 6.0},
    ]

    result = aggregate_reach_by_video(rows)

    # weighted mean: (100*10 + 300*6) / 400 = 7.0
    assert result == {"vid1": {"thumbnail_impressions": 400, "thumbnail_impressions_click_rate": 7.0}}


def test_aggregate_reach_by_video_empty_input():
    assert aggregate_reach_by_video([]) == {}


def test_fetch_reach_by_video_sums_across_every_available_daily_report(monkeypatch):
    service = FakeReportingService(
        jobs_list_response={"jobs": [{"id": "job1", "reportTypeId": "channel_reach_basic_a1"}]},
        reports_list_response={
            "reports": [{"id": "r1", "downloadUrl": "https://d1"}, {"id": "r2", "downloadUrl": "https://d2"}]
        },
    )
    csv_bodies = {
        "https://d1": (
            "date,channel_id,video_id,video_thumbnail_impressions,video_thumbnail_impressions_ctr\n"
            "2026-07-01,UC1,vid1,100,10.0\n"
        ),
        "https://d2": (
            "date,channel_id,video_id,video_thumbnail_impressions,video_thumbnail_impressions_ctr\n"
            "2026-07-02,UC1,vid1,300,6.0\n"
        ),
    }
    monkeypatch.setattr(
        "scripts.youtube_analytics.download_report_csv",
        lambda download_url, access_token, session=requests: csv_bodies[download_url],
    )

    result = fetch_reach_by_video(service, "tok")

    assert result == {"vid1": {"thumbnail_impressions": 400, "thumbnail_impressions_click_rate": 7.0}}


def test_fetch_reach_by_video_empty_when_job_freshly_created_with_no_reports():
    service = FakeReportingService(
        jobs_list_response={"jobs": []},
        job_create_response={"id": "brand-new-job"},
        reports_list_response={"reports": []},
    )

    assert fetch_reach_by_video(service, "tok") == {}


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
    impressions = {"vid1": {"thumbnail_impressions": 5000, "thumbnail_impressions_click_rate": 8.2}}

    merged = merge_performance_records(videos, statistics, analytics, traffic, impressions)

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
            "thumbnail_impressions": 5000,
            "thumbnail_impressions_click_rate": 8.2,
            "traffic_sources": {"YT_SHORTS": 775},
        }
    ]


class FakeDataService:
    """Combines channels/playlistItems/videos resources on one object, since
    fetch_channel_performance calls all three on the same data_service.
    """

    def __init__(self, channel_response, playlist_pages, video_stats_responses):
        self._channel_response = channel_response
        self._playlist_pages = list(playlist_pages)
        self._video_stats_responses = list(video_stats_responses)
        self._mode = None

    def channels(self):
        self._mode = "channels"
        return self

    def playlistItems(self):
        self._mode = "playlistItems"
        return self

    def videos(self):
        self._mode = "videos"
        return self

    def list(self, **kwargs):
        if self._mode == "channels":
            self._current = self._channel_response
        elif self._mode == "playlistItems":
            self._current = self._playlist_pages.pop(0)
        else:
            self._current = self._video_stats_responses.pop(0)
        return self

    def execute(self):
        return self._current


class BrokenAnalyticsService:
    def reports(self):
        return self

    def query(self, **kwargs):
        return self

    def execute(self):
        raise ConnectionResetError("simulated network block on youtubeanalytics.googleapis.com")


def test_fetch_channel_performance_fails_open_when_analytics_unreachable(capsys):
    data_service = FakeDataService(
        channel_response={"items": [{"id": "UC1", "contentDetails": {"relatedPlaylists": {"uploads": "UU1"}}}]},
        playlist_pages=[
            {"items": [{"snippet": {"resourceId": {"videoId": "vid1"}, "title": "T", "publishedAt": "t1"}}]}
        ],
        video_stats_responses=[{"items": [{"id": "vid1", "statistics": {"viewCount": "10"}}]}],
    )

    records = fetch_channel_performance(
        data_service, BrokenAnalyticsService(), start_date="2020-01-01", end_date="2020-02-01"
    )

    assert records == [
        {
            "video_id": "vid1",
            "title": "T",
            "published_at": "t1",
            "view_count": 10,
            "like_count": None,
            "comment_count": None,
            "views_in_range": None,
            "average_view_duration": None,
            "average_view_percentage": None,
            "thumbnail_impressions": None,
            "thumbnail_impressions_click_rate": None,
            "traffic_sources": {},
        }
    ]
    assert "unreachable" in capsys.readouterr().err


def test_fetch_channel_performance_skips_reach_when_reporting_service_not_passed():
    data_service = FakeDataService(
        channel_response={"items": [{"id": "UC1", "contentDetails": {"relatedPlaylists": {"uploads": "UU1"}}}]},
        playlist_pages=[
            {"items": [{"snippet": {"resourceId": {"videoId": "vid1"}, "title": "T", "publishedAt": "t1"}}]}
        ],
        video_stats_responses=[{"items": [{"id": "vid1", "statistics": {"viewCount": "10"}}]}],
    )
    analytics_service = FakeAnalyticsService({"rows": []})

    records = fetch_channel_performance(
        data_service, analytics_service, start_date="2020-01-01", end_date="2020-02-01"
    )

    assert records[0]["thumbnail_impressions"] is None


def test_fetch_channel_performance_wires_in_reach_data(monkeypatch):
    data_service = FakeDataService(
        channel_response={"items": [{"id": "UC1", "contentDetails": {"relatedPlaylists": {"uploads": "UU1"}}}]},
        playlist_pages=[
            {"items": [{"snippet": {"resourceId": {"videoId": "vid1"}, "title": "T", "publishedAt": "t1"}}]}
        ],
        video_stats_responses=[{"items": [{"id": "vid1", "statistics": {"viewCount": "10"}}]}],
    )
    analytics_service = FakeAnalyticsService({"rows": []})
    reporting_service = FakeReportingService()
    monkeypatch.setattr(
        "scripts.youtube_analytics.fetch_reach_by_video",
        lambda service, token: {"vid1": {"thumbnail_impressions": 5000, "thumbnail_impressions_click_rate": 8.2}},
    )

    records = fetch_channel_performance(
        data_service, analytics_service, reporting_service, "tok", start_date="2020-01-01", end_date="2020-02-01"
    )

    assert records[0]["thumbnail_impressions"] == 5000
    assert records[0]["thumbnail_impressions_click_rate"] == 8.2


def test_fetch_channel_performance_fails_open_when_reporting_api_unavailable(capsys):
    data_service = FakeDataService(
        channel_response={"items": [{"id": "UC1", "contentDetails": {"relatedPlaylists": {"uploads": "UU1"}}}]},
        playlist_pages=[
            {"items": [{"snippet": {"resourceId": {"videoId": "vid1"}, "title": "T", "publishedAt": "t1"}}]}
        ],
        video_stats_responses=[{"items": [{"id": "vid1", "statistics": {"viewCount": "10"}}]}],
    )
    analytics_service = FakeAnalyticsService({"rows": []})

    class BrokenReportingService:
        def jobs(self):
            return self

        def list(self, **kwargs):
            return self

        def execute(self):
            raise RuntimeError("simulated Reporting API disabled")

    records = fetch_channel_performance(
        data_service, analytics_service, BrokenReportingService(), "tok",
        start_date="2020-01-01", end_date="2020-02-01",
    )

    assert records[0]["thumbnail_impressions"] is None
    assert "Reporting API unavailable" in capsys.readouterr().err


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
            "thumbnail_impressions": None,
            "thumbnail_impressions_click_rate": None,
            "traffic_sources": {},
        }
    ]
