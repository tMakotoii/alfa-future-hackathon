import json

import httpx
import pytest

from app.db import connect, init_schema
from app.llm import LLM, BudgetExhausted, budget_level, load_models, parse_json

CFG = {**load_models(), "backoff_s": [0, 0]}


class Transport(httpx.MockTransport):
    """Отвечает handler(model, body) -> (status, content); считает вызовы, помнит последнее тело."""

    def __init__(self, handler):
        self.calls, self.bodies = 0, []

        def h(request):
            body = json.loads(request.content)
            self.calls += 1
            self.bodies.append(body)
            status, content = handler(body["model"], body)
            return httpx.Response(status, json={"choices": [{"message": {"content": content}}],
                                                "usage": {"prompt_tokens": 100, "completion_tokens": 50}})
        super().__init__(h)

    def last_body_contains(self, s):
        return s in json.dumps(self.bodies[-1], ensure_ascii=False)


@pytest.fixture
def conn(tmp_path):
    c = connect(str(tmp_path / "l.db"))
    init_schema(c)
    return c


def make(conn, handler, **kw):
    t = Transport(handler)
    llm = LLM(conn, CFG, transport=t, **kw)
    llm.transport = t
    return llm


def insert_cost(conn, rub):
    conn.execute("insert into llm_calls(model, purpose, cost_rub, cache_hit) values ('m', 'x', ?, 0)", (rub,))
    conn.commit()


def test_parse_json_fenced_and_wrapped():  # Review Focus 2
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json('Вот ответ: {"a": {"b": 2}} спасибо') == {"a": {"b": 2}}
    with pytest.raises(ValueError):
        parse_json("нет json")


def test_cache_hit_second_call(conn):
    llm = make(conn, lambda m, b: (200, '{"x": 1}'))
    llm.chat("classify", [{"role": "user", "content": "x"}])
    r = llm.chat("classify", [{"role": "user", "content": "x"}])
    assert r.cache_hit and llm.transport.calls == 1 and r.data == {"x": 1}


def test_invalid_json_retries_then_fallback(conn):
    primary = CFG["purposes"]["synthesize"]["model"]
    llm = make(conn, lambda m, b: (200, "не json") if m == primary else (200, '{"ok": true}'))
    r = llm.chat("synthesize", [{"role": "user", "content": "x"}])
    assert r.model == "qwen/qwen3.6-35b-a3b" and r.data == {"ok": True}
    assert llm.transport.calls == 3  # основная + ретрай JSON + fallback


def test_server_error_falls_back(conn):
    primary = CFG["purposes"]["plan"]["model"]
    llm = make(conn, lambda m, b: (503, "") if m == primary else (200, '{"steps": []}'))
    assert llm.chat("plan", [{"role": "user", "content": "x"}]).data == {"steps": []}


def test_cost_logged(conn):
    llm = make(conn, lambda m, b: (200, '{"x": 1}'))
    r = llm.chat("classify", [{"role": "user", "content": "x"}], trace_id="t1")
    row = conn.execute("select * from llm_calls where trace_id='t1'").fetchone()
    assert r.cost_rub > 0 and row["cost_rub"] == pytest.approx(r.cost_rub) and row["prompt_tokens"] == 100


def test_budget_ladder(conn):
    insert_cost(conn, 360)
    assert budget_level(conn, 500) == "fallback"
    insert_cost(conn, 100)
    assert budget_level(conn, 500) == "cache_only"


def test_cache_only_raises_on_miss(conn):
    insert_cost(conn, 480)
    llm = make(conn, lambda m, b: (200, '{"x": 1}'), budget_rub=500)
    with pytest.raises(BudgetExhausted):
        llm.chat("classify", [{"role": "user", "content": "новое"}])
    assert llm.transport.calls == 0


def test_masking_roundtrip(conn):
    llm = make(conn, lambda m, b: (200, b["messages"][-1]["content"]))
    r = llm.chat("chat", [{"role": "user", "content": "group_134402_sb"}], json_mode=False,
                 aliases={"group_134402_sb": "Группа А"})
    assert llm.transport.last_body_contains("Группа А") and not llm.transport.last_body_contains("group_134402_sb")
    assert r.text == "group_134402_sb"


def test_extra_body_from_config_sent(conn):
    llm = LLM(conn, {**CFG, "extra_body": {"reasoning": {"enabled": False}}}, transport=Transport(lambda m, b: (200, '{"x": 1}')))
    llm.chat("classify", [{"role": "user", "content": "x"}])
    assert llm.client._transport.bodies[-1]["reasoning"] == {"enabled": False}


def test_gateway_cost_preferred_over_price_table(conn):
    def h(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"x": 1}'}}],
                                         "usage": {"prompt_tokens": 100, "completion_tokens": 50, "cost": 0.42}})
    r = LLM(conn, CFG, transport=httpx.MockTransport(h)).chat("classify", [{"role": "user", "content": "x"}])
    assert r.cost_rub == 0.42
    assert conn.execute("select cost_rub from llm_calls").fetchone()[0] == 0.42
