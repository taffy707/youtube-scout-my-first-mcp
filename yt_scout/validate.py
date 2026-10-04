import re
from dataclasses import dataclass
from datetime import date
from typing import Literal
from urllib.parse import parse_qs, urlparse

from yt_scout.errors import ToolError

VIDEO_ID_RE = re.compile(r"[A-Za-z0-9_-]{11}")
CHANNEL_ID_RE = re.compile(r"UC[A-Za-z0-9_-]{22}")
HANDLE_RE = re.compile(r"@[A-Za-z0-9._-]{3,30}")
MAX_FOCUS = 500
DETAILS = ("skim", "normal", "high")


class InvalidInput(ToolError):
    def __init__(self, field: str, reason: str):
        super().__init__("invalid_input", f"{field}: {reason}")
        self.field = field


@dataclass(frozen=True)
class ChannelRef:
    kind: Literal["id", "handle"]
    value: str


def _youtube_url(value: str):
    """Return (host, path, query) for a youtube.com / youtu.be URL, else None."""
    if value.startswith(("youtube.com/", "www.youtube.com/", "m.youtube.com/", "youtu.be/")):
        value = "https://" + value
    if not value.startswith(("http://", "https://")):
        return None
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    if host == "youtu.be" or host == "youtube.com" or host.endswith(".youtube.com"):
        return host, parsed.path, parse_qs(parsed.query)
    return None


def video_id(value: str) -> str:
    raw = (value or "").strip()
    if VIDEO_ID_RE.fullmatch(raw):
        return raw
    url = _youtube_url(raw)
    if url:
        host, path, query = url
        parts = [p for p in path.split("/") if p]
        candidate = ""
        if host == "youtu.be" and parts:
            candidate = parts[0]
        elif path == "/watch":
            candidate = (query.get("v") or [""])[0]
        elif len(parts) >= 2 and parts[0] in ("live", "shorts", "embed"):
            candidate = parts[1]
        if VIDEO_ID_RE.fullmatch(candidate):
            return candidate
    raise InvalidInput("video_id", "expected an 11-character YouTube video ID or a youtube.com / youtu.be video URL")


def channel(value: str) -> ChannelRef:
    raw = (value or "").strip()
    url = _youtube_url(raw)
    if url:
        _, path, _ = url
        parts = [p for p in path.split("/") if p]
        if parts and parts[0].startswith("@"):
            raw = parts[0]
        elif len(parts) >= 2 and parts[0] == "channel":
            raw = parts[1]
        else:
            raise InvalidInput("channel", "use the channel's @handle or a youtube.com/@handle or /channel/UC... URL")
    if CHANNEL_ID_RE.fullmatch(raw):
        return ChannelRef("id", raw)
    handle = raw if raw.startswith("@") else "@" + raw
    if HANDLE_RE.fullmatch(handle):
        return ChannelRef("handle", handle.lower())
    raise InvalidInput("channel", "expected a channel @handle, a UC... channel ID, or a channel URL")


def time_range(start_s: int | None, end_s: int | None, duration_s: int) -> tuple[int, int]:
    start = 0 if start_s is None else int(start_s)
    if start < 0:
        raise InvalidInput("start_s", "must be 0 or more")
    if end_s is None:
        if not duration_s:
            raise InvalidInput("end_s", "is required because this video's duration is unknown")
        end = duration_s
    else:
        end = int(end_s)
        if duration_s:
            end = min(end, duration_s)
    if end <= start:
        raise InvalidInput("end_s", "must be greater than start_s, and start_s must be inside the video")
    return start, end


def focus(text: str) -> str:
    cleaned = " ".join((text or "").split())
    if not cleaned:
        raise InvalidInput("focus", "must not be empty")
    if len(cleaned) > MAX_FOCUS:
        raise InvalidInput("focus", f"must be at most {MAX_FOCUS} characters")
    return cleaned


def detail(value: str) -> str:
    if value not in DETAILS:
        raise InvalidInput("detail", f"must be one of {', '.join(DETAILS)}")
    return value


def iso_date(value: str) -> date:
    try:
        return date.fromisoformat((value or "").strip())
    except ValueError:
        raise InvalidInput("published_after", "must be a date like 2024-01-31") from None


def limit(value: int | None, default: int = 25, maximum: int = 50) -> int:
    if value is None:
        return default
    return max(1, min(maximum, int(value)))


def watch_url(video_id: str, t: int | None = None) -> str:
    url = f"https://www.youtube.com/watch?v={video_id}"
    return url if t is None else f"{url}&t={int(t)}s"
