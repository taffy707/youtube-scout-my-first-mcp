import asyncio
import json
from dataclasses import replace

import pytest

from yt_scout.config import load_settings
from yt_scout.server import build_server, build_services

pytestmark = pytest.mark.live


def call(server, name, args=None):
    return json.loads(asyncio.run(server.call_tool(name, args or {})).content[0].text)


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    settings = load_settings()
    if not (settings.youtube_api_key and settings.gemini_api_key):
        pytest.skip("YOUTUBE_API_KEY and GEMINI_API_KEY must be set in .env")
    settings = replace(settings, db_path=tmp_path_factory.mktemp("live") / "cache.db")
    return build_server(build_services(settings))


def test_end_to_end(server):
    indexed = call(server, "index_channel", {"channel": "@ycombinator"})
    assert "error" not in indexed, indexed
    assert indexed["total_videos"] > 100

    found = call(server, "search_videos", {"channel": "@ycombinator", "query": "startup metrics KPIs", "limit": 5})
    assert found["count"] > 0, found
    video_id = found["results"][0]["video_id"]

    transcript = call(server, "get_transcript", {"video_id": video_id, "start_s": 0, "end_s": 120})
    assert "segments" in transcript or transcript.get("error") in ("no_captions", "transcripts_blocked"), transcript

    watched = call(server, "watch_video", {"video_id": video_id, "focus": "startup metrics and KPIs",
                                           "start_s": 0, "end_s": 120, "detail": "normal"})
    assert "error" not in watched, watched
    assert all(0 <= n["timestamp_s"] <= 120 for n in watched["notes"]), watched["notes"]

    status = call(server, "usage_status")
    assert status["gemini_video_seconds_used"] >= 120
