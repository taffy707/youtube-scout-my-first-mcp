from datetime import datetime, timedelta, timezone

import pytest

from tests.fakes import CHANNEL_ID, FakeYouTube, make_ids
from yt_scout.store import Store
from yt_scout.validate import ChannelRef
from yt_scout.youtube import YouTubeError, parse_chapters, parse_iso_duration

YC = ChannelRef("handle", "@ycombinator")
T0 = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


@pytest.fixture
def store():
    return Store(":memory:")


def test_make_ids_are_valid_and_unique():
    ids = make_ids(120)
    assert len(set(ids)) == 120 and all(len(i) == 11 for i in ids)


def test_first_index_fetches_everything(store):
    fake = FakeYouTube(make_ids(120))
    result = fake.client(store, now=Clock(T0)).index_channel(YC)
    assert result["channel_id"] == CHANNEL_ID
    assert result["title"] == "Y Combinator"
    assert result["total_videos"] == 120 and result["new_videos"] == 120
    assert result["from_cache"] is False
    assert fake.calls_to("playlistItems") == 3
    assert fake.calls_to("videos") == 3
    video = store.get_video(make_ids(120)[0])
    assert video["duration_s"] == 725
    assert video["view_count"] == 1234
    assert video["chapters"] == [{"start_s": 0, "title": "Intro"}, {"start_s": 90, "title": "Metrics that matter"}]
    assert video["thumbnail_url"].endswith("hqdefault.jpg")


def test_second_call_within_seven_days_uses_cache(store):
    fake = FakeYouTube(make_ids(10))
    clock = Clock(T0)
    client = fake.client(store, now=clock)
    client.index_channel(YC)
    calls = len(fake.calls)
    clock.now = T0 + timedelta(days=6)
    result = client.index_channel(YC)
    assert result["from_cache"] is True and result["total_videos"] == 10
    assert len(fake.calls) == calls


def test_stale_channel_is_refreshed_and_stops_at_known_video(store):
    ids = make_ids(120)
    fake = FakeYouTube(ids)
    clock = Clock(T0)
    client = fake.client(store, now=clock)
    client.index_channel(YC)
    fake.video_ids = ["new00000001", "new00000002"] + ids
    fake.calls.clear()
    clock.now = T0 + timedelta(days=8)
    result = client.index_channel(YC)
    assert result["new_videos"] == 2 and result["total_videos"] == 122
    assert fake.calls_to("playlistItems") == 1
    assert fake.calls_to("videos") == 1


def test_refresh_flag_forces_reindex(store):
    fake = FakeYouTube(make_ids(5))
    client = fake.client(store, now=Clock(T0))
    client.index_channel(YC)
    fake.video_ids = ["new00000001"] + fake.video_ids
    assert client.index_channel(YC, refresh=True)["new_videos"] == 1


def test_quota_failure_mid_index_is_recovered_on_next_call(store):
    ids = make_ids(120)
    # calls 1-5 succeed: channels, 3 playlist pages, first videos batch; call 6 fails
    fake = FakeYouTube(ids, quota_fail_after=5)
    client = fake.client(store, now=Clock(T0))
    with pytest.raises(YouTubeError) as exc:
        client.index_channel(YC)
    assert exc.value.code == "youtube_quota_exceeded"
    assert store.count_videos(CHANNEL_ID) == 50
    assert store.get_channel(YC)["fully_indexed"] is False

    fake.quota_fail_after = None
    result = client.index_channel(YC)
    assert result["total_videos"] == 120
    assert result["new_videos"] == 70


def test_unknown_channel(store):
    fake = FakeYouTube([])
    with pytest.raises(YouTubeError) as exc:
        fake.client(store).index_channel(ChannelRef("handle", "@nobody123"))
    assert exc.value.code == "channel_not_found"


def test_usage_counts_every_api_call(store):
    fake = FakeYouTube(make_ids(10))
    fake.client(store, now=Clock(T0)).index_channel(YC)
    assert store.get_usage("2026-10-04", "youtube_units") == len(fake.calls)


def test_fetch_video_caches_single_video(store):
    ids = make_ids(3)
    fake = FakeYouTube(ids)
    client = fake.client(store)
    assert client.fetch_video(ids[1])["video_id"] == ids[1]
    assert store.get_video(ids[1]) is not None
    assert client.fetch_video("zzzzzzzzzzz") is None


@pytest.mark.parametrize("raw,expected", [
    ("PT12M5S", 725), ("PT1H", 3600), ("PT1H2M3S", 3723), ("P1DT2H", 93600),
    ("PT45S", 45), ("P0D", 0), ("", 0), (None, 0), ("garbage", 0),
])
def test_parse_iso_duration(raw, expected):
    assert parse_iso_duration(raw) == expected


def test_parse_chapters():
    desc = "Intro text\n00:00 Welcome\n(1:02:03) Deep dive\n12:30 - Hiring\nAt 3:45 he said\n"
    assert parse_chapters(desc) == [
        {"start_s": 0, "title": "Welcome"},
        {"start_s": 750, "title": "Hiring"},
        {"start_s": 3723, "title": "Deep dive"},
    ]


def test_parse_chapters_needs_two():
    assert parse_chapters("0:00 Only one") == []
