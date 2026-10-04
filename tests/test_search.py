import pytest

from yt_scout.search import build_fts_query, search_videos
from yt_scout.store import Store
from yt_scout.validate import InvalidInput

CID = "UC" + "a" * 22
OTHER = "UC" + "b" * 22
FILLER = "We talk with founders about building companies and lessons learned along the way."


def v(vid, title, description=FILLER, tags=(), duration_s=1200, views=1000,
      published_at="2024-06-01T00:00:00Z", channel_id=CID):
    return {"video_id": vid, "channel_id": channel_id, "title": title, "description": description,
            "tags": list(tags), "published_at": published_at, "duration_s": duration_s,
            "view_count": views, "thumbnail_url": None, "chapters": []}


@pytest.fixture
def store():
    s = Store(":memory:")
    s.upsert_videos([
        v("kpi00000001", "The KPIs every startup should track", tags=["kpi", "metrics"]),
        v("met00000001", "How to measure growth: metrics that matter"),
        v("ret00000001", "Retention is the only metric that matters early"),
        v("ret00000002", "Office hours with founders", description="We discuss retention cohorts. " + FILLER),
        v("rai00000001", "How to raise a seed round", description="Fundraising advice for founders."),
        v("cof00000001", "Cofounder conflicts and how to resolve them"),
        v("sht00000001", "Quick metric tip", duration_s=45),
        v("old00000001", "Metrics from the archive", published_at="2015-01-01T00:00:00Z"),
        v("oth00000001", "KPIs on another channel", channel_id=OTHER),
        v("lng00000001", "Long description video", description="metrics " + "x" * 1000),
    ])
    return s


def ids(results):
    return [r["video_id"] for r in results]


def test_build_fts_query_quotes_terms_and_drops_stopwords():
    assert build_fts_query("What are the KPIs for a startup?") == '"kpis" OR "startup"'


@pytest.mark.parametrize("raw", ['kpi" OR title:*', "NEAR(a b)", "metrics -growth", "^start*"])
def test_build_fts_query_strips_operators(raw):
    query = build_fts_query(raw)
    assert query is not None
    for ch in ':*()^-':
        assert ch not in query


def test_build_fts_query_none_when_only_stopwords():
    assert build_fts_query("what is the") is None
    assert build_fts_query("?!") is None


def test_kpi_query_ranks_kpi_video_first_and_excludes_unrelated(store):
    results = ids(search_videos(store, CID, "startup KPIs metrics"))
    assert results[0] == "kpi00000001"
    assert "met00000001" in results[:5]
    assert "rai00000001" not in results
    assert "oth00000001" not in results


def test_title_match_beats_description_match(store):
    results = ids(search_videos(store, CID, "retention"))
    assert results.index("ret00000001") < results.index("ret00000002")


def test_filters(store):
    assert "sht00000001" not in ids(search_videos(store, CID, "metric", min_duration_s=60))
    assert ids(search_videos(store, CID, "metric", max_duration_s=60)) == ["sht00000001"]
    assert "old00000001" not in ids(search_videos(store, CID, "metrics", published_after="2020-01-01"))


def test_special_characters_do_not_raise(store):
    assert "kpi00000001" in ids(search_videos(store, CID, 'kpi" OR title:*'))


def test_empty_query_rejected(store):
    with pytest.raises(InvalidInput):
        search_videos(store, CID, "the")


def test_bad_date_rejected(store):
    with pytest.raises(InvalidInput):
        search_videos(store, CID, "metrics", published_after="yesterday")


def test_limit_and_result_shape(store):
    results = search_videos(store, CID, "metrics", limit=1)
    assert len(results) == 1
    r = results[0]
    assert set(r) == {"video_id", "title", "description_snippet", "duration_s", "view_count", "published_at", "url"}
    assert r["url"] == f"https://www.youtube.com/watch?v={r['video_id']}"


def test_snippet_truncated(store):
    r = next(x for x in search_videos(store, CID, "metrics", limit=50) if x["video_id"] == "lng00000001")
    assert len(r["description_snippet"]) <= 300
    assert r["description_snippet"].endswith("…")
