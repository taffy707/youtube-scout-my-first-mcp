import httpx

from yt_scout.store import utc_now
from yt_scout.youtube import YouTubeClient

API_KEY = "test-yt-key"
CHANNEL_ID = "UC" + "y" * 22
UPLOADS = "UU" + "y" * 22


def make_ids(n: int, prefix: str = "vid") -> list[str]:
    """Distinct 11-character video IDs, newest first."""
    return [f"{prefix}{i:08d}"[-11:].rjust(11, "0") for i in range(n)]


class FakeYouTube:
    """Offline stand-in for the YouTube Data API v3, served through httpx.MockTransport."""

    def __init__(self, video_ids: list[str], quota_fail_after: int | None = None,
                 playlists: dict[str, dict] | None = None):
        self.video_ids = list(video_ids)  # newest first, like the uploads playlist
        # playlist_id -> {"title": str, "video_ids": [...]}; IDs not in video_ids act as deleted/private videos
        self.playlists = playlists or {}
        self.quota_fail_after = quota_fail_after
        self.calls: list[httpx.Request] = []

    def client(self, store, now=utc_now) -> YouTubeClient:
        http = httpx.Client(transport=httpx.MockTransport(self.handler))
        return YouTubeClient(API_KEY, store, http=http, now=now)

    def calls_to(self, resource: str) -> int:
        return sum(1 for r in self.calls if r.url.path.endswith("/" + resource))

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        assert request.headers.get("x-goog-api-key") == API_KEY
        assert "key" not in request.url.params
        if self.quota_fail_after is not None and len(self.calls) > self.quota_fail_after:
            return httpx.Response(403, json={"error": {"code": 403, "errors": [{"reason": "quotaExceeded"}]}})
        resource = request.url.path.rsplit("/", 1)[-1]
        params = request.url.params
        if resource == "channels":
            if params.get("forHandle") == "@ycombinator" or params.get("id") == CHANNEL_ID:
                return httpx.Response(200, json={"items": [{
                    "id": CHANNEL_ID,
                    "snippet": {"title": "Y Combinator", "customUrl": "@ycombinator"},
                    "contentDetails": {"relatedPlaylists": {"uploads": UPLOADS}},
                }]})
            return httpx.Response(200, json={"pageInfo": {"totalResults": 0}})
        if resource == "playlists":
            if params.get("channelId") == CHANNEL_ID:
                wanted = list(self.playlists)
            else:
                wanted = [p for p in params.get("id", "").split(",") if p in self.playlists]
            start = int(params.get("pageToken") or 0)
            body = {"items": [self._playlist(p) for p in wanted[start:start + 50]]}
            if start + 50 < len(wanted):
                body["nextPageToken"] = str(start + 50)
            return httpx.Response(200, json=body)
        if resource == "playlistItems":
            pid = params["playlistId"]
            if pid == UPLOADS:
                ids = self.video_ids
            elif pid in self.playlists:
                ids = self.playlists[pid]["video_ids"]
            else:
                return httpx.Response(404, json={"error": {"errors": [{"reason": "playlistNotFound"}]}})
            start = int(params.get("pageToken") or 0)
            page = ids[start:start + 50]
            body = {"items": [{"contentDetails": {"videoId": vid}} for vid in page]}
            if start + 50 < len(ids):
                body["nextPageToken"] = str(start + 50)
            return httpx.Response(200, json=body)
        if resource == "videos":
            wanted = params["id"].split(",")
            assert len(wanted) <= 50
            return httpx.Response(200, json={"items": [self._video(v) for v in wanted if v in self.video_ids]})
        return httpx.Response(404, json={"error": {"errors": [{"reason": "notFound"}]}})

    def _playlist(self, pid: str) -> dict:
        p = self.playlists[pid]
        return {"id": pid,
                "snippet": {"channelId": CHANNEL_ID, "title": p["title"], "description": p.get("description", "")},
                "contentDetails": {"itemCount": len(p["video_ids"])}}

    @staticmethod
    def _video(vid: str) -> dict:
        return {
            "id": vid,
            "snippet": {
                "channelId": CHANNEL_ID,
                "title": f"Video {vid}",
                "description": "0:00 Intro\n1:30 Metrics that matter\nThanks for watching",
                "tags": ["startup"],
                "publishedAt": "2024-05-01T12:00:00Z",
                "thumbnails": {"high": {"url": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"}},
            },
            "contentDetails": {"duration": "PT12M5S"},
            "statistics": {"viewCount": "1234"},
        }


from types import SimpleNamespace

from youtube_transcript_api import NoTranscriptFound


class FakeTranscript:
    def __init__(self, language_code: str, is_generated: bool, raw: list[dict]):
        self.language_code = language_code
        self.is_generated = is_generated
        self.raw = raw

    def fetch(self):
        return SimpleNamespace(to_raw_data=lambda: list(self.raw))


class FakeTranscriptList:
    def __init__(self, video_id: str, transcripts: list[FakeTranscript]):
        self.video_id = video_id
        self.transcripts = transcripts

    def _find(self, langs, generated: bool):
        for lang in langs:
            for t in self.transcripts:
                if t.language_code == lang and t.is_generated == generated:
                    return t
        raise NoTranscriptFound(self.video_id, langs, None)

    def find_manually_created_transcript(self, langs):
        return self._find(langs, generated=False)

    def find_generated_transcript(self, langs):
        return self._find(langs, generated=True)

    def __iter__(self):
        return iter(self.transcripts)


class FakeTranscriptApi:
    def __init__(self, transcripts: list[FakeTranscript] | None = None, error: Exception | None = None):
        self.transcripts = transcripts or []
        self.error = error
        self.list_calls = 0

    def list(self, video_id: str):
        self.list_calls += 1
        if self.error is not None:
            raise self.error
        return FakeTranscriptList(video_id, self.transcripts)


import json
import threading


def default_response(cs: int, ce: int, attempt: int) -> str:
    return json.dumps({"summary": f"clip {cs}-{ce}",
                       "notes": [{"timestamp": "00:10", "observation": f"point at {cs}+10"}]})


class FakeAnalyzer:
    def __init__(self, responder=None):
        self.responder = responder or default_response
        self.calls: list[tuple] = []
        self.text_calls: list[str] = []
        self._lock = threading.Lock()

    def analyze_clip(self, video_url, start_s, end_s, level, prompt):
        with self._lock:
            attempt = sum(1 for c in self.calls if c[1] == start_s)
            self.calls.append((video_url, start_s, end_s, level, prompt))
        result = self.responder(start_s, end_s, attempt)
        if isinstance(result, Exception):
            raise result
        return result

    def complete_text(self, prompt):
        self.text_calls.append(prompt)
        return "merged summary"
