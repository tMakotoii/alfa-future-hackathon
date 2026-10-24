"""Регрессионные тесты по находкам финального ревью."""
import time

import pytest

from app import jobs
from app.agent import Ctx, Trace, run_chat, run_insight
from app.db import connect
from app.news import add_manual
from app.rank import rank_feed
from tests.factories import good_insight_for
from tests.fakes import FakeLLM

G, OTHER = "group_134402_sb", "group_134409_sb"


def test_i1_group_name_is_not_unmasked(real_db_news):
    ctx = Ctx(real_db_news, None, G, "fx01", Trace(real_db_news, "a1"))
    ctx.gathered.append({"source_id": "f:x", "kind": "client_data", "ref": "", "payload": {"uid": "U_123"}})
    aliases = ctx.aliases()
    assert G not in aliases and aliases == {"U_123": "Компания-1"}


class TxProbe(FakeLLM):
    def __init__(self, conn, script):
        super().__init__(script)
        self.conn_probe, self.in_tx = conn, []

    def chat(self, purpose, messages, **kw):
        self.in_tx.append(self.conn_probe.in_transaction)
        return super().chat(purpose, messages, **kw)


def _insight(db):
    llm = FakeLLM({"plan": [{"steps": []}], "synthesize": [good_insight_for(G, "fx01")], "check": [{"problems": []}]})
    return run_insight(db, llm, G, "fx01", "t-rv")


def test_i2_chat_does_not_hold_write_lock_during_llm(real_db_news):
    ins = _insight(real_db_news)
    probe = TxProbe(real_db_news, {"plan": [{"steps": []}], "chat": [{"claims": []}]})
    run_chat(real_db_news, probe, ins.insight_id, "opt-cfo", "вопрос", "t-rv2")
    assert probe.in_tx and not any(probe.in_tx)


def test_i3_malformed_chat_answer_gives_empty_claims(real_db_news):
    ins = _insight(real_db_news)
    llm = FakeLLM({"plan": [{"steps": []}], "chat": [{"answer": "текст без claims"}]})
    assert run_chat(real_db_news, llm, ins.insight_id, "opt-cfo", "вопрос", "t-rv3").claims == []


def test_i4_manual_news_visible_only_to_owner(real_db_news):
    nid = add_manual(real_db_news, text="Секретная новость группы\nтекст", owner_group=G)
    real_db_news.execute("update news set classification=? where news_id=?",
                         ('{"is_business": true, "factors": [], "okved2": [], "regions": ["RU"], "topics": ["other"]}', nid))
    real_db_news.commit()
    assert nid in [x["news_id"] for x in rank_feed(real_db_news, G, "CFO")]
    assert nid not in [x["news_id"] for x in rank_feed(real_db_news, OTHER, "CFO")]


def test_i4_manual_news_api_scoped(client_fake_llm):
    client_fake_llm.post("/api/login", json={"login": "opt-cfo"})
    nid = client_fake_llm.post("/api/news/manual", json={"text": "Наша внутренняя новость\nтекст"}).json()["news_id"]
    client_fake_llm.post("/api/login", json={"login": "stroy-cfo"})
    assert client_fake_llm.get(f"/api/sources/news/{nid}").status_code == 404
    assert client_fake_llm.get(f"/api/insights/{nid}").status_code == 404


def test_i5_user_request_not_queued_behind_background(api_db, monkeypatch):
    path = api_db.execute("pragma database_list").fetchone()[2]
    factory = lambda: connect(path)  # noqa: E731
    slow = lambda c: FakeLLM({"plan": [{"steps": []}], "synthesize": [good_insight_for()],  # noqa: E731
                              "check": [{"problems": []}]}, conn=c, delay=1.0)
    for nid in ("fx02", "fx03", "fx04", "fx05"):
        jobs.ensure_insight(factory, slow, G, nid, background=True)
    t0 = time.monotonic()
    jobs.ensure_insight(factory, lambda c: FakeLLM({"plan": [{"steps": []}], "synthesize": [good_insight_for()],
                                                    "check": [{"problems": []}]}, conn=c), OTHER, "fx06")
    while (OTHER, "fx06") in jobs._inflight:
        time.sleep(0.05)
    assert time.monotonic() - t0 < 2.5
    jobs.wait_idle(30)


@pytest.mark.parametrize("url", ["https://site.ru:abc/", "http://[::1"])
def test_i6_malformed_url_is_value_error(real_db_news, url):
    with pytest.raises(ValueError):
        add_manual(real_db_news, url=url)


def test_chat_bank_label_on_client_data_becomes_fact(real_db_news):
    ins = _insight(real_db_news)
    nb = next(s.id for s in ins.sources if not s.id.startswith("b:"))
    llm = FakeLLM({"plan": [{"steps": []}], "chat": [{"claims": [
        {"text": "У группы 34 компании с лизингом", "origin": "bank", "source_ids": [nb]},
        {"text": "Без источника", "origin": "bank", "source_ids": []}]}]})
    claims = run_chat(real_db_news, llm, ins.insight_id, "opt-cfo", "лизинг?", "t-rv-bank").claims
    assert [(c.text, c.origin) for c in claims] == [("У группы 34 компании с лизингом", "fact")]


def test_chat_prompt_has_profile_summary(real_db_news):
    ins = _insight(real_db_news)
    llm = FakeLLM({"plan": [{"steps": []}], "chat": [{"claims": []}]})
    run_chat(real_db_news, llm, ins.insight_id, "opt-cfo", "лизинг?", "t-rv-prof")
    user_msg = llm.last_messages[-1]["content"]
    assert "Профиль группы:" in user_msg and "Продукты банка:" in user_msg


def test_insight_sources_are_only_cited_ones(real_db_news):
    from app.agent import _build
    from app.schemas import check_invariants
    ctx = Ctx(real_db_news, None, G, "fx01", Trace(real_db_news, "t-src"))
    for sid, kind in [("fx01", "news"), ("f:products.leasing", "client_data"), ("b:steel#p1", "bank_analytics")]:
        ctx.gathered.append({"source_id": sid, "kind": kind, "ref": sid, "payload": {}})
    data = good_insight_for(G, "fx01")
    data["impacts"][0]["source_ids"] = ["f:products.leasing"]
    data["impacts"][0]["origin"] = "ai"
    data["bank_view"] = {"available": False, "items": []}
    data["why_it_matters"][1]["source_ids"] = ["f:not_gathered"]
    ins = _build(ctx, data)
    assert {s.id for s in ins.sources} == {"fx01", "f:products.leasing"}
    assert any(p.code == "unknown_source" for p in check_invariants(ins))
