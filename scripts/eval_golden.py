"""Прогон золотого набора: группа × новость → агент → метрики качества. Пишет итог в eval_runs (видно в /api/metrics).

Запуск (нужен LLM_API_KEY): python -m uv run python scripts/eval_golden.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.agent import new_trace_id, run_insight  # noqa: E402
from app.classify import classify_news  # noqa: E402
from app.db import connect, init_schema  # noqa: E402
from app.llm import LLM, load_models  # noqa: E402
from app.metrics import _claims  # noqa: E402
from app.news import add_manual  # noqa: E402

conn = connect()
init_schema(conn)
llm = LLM(conn, load_models())
rows = []
for line in Path("data/golden.jsonl").read_text(encoding="utf-8").splitlines():
    case = json.loads(line)
    nid = add_manual(conn, text=f"{case['news']['title']}\n{case['news']['body']}")
    cls = classify_news(conn, llm, nid)
    tid = new_trace_id()
    ins = run_insight(conn, llm, case["group_id"], nid, tid)
    ids = {s.id for s in ins.sources}
    claims = _claims(ins.model_dump())
    grounded = sum(bool(c["source_ids"]) and all(s in ids for s in c["source_ids"]) for c in claims) / max(len(claims), 1)
    feats = sum(f in ids for f in case["expected_features"]) / len(case["expected_features"])
    factors = sum(f in {x.name for x in cls.factors} for f in case["expected_factors"]) / len(case["expected_factors"])
    revisions, cost = conn.execute("select sum(name like 'revise:%'), coalesce(sum(cost_rub), 0) from trace_steps "
                                   "where trace_id=?", (tid,)).fetchone()
    status = conn.execute("select status from insights where trace_id=?", (tid,)).fetchone()[0]
    rows.append({"group": case["group_id"], "news": case["news"]["title"][:50], "status": status,
                 "groundedness": round(grounded, 3), "features": round(feats, 3), "factors": round(factors, 3),
                 "bank_view": ins.bank_view.available, "revisions": revisions or 0, "cost_rub": round(cost, 3)})
    print(json.dumps(rows[-1], ensure_ascii=False))

n = len(rows)
summary = {"cases": n, **{k: round(sum(r[k] for r in rows) / n, 3)
                          for k in ("groundedness", "features", "factors", "revisions", "cost_rub")},
           "bank_view_share": round(sum(r["bank_view"] for r in rows) / n, 3),
           "ready_share": round(sum(r["status"] == "ready" for r in rows) / n, 3)}
conn.execute("insert into eval_runs(payload) values (?)", (json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False),))
conn.commit()
print("ИТОГ:", json.dumps(summary, ensure_ascii=False))
