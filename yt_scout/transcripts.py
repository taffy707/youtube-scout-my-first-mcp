import math
from datetime import datetime
from typing import Callable

import requests
from youtube_transcript_api import (
    AgeRestricted,
    CouldNotRetrieveTranscript,
    InvalidVideoId,
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
    VideoUnplayable,
    YouTubeTranscriptApi,
)

from yt_scout.errors import ToolError
from yt_scout.store import Store, utc_now

PREFERRED_LANGUAGES = ["en", "en-US", "en-GB"]
BLOCK_S = 30
MAX_WORDS = 12000  # keeps one tool result well under Claude Code's MCP output limit


class TranscriptError(ToolError):
    pass


def merge_blocks(segments: list[dict], block_s: int = BLOCK_S) -> list[dict]:
    blocks: list[dict] = []
    for seg in segments:
        text = " ".join(str(seg.get("text") or "").split())
        if not text:
            continue
        start = int(seg["start"])
        if blocks and start - blocks[-1]["start_s"] < block_s:
            blocks[-1]["text"] += " " + text
        else:
            blocks.append({"start_s": start, "text": text})
    if not blocks:
        return []
    last = segments[-1]
    final_end = math.ceil(float(last["start"]) + float(last.get("duration") or 0))
    out = []
    for i, block in enumerate(blocks):
        end = blocks[i + 1]["start_s"] if i + 1 < len(blocks) else max(final_end, block["start_s"] + 1)
        out.append({"start_s": block["start_s"], "end_s": end, "text": block["text"]})
    return out


def _pick(listing):
    for finder in (listing.find_manually_created_transcript, listing.find_generated_transcript):
        try:
            return finder(PREFERRED_LANGUAGES)
        except NoTranscriptFound:
            pass
    return next(iter(listing), None)


class TranscriptFetcher:
    def __init__(self, store: Store, api=None, now: Callable[[], datetime] = utc_now):
        self._store = store
        self._api = api or YouTubeTranscriptApi()
        self._now = now

    def get(self, video_id: str, start_s: int | None = None, end_s: int | None = None) -> dict:
        row = self._store.get_transcript(video_id) or self._fetch_and_cache(video_id)
        if row["status"] == "no_captions":
            raise TranscriptError("no_captions", "This video has no captions. Use watch_video instead.")
        blocks = merge_blocks(row["segments"])
        if start_s is not None or end_s is not None:
            lo = start_s or 0
            hi = end_s if end_s is not None else math.inf
            blocks = [b for b in blocks if b["start_s"] < hi and b["end_s"] > lo]
        page, words = [], 0
        for block in blocks:
            words += len(block["text"].split())
            if page and words > MAX_WORDS:
                break
            page.append(block)
        truncated = len(page) < len(blocks)
        return {"video_id": video_id, "language": row["language"], "source": row["source"], "segments": page,
                "truncated": truncated, "next_start_s": blocks[len(page)]["start_s"] if truncated else None}

    def _fetch_and_cache(self, video_id: str) -> dict:
        now = self._now().isoformat()
        try:
            transcript = _pick(self._api.list(video_id))
            if transcript is None:
                raise NoTranscriptFound(video_id, PREFERRED_LANGUAGES, None)
            raw = transcript.fetch().to_raw_data()
        except (TranscriptsDisabled, NoTranscriptFound):
            self._store.put_transcript(video_id, "no_captions", None, None, [], now)
            return self._store.get_transcript(video_id)
        except (VideoUnavailable, VideoUnplayable, AgeRestricted, InvalidVideoId) as exc:
            raise TranscriptError("video_unavailable",
                                  f"YouTube reports this video as unavailable ({type(exc).__name__}).") from None
        except (CouldNotRetrieveTranscript, requests.RequestException) as exc:
            raise TranscriptError("transcripts_blocked",
                                  f"Captions could not be fetched right now ({type(exc).__name__}). "
                                  "Use watch_video instead, or retry later.") from None
        segments = [{"start": float(s["start"]), "duration": float(s.get("duration") or 0), "text": s["text"]}
                    for s in raw]
        source = "auto" if transcript.is_generated else "manual"
        self._store.put_transcript(video_id, "ok", transcript.language_code, source, segments, now)
        return self._store.get_transcript(video_id)
