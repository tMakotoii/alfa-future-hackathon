import itertools
import json
from datetime import datetime, timezone

from app.ingest import DEMO_GROUPS
from app.rank import load_ranking, rank_feed, score_news
from app.sectors import load_sectors

NOW = datetime(2026, 10, 24, 12, tzinfo=timezone.utc)
FIXTURE = json.load(open("tests/fixtures/classified_news.json", encoding="utf-8"))
EMPTY_PROFILE = {"features": {"sector_mix": {"value": []}, "products": {"value": {}},
                              "counterparty_mix": {"value": {"out": [], "in": []}}, "regions": {"value": []}}}


def rank_feed_on_fixture(conn, group_id, role):
    for n in FIXTURE:
        conn.execute("insert or ignore into news(news_id, source, url, published_at, title, body, hash, cluster_id, origin,"
                     " classification) values (?,?,?,?,?,?,?,?,?,?)",
                     (n["news_id"], n["source"], "", NOW.isoformat(), n["title"], "", n["news_id"], n["news_id"], "rss",
                      json.dumps(n["classification"], ensure_ascii=False)))
    conn.commit()
    return [x for x in rank_feed(conn, group_id, role, now=NOW) if x["news_id"].startswith("fx")]


def test_feeds_differ_between_demo_groups(real_db):
    tops = [{x["news_id"] for x in rank_feed_on_fixture(real_db, g, "CEO")[:5]} for g in DEMO_GROUPS]
    for a, b in itertools.combinations(tops, 2):
        assert len(a & b) / 5 < 0.5, tops


def test_role_changes_order(real_db):
    cfo = [x["news_id"] for x in rank_feed_on_fixture(real_db, "group_134409_sb", "CFO")]
    ceo = [x["news_id"] for x in rank_feed_on_fixture(real_db, "group_134409_sb", "CEO")]
    assert cfo != ceo


def test_every_component_has_evidence(real_db):
    items = rank_feed_on_fixture(real_db, "group_134402_sb", "CFO")
    assert items and all(c["evidence"] for item in items for c in item["components"])
    assert all(0 <= item["score"] <= 1 for item in items)
    assert items == sorted(items, key=lambda x: -x["score"])


def test_empty_profile_scores_without_crash():  # Review Focus 3
    s = score_news(FIXTURE[0]["classification"], NOW, EMPTY_PROFILE, "CFO", load_ranking(), load_sectors(), False, NOW)
    assert 0 <= s.value <= 1 and any("нет данных" in c.evidence for c in s.components)


def test_freshness_decays():
    cls = FIXTURE[0]["classification"]
    fresh = score_news(cls, NOW, EMPTY_PROFILE, "CFO", load_ranking(), load_sectors(), False, NOW)
    old = score_news(cls, datetime(2026, 10, 18, tzinfo=timezone.utc), EMPTY_PROFILE, "CFO", load_ranking(),
                     load_sectors(), False, NOW)
    assert old.value < fresh.value


def test_cfo_and_treasurer_feeds_differ(real_db):
    cfo = [x["news_id"] for x in rank_feed_on_fixture(real_db, "group_134402_sb", "CFO")[:5]]
    tr = [x["news_id"] for x in rank_feed_on_fixture(real_db, "group_134402_sb", "TREASURER")[:5]]
    assert cfo != tr
