import asyncio
import json

import pytest

from tests.fakes import API_KEY, CHANNEL_ID, FakeAnalyzer, FakeTranscript, FakeTranscriptApi, FakeYouTube, make_ids
from yt_scout.config import load_settings
from yt_scout.gemini import Watcher
from yt_scout.server import INSTRUCTIONS, Services, build_server, redact
from yt_scout.store import Store
from yt_scout.transcripts import TranscriptFetcher

IDS = make_ids(3)


def make_server(with_youtube=True, with_watcher=True):
    store = Store(":memory:")
    settings = load_settings({"YOUTUBE_API_KEY": API_KEY, "GEMINI_API_KEY": "test-gemini-key"})
    youtube = FakeYouTube(IDS).client(store) if with_youtube else None
    transcripts = TranscriptFetcher(store, api=FakeTranscriptApi(
        [FakeTranscript("en", False, [{"text": "track weekly growth", "start": 0.0, "duration": 5.0}])]))
    watcher = Watcher(store, FakeAnalyzer(), "test-model", 25200, 180, sleep=lambda s: None) if with_watcher else None
    return build_server(Services(settings, store, youtube, transcripts, watcher))


def call(server, name, args=None):
    result = asyncio.run(server.call_tool(name, args or {}))
    return json.loads(result.content[0].text)


def test_lists_all_tools():
    tools = asyncio.run(make_server().list_tools())
    assert {t.name for t in tools} == {"index_channel", "search_videos", "get_video_details",
                                       "get_transcript", "watch_video", "usage_status"}


def test_instructions_cover_workflow_and_untrusted_content():
    assert "untrusted" in INSTRUCTIONS
    assert "detail=\"skim\"" in INSTRUCTIONS
    assert "60 minutes" in INSTRUCTIONS


def test_index_then_search():
    server = make_server()
    indexed = call(server, "index_channel", {"channel": "https://www.youtube.com/@ycombinator/videos"})
    assert indexed["channel_id"] == CHANNEL_ID and indexed["total_videos"] == 3
    found = call(server, "search_videos", {"channel": "@ycombinator", "query": "metrics startup"})
    assert found["count"] == 3
    assert found["results"][0]["url"].startswith("https://www.youtube.com/watch?v=")


def test_search_before_index_explains_next_step():
    out = call(make_server(), "search_videos", {"channel": "@ycombinator", "query": "kpis"})
    assert out["error"] == "channel_not_indexed"
    assert "index_channel" in out["message"]


def test_invalid_input_is_returned_not_raised():
    out = call(make_server(), "get_video_details", {"video_id": "nope"})
    assert out["error"] == "invalid_input"


def test_video_details_fetches_uncached_video():
    out = call(make_server(), "get_video_details", {"video_id": IDS[0]})
    assert out["video_id"] == IDS[0]
    assert out["chapters"][1]["title"] == "Metrics that matter"
    assert out["url"].endswith(IDS[0])


def test_transcript_tool():
    out = call(make_server(), "get_transcript", {"video_id": IDS[0]})
    assert out["segments"] == [{"start_s": 0, "end_s": 5, "text": "track weekly growth"}]


def test_transcript_range_validation():
    out = call(make_server(), "get_transcript", {"video_id": IDS[0], "start_s": 50, "end_s": 10})
    assert out["error"] == "invalid_input"


def test_watch_video_clamps_range_and_adds_title():
    server = make_server()
    out = call(server, "watch_video", {"video_id": IDS[0], "focus": "KPIs", "start_s": 600, "end_s": 9999,
                                       "detail": "high"})
    assert out["start_s"] == 600 and out["end_s"] == 725  # fake video duration is 12m05s
    assert out["title"] == f"Video {IDS[0]}"
    status = call(server, "usage_status")
    assert status["gemini_video_seconds_used"] == 125


def test_watch_video_without_gemini_key():
    out = call(make_server(with_watcher=False), "watch_video", {"video_id": IDS[0], "focus": "KPIs"})
    assert out["error"] == "missing_api_key"
    assert "GEMINI_API_KEY" in out["message"]


def test_index_without_youtube_key():
    out = call(make_server(with_youtube=False), "index_channel", {"channel": "@ycombinator"})
    assert out["error"] == "missing_api_key"


def test_usage_status_shape():
    out = call(make_server(), "usage_status")
    assert out["gemini_video_seconds_cap"] == 25200
    assert out["gemini_video_seconds_remaining"] == 25200
    assert out["youtube_units_cap"] == 10000


def test_redact():
    assert redact("bad key AIzaXYZ in message", ["AIzaXYZ", ""]) == "bad key [REDACTED] in message"
