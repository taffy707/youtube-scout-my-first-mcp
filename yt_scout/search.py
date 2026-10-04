import re

from yt_scout import validate
from yt_scout.store import Store
from yt_scout.validate import InvalidInput

_WORD = re.compile(r"[^\W_]+")
_STOPWORDS = frozenset(
    "a an and are as at be by can do does for from how i in is it me my of on or should "
    "that the this to what when where which who why will with you your".split()
)
MAX_TERMS = 20
SNIPPET_CHARS = 300


def build_fts_query(query: str) -> str | None:
    """Turn free text into a safe FTS5 query: quoted terms joined with OR (no user operators)."""
    terms: list[str] = []
    for word in _WORD.findall((query or "").lower()):
        if word not in _STOPWORDS and word not in terms:
            terms.append(word)
    if not terms:
        return None
    return " OR ".join(f'"{t}"' for t in terms[:MAX_TERMS])


def snippet(text: str) -> str:
    flat = " ".join(text.split())
    if len(flat) <= SNIPPET_CHARS:
        return flat
    return flat[: SNIPPET_CHARS - 1].rstrip() + "…"


def search_videos(store: Store, channel_id: str, query: str, *, min_duration_s: int | None = None,
                  max_duration_s: int | None = None, published_after: str | None = None,
                  limit: int | None = None) -> list[dict]:
    fts = build_fts_query(query)
    if fts is None:
        raise InvalidInput("query", "needs at least one meaningful keyword")
    after = validate.iso_date(published_after).isoformat() if published_after else None
    rows = store.search_videos(channel_id, fts, min_duration_s=min_duration_s, max_duration_s=max_duration_s,
                               published_after=after, limit=validate.limit(limit))
    return [
        {
            "video_id": r["video_id"],
            "title": r["title"],
            "description_snippet": snippet(r["description"]),
            "duration_s": r["duration_s"],
            "view_count": r["view_count"],
            "published_at": r["published_at"],
            "url": validate.watch_url(r["video_id"]),
        }
        for r in rows
    ]
