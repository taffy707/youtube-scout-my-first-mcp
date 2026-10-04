import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from yt_scout.validate import ChannelRef

_SCHEMA = """
CREATE TABLE IF NOT EXISTS channels (
    channel_id TEXT PRIMARY KEY,
    handle TEXT,
    title TEXT NOT NULL,
    uploads_playlist TEXT NOT NULL,
    indexed_at TEXT,
    fully_indexed INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS channels_handle ON channels(handle);
CREATE TABLE IF NOT EXISTS videos (
    video_id TEXT PRIMARY KEY,
    channel_id TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    tags_json TEXT NOT NULL DEFAULT '[]',
    published_at TEXT,
    duration_s INTEGER NOT NULL DEFAULT 0,
    view_count INTEGER NOT NULL DEFAULT 0,
    thumbnail_url TEXT,
    chapters_json TEXT NOT NULL DEFAULT '[]',
    listed INTEGER NOT NULL DEFAULT 0  -- 1 once seen in the channel's uploads playlist
);
CREATE INDEX IF NOT EXISTS videos_channel ON videos(channel_id);
CREATE VIRTUAL TABLE IF NOT EXISTS videos_fts USING fts5(
    video_id UNINDEXED, title, description, tags, tokenize='porter unicode61'
);
CREATE TABLE IF NOT EXISTS transcripts (
    video_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    language TEXT,
    source TEXT,
    segments_json TEXT NOT NULL DEFAULT '[]',
    fetched_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS watches (
    cache_key TEXT PRIMARY KEY,
    video_id TEXT NOT NULL,
    start_s INTEGER NOT NULL,
    end_s INTEGER NOT NULL,
    detail TEXT NOT NULL,
    focus TEXT NOT NULL,
    model TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS usage (
    day TEXT NOT NULL,
    kind TEXT NOT NULL,
    amount INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (day, kind)
);
"""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_day(now: datetime | None = None) -> str:
    return (now or utc_now()).astimezone(timezone.utc).date().isoformat()


def _video_from_row(row: sqlite3.Row) -> dict:
    return {
        "video_id": row["video_id"],
        "channel_id": row["channel_id"],
        "title": row["title"],
        "description": row["description"],
        "tags": json.loads(row["tags_json"]),
        "published_at": row["published_at"],
        "duration_s": row["duration_s"],
        "view_count": row["view_count"],
        "thumbnail_url": row["thumbnail_url"],
        "chapters": json.loads(row["chapters_json"]),
    }


class Store:
    def __init__(self, path: str | Path):
        path = str(path)
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            if path != ":memory:":
                self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(_SCHEMA)
            columns = {r["name"] for r in self._conn.execute("PRAGMA table_info(videos)")}
            if "listed" not in columns:  # databases created before the column existed
                self._conn.execute("ALTER TABLE videos ADD COLUMN listed INTEGER NOT NULL DEFAULT 0")
            self._conn.commit()

    def _one(self, sql: str, params=()) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(sql, params).fetchone()

    def _all(self, sql: str, params=()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def _write(self, sql: str, params=()) -> None:
        with self._lock, self._conn:
            self._conn.execute(sql, params)

    # --- channels -------------------------------------------------------
    def upsert_channel(self, channel_id: str, handle: str | None, title: str, uploads_playlist: str,
                       indexed_at: str | None, fully_indexed: bool) -> None:
        self._write(
            """INSERT INTO channels (channel_id, handle, title, uploads_playlist, indexed_at, fully_indexed)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(channel_id) DO UPDATE SET
                 handle = COALESCE(excluded.handle, channels.handle),
                 title = excluded.title,
                 uploads_playlist = excluded.uploads_playlist,
                 indexed_at = excluded.indexed_at,
                 fully_indexed = excluded.fully_indexed""",
            (channel_id, handle.lower() if handle else None, title, uploads_playlist, indexed_at, int(fully_indexed)),
        )

    def get_channel(self, ref: ChannelRef) -> dict | None:
        column = "channel_id" if ref.kind == "id" else "handle"
        row = self._one(f"SELECT * FROM channels WHERE {column} = ?", (ref.value,))
        if row is None:
            return None
        return {**dict(row), "fully_indexed": bool(row["fully_indexed"])}

    # --- videos ---------------------------------------------------------
    def upsert_videos(self, videos: list[dict], listed: bool = True) -> None:
        """listed=False for videos fetched one-off (not seen in the uploads playlist)."""
        with self._lock, self._conn:
            for v in videos:
                self._conn.execute(
                    """INSERT INTO videos (video_id, channel_id, title, description, tags_json, published_at,
                                           duration_s, view_count, thumbnail_url, chapters_json, listed)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(video_id) DO UPDATE SET
                         channel_id = excluded.channel_id, title = excluded.title,
                         description = excluded.description, tags_json = excluded.tags_json,
                         published_at = excluded.published_at, duration_s = excluded.duration_s,
                         view_count = excluded.view_count, thumbnail_url = excluded.thumbnail_url,
                         chapters_json = excluded.chapters_json,
                         listed = MAX(videos.listed, excluded.listed)""",
                    (v["video_id"], v["channel_id"], v["title"], v["description"], json.dumps(v["tags"]),
                     v["published_at"], v["duration_s"], v["view_count"], v["thumbnail_url"],
                     json.dumps(v["chapters"]), int(listed)),
                )
                self._conn.execute("DELETE FROM videos_fts WHERE video_id = ?", (v["video_id"],))
                self._conn.execute(
                    "INSERT INTO videos_fts (video_id, title, description, tags) VALUES (?, ?, ?, ?)",
                    (v["video_id"], v["title"], v["description"], " ".join(v["tags"])),
                )

    def get_video(self, video_id: str) -> dict | None:
        row = self._one("SELECT * FROM videos WHERE video_id = ?", (video_id,))
        return _video_from_row(row) if row else None

    def known_video_ids(self, channel_id: str) -> set[str]:
        """IDs already seen in the channel's uploads playlist."""
        rows = self._all("SELECT video_id FROM videos WHERE channel_id = ? AND listed = 1", (channel_id,))
        return {r["video_id"] for r in rows}

    def count_videos(self, channel_id: str) -> int:
        return self._one("SELECT COUNT(*) AS n FROM videos WHERE channel_id = ?", (channel_id,))["n"]

    def search_videos(self, channel_id: str, fts_query: str, *, min_duration_s: int | None = None,
                      max_duration_s: int | None = None, published_after: str | None = None,
                      limit: int = 25) -> list[dict]:
        sql = """SELECT v.*, bm25(videos_fts, 0.0, 3.0, 1.0, 2.0) AS score
                 FROM videos_fts JOIN videos v ON v.video_id = videos_fts.video_id
                 WHERE videos_fts MATCH ? AND v.channel_id = ?"""
        params: list = [fts_query, channel_id]
        if min_duration_s is not None:
            sql += " AND v.duration_s >= ?"
            params.append(min_duration_s)
        if max_duration_s is not None:
            sql += " AND v.duration_s <= ?"
            params.append(max_duration_s)
        if published_after is not None:
            sql += " AND v.published_at >= ?"
            params.append(published_after)
        sql += " ORDER BY score ASC, v.view_count DESC LIMIT ?"
        params.append(limit)
        return [_video_from_row(r) for r in self._all(sql, params)]

    # --- transcripts ----------------------------------------------------
    def put_transcript(self, video_id: str, status: str, language: str | None, source: str | None,
                       segments: list[dict], fetched_at: str) -> None:
        self._write(
            """INSERT OR REPLACE INTO transcripts (video_id, status, language, source, segments_json, fetched_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (video_id, status, language, source, json.dumps(segments), fetched_at),
        )

    def get_transcript(self, video_id: str) -> dict | None:
        row = self._one("SELECT * FROM transcripts WHERE video_id = ?", (video_id,))
        if row is None:
            return None
        return {"status": row["status"], "language": row["language"], "source": row["source"],
                "segments": json.loads(row["segments_json"]), "fetched_at": row["fetched_at"]}

    # --- watches --------------------------------------------------------
    def put_watch(self, cache_key: str, video_id: str, start_s: int, end_s: int, detail: str, focus: str,
                  model: str, result: dict, created_at: str) -> None:
        self._write(
            """INSERT OR REPLACE INTO watches
               (cache_key, video_id, start_s, end_s, detail, focus, model, result_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (cache_key, video_id, start_s, end_s, detail, focus, model, json.dumps(result), created_at),
        )

    def get_watch(self, cache_key: str) -> dict | None:
        row = self._one("SELECT result_json FROM watches WHERE cache_key = ?", (cache_key,))
        return json.loads(row["result_json"]) if row else None

    # --- usage ----------------------------------------------------------
    def get_usage(self, day: str, kind: str) -> int:
        row = self._one("SELECT amount FROM usage WHERE day = ? AND kind = ?", (day, kind))
        return row["amount"] if row else 0

    def add_usage(self, day: str, kind: str, amount: int) -> None:
        self._write(
            """INSERT INTO usage (day, kind, amount) VALUES (?, ?, ?)
               ON CONFLICT(day, kind) DO UPDATE SET amount = usage.amount + excluded.amount""",
            (day, kind, amount),
        )

    def reserve_usage(self, day: str, kind: str, amount: int, cap: int) -> bool:
        with self._lock:
            if self.get_usage(day, kind) + amount > cap:
                return False
            self.add_usage(day, kind, amount)
            return True
