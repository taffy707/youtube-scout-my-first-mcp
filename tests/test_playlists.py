from datetime import datetime, timedelta, timezone

import pytest

from tests.fakes import CHANNEL_ID, FakeYouTube, make_ids
from yt_scout import validate
from yt_scout.store import Store
from yt_scout.validate import ChannelRef, InvalidInput
from yt_scout.youtube import YouTubeError

YC = ChannelRef("handle", "@ycombinator")
T0 = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)
PL_SCHOOL = "PL" + "s" * 32
PL_HOWTO = "PL" + "h" * 32
IDS = make_ids(120)


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


def fake():
    return FakeYouTube(IDS, playlists={
        PL_SCHOOL: {"title": "Startup School", "description": "Lectures for founders", "video_ids": IDS[:70]},
        PL_HOWTO: {"title": "How to Start a Startup", "video_ids": [IDS[5], "gone0000001", IDS[6]]},
    })


@pytest.fixture
def store():
    return Store(":memory:")


# --- validation --------------------------------------------------------------

@pytest.mark.parametrize("raw", [
    PL_SCHOOL,
    f" {PL_SCHOOL} ",
    f"https://www.youtube.com/playlist?list={PL_SCHOOL}",
    f"https://www.youtube.com/watch?v=dQw4w9WgXcQ&list={PL_SCHOOL}&index=3",
    f"youtube.com/playlist?list={PL_SCHOOL}",
])
def test_playlist_id_accepts(raw):
    assert validate.playlist_id(raw) == PL_SCHOOL


@pytest.mark.parametrize("raw", [
    "", None, "PL", "PLshort", "XX" + "a" * 32, "PL" + "a" * 32 + "!",
    f"https://evil.com/playlist?list={PL_SCHOOL}",
    "https://www.youtube.com/playlist",
])
def test_playlist_id_rejects(raw):
    with pytest.raises(InvalidInput) as exc:
        validate.playlist_id(raw)
    assert exc.value.field == "playlist"


# --- store -------------------------------------------------------------------

def test_store_playlists_round_trip(store):
    store.replace_playlists(CHANNEL_ID, [
        {"playlist_id": PL_SCHOOL, "title": "Startup School", "description": "d", "video_count": 70},
        {"playlist_id": PL_HOWTO, "title": "How to", "description": "", "video_count": 3},
    ], "2026-10-04T12:00:00+00:00")
    assert [p["playlist_id"] for p in store.get_playlists(CHANNEL_ID)] == [PL_SCHOOL, PL_HOWTO]
    assert store.get_playlist(PL_HOWTO)["title"] == "How to"
    assert store.get_fetched_at(f"playlists:{CHANNEL_ID}") == "2026-10-04T12:00:00+00:00"
    store.replace_playlists(CHANNEL_ID, [
        {"playlist_id": PL_HOWTO, "title": "How to", "description": "", "video_count": 3}], "later")
    assert [p["playlist_id"] for p in store.get_playlists(CHANNEL_ID)] == [PL_HOWTO]


def test_store_playlist_items_keep_order(store):
    store.replace_playlist_items(PL_HOWTO, ["b0000000000", "a0000000000", "b0000000000"], "t1")
    assert store.get_playlist_items(PL_HOWTO) == ["b0000000000", "a0000000000", "b0000000000"]
    assert store.get_fetched_at(f"playlist:{PL_HOWTO}") == "t1"
    store.replace_playlist_items(PL_HOWTO, ["c0000000000"], "t2")
    assert store.get_playlist_items(PL_HOWTO) == ["c0000000000"]
    assert store.get_playlist_items("PLnone") == []


# --- YouTube client ----------------------------------------------------------

def test_list_playlists_fetches_and_caches(store):
    yt = fake()
    clock = Clock(T0)
    client = yt.client(store, now=clock)
    first = client.list_playlists(YC)
    assert first["channel_id"] == CHANNEL_ID and first["from_cache"] is False
    assert [(p["title"], p["video_count"]) for p in first["playlists"]] == [
        ("Startup School", 70), ("How to Start a Startup", 3)]
    calls = len(yt.calls)
    clock.now = T0 + timedelta(days=6)
    assert client.list_playlists(YC)["from_cache"] is True
    assert len(yt.calls) == calls
    clock.now = T0 + timedelta(days=8)
    assert client.list_playlists(YC)["from_cache"] is False


def test_list_playlists_refresh_flag(store):
    yt = fake()
    client = yt.client(store, now=Clock(T0))
    client.list_playlists(YC)
    assert client.list_playlists(YC, refresh=True)["from_cache"] is False


def test_playlist_videos_paged_fetch_and_cache(store):
    yt = fake()
    clock = Clock(T0)
    client = yt.client(store, now=clock)
    result = client.playlist_videos(PL_SCHOOL)
    assert result["title"] == "Startup School"
    assert result["video_ids"] == IDS[:70]
    assert result["from_cache"] is False
    assert yt.calls_to("playlistItems") == 2
    assert store.get_video(IDS[0]) is not None
    calls = len(yt.calls)
    assert client.playlist_videos(PL_SCHOOL)["from_cache"] is True
    assert len(yt.calls) == calls


def test_playlist_videos_do_not_count_as_indexed_uploads(store):
    client = fake().client(store, now=Clock(T0))
    client.playlist_videos(PL_HOWTO)
    assert store.known_video_ids(CHANNEL_ID) == set()


def test_playlist_videos_skips_only_fetching_cached_videos(store):
    yt = fake()
    client = yt.client(store, now=Clock(T0))
    client.index_channel(YC)
    yt.calls.clear()
    client.playlist_videos(PL_SCHOOL)
    assert yt.calls_to("videos") == 0


def test_unknown_playlist(store):
    with pytest.raises(YouTubeError) as exc:
        fake().client(store).playlist_videos("PL" + "z" * 32)
    assert exc.value.code == "playlist_not_found"
