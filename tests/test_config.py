from pathlib import Path

import pytest

from yt_scout.config import load_settings


def test_defaults_when_env_empty():
    s = load_settings({})
    assert s.youtube_api_key is None
    assert s.gemini_api_key is None
    assert s.gemini_model == "gemini-3.7-flash"
    assert s.daily_video_seconds == 25200
    assert s.chunk_seconds == 180
    assert s.db_path == Path("~/.yt-scout/cache.db").expanduser()


def test_values_are_read_and_keys_stripped():
    s = load_settings({
        "YOUTUBE_API_KEY": "  yt-key \n",
        "GEMINI_API_KEY": "gm-key",
        "GEMINI_MODEL": "some-model",
        "GEMINI_DAILY_VIDEO_SECONDS": "3600",
        "WATCH_CHUNK_SECONDS": "120",
        "YT_SCOUT_DB": "/tmp/yt.db",
    })
    assert s.youtube_api_key == "yt-key"
    assert s.gemini_api_key == "gm-key"
    assert s.gemini_model == "some-model"
    assert s.daily_video_seconds == 3600
    assert s.chunk_seconds == 120
    assert s.db_path == Path("/tmp/yt.db")


def test_blank_key_is_none():
    assert load_settings({"GEMINI_API_KEY": "   "}).gemini_api_key is None


@pytest.mark.parametrize("name,value", [
    ("WATCH_CHUNK_SECONDS", "abc"),
    ("WATCH_CHUNK_SECONDS", "5"),
    ("WATCH_CHUNK_SECONDS", "5000"),
    ("GEMINI_DAILY_VIDEO_SECONDS", "-1"),
])
def test_bad_numbers_rejected(name, value):
    with pytest.raises(ValueError, match=name):
        load_settings({name: value})


def test_skim_model_defaults_to_none_and_is_read():
    assert load_settings({}).gemini_skim_model is None
    assert load_settings({"GEMINI_SKIM_MODEL": " gemini-3.5-flash-lite "}).gemini_skim_model == "gemini-3.5-flash-lite"
