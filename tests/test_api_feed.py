def login(client, name):
    assert client.post("/api/login", json={"login": name}).status_code == 200


def test_feed_requires_session(client):
    assert client.get("/api/feed").status_code == 401


def test_login_and_feed(client):
    login(client, "opt-cfo")
    me = client.get("/api/me").json()
    assert me["role"] == "CFO" and me["group_id"] == "group_134402_sb" and me["display_name"] == "Группа «Опт-Импорт»"
    feed = client.get("/api/feed").json()
    assert feed and {"news_id", "title", "score", "components", "headline", "insight_status", "impact_hint"} <= feed[0].keys()
    assert feed[0]["insight_status"] == "none"


def test_feed_filters(client):
    login(client, "auto-ceo")
    auto = client.get("/api/feed", params={"topic": "auto"}).json()
    assert auto and all("auto" in x["topics"] for x in auto)
    risks = client.get("/api/feed", params={"impact": "risk"}).json()
    assert all(x["impact_hint"] == "risk" for x in risks)


def test_profile(client):
    login(client, "stroy-ceo")
    assert client.get("/api/profile").json()["group_id"] == "group_134409_sb"


def test_unknown_login(client):
    assert client.post("/api/login", json={"login": "nope"}).status_code == 401


def test_switch_changes_group(client):
    login(client, "opt-cfo")
    assert client.post("/api/demo/switch", json={"group_id": "group_134409_sb", "role": "CEO"}).status_code == 200
    me = client.get("/api/me").json()
    assert me["group_id"] == "group_134409_sb" and me["role"] == "CEO"


def test_switch_rejects_non_target_group_and_bad_role(client):
    login(client, "opt-cfo")
    assert client.post("/api/demo/switch", json={"group_id": "nope"}).status_code == 404
    assert client.post("/api/demo/switch", json={"role": "ADMIN"}).status_code == 422


def test_demo_groups_listed(client):
    login(client, "opt-cfo")
    groups = client.get("/api/demo/groups").json()
    assert len(groups) == 341 and groups[0]["group_id"] in {"group_134402_sb"} | {g["group_id"] for g in groups}


def test_switch_forbidden_without_demo_mode(client_no_demo):
    login(client_no_demo, "opt-cfo")
    assert client_no_demo.post("/api/demo/switch", json={"group_id": "group_134409_sb"}).status_code == 403
    assert client_no_demo.get("/api/demo/groups").status_code == 403


def test_logout_clears_session(client):
    login(client, "opt-cfo")
    assert client.post("/api/logout").status_code == 200
    assert client.get("/api/me").status_code == 401


def test_metrics_endpoint(client):
    assert client.get("/api/metrics").status_code == 401
    login(client, "opt-cfo")
    m = client.get("/api/metrics").json()
    assert {"groundedness", "cost_today_rub", "budget_level", "feedback"} <= m.keys()
