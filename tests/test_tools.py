import pytest

from app.tools import TOOLS, ToolRejected, catalog, run_tool
from tests.conftest import seed_fixture_news

G = "group_134402_sb"


def group_of(db, uid):
    return db.execute("select group_id from companies where uid=?", (uid,)).fetchone()[0]


def test_exactly_seven_tools():
    assert set(TOOLS) == {"get_company_profile", "get_counterparties", "get_affected_members", "search_bank_analytics",
                          "search_news", "get_related_events", "compute_relevance"}
    assert all(name in catalog() for name in TOOLS)


def test_unknown_tool_rejected(real_db):
    with pytest.raises(ToolRejected):
        run_tool(real_db, G, "CFO", "drop_table", {})


def test_group_id_in_args_rejected(real_db):  # Review Focus 1
    with pytest.raises(ToolRejected):
        run_tool(real_db, G, "CFO", "get_company_profile", {"sections": ["products"], "group_id": "group_134409_sb"})


def test_profile_tool_returns_feature_sources(real_db):
    r = run_tool(real_db, G, "CFO", "get_company_profile", {"sections": ["products", "sector_mix"]})
    ids = {i["source_id"] for i in r.items}
    assert "f:products.leasing" in ids and "f:sector_mix" in ids
    assert all(i["kind"] == "client_data" for i in r.items)


def test_bank_search_k_capped(real_db):
    with pytest.raises(ToolRejected):
        run_tool(real_db, G, "CFO", "search_bank_analytics", {"query": "ставка", "k": 50})


def test_bank_search_source_ids(real_db):
    r = run_tool(real_db, G, "CFO", "search_bank_analytics", {"query": "ключевая ставка"})
    assert r.items and all(i["source_id"].startswith("b:") and "#p" in i["source_id"] for i in r.items)
    assert {"text", "doc_date", "stale"} <= r.items[0]["payload"].keys()


def test_affected_members_scoped_to_group(real_db):
    r = run_tool(real_db, G, "CFO", "get_affected_members", {"product": "leasing"})
    uids = [i["payload"]["uid"] for i in r.items]
    assert uids and all(group_of(real_db, u) == G for u in uids)


def test_counterparties(real_db):
    r = run_tool(real_db, G, "CFO", "get_counterparties", {"direction": "out"})
    assert r.items[0]["source_id"] == "f:counterparty_mix.out" and r.items[0]["payload"]["top"]


def test_news_tools(real_db):
    seed_fixture_news(real_db)
    assert run_tool(real_db, G, "CFO", "search_news", {"query": "ставка"}).items
    rel = run_tool(real_db, G, "CFO", "compute_relevance", {"news_id": "fx01"})
    assert rel.items[0]["payload"]["components"]
    assert run_tool(real_db, G, "CFO", "get_related_events", {"news_id": "fx01"}).items is not None
