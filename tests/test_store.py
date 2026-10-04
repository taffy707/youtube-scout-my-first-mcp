import threading
from datetime import datetime, timezone

import pytest

from yt_scout.store import Store, utc_day
from yt_scout.validate import ChannelRef

CID = "UC" + "a" * 22


def video(vid, title="Title", description="", tags=None, duration_s=600, views=10,
          published_at="2024-05-01T12:00:00Z", channel_id=CID):
    return {
        "video_id": vid, "channel_id": channel_id, "title": title, "description": description,
        "tags": tags or [], "published_at": published_at, "duration_s": duration_s,
        "view_count": views, "thumbnail_url": None, "chapters": [{"start_s": 0, "title": "Intro"}],
    }


@pytest.fixture
def store():
    return Store(":memory:")


def test_file_db_creates_parent_dirs(tmp_path):
    path = tmp_path / "nested" / "cache.db"
    Store(path)
    assert path.exists()


def test_channel_round_trip_by_id_and_handle(store):
    store.upsert_channel(CID, "@YCombinator", "Y Combinator", "UU" + "a" * 22, None, False)
    by_handle = store.get_channel(ChannelRef("handle", "@ycombinator"))
    by_id = store.get_channel(ChannelRef("id", CID))
    assert by_handle == by_id
    assert by_id["title"] == "Y Combinator"
    assert by_id["fully_indexed"] is False
    store.upsert_channel(CID, None, "Y Combinator", "UU" + "a" * 22, "2026-10-04T00:00:00+00:00", True)
    again = store.get_channel(ChannelRef("handle", "@ycombinator"))
    assert again["fully_indexed"] is True and again["handle"] == "@ycombinator"


def test_video_round_trip_and_counts(store):
    store.upsert_videos([video("vid00000001", tags=["kpi", "growth metrics"]), video("vid00000002")])
    got = store.get_video("vid00000001")
    assert got["tags"] == ["kpi", "growth metrics"]
    assert got["chapters"] == [{"start_s": 0, "title": "Intro"}]
    assert store.known_video_ids(CID) == {"vid00000001", "vid00000002"}
    assert store.count_videos(CID) == 2
    assert store.get_video("vid99999999") is None


def test_upsert_replaces_search_index(store):
    store.upsert_videos([video("vid00000001", title="Old cooking title")])
    store.upsert_videos([video("vid00000001", title="Startup metrics")])
    assert store.search_videos(CID, '"cooking"') == []
    assert [v["video_id"] for v in store.search_videos(CID, '"metrics"')] == ["vid00000001"]


def test_transcript_round_trip(store):
    segs = [{"start": 0.0, "duration": 2.0, "text": "hello"}]
    store.put_transcript("vid00000001", "ok", "en", "manual", segs, "2026-10-04T00:00:00+00:00")
    got = store.get_transcript("vid00000001")
    assert got["status"] == "ok" and got["segments"] == segs and got["source"] == "manual"
    assert store.get_transcript("vid00000002") is None


def test_watch_round_trip(store):
    store.put_watch("k1", "vid00000001", 0, 180, "high", "kpis", "m", {"notes": [1]}, "2026-10-04T00:00:00+00:00")
    assert store.get_watch("k1") == {"notes": [1]}
    assert store.get_watch("k2") is None


def test_usage_is_per_day_and_kind(store):
    store.add_usage("2026-10-04", "gemini_video_s", 100)
    store.add_usage("2026-10-04", "gemini_video_s", 50)
    store.add_usage("2026-10-05", "gemini_video_s", 7)
    assert store.get_usage("2026-10-04", "gemini_video_s") == 150
    assert store.get_usage("2026-10-05", "gemini_video_s") == 7
    assert store.get_usage("2026-10-04", "youtube_units") == 0


def test_reserve_respects_cap(store):
    assert store.reserve_usage("d", "k", 60, cap=100) is True
    assert store.reserve_usage("d", "k", 50, cap=100) is False
    assert store.reserve_usage("d", "k", 40, cap=100) is True
    assert store.get_usage("d", "k") == 100


def test_reserve_is_atomic_across_threads(tmp_path):
    store = Store(tmp_path / "c.db")
    results = []
    threads = [threading.Thread(target=lambda: results.append(store.reserve_usage("d", "k", 10, cap=100)))
               for _ in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(True) == 10
    assert store.get_usage("d", "k") == 100


def test_utc_day():
    assert utc_day(datetime(2026, 10, 4, 23, 59, tzinfo=timezone.utc)) == "2026-10-04"


def test_old_database_gains_listed_column(tmp_path):
    import sqlite3
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE videos (video_id TEXT PRIMARY KEY, channel_id TEXT NOT NULL, title TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '', tags_json TEXT NOT NULL DEFAULT '[]', published_at TEXT,
        duration_s INTEGER NOT NULL DEFAULT 0, view_count INTEGER NOT NULL DEFAULT 0, thumbnail_url TEXT,
        chapters_json TEXT NOT NULL DEFAULT '[]')""")
    conn.commit()
    conn.close()
    store = Store(path)
    store.upsert_videos([video("vid00000001")])
    assert store.known_video_ids(CID) == {"vid00000001"}
