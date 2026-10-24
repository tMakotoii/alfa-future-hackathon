"""Агент: plan → execute → synthesize → check → revise (≤2). Каждый шаг пишется в trace_steps."""
import json
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError

from app import prompts
from app.ingest import search_bank
from app.llm import LLMError
from app.rank import impact_hint, load_ranking
from app.schemas import ROLES, ChatAnswer, Claim, Insight, Source, check_chat, check_invariants
from app.sectors import load_sectors
from app.tools import ToolRejected, catalog, run_tool

MAX_PLAN_STEPS = 6
MAX_REVISIONS = 2
MAX_PAYLOAD_CHARS = 900
PROFILE_SECTIONS = ["sector_mix", "products", "counterparty_mix", "sector_position", "data_gaps"]
COMPONENT_SOURCE = {"sector": "f:sector_mix", "macro": "f:sector_mix", "products": "f:products",
                    "counterparties": "f:counterparty_mix", "region": "f:regions"}


def new_trace_id() -> str:
    return "tr_" + uuid.uuid4().hex[:12]


class Trace:
    def __init__(self, conn, trace_id: str):
        self.conn, self.trace_id = conn, trace_id
        self.idx = conn.execute("select count(*) from trace_steps where trace_id=?", (trace_id,)).fetchone()[0]

    def step(self, kind: str, name: str, input: Any, output: Any, tokens: int = 0, cost_rub: float = 0.0,
             ms: int = 0) -> None:
        self.conn.execute("insert into trace_steps(trace_id, idx, kind, name, input, output, tokens, cost_rub, ms) "
                          "values (?,?,?,?,?,?,?,?,?)",
                          (self.trace_id, self.idx, kind, name, json.dumps(input, ensure_ascii=False, default=str),
                           json.dumps(output, ensure_ascii=False, default=str), tokens, cost_rub, ms))
        self.conn.commit()
        self.idx += 1


class Ctx:
    """Единое состояние агента: группа + событие + собранные источники."""

    def __init__(self, conn, llm, group_id: str, news_id: str, trace: Trace, role: str = "CFO"):
        self.conn, self.llm, self.group_id, self.news_id, self.trace, self.role = conn, llm, group_id, news_id, trace, role
        self.news = conn.execute("select * from news where news_id=?", (news_id,)).fetchone()
        self.cls = json.loads(self.news["classification"] or "{}")
        self.profile = json.loads(conn.execute("select profile from groups where group_id=?", (group_id,)).fetchone()[0])
        self.gathered: list[dict] = [{"source_id": news_id, "kind": "news", "ref": self.news["url"] or self.news["source"],
                                      "payload": {"title": self.news["title"], "published_at": self.news["published_at"],
                                                  "text": (self.news["body"] or "")[:1500]}}]

    def aliases(self) -> dict[str, str]:
        uids = sorted(set(re.findall(r"U_\d+", json.dumps([g["payload"] for g in self.gathered]))))
        # группа и так видна модели под публичным псевдонимом; маскируем только идентификаторы компаний
        return {u: f"Компания-{i + 1}" for i, u in enumerate(uids)}

    def llm_call(self, purpose: str, messages: list[dict], name: str | None = None):
        t0 = time.monotonic()
        try:
            res = self.llm.chat(purpose, messages, trace_id=self.trace.trace_id, aliases=self.aliases())
        except LLMError as e:
            self.trace.step("llm", name or purpose, {"purpose": purpose}, {"error": str(e)}, ms=_ms(t0))
            raise
        self.trace.step("llm", name or purpose, {"purpose": purpose, "model": res.model},
                        res.data if res.data is not None else res.text, res.prompt_tokens + res.completion_tokens,
                        res.cost_rub, _ms(t0))
        return res

    def execute(self, steps: list[dict]) -> None:
        for st in steps:
            name, args = str(st.get("tool", "")), st.get("args") or {}
            t0 = time.monotonic()
            try:
                items = run_tool(self.conn, self.group_id, self.role, name, args).items
            except ToolRejected as e:
                self.trace.step("tool", f"tool:{name}", {"args": args, "why": st.get("why")}, {"rejected": str(e)},
                                ms=_ms(t0))
                continue
            known = {(g["source_id"], json.dumps(g["payload"], sort_keys=True, default=str)) for g in self.gathered}
            new = [i for i in items if (i["source_id"], json.dumps(i["payload"], sort_keys=True, default=str)) not in known]
            self.gathered += new
            self.trace.step("tool", f"tool:{name}", {"args": args, "why": st.get("why")},
                            {"items": len(items), "source_ids": sorted({i["source_id"] for i in items})}, ms=_ms(t0))

    def sources(self) -> list[Source]:
        seen = {}
        for g in self.gathered:
            seen.setdefault(g["source_id"], Source(id=g["source_id"], type=g["kind"], ref=str(g["ref"])))
        return list(seen.values())

    def context_text(self) -> str:
        lines = []
        for g in self.gathered:
            body = json.dumps(g["payload"], ensure_ascii=False, default=str)[:MAX_PAYLOAD_CHARS]
            lines.append(f"[{g['source_id']}] ({g['kind']}; {g['ref']}): {body}")
        return "\n".join(lines)

    def news_text(self) -> str:
        return prompts.wrap_untrusted(f"{self.news['title']}\n\n{(self.news['body'] or '')[:1500]}")


def _ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)


def profile_summary(profile: dict) -> str:
    f = profile["features"]
    prods = ", ".join(f"{k}: {v['n']} комп. ({v.get('revenue_share', 0) * 100:.0f}% выручки)"
                      for k, v in f["products"]["value"].items() if v["n"])
    sectors = ", ".join(f"{m['okved2']} {m.get('name') or ''} {m['share'] * 100:.0f}%" for m in f["sector_mix"]["value"])
    cm = f["counterparty_mix"]["value"]
    cps = lambda xs: ", ".join(f"{x['okved2']} {x['share'] * 100:.0f}%" for x in xs[:3])  # noqa: E731
    pos = f["sector_position"]["value"]
    return (f"{profile['display_name']}: выручка {f['revenue_total']['value'] / 1e9:.0f} млрд ₽, "
            f"{f['n_companies']['value']} компаний. Отрасли: {sectors}. Продукты банка: {prods or 'нет'}. "
            f"Поставщики по ОКВЭД: {cps(cm['out'])}; покупатели: {cps(cm['in'])}. "
            f"Регионы: {', '.join(f['regions']['value'][:3]) or 'нет данных'}. "
            f"Позиция в отрасли {pos.get('okved2')}: №{pos.get('rank')} из {pos.get('of')} (оценка по выборке банка).")


def _save(conn, ins: Insight, status: str, gathered: list[dict]) -> None:
    payload = {**ins.model_dump(), "gathered": gathered}
    conn.execute("insert or replace into insights(insight_id, group_id, news_id, score, payload, status, trace_id, "
                 "created_at) values (?,?,?,?,?,?,?,?)",
                 (ins.insight_id, ins.group_id, ins.news_id, ins.relevance.score, json.dumps(payload, ensure_ascii=False),
                  status, ins.trace_id, datetime.now(timezone.utc).isoformat()))
    conn.commit()


def _relevance(ctx: Ctx) -> dict:
    for g in ctx.gathered:
        if g["source_id"] == "f:relevance":
            return g["payload"]
    return {"score": 0.0, "components": []}


def _build(ctx: Ctx, data: dict) -> Insight:
    """Серверные поля (id, источники, score) не доверяем LLM."""
    data = {**data, "insight_id": f"ins_{ctx.group_id}_{ctx.news_id}", "group_id": ctx.group_id,
            "news_id": ctx.news_id, "trace_id": ctx.trace.trace_id, "relevance": _relevance(ctx),
            "sources": [s.model_dump() for s in ctx.sources()]}
    data.setdefault("event", {"title": ctx.news["title"], "facts": []})
    return Insight.model_validate(data)


def _synthesize(ctx: Ctx, revise: tuple[dict, list[str]] | None = None) -> Insight:
    user = (f"Новость:\n{ctx.news_text()}\n\nПрофиль группы:\n{profile_summary(ctx.profile)}\n\n"
            f"Контекст (источники):\n{ctx.context_text()}")
    msgs = [{"role": "system", "content": prompts.fmt(prompts.SYNTHESIZE)}, {"role": "user", "content": user}]
    if revise:
        draft, problems = revise
        msgs.append({"role": "user", "content": prompts.REVISE.format(
            problems="\n".join(f"- {p}" for p in problems), draft=json.dumps(draft, ensure_ascii=False)[:6000])})
    res = ctx.llm_call("synthesize", msgs)
    try:
        return _build(ctx, res.data or {})
    except ValidationError as e:
        msgs.append({"role": "user", "content": f"JSON не соответствует схеме: {e.errors(include_url=False)}. Исправь."})
        res = ctx.llm_call("synthesize", msgs, name="synthesize:retry")
        return _build(ctx, res.data or {})


def _check(ctx: Ctx, ins: Insight) -> list[str]:
    t0 = time.monotonic()
    problems = [f"{p.field}: {p.code} — {p.message}" for p in check_invariants(ins)]
    ctx.trace.step("check", "check:code", {"invariants": 7}, {"problems": problems}, ms=_ms(t0))
    try:
        claims = ins.model_dump(include={"headline", "why_it_matters", "impacts", "bank_view", "actions"})
        res = ctx.llm_call("check", [{"role": "system", "content": prompts.fmt(prompts.CHECK)},
                                     {"role": "user", "content": f"Профиль группы:\n{profile_summary(ctx.profile)}\n\n"
                                                                 f"Контекст:\n{ctx.context_text()}\n\nИнсайт:\n"
                                                                 f"{json.dumps(claims, ensure_ascii=False)}"}],
                           name="check:llm")
        problems += [f"{p.get('field')}: {p.get('problem')}" for p in (res.data or {}).get("problems", [])
                     if isinstance(p, dict)]
    except LLMError:
        pass  # LLM-проверка необязательна: кодовые инварианты уже проверены
    return problems


def _extra_steps(ctx: Ctx, problems: list[str]) -> list[dict]:
    """Нехватка данных → дополнительный сбор перед переписыванием."""
    text = " ".join(problems)
    steps = []
    if "single_factor" in text or "bank_view" in text:
        kw = load_ranking()["factor_keywords"]
        for f in ctx.cls.get("factors", [])[:2]:
            if f["name"] in kw:
                steps.append({"tool": "search_bank_analytics", "args": {"query": kw[f["name"]]}, "why": "доп. поиск позиции банка"})
        steps.append({"tool": "get_counterparties", "args": {"direction": "out"}, "why": "доп. фактор: поставщики"})
        steps.append({"tool": "get_counterparties", "args": {"direction": "in"}, "why": "доп. фактор: покупатели"})
    return steps


def run_insight(conn, llm, group_id: str, news_id: str, trace_id: str, role: str = "CFO") -> Insight:
    ctx = Ctx(conn, llm, group_id, news_id, Trace(conn, trace_id), role)
    try:
        plan = ctx.llm_call("plan", [
            {"role": "system", "content": prompts.fmt(prompts.PLAN, catalog=catalog())},
            {"role": "user", "content": f"Новость:\n{ctx.news_text()}\n\nПрофиль группы:\n{profile_summary(ctx.profile)}"}],
            name="plan")
        steps = (plan.data or {}).get("steps", [])
        steps = steps[:MAX_PLAN_STEPS] if isinstance(steps, list) else []
        ctx.execute([{"tool": "get_company_profile", "args": {"sections": PROFILE_SECTIONS}, "why": "обязательный шаг"},
                     {"tool": "compute_relevance", "args": {"news_id": news_id}, "why": "обязательный шаг"}]
                    + [s for s in steps if isinstance(s, dict)])
        ins = _synthesize(ctx)
        problems = _check(ctx, ins)
        for n in range(1, MAX_REVISIONS + 1):
            if not problems:
                break
            ctx.trace.step("revise", f"revise:{n}", {"problems": problems}, {})
            ctx.execute(_extra_steps(ctx, problems))
            ins = _synthesize(ctx, revise=(ins.model_dump(), problems))
            problems = _check(ctx, ins)
    except (LLMError, ValidationError) as e:
        ctx.trace.step("revise", "fallback:rule_only", {"reason": str(e)[:500]}, {})
        return rule_only_insight(conn, group_id, news_id, trace_id, ctx=ctx)
    status = "ready"
    if problems:
        status = "degraded"
        ins.caveats += [f"Не прошло проверку: {p}" for p in problems]
    _save(conn, ins, status, ctx.gathered)
    return ins


def rule_only_insight(conn, group_id: str, news_id: str, trace_id: str, ctx: Ctx | None = None) -> Insight:
    """Карточка без LLM: факты классификации + разбивка score + найденные материалы банка."""
    ctx = ctx or Ctx(conn, None, group_id, news_id, Trace(conn, trace_id))
    if not any(g["source_id"] == "f:relevance" for g in ctx.gathered):
        ctx.execute([{"tool": "get_company_profile", "args": {"sections": PROFILE_SECTIONS}, "why": "rule-only"},
                     {"tool": "compute_relevance", "args": {"news_id": news_id}, "why": "rule-only"}])
    rel = _relevance(ctx)
    for sid in set(COMPONENT_SOURCE.values()):
        if not any(g["source_id"] == sid for g in ctx.gathered):
            ctx.gathered.append({"source_id": sid, "kind": "client_data", "ref": "профиль группы", "payload": {}})
    why = [Claim(text=c["evidence"], origin="fact", source_ids=[COMPONENT_SOURCE[c["name"]]])
           for c in sorted(rel["components"], key=lambda c: -c["value"])
           if c["name"] in COMPONENT_SOURCE and c["value"] > 0][:3]
    kw = load_ranking()["factor_keywords"]
    hits = []
    for f in ctx.cls.get("factors", [])[:2]:
        hits += search_bank(conn, kw.get(f["name"], ""), k=2)
    items, caveats = [], ["Сформировано без AI: исчерпан бюджет или недоступна модель. Выводы не делались."]
    for h in {h["chunk_id"]: h for h in hits}.values():
        sid = f"b:{h['doc_id']}#p{h['page']}"
        ctx.gathered.append({"source_id": sid, "kind": "bank_analytics", "ref": f"{h['doc_title']}, стр. {h['page']}",
                             "payload": {"text": h["text"], "doc_date": h["doc_date"], "stale": bool(h["stale"])}})
        items.append({"text": h["text"][:400], "origin": "bank", "source_ids": [sid], "doc_date": h["doc_date"],
                      "stale": bool(h["stale"])})
        if h["stale"]:
            caveats.append(f"Материал банка «{h['doc_title']}» от {h['doc_date']} может быть неактуален")
    title = ctx.news["title"]
    data = {"impact": impact_hint(ctx.cls, ctx.profile, load_sectors()), "headline": title,
            "event": {"title": title, "date": ctx.news["published_at"][:10],
                      "facts": [{"text": f["text"], "origin": "fact", "source_ids": [news_id]}
                                for f in ctx.cls.get("facts", [])] or [{"text": title, "origin": "fact",
                                                                        "source_ids": [news_id]}]},
            "why_it_matters": [c.model_dump() for c in why],
            "bank_view": {"available": bool(items), "items": items},
            "role_views": {r: {"headline": title, "focus": []} for r in ROLES}, "caveats": caveats}
    ins = _build(ctx, data)
    _save(conn, ins, "rule_only", ctx.gathered)
    ctx.trace.step("check", "rule_only", {}, {"bank_items": len(items), "why": len(why)})
    return ins


def run_chat(conn, llm, insight_id: str, login: str, question: str, trace_id: str) -> ChatAnswer:
    row = conn.execute("select group_id, news_id, payload from insights where insight_id=?", (insight_id,)).fetchone()
    payload = json.loads(row["payload"])
    role = conn.execute("select role from users where login=?", (login,)).fetchone()
    ctx = Ctx(conn, llm, row["group_id"], row["news_id"], Trace(conn, trace_id), role[0] if role else "CFO")
    ctx.gathered = payload["gathered"]
    q = f"<user_question>{question[:1000]}</user_question>"
    insight_brief = json.dumps({k: payload[k] for k in ("headline", "why_it_matters", "impacts", "bank_view")},
                               ensure_ascii=False)[:4000]
    conn.execute("insert into chat_messages(insight_id, login, role, content, trace_id) values (?,?,?,?,?)",
                 (insight_id, login, "user", json.dumps({"text": question}, ensure_ascii=False), trace_id))
    conn.commit()  # не держим блокировку записи на время вызовов LLM
    plan = ctx.llm_call("plan", [{"role": "system", "content": prompts.fmt(prompts.PLAN_CHAT, catalog=catalog())},
                                 {"role": "user", "content": f"Инсайт: {insight_brief}\n\nВопрос: {q}"}], name="plan")
    steps = (plan.data or {}).get("steps", [])
    ctx.execute([s for s in steps[:3] if isinstance(s, dict)] if isinstance(steps, list) else [])
    msgs = [{"role": "system", "content": prompts.fmt(prompts.CHAT)},
            {"role": "user", "content": f"Новость:\n{ctx.news_text()}\n\nПрофиль группы:\n{profile_summary(ctx.profile)}\n\n"
                                        f"Инсайт: {insight_brief}\n\n"
                                        f"Контекст:\n{ctx.context_text()}\n\nВопрос: {q}"}]
    try:
        ans = ChatAnswer.model_validate(ctx.llm_call("chat", msgs).data or {"claims": []})
    except ValidationError as e:  # модель вернула не тот формат — пустой ответ вместо 500
        ctx.trace.step("check", "check:schema", {}, {"error": str(e)[:500]})
        ans = ChatAnswer(claims=[])
    sources = ctx.sources()
    problems = check_chat(ans, sources)
    ctx.trace.step("check", "check:code", {}, {"problems": [f"{p.field}: {p.code}" for p in problems]})
    if problems:
        known = {s.id for s in sources}
        cleaned = []
        for c in ans.claims:  # неизвестные источники выкидываем; «банк/факт» без источника не показываем
            c.source_ids = [s for s in c.source_ids if s in known]
            if c.origin == "bank" and not any(s.startswith("b:") for s in c.source_ids):
                if not c.source_ids:
                    continue
                c.origin = "fact"  # модель перепутала метку: ссылки на новость/данные клиента — это факт
            if c.origin == "fact" and not c.source_ids:
                continue
            cleaned.append(c)
        ans.claims = cleaned
    ans.sources = sources
    conn.execute("insert into chat_messages(insight_id, login, role, content, trace_id) values (?,?,?,?,?)",
                 (insight_id, login, "assistant", ans.model_dump_json(), trace_id))
    conn.commit()
    return ans


if __name__ == "__main__":  # живая проверка: python -m app.agent <group_id> <news_id>
    import sys

    from app.db import connect
    from app.llm import LLM, load_models

    c = connect()
    tid = new_trace_id()
    result = run_insight(c, LLM(c, load_models()), sys.argv[1], sys.argv[2], tid)
    steps = c.execute("select count(*), coalesce(sum(cost_rub), 0) from trace_steps where trace_id=?", (tid,)).fetchone()
    print(result.headline, f"\nшагов: {steps[0]}, ₽: {steps[1]:.2f}, trace: {tid}")
