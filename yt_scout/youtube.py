import re
from datetime import datetime, timedelta
from typing import Callable

import httpx

from yt_scout.errors import ToolError
from yt_scout.store import Store, utc_day, utc_now
from yt_scout.validate import ChannelRef

API_BASE = "https://www.googleapis.com/youtube/v3"
STALE_AFTER = timedelta(days=7)
BATCH = 50

_DURATION = re.compile(r"^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$")
_CHAPTER = re.compile(r"^\s*\(?((?:\d{1,2}:)?\d{1,2}:\d{2})\)?\s*(?:[-–—:|]\s*)?(\S.*?)\s*$")


class YouTubeError(ToolError):
    pass


def parse_iso_duration(value: str | None) -> int:
    match = _DURATION.match(value or "")
    if not match or not value or value == "P":
        return 0
    days, hours, minutes, seconds = (int(x) if x else 0 for x in match.groups())
    return days * 86400 + hours * 3600 + minutes * 60 + seconds


def _hms(text: str) -> int:
    total = 0
    for part in text.split(":"):
        total = total * 60 + int(part)
    return total


def parse_chapters(description: str) -> list[dict]:
    chapters = []
    for line in (description or "").splitlines():
        match = _CHAPTER.match(line)
        if match:
            chapters.append({"start_s": _hms(match.group(1)), "title": match.group(2)})
    chapters.sort(key=lambda c: c["start_s"])
    return chapters if len(chapters) >= 2 else []


def _error_reason(response: httpx.Response) -> str:
    try:
        return response.json()["error"]["errors"][0]["reason"]
    except (ValueError, KeyError, IndexError, TypeError):
        return ""


def _to_video(item: dict) -> dict:
    snippet = item.get("snippet") or {}
    thumbs = snippet.get("thumbnails") or {}
    thumb = next((thumbs[k]["url"] for k in ("maxres", "high", "medium", "default") if k in thumbs), None)
    description = snippet.get("description") or ""
    return {
        "video_id": item["id"],
        "channel_id": snippet.get("channelId", ""),
        "title": snippet.get("title", ""),
        "description": description,
        "tags": snippet.get("tags") or [],
        "published_at": snippet.get("publishedAt"),
        "duration_s": parse_iso_duration((item.get("contentDetails") or {}).get("duration")),
        "view_count": int((item.get("statistics") or {}).get("viewCount") or 0),
        "thumbnail_url": thumb,
        "chapters": parse_chapters(description),
    }


class YouTubeClient:
    def __init__(self, api_key: str, store: Store, http: httpx.Client | None = None,
                 now: Callable[[], datetime] = utc_now):
        self._key = api_key
        self._store = store
        self._http = http or httpx.Client(timeout=30)
        self._now = now

    def _get(self, resource: str, params: dict) -> dict:
        try:
            response = self._http.get(f"{API_BASE}/{resource}", params=params,
                                      headers={"x-goog-api-key": self._key})
        except httpx.HTTPError as exc:
            raise YouTubeError("youtube_unreachable", f"Could not reach the YouTube API ({type(exc).__name__})") from None
        self._store.add_usage(utc_day(self._now()), "youtube_units", 1)
        if response.status_code == 200:
            return response.json()
        reason = _error_reason(response)
        if reason in ("quotaExceeded", "dailyLimitExceeded"):
            raise YouTubeError("youtube_quota_exceeded",
                               "The YouTube API daily quota is used up; it resets at midnight Pacific time.")
        raise YouTubeError("youtube_api_error",
                           f"YouTube API returned HTTP {response.status_code} ({reason or 'no reason given'})")

    def _resolve(self, ref: ChannelRef) -> dict:
        params = {"part": "snippet,contentDetails", ("id" if ref.kind == "id" else "forHandle"): ref.value}
        items = self._get("channels", params).get("items") or []
        if not items:
            raise YouTubeError("channel_not_found", f"No YouTube channel found for {ref.value}")
        item = items[0]
        return {
            "channel_id": item["id"],
            "title": item["snippet"]["title"],
            "handle": ref.value if ref.kind == "handle" else item["snippet"].get("customUrl"),
            "uploads_playlist": item["contentDetails"]["relatedPlaylists"]["uploads"],
        }

    def _is_fresh(self, channel: dict) -> bool:
        if not channel["fully_indexed"] or not channel["indexed_at"]:
            return False
        return self._now() - datetime.fromisoformat(channel["indexed_at"]) < STALE_AFTER

    def _summary(self, channel: dict, new_videos: int, from_cache: bool) -> dict:
        return {
            "channel_id": channel["channel_id"],
            "title": channel["title"],
            "handle": channel["handle"],
            "total_videos": self._store.count_videos(channel["channel_id"]),
            "new_videos": new_videos,
            "indexed_at": channel["indexed_at"],
            "from_cache": from_cache,
        }

    def _new_upload_ids(self, playlist: str, known: set[str], stop_at_known: bool) -> list[str]:
        new_ids: list[str] = []
        seen: set[str] = set()
        token = None
        while True:
            params = {"part": "contentDetails", "playlistId": playlist, "maxResults": BATCH}
            if token:
                params["pageToken"] = token
            data = self._get("playlistItems", params)
            for item in data.get("items") or []:
                vid = item["contentDetails"]["videoId"]
                if vid in known:
                    if stop_at_known:
                        return new_ids
                    continue
                if vid not in seen:
                    seen.add(vid)
                    new_ids.append(vid)
            token = data.get("nextPageToken")
            if not token:
                return new_ids

    def _fetch_videos(self, ids: list[str]) -> list[dict]:
        data = self._get("videos", {"part": "snippet,contentDetails,statistics", "id": ",".join(ids),
                                    "maxResults": BATCH})
        return [_to_video(item) for item in data.get("items") or []]

    def index_channel(self, ref: ChannelRef, refresh: bool = False) -> dict:
        cached = self._store.get_channel(ref)
        if cached and not refresh and self._is_fresh(cached):
            return self._summary(cached, new_videos=0, from_cache=True)

        info = self._resolve(ref)
        cid = info["channel_id"]
        prior = self._store.get_channel(ChannelRef("id", cid))
        # Only trust "newest first, stop at first known ID" if the previous pass completed.
        stop_at_known = bool(prior and prior["fully_indexed"])
        self._store.upsert_channel(cid, info["handle"], info["title"], info["uploads_playlist"],
                                   prior["indexed_at"] if prior else None, fully_indexed=False)

        new_ids = self._new_upload_ids(info["uploads_playlist"], self._store.known_video_ids(cid), stop_at_known)
        for i in range(0, len(new_ids), BATCH):
            self._store.upsert_videos(self._fetch_videos(new_ids[i:i + BATCH]))

        self._store.upsert_channel(cid, info["handle"], info["title"], info["uploads_playlist"],
                                   self._now().isoformat(), fully_indexed=True)
        return self._summary(self._store.get_channel(ChannelRef("id", cid)), new_videos=len(new_ids),
                             from_cache=False)

    def fetch_video(self, video_id: str) -> dict | None:
        videos = self._fetch_videos([video_id])
        if not videos:
            return None
        self._store.upsert_videos(videos)
        return videos[0]
