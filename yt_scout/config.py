import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    youtube_api_key: str | None
    gemini_api_key: str | None
    gemini_model: str
    daily_video_seconds: int
    chunk_seconds: int
    db_path: Path


def _key(env: Mapping[str, str], name: str) -> str | None:
    value = (env.get(name) or "").strip()
    return value or None


def _int(env: Mapping[str, str], name: str, default: int, lo: int, hi: int) -> int:
    raw = (env.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"{name} must be a whole number, got {raw!r}") from None
    if not lo <= value <= hi:
        raise ValueError(f"{name} must be between {lo} and {hi}, got {value}")
    return value


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    if env is None:
        load_dotenv(PROJECT_ROOT / ".env")
        env = dict(os.environ)
    return Settings(
        youtube_api_key=_key(env, "YOUTUBE_API_KEY"),
        gemini_api_key=_key(env, "GEMINI_API_KEY"),
        gemini_model=(env.get("GEMINI_MODEL") or "").strip() or "gemini-3.8-flash",
        daily_video_seconds=_int(env, "GEMINI_DAILY_VIDEO_SECONDS", 25200, 0, 86400),
        chunk_seconds=_int(env, "WATCH_CHUNK_SECONDS", 180, 30, 900),
        db_path=Path((env.get("YT_SCOUT_DB") or "").strip() or "~/.yt-scout/cache.db").expanduser(),
    )
