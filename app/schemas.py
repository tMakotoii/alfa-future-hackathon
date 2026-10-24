from typing import Literal

from pydantic import BaseModel


class Factor(BaseModel):
    name: str
    direction: Literal["up", "down", "flat", "unknown"] = "unknown"


class NewsFact(BaseModel):
    text: str
    confirmed: bool = False


class Classification(BaseModel):
    is_business: bool = False
    topics: list[str] = []
    okved2: list[str] = []
    factors: list[Factor] = []
    regions: list[str] = []
    entities: list[str] = []
    facts: list[NewsFact] = []
    sentiment: Literal["negative", "neutral", "positive"] = "neutral"


# ---------- Insight v1 (§3.4) ----------
from dataclasses import dataclass  # noqa: E402

Origin = Literal["fact", "bank", "ai"]
Role = Literal["CEO", "CFO", "TREASURER"]
ROLES: tuple[str, ...] = ("CEO", "CFO", "TREASURER")


class Source(BaseModel):
    id: str
    type: Literal["news", "bank_analytics", "client_data"]
    ref: str = ""


class Claim(BaseModel):
    text: str
    origin: Origin
    source_ids: list[str] = []


class Event(BaseModel):
    title: str
    date: str | None = None
    facts: list[Claim] = []


class RelevanceComponent(BaseModel):
    name: str
    value: float
    evidence: str = ""


class Relevance(BaseModel):
    score: float
    components: list[RelevanceComponent] = []


class AffectedMember(BaseModel):
    uid: str
    alias: str = ""
    reason: str = ""


class Impact(Claim):
    type: Literal["risk", "opportunity"]
    horizon: str = ""
    confidence: Literal["low", "med", "high"] = "med"


class BankItem(Claim):
    origin: Literal["bank"] = "bank"
    doc_date: str | None = None
    stale: bool = False


class BankView(BaseModel):
    available: bool  # обязателен: «позиции банка нет» должно быть явным
    items: list[BankItem] = []


class Action(BaseModel):
    text: str
    product: str | None = None


class RoleView(BaseModel):
    headline: str
    focus: list[str] = []


class Insight(BaseModel):
    insight_id: str
    group_id: str
    news_id: str
    trace_id: str
    impact: Literal["risk", "opportunity", "neutral", "mixed"]
    headline: str
    event: Event
    relevance: Relevance
    affected_members: list[AffectedMember] = []
    why_it_matters: list[Claim]
    impacts: list[Impact] = []
    bank_view: BankView
    actions: list[Action] = []
    role_views: dict[Role, RoleView]
    caveats: list[str] = []
    sources: list[Source]


class ChatAnswer(BaseModel):
    claims: list[Claim]


@dataclass
class Problem:
    field: str
    code: str
    message: str


def _claim_problems(field: str, claims, by_id: dict[str, Source]) -> list[Problem]:
    out = []
    for i, c in enumerate(claims):
        f = f"{field}[{i}]"
        if not c.source_ids:
            out.append(Problem(f, "no_source", "утверждение без источника"))
        unknown = [s for s in c.source_ids if s not in by_id]
        if unknown:
            out.append(Problem(f, "unknown_source", f"нет в sources: {unknown}"))
        types = {by_id[s].type for s in c.source_ids if s in by_id}
        if c.origin == "fact" and (types - {"news", "client_data"} or any(s.startswith("b:") for s in c.source_ids)):
            out.append(Problem(f, "fact_not_news", "факт должен ссылаться на новость или данные клиента"))
        if c.origin == "bank" and (types - {"bank_analytics"} or any(not s.startswith("b:") for s in c.source_ids)):
            out.append(Problem(f, "bank_not_bank", "мнение банка должно ссылаться на аналитику банка"))
    return out


def check_invariants(ins: Insight) -> list[Problem]:
    by_id = {s.id: s for s in ins.sources}
    p = (_claim_problems("event.facts", ins.event.facts, by_id)
         + _claim_problems("why_it_matters", ins.why_it_matters, by_id)
         + _claim_problems("impacts", ins.impacts, by_id)
         + _claim_problems("bank_view.items", ins.bank_view.items, by_id))
    if ins.bank_view.available != bool(ins.bank_view.items):
        p.append(Problem("bank_view", "bank_view_inconsistent", "available не соответствует items"))
    used = [s for c in ins.why_it_matters + ins.impacts for s in c.source_ids]
    factors = {s for s in used if s.startswith("f:")} | {s.split("#")[0] for s in used if s.startswith("b:")}
    if len(factors) < 2:
        p.append(Problem("why_it_matters", "single_factor", "учтено меньше двух факторов (признаков клиента / документов банка)"))
    missing = [r for r in ROLES if r not in ins.role_views]
    if missing:
        p.append(Problem("role_views", "missing_role", f"нет ролей: {missing}"))
    if any(i.stale for i in ins.bank_view.items) and not ins.caveats:
        p.append(Problem("caveats", "stale_without_caveat", "использована устаревшая аналитика без оговорки"))
    return p


def check_chat(ans: ChatAnswer, sources: list[Source]) -> list[Problem]:
    return [x for x in _claim_problems("claims", ans.claims, {s.id: s for s in sources}) if x.code != "no_source"]
