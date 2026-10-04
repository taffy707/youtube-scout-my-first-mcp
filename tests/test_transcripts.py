import pytest
from youtube_transcript_api import RequestBlocked, TranscriptsDisabled, VideoUnavailable

from tests.fakes import FakeTranscript, FakeTranscriptApi
from yt_scout.store import Store
from yt_scout.transcripts import TranscriptError, TranscriptFetcher, merge_blocks

VID = "vid00000001"
RAW = [
    {"text": "Welcome  to\nthe talk", "start": 0.0, "duration": 4.0},
    {"text": "today: KPIs", "start": 12.5, "duration": 5.0},
    {"text": "first, revenue", "start": 31.0, "duration": 6.0},
    {"text": "", "start": 40.0, "duration": 1.0},
    {"text": "then retention", "start": 65.0, "duration": 5.5},
]


def fetcher(api):
    return TranscriptFetcher(Store(":memory:"), api=api)


def test_merge_blocks_groups_by_30_seconds_and_cleans_text():
    assert merge_blocks(RAW) == [
        {"start_s": 0, "end_s": 31, "text": "Welcome to the talk today: KPIs"},
        {"start_s": 31, "end_s": 65, "text": "first, revenue"},
        {"start_s": 65, "end_s": 71, "text": "then retention"},
    ]


def test_merge_blocks_empty():
    assert merge_blocks([]) == []


def test_prefers_manual_english_over_auto():
    api = FakeTranscriptApi([FakeTranscript("en", True, [{"text": "auto", "start": 0, "duration": 1}]),
                             FakeTranscript("en", False, [{"text": "manual", "start": 0, "duration": 1}])])
    result = fetcher(api).get(VID)
    assert result["source"] == "manual" and result["segments"][0]["text"] == "manual"


def test_falls_back_to_auto_english_then_any_language():
    auto = FakeTranscriptApi([FakeTranscript("en", True, RAW)])
    assert fetcher(auto).get(VID)["source"] == "auto"
    spanish = FakeTranscriptApi([FakeTranscript("es", False, RAW)])
    result = fetcher(spanish).get(VID)
    assert result["language"] == "es" and result["source"] == "manual"


def test_range_filter_keeps_overlapping_blocks():
    result = fetcher(FakeTranscriptApi([FakeTranscript("en", False, RAW)])).get(VID, start_s=40, end_s=66)
    assert [s["start_s"] for s in result["segments"]] == [31, 65]


def test_cached_transcript_skips_api():
    api = FakeTranscriptApi([FakeTranscript("en", False, RAW)])
    f = fetcher(api)
    f.get(VID)
    f.get(VID)
    assert api.list_calls == 1


def test_disabled_captions_cached_as_no_captions():
    api = FakeTranscriptApi(error=TranscriptsDisabled(VID))
    f = fetcher(api)
    for _ in range(2):
        with pytest.raises(TranscriptError) as exc:
            f.get(VID)
        assert exc.value.code == "no_captions"
    assert api.list_calls == 1


def test_empty_transcript_list_is_no_captions():
    with pytest.raises(TranscriptError) as exc:
        fetcher(FakeTranscriptApi([])).get(VID)
    assert exc.value.code == "no_captions"


def test_blocked_is_reported_and_not_cached():
    api = FakeTranscriptApi(error=RequestBlocked(VID))
    f = fetcher(api)
    for _ in range(2):
        with pytest.raises(TranscriptError) as exc:
            f.get(VID)
        assert exc.value.code == "transcripts_blocked"
    assert api.list_calls == 2


def test_unavailable_video():
    with pytest.raises(TranscriptError) as exc:
        fetcher(FakeTranscriptApi(error=VideoUnavailable(VID))).get(VID)
    assert exc.value.code == "video_unavailable"
