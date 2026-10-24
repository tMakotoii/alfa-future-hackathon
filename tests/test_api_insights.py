from app import jobs


def login(c, name):
    assert c.post("/api/login", json={"login": name}).status_code == 200


def first_feed_id(c):
    return c.get("/api/feed").json()[0]["news_id"]


def start_insight(c, name):
    login(c, name)
    r = c.get(f"/api/insights/{first_feed_id(c)}")
    assert r.status_code == 202
    return r.json()["trace_id"]


def ready_insight(c, name):
    login(c, name)
    nid = first_feed_id(c)
    c.get(f"/api/insights/{nid}")
    jobs.wait_idle(20)
    r = c.get(f"/api/insights/{nid}")
    assert r.status_code == 200
    return r.json()


def test_insight_202_then_200(client_fake_llm):
    login(client_fake_llm, "stroy-cfo")
    nid = first_feed_id(client_fake_llm)
    assert client_fake_llm.get(f"/api/insights/{nid}").status_code == 202
    jobs.wait_idle(20)
    r = client_fake_llm.get(f"/api/insights/{nid}")
    body = r.json()
    assert r.status_code == 200 and "gathered" not in body and body["status"] in {"ready", "degraded"}
    assert body["group_id"] == "group_134409_sb"
    assert client_fake_llm.get("/api/feed").json()[0]["insight_status"] != "none"


def test_unknown_news_404(client_fake_llm):
    login(client_fake_llm, "stroy-cfo")
    assert client_fake_llm.get("/api/insights/nope").status_code == 404


def test_parallel_requests_single_run(client_slow_llm):  # Review Focus 5
    login(client_slow_llm, "stroy-cfo")
    nid = first_feed_id(client_slow_llm)
    a = client_slow_llm.get(f"/api/insights/{nid}").json()["trace_id"]
    b = client_slow_llm.get(f"/api/insights/{nid}").json()["trace_id"]
    assert a == b


def test_foreign_trace_and_insight_404(client_fake_llm):
    ins = ready_insight(client_fake_llm, "opt-cfo")
    login(client_fake_llm, "stroy-cfo")
    assert client_fake_llm.get(f"/api/traces/{ins['trace_id']}").status_code == 404
    assert client_fake_llm.post(f"/api/insights/{ins['insight_id']}/chat", json={"question": "?"}).status_code == 404


def test_trace_steps_visible_to_owner(client_fake_llm):
    ins = ready_insight(client_fake_llm, "opt-cfo")
    steps = client_fake_llm.get(f"/api/traces/{ins['trace_id']}").json()
    assert steps[0]["name"] == "plan" and all("kind" in s for s in steps)


def test_manual_news_validation(client_fake_llm):  # Review Focus 4
    login(client_fake_llm, "opt-cfo")
    assert client_fake_llm.post("/api/news/manual", json={"text": ""}).status_code == 422
    assert client_fake_llm.post("/api/news/manual", json={}).status_code == 422
    r = client_fake_llm.post("/api/news/manual", json={"text": "ЦБ поднял ставку до 16%\nНеожиданное решение"})
    assert r.status_code == 200
    nid = r.json()["news_id"]
    assert client_fake_llm.get(f"/api/sources/news/{nid}").json()["title"] == "ЦБ поднял ставку до 16%"


def test_manual_news_without_llm_still_listed(client):
    from tests.fakes import FakeLLM
    client.app.state.llm_factory = lambda conn: FakeLLM({}, raise_budget=True)
    login(client, "stroy-cfo")
    nid = client.post("/api/news/manual", json={"text": "Новые правила для застройщиков\nтекст"}).json()["news_id"]
    assert client.get(f"/api/sources/news/{nid}").json()["classification"]["is_business"] is True
    assert nid in [x["news_id"] for x in client.get("/api/feed").json()]  # ручная новость видна всегда


def test_chat_answer_has_origins(client_fake_llm):
    ins = ready_insight(client_fake_llm, "opt-cfo")
    r = client_fake_llm.post(f"/api/insights/{ins['insight_id']}/chat", json={"question": "а как это повлияет на лизинг?"})
    body = r.json()
    assert r.status_code == 200 and body["claims"] and body["trace_id"]
    assert all(c["origin"] in {"fact", "bank", "ai"} for c in body["claims"])


def test_feedback(client_fake_llm):
    ins = ready_insight(client_fake_llm, "opt-cfo")
    assert client_fake_llm.post(f"/api/insights/{ins['insight_id']}/feedback",
                                json={"verdict": "down", "reason": "irrelevant"}).status_code == 200
    assert client_fake_llm.post(f"/api/insights/{ins['insight_id']}/feedback", json={"verdict": "meh"}).status_code == 422


def test_bank_source_page(client_fake_llm):
    login(client_fake_llm, "opt-cfo")
    r = client_fake_llm.get("/api/sources/bank/alfa-macro_insights-policy_rate_11sep/1")
    assert r.status_code == 200 and "14,0%" in r.json()["text"]
    assert client_fake_llm.get("/api/sources/bank/nope/1").status_code == 404


def test_sse_streams_steps(client_fake_llm):
    tid = start_insight(client_fake_llm, "auto-cfo")
    body = client_fake_llm.get(f"/api/traces/{tid}/stream").text
    assert "event: step" in body and "event: done" in body
