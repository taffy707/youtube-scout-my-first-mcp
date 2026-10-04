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
                                       "get_transcript", "watch_video", "usage_status",
                                       "list_playlists", "list_playlist_videos"}


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


PL = "PL" + "s" * 32


def make_playlist_server(n_videos=60, with_youtube=True):
    store = Store(":memory:")
    settings = load_settings({"YOUTUBE_API_KEY": API_KEY})
    ids = make_ids(n_videos)
    yt = FakeYouTube(ids, playlists={PL: {"title": "Startup School", "description": "Lectures " * 80,
                                          "video_ids": ids + ["gone0000001"]}})
    youtube = yt.client(store) if with_youtube else None
    return build_server(Services(settings, store, youtube, TranscriptFetcher(store, api=FakeTranscriptApi()), None)), ids


def test_list_playlists_tool():
    server, _ = make_playlist_server()
    out = call(server, "list_playlists", {"channel": "@ycombinator"})
    assert out["count"] == 1
    p = out["playlists"][0]
    assert p["title"] == "Startup School" and p["video_count"] == 61
    assert len(p["description_snippet"]) <= 300
    assert p["url"] == f"https://www.youtube.com/playlist?list={PL}"


def test_list_playlist_videos_pages_and_skips_unavailable():
    server, ids = make_playlist_server(60)
    first = call(server, "list_playlist_videos", {"playlist": f"https://www.youtube.com/playlist?list={PL}"})
    assert first["title"] == "Startup School" and first["total_videos"] == 61
    assert [v["video_id"] for v in first["videos"]] == ids[:50]
    assert first["next_offset"] == 50
    v = first["videos"][0]
    assert set(v) == {"video_id", "title", "duration_s", "view_count", "published_at", "url"}
    second = call(server, "list_playlist_videos", {"playlist": PL, "offset": 50})
    assert [v["video_id"] for v in second["videos"]] == ids[50:]
    assert second["skipped_unavailable"] == 1
    assert second["next_offset"] is None


def test_list_playlist_videos_rejects_negative_offset():
    server, _ = make_playlist_server()
    assert call(server, "list_playlist_videos", {"playlist": PL, "offset": -1})["error"] == "invalid_input"


def test_playlist_tools_need_youtube_key():
    server, _ = make_playlist_server(with_youtube=False)
    assert call(server, "list_playlists", {"channel": "@ycombinator"})["error"] == "missing_api_key"
    assert call(server, "list_playlist_videos", {"playlist": PL})["error"] == "missing_api_key"


def test_instructions_mention_playlist_browsing():
    assert "list_playlists" in INSTRUCTIONS and "list_playlist_videos" in INSTRUCTIONS


def test_build_services_wires_separate_skim_model(tmp_path):
    from yt_scout.server import build_services
    settings = load_settings({"GEMINI_API_KEY": "k", "GEMINI_MODEL": "gemini-3.7-flash",
                              "GEMINI_SKIM_MODEL": "gemini-3.5-flash-lite", "YT_SCOUT_DB": str(tmp_path / "c.db")})
    watcher = build_services(settings).watcher
    assert watcher.model_for("skim") == "gemini-3.5-flash-lite"
    assert watcher.model_for("high") == "gemini-3.7-flash"


def test_build_services_without_skim_model_uses_main(tmp_path):
    from yt_scout.server import build_services
    settings = load_settings({"GEMINI_API_KEY": "k", "GEMINI_MODEL": "gemini-3.7-flash",
                              "YT_SCOUT_DB": str(tmp_path / "c.db")})
    assert build_services(settings).watcher.model_for("skim") == "gemini-3.7-flash"
