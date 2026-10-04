from datetime import date

import pytest

from yt_scout import validate as v
from yt_scout.validate import ChannelRef, InvalidInput

VID = "dQw4w9WgXcQ"
CID = "UCcefcZRL2oaA_uBNeo5UOWg"


@pytest.mark.parametrize("raw", [
    VID,
    f" {VID} ",
    f"https://www.youtube.com/watch?v={VID}",
    f"https://m.youtube.com/watch?v={VID}&t=10s",
    f"https://youtu.be/{VID}?t=42",
    f"https://www.youtube.com/live/{VID}",
    f"https://www.youtube.com/shorts/{VID}",
    f"youtube.com/watch?v={VID}",
])
def test_video_id_accepts(raw):
    assert v.video_id(raw) == VID


@pytest.mark.parametrize("raw", [
    "", None, "short", VID + "1", "dQw4w9WgXc!",
    f"https://evil.com/watch?v={VID}",
    f"https://notyoutube.com/watch?v={VID}",
    "https://www.youtube.com/watch?v=bad",
    "'; DROP TABLE videos;--",
])
def test_video_id_rejects(raw):
    with pytest.raises(InvalidInput) as exc:
        v.video_id(raw)
    assert exc.value.code == "invalid_input"
    assert exc.value.field == "video_id"


@pytest.mark.parametrize("raw,expected", [
    ("@ycombinator", ChannelRef("handle", "@ycombinator")),
    ("@YCombinator", ChannelRef("handle", "@ycombinator")),
    ("ycombinator", ChannelRef("handle", "@ycombinator")),
    ("https://www.youtube.com/@ycombinator", ChannelRef("handle", "@ycombinator")),
    ("https://www.youtube.com/@ycombinator/videos", ChannelRef("handle", "@ycombinator")),
    ("youtube.com/@ycombinator", ChannelRef("handle", "@ycombinator")),
    (CID, ChannelRef("id", CID)),
    (f"https://www.youtube.com/channel/{CID}", ChannelRef("id", CID)),
])
def test_channel_accepts(raw, expected):
    assert v.channel(raw) == expected


@pytest.mark.parametrize("raw", [
    "", "@a", "ab", "@bad handle", "@x;drop",
    "https://www.youtube.com/c/ycombinator",
    "https://www.youtube.com/user/ycombinator",
    "https://evil.com/@ycombinator",
])
def test_channel_rejects(raw):
    with pytest.raises(InvalidInput):
        v.channel(raw)


def test_range_defaults_to_full_video():
    assert v.time_range(None, None, 600) == (0, 600)


def test_range_end_clamped_to_duration():
    assert v.time_range(100, 605, 600) == (100, 600)


@pytest.mark.parametrize("start,end,duration", [
    (-1, 100, 600),
    (300, 200, 600),
    (600, None, 600),
    (700, 800, 600),
    (0, None, 0),
])
def test_range_rejects(start, end, duration):
    with pytest.raises(InvalidInput):
        v.time_range(start, end, duration)


def test_range_unknown_duration_uses_given_end():
    assert v.time_range(0, 120, 0) == (0, 120)


def test_focus_normalises_whitespace_and_limits_length():
    assert v.focus("  what   KPIs\nmatter ") == "what KPIs matter"
    with pytest.raises(InvalidInput):
        v.focus("   ")
    with pytest.raises(InvalidInput):
        v.focus("x" * 501)


def test_detail():
    assert v.detail("high") == "high"
    with pytest.raises(InvalidInput):
        v.detail("ultra")


def test_iso_date():
    assert v.iso_date("2024-01-31") == date(2024, 1, 31)
    with pytest.raises(InvalidInput):
        v.iso_date("last year")


def test_limit_clamps():
    assert v.limit(None) == 25
    assert v.limit(0) == 1
    assert v.limit(1000) == 50


def test_watch_url():
    assert v.watch_url(VID) == f"https://www.youtube.com/watch?v={VID}"
    assert v.watch_url(VID, 754) == f"https://www.youtube.com/watch?v={VID}&t=754s"
