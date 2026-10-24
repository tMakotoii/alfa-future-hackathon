"""Инструменты агента: только чтение, allow-list, Pydantic-аргументы. group_id подставляет сервер."""
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.ingest import PRODUCTS, fts_query, search_bank
from app.rank import bank_hit, load_ranking, score_news
from app.sectors import load_sectors


class ToolRejected(Exception):
    pass


@dataclass
class ToolResult:
    items: list[dict]


class Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


Section = Literal["revenue_total", "n_companies", "sector_mix", "products", "sector_position", "counterparty_mix",
                  "regions", "negative_marks", "data_gaps"]
Product = Literal["rko", "guarantee", "credit", "leasing", "deposit", "payroll", "factoring", "fts"]


class ProfileArgs(Args):
    sections: list[Section] = Field(min_length=1)


class CounterpartyArgs(Args):
    direction: Literal["in", "out"]
    okved2: str | None = None


class MembersArgs(Args):
    product: Product | None = None
    okved2: str | None = None
    region: str | None = None


class BankArgs(Args):
    query: str = Field(min_length=2, max_length=200)
    k: int = Field(5, ge=1, le=5)


class NewsArgs(Args):
    query: str = Field(min_length=2, max_length=200)
    days: int = Field(7, ge=1, le=30)


class NewsIdArgs(Args):
    news_id: str = Field(max_length=40)


def _profile(conn, group_id) -> dict:
    return json.loads(conn.execute("select profile from groups where group_id=?", (group_id,)).fetchone()[0])


def _item(source_id, kind, ref, payload) -> dict:
    return {"source_id": source_id, "kind": kind, "ref": ref, "payload": payload}


def get_company_profile(conn, group_id, role, a: ProfileArgs) -> ToolResult:
    p = _profile(conn, group_id)
    items = []
    for s in a.sections:
        if s == "data_gaps":
            items.append(_item("f:data_gaps", "client_data", "пропуски в данных", p["data_gaps"]))
        elif s == "products":
            src = p["features"]["products"]["src"]
            for prod, v in p["features"]["products"]["value"].items():
                if v["n"]:
                    items.append(_item(f"f:products.{prod}", "client_data", src, {"product": prod, **v}))
        else:
            feat = p["features"][s]
            items.append(_item(f"f:{s}", "client_data", feat["src"],
                               {k: v for k, v in feat.items() if k != "src"}))
    return ToolResult(items)


def get_counterparties(conn, group_id, role, a: CounterpartyArgs) -> ToolResult:
    q = "select cp_uid, cp_okved2, amount, cnt from counterparties where group_id=? and direction=?"
    params = [group_id, a.direction]
    if a.okved2:
        q += " and cp_okved2=?"
        params.append(a.okved2)
    top = [dict(r) for r in conn.execute(q + " order by rank", params)]
    mix = _profile(conn, group_id)["features"]["counterparty_mix"]["value"]
    payload = {"direction": "поставщики (платежи группы)" if a.direction == "out" else "покупатели (поступления группе)",
               "top": top, "by_okved2": mix[a.direction],
               "top5_share": mix[f"top5_share_{a.direction}"], "hhi": mix[f"hhi_{a.direction}"]}
    return ToolResult([_item(f"f:counterparty_mix.{a.direction}", "client_data", "df_Uid_payment_hack", payload)])


def get_affected_members(conn, group_id, role, a: MembersArgs) -> ToolResult:
    q, params, why = "select uid, okved, okved_name, revenue, region from companies where group_id=?", [group_id], []
    if a.product:
        q += f" and {'fts_flag' if a.product == 'fts' else PRODUCTS[a.product]}=1"
        why.append(a.product)
    if a.okved2:
        q += " and okved2=?"
        params.append(a.okved2)
        why.append(f"ОКВЭД {a.okved2}")
    if a.region:
        q += " and region like ?"
        params.append(f"%{a.region}%")
        why.append(a.region)
    sid = f"f:products.{a.product}" if a.product else "f:sector_mix" if a.okved2 else "f:regions"
    rows = conn.execute(q + " order by revenue desc limit 20", params).fetchall()
    return ToolResult([_item(sid, "client_data", "df_Uid_data_hack", {**dict(r), "reason": ", ".join(why)}) for r in rows])


def search_bank_analytics(conn, group_id, role, a: BankArgs) -> ToolResult:
    return ToolResult([_item(f"b:{h['doc_id']}#p{h['page']}", "bank_analytics", f"{h['doc_title']}, стр. {h['page']}",
                             {"text": h["text"], "doc_date": h["doc_date"], "stale": bool(h["stale"])})
                       for h in search_bank(conn, a.query, a.k)])


def _news_item(r) -> dict:
    return _item(r["news_id"], "news", r["url"] or r["source"],
                 {"title": r["title"], "published_at": r["published_at"], "source": r["source"],
                  "snippet": (r["body"] or "")[:500]})


def search_news(conn, group_id, role, a: NewsArgs) -> ToolResult:
    q = fts_query(a.query)
    if not q:
        return ToolResult([])
    since = (datetime.now(timezone.utc) - timedelta(days=a.days)).isoformat()
    rows = conn.execute("select n.* from news_fts join news n on n.rowid = news_fts.rowid where news_fts match ? "
                        "and n.published_at >= ? order by bm25(news_fts) limit 5", (q, since)).fetchall()
    return ToolResult([_news_item(r) for r in rows])


def _news(conn, news_id):
    r = conn.execute("select * from news where news_id=?", (news_id,)).fetchone()
    if not r:
        raise ToolRejected(f"нет новости {news_id}")
    return r


def get_related_events(conn, group_id, role, a: NewsIdArgs) -> ToolResult:
    n = _news(conn, a.news_id)
    rows = list(conn.execute("select * from news where cluster_id=? and news_id<>? limit 5", (n["cluster_id"], n["news_id"])))
    cls = json.loads(n["classification"] or "{}")
    q = fts_query(" ".join(cls.get("entities", [])[:3]))
    if q:
        seen = {r["news_id"] for r in rows} | {n["news_id"]}
        rows += [r for r in conn.execute("select n.* from news_fts join news n on n.rowid = news_fts.rowid "
                                         "where news_fts match ? order by bm25(news_fts) limit 5", (q,))
                 if r["news_id"] not in seen]
    return ToolResult([_news_item(r) for r in rows[:5]])


def compute_relevance(conn, group_id, role, a: NewsIdArgs) -> ToolResult:
    n = _news(conn, a.news_id)
    cls = json.loads(n["classification"] or "{}")
    cfg = load_ranking()
    s = score_news(cls, datetime.fromisoformat(n["published_at"]), _profile(conn, group_id), role, cfg, load_sectors(),
                   bank_hit(conn, cls, cfg), datetime.now(timezone.utc))
    return ToolResult([_item("f:relevance", "client_data", "rank.score_news",
                             {"score": s.value, "components": [asdict(c) for c in s.components]})])


TOOLS: dict[str, tuple[type[BaseModel], Callable, str]] = {
    "get_company_profile": (ProfileArgs, get_company_profile,
                            "sections: [revenue_total|n_companies|sector_mix|products|sector_position|counterparty_mix|"
                            "regions|negative_marks|data_gaps] — признаки группы с происхождением"),
    "get_counterparties": (CounterpartyArgs, get_counterparties,
                           "direction: in|out, okved2?: str — ключевые поставщики (out) / покупатели (in), концентрация"),
    "get_affected_members": (MembersArgs, get_affected_members,
                             "product?: rko|guarantee|credit|leasing|deposit|payroll|factoring|fts, okved2?: str, "
                             "region?: str — компании группы, которых касается событие"),
    "search_bank_analytics": (BankArgs, search_bank_analytics,
                              "query: str, k?: 1..5 — позиция Альфа-Банка в аналитике (с датой документа)"),
    "search_news": (NewsArgs, search_news, "query: str, days?: 1..30 — другие новости за последние дни"),
    "get_related_events": (NewsIdArgs, get_related_events, "news_id: str — связанные новости того же события"),
    "compute_relevance": (NewsIdArgs, compute_relevance, "news_id: str — разбивка значимости новости для группы"),
}


def run_tool(conn, group_id: str, role: str, name: str, args: dict) -> ToolResult:
    if name not in TOOLS:
        raise ToolRejected(f"инструмент не в allow-list: {name}")
    model, fn, _ = TOOLS[name]
    try:
        parsed = model.model_validate(args or {})
    except ValidationError as e:
        raise ToolRejected(f"невалидные аргументы {name}: {e.errors(include_url=False)}") from e
    return fn(conn, group_id, role, parsed)


def catalog() -> str:
    lines = []
    for name, (_, _, desc) in TOOLS.items():
        args, what = desc.split(" — ")
        lines.append(f"- {name}({args}) — {what}")
    return "\n".join(lines)
