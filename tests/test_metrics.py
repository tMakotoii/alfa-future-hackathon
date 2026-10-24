import json

import pytest

from app.db import connect, init_schema
from app.metrics import compute_metrics
from tests.factories import good_insight_for


@pytest.fixture
def db_two_insights(tmp_path):
    c = connect(str(tmp_path / "m.db"))
    init_schema(c)
    good, bad = good_insight_for("G", "n1", "t1"), good_insight_for("G", "n2", "t2")
    bad["why_it_matters"][0]["source_ids"] = ["n999"]
    bad["bank_view"] = {"available": False, "items": []}
    for ins, status in ((good, "ready"), (bad, "degraded")):
        c.execute("insert into insights(insight_id, group_id, news_id, score, payload, status, trace_id) values (?,?,?,?,?,?,?)",
                  (ins["insight_id"], "G", ins["news_id"], 0.5, json.dumps(ins, ensure_ascii=False), status, ins["trace_id"]))
    c.execute("insert into trace_steps(trace_id, idx, kind, name, input, output) values ('t2', 0, 'revise', 'revise:1', '{}', '{}')")
    c.execute("insert into llm_calls(model, purpose, cost_rub, cache_hit, trace_id) values ('m', 'plan', 0.5, 0, 't1'), "
              "('m', 'plan', 0, 1, 't2')")
    c.execute("insert into feedback(insight_id, login, verdict, reason) values (?, 'u', 'down', 'irrelevant')",
              (good["insight_id"],))
    c.commit()
    return c


def test_metrics_groundedness(db_two_insights):
    m = compute_metrics(db_two_insights)
    assert 0 < m["groundedness"] < 1 and m["insights"]["total"] == 2 and m["insights"]["degraded"] == 1
    assert m["bank_view_share"] == 0.5 and m["avg_revisions"] == 0.5
    assert m["cache_hit_rate"] == 0.5 and m["cost_today_rub"] == pytest.approx(0.5)
    assert m["feedback"] == {"up": 0, "down": 1, "irrelevant": 1, "wrong": 0}
    assert m["last_eval"] is None


def test_metrics_empty_db(tmp_path):
    c = connect(str(tmp_path / "e.db"))
    init_schema(c)
    m = compute_metrics(c)
    assert m["insights"]["total"] == 0 and m["groundedness"] is None
