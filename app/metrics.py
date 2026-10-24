"""Метрики качества AI-компонента и персонализации."""
import json
import os

from app.llm import budget_level, spent_today


def _claims(p: dict) -> list[dict]:
    return p["event"]["facts"] + p["why_it_matters"] + p["impacts"] + p["bank_view"]["items"]


def compute_metrics(conn) -> dict:
    rows = conn.execute("select payload, status, trace_id from insights").fetchall()
    statuses = {"ready": 0, "degraded": 0, "rule_only": 0}
    grounded = total_claims = with_bank = 0
    for r in rows:
        p = json.loads(r["payload"])
        statuses[r["status"]] = statuses.get(r["status"], 0) + 1
        ids = {s["id"] for s in p["sources"]}
        for c in _claims(p):
            total_claims += 1
            grounded += bool(c["source_ids"]) and all(s in ids for s in c["source_ids"])
        with_bank += p["bank_view"]["available"]
    n = len(rows)
    traces = [r["trace_id"] for r in rows]
    marks = ",".join("?" * len(traces)) or "''"
    revisions = conn.execute(f"select count(*) from trace_steps where name like 'revise:%' and trace_id in ({marks})",
                             traces).fetchone()[0]
    insight_cost = conn.execute(f"select coalesce(sum(cost_rub), 0) from llm_calls where trace_id in ({marks})",
                                traces).fetchone()[0]
    calls, hits = conn.execute("select count(*), coalesce(sum(cache_hit), 0) from llm_calls").fetchone()
    fb = dict(conn.execute("select verdict, count(*) from feedback group by verdict").fetchall())
    reasons = dict(conn.execute("select reason, count(*) from feedback where reason is not null group by reason").fetchall())
    last = conn.execute("select payload from eval_runs order by ts desc limit 1").fetchone()
    budget = float(os.environ.get("DAILY_BUDGET_RUB", 500))
    return {
        "insights": {"total": n, **statuses},
        "groundedness": round(grounded / total_claims, 4) if total_claims else None,
        "bank_view_share": round(with_bank / n, 4) if n else None,
        "avg_revisions": round(revisions / n, 4) if n else None,
        "cost_today_rub": round(spent_today(conn), 4),
        "budget_rub": budget,
        "budget_level": budget_level(conn, budget),
        "cache_hit_rate": round(hits / calls, 4) if calls else None,
        "avg_cost_per_insight_rub": round(insight_cost / n, 4) if n else None,
        "feedback": {"up": fb.get("up", 0), "down": fb.get("down", 0),
                     "irrelevant": reasons.get("irrelevant", 0), "wrong": reasons.get("wrong", 0)},
        "last_eval": json.loads(last[0]) if last else None,
    }
