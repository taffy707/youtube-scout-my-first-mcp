import json
from datetime import datetime, timezone

import pytest

from tests.fakes import FakeAnalyzer
from yt_scout.gemini import DETAIL_LEVELS, USAGE_KIND, GeminiUnavailable, Watcher
from yt_scout.store import Store

VID = "vid00000001"
DAY = "2026-10-04"
NOW = datetime(2026, 10, 4, 9, 0, tzinfo=timezone.utc)


def make(analyzer, cap=25200, store=None):
    store = store or Store(":memory:")
    sleeps = []
    watcher = Watcher(store, analyzer, "test-model", cap, 180, sleep=sleeps.append, now=lambda: NOW)
    return watcher, store, sleeps


def test_twelve_minute_high_watch_runs_four_parallel_chunks():
    analyzer = FakeAnalyzer()
    watcher, store, _ = make(analyzer)
    result = watcher.watch(VID, "startup KPIs", 0, 720, "high")
    assert sorted(c[1:3] for c in analyzer.calls) == [(0, 180), (180, 360), (360, 540), (540, 720)]
    assert all(c[3] == DETAIL_LEVELS["high"] for c in analyzer.calls)
    assert all(c[0] == f"https://www.youtube.com/watch?v={VID}" for c in analyzer.calls)
    assert [n["timestamp_s"] for n in result["notes"]] == [10, 190, 370, 550]
    assert result["notes"][1]["timestamp"] == "3:10"
    assert result["notes"][1]["url"].endswith("&t=190s")
    assert result["summary"] == "merged summary"
    assert result["segments_failed"] == []
    assert result["cached"] is False and result["video_seconds_charged"] == 720
    assert store.get_usage(DAY, USAGE_KIND) == 720


def test_single_chunk_uses_chunk_summary_without_merge_call():
    analyzer = FakeAnalyzer()
    watcher, _, _ = make(analyzer)
    result = watcher.watch(VID, "kpis", 60, 200, "normal")
    assert result["summary"] == "clip 60-200"
    assert analyzer.text_calls == []


def test_skim_uses_15_minute_chunks():
    analyzer = FakeAnalyzer()
    watcher, _, _ = make(analyzer)
    watcher.watch(VID, "map the video", 0, 2820, "skim")
    assert sorted(c[1:3] for c in analyzer.calls) == [(0, 900), (900, 1800), (1800, 2700), (2700, 2820)]


def test_repeat_watch_is_served_from_cache():
    analyzer = FakeAnalyzer()
    watcher, store, _ = make(analyzer)
    first = watcher.watch(VID, "KPIs", 0, 360, "high")
    calls = len(analyzer.calls)
    second = watcher.watch(VID, "  kpis ", 0, 360, "high")
    assert len(analyzer.calls) == calls
    assert second["cached"] is True and second["video_seconds_charged"] == 0
    assert second["notes"] == first["notes"]
    assert store.get_usage(DAY, USAGE_KIND) == 360


def test_different_focus_is_a_new_watch():
    analyzer = FakeAnalyzer()
    watcher, _, _ = make(analyzer)
    watcher.watch(VID, "KPIs", 0, 120, "high")
    watcher.watch(VID, "hiring", 0, 120, "high")
    assert len(analyzer.calls) == 2


def test_budget_exceeded_makes_no_calls():
    analyzer = FakeAnalyzer()
    watcher, store, _ = make(analyzer, cap=600)
    result = watcher.watch(VID, "KPIs", 0, 720, "high")
    assert result["error"] == "budget_exceeded"
    assert result["remaining_seconds"] == 600
    assert analyzer.calls == []
    assert store.get_usage(DAY, USAGE_KIND) == 0


def test_transient_errors_are_retried_with_backoff():
    def responder(cs, ce, attempt):
        return RuntimeError("503") if attempt < 2 else json.dumps({"summary": "ok", "notes": []})
    watcher, _, sleeps = make(FakeAnalyzer(responder))
    result = watcher.watch(VID, "KPIs", 0, 120, "normal")
    assert result["segments_failed"] == []
    assert sleeps == [2, 4]


def test_partial_failure_refunds_and_is_not_cached():
    def responder(cs, ce, attempt):
        return RuntimeError("boom") if cs == 180 else json.dumps(
            {"summary": "s", "notes": [{"timestamp": "00:05", "observation": "x"}]})
    analyzer = FakeAnalyzer(responder)
    watcher, store, _ = make(analyzer)
    result = watcher.watch(VID, "KPIs", 0, 720, "high")
    assert [(f["start_s"], f["end_s"]) for f in result["segments_failed"]] == [(180, 360)]
    assert "boom" in result["segments_failed"][0]["reason"]
    assert [n["timestamp_s"] for n in result["notes"]] == [5, 365, 545]
    assert result["video_seconds_charged"] == 540
    assert store.get_usage(DAY, USAGE_KIND) == 540
    calls = len(analyzer.calls)
    watcher.watch(VID, "KPIs", 0, 720, "high")
    assert len(analyzer.calls) > calls  # not cached, so retried


def test_rejected_video_fails_fast_and_refunds_everything():
    analyzer = FakeAnalyzer(lambda cs, ce, a: GeminiUnavailable("gemini_rejected", "Video unavailable"))
    watcher, store, sleeps = make(analyzer)
    result = watcher.watch(VID, "KPIs", 0, 360, "high")
    assert result["error"] == "gemini_rejected"
    assert len(result["segments_failed"]) == 2
    assert len(analyzer.calls) == 2 and sleeps == []
    assert store.get_usage(DAY, USAGE_KIND) == 0


def test_malformed_json_retried_then_reported():
    watcher, _, _ = make(FakeAnalyzer(lambda cs, ce, a: "not json"))
    result = watcher.watch(VID, "KPIs", 0, 120, "normal")
    assert result["error"] == "watch_failed"
    assert "malformed" in result["segments_failed"][0]["reason"]


def test_absolute_timestamps_from_model_not_double_offset():
    def responder(cs, ce, attempt):
        ts = "03:10" if cs == 180 else "00:10"
        return json.dumps({"summary": "s", "notes": [{"timestamp": ts, "observation": "x"}]})
    watcher, _, _ = make(FakeAnalyzer(responder))
    result = watcher.watch(VID, "KPIs", 0, 360, "high")
    assert [n["timestamp_s"] for n in result["notes"]] == [10, 190]


def test_merge_failure_falls_back_to_joined_chunk_summaries():
    analyzer = FakeAnalyzer()
    analyzer.complete_text = lambda prompt: (_ for _ in ()).throw(RuntimeError("down"))
    watcher, _, _ = make(analyzer)
    result = watcher.watch(VID, "KPIs", 0, 360, "high")
    assert result["summary"] == "clip 0-180 clip 180-360"


def test_absolute_timestamps_early_in_video_detected_per_chunk():
    # chunk 180-360: model answers in absolute time; 3:05 alone is ambiguous, 3:20 proves the chunk is absolute
    def responder(cs, ce, attempt):
        notes = [{"timestamp": "03:05", "observation": "a"}, {"timestamp": "03:20", "observation": "b"}] \
            if cs == 180 else []
        return json.dumps({"summary": "s", "notes": notes})
    watcher, _, _ = make(FakeAnalyzer(responder))
    result = watcher.watch(VID, "KPIs", 0, 360, "high")
    assert [n["timestamp_s"] for n in result["notes"]] == [185, 200]


class Overloaded(Exception):
    def __init__(self, code):
        super().__init__(f"{code} UNAVAILABLE")
        self.code = code


@pytest.mark.parametrize("code", [429, 503])
def test_overload_errors_back_off_longer(code):
    def responder(cs, ce, attempt):
        return Overloaded(code) if attempt < 2 else json.dumps({"summary": "ok", "notes": []})
    watcher, _, sleeps = make(FakeAnalyzer(responder))
    assert watcher.watch(VID, "KPIs", 0, 120, "normal")["segments_failed"] == []
    assert sleeps == [5, 20]
