"""Объяснимое ранжирование новостей для группы и роли (без LLM)."""
import fnmatch
import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache

import yaml

from app.ingest import search_bank
from app.sectors import load_sectors, sensitivity

PRODUCT_RU = {"credit": "кредиты", "leasing": "лизинг", "deposit": "депозиты", "guarantee": "гарантии",
              "factoring": "факторинг", "fts": "ВЭД", "payroll": "ЗП-проект", "rko": "РКО"}
DIR_SIGN = {"up": 1, "down": -1, "flat": 0, "unknown": 0}


@dataclass
class Component:
    name: str
    value: float
    evidence: str


@dataclass
class Score:
    value: float
    components: list[Component]


@lru_cache
def load_ranking(path: str = "config/ranking.yaml") -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _mult(table: dict, key: str) -> float:
    return max([v for pat, v in table.items() if fnmatch.fnmatch(key, pat)], default=1.0)


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def score_news(classification: dict, published_at: datetime, profile: dict, role: str, cfg: dict, sectors: dict,
               bank_hit: bool, now: datetime) -> Score:
    f = profile["features"]
    w, roles = cfg["weights"], cfg["role_multipliers"].get(role, {})
    news_okved = set(classification.get("okved2", []))
    factors = [x["name"] for x in classification.get("factors", [])]
    mix = f["sector_mix"]["value"]
    comps: list[tuple[str, float, str]] = []

    # отраслевое совпадение
    hit = [m for m in mix if m["okved2"] in news_okved]
    if not mix:
        comps.append(("sector", 0.0, "нет данных: отрасли группы"))
    elif hit:
        comps.append(("sector", sum(m["share"] for m in hit),
                      "; ".join(f"ОКВЭД {m['okved2']} — {_pct(m['share'])} выручки группы" for m in hit)))
    else:
        comps.append(("sector", 0.0, "отрасли новости не совпадают с отраслями группы"))

    # макрочувствительность отраслей группы
    best = (0.0, "", 0.0)
    covered = sum(m["share"] for m in mix) or 1.0
    for fac in factors:
        sens = sum(sensitivity(sectors, m["okved2"], fac) * m["share"] for m in mix) / covered if mix \
            else sectors["default"].get(fac, 0.0)
        c = abs(sens) * _mult(roles.get("factors", {}), fac)
        if c > best[0]:
            best = (c, fac, sens)
    if best[1]:
        comps.append(("macro", best[0], f"фактор {best[1]}: чувствительность отраслей группы {best[2]:+.2f}"
                      + ("" if mix else " (по умолчанию, нет данных об отраслях)")))
    else:
        comps.append(("macro", 0.0, "в новости нет макрофакторов"))

    # финансовая чувствительность через продукты банка
    products = f["products"]["value"]
    pbest = (0.0, "")
    for fac in factors:
        for prod in cfg["product_map"].get(fac, []):
            p = products.get(prod, {})
            n, share = p.get("n", 0), p.get("revenue_share", 0.0)
            if n:
                # сила = √(доля выручки участников с продуктом): log1p(n) насыщается для групп из сотен компаний
                c = min(1.0, math.sqrt(share)) * _mult(roles.get("factors", {}), fac) \
                    * _mult(roles.get("products", {}), prod)
                if c > pbest[0]:
                    pbest = (c, f"{fac} → {PRODUCT_RU.get(prod, prod)}: {n} участник(ов), "
                                f"{_pct(share)} выручки группы")
    if not products:
        comps.append(("products", 0.0, "нет данных: продукты группы"))
    else:
        comps.append(("products", pbest[0], pbest[1] or "продукты группы не чувствительны к факторам новости"))

    # контрагенты в отраслях новости
    cm = f["counterparty_mix"]["value"]
    out = sum(x["share"] for x in cm.get("out", []) if x["okved2"] in news_okved)
    inn = sum(x["share"] for x in cm.get("in", []) if x["okved2"] in news_okved)
    if not cm.get("out") and not cm.get("in"):
        comps.append(("counterparties", 0.0, "нет данных: платежи с контрагентами"))
    elif out or inn:
        comps.append(("counterparties", max(out, inn),
                      f"в отраслях новости {_pct(out)} платежей поставщикам и {_pct(inn)} поступлений от покупателей"))
    else:
        comps.append(("counterparties", 0.0, "контрагенты группы не в отраслях новости"))

    # регион
    regions = [r.lower() for r in f["regions"]["value"]]
    news_regions = [r.lower() for r in classification.get("regions", [])]
    if "ru" in news_regions or "россия" in news_regions:
        comps.append(("region", 1.0, "федеральное событие"))
    elif not regions:
        comps.append(("region", 0.0, "нет данных: REGION"))
    else:
        match = [r for r in news_regions if any(r in g or g in r for g in regions)]
        comps.append(("region", 1.0 if match else 0.0, f"регион: {', '.join(match)}" if match else "другой регион"))

    age = max((now - published_at).total_seconds() / 86400, 0)
    comps.append(("freshness", math.exp(-math.log(2) * age / cfg["half_life_days"]), f"{age:.1f} дн. назад"))
    comps.append(("bank_view", 1.0 if bank_hit else 0.0,
                  "в аналитике банка есть материалы по теме" if bank_hit else "в аналитике банка нет материалов по теме"))

    comp_mult = roles.get("components", {})
    out_comps = [Component(n, round(w[n] * c * comp_mult.get(n, 1.0), 4), e) for n, c, e in comps]
    return Score(round(min(1.0, sum(c.value for c in out_comps)), 4), out_comps)


def impact_hint(classification: dict, profile: dict, sectors: dict) -> str:
    mix = profile["features"]["sector_mix"]["value"]
    effect = 0.0
    for fac in classification.get("factors", []):
        sens = sum(sensitivity(sectors, m["okved2"], fac["name"]) * m["share"] for m in mix) if mix \
            else sectors["default"].get(fac["name"], 0.0)
        effect += sens * DIR_SIGN.get(fac.get("direction"), 0)
    return "opportunity" if effect > 0.1 else "risk" if effect < -0.1 else "neutral"


def bank_hit(conn, classification: dict, cfg: dict) -> bool:
    kw = cfg["factor_keywords"]
    return any(search_bank(conn, kw[f["name"]], k=1) for f in classification.get("factors", []) if f["name"] in kw)


def rank_feed(conn, group_id: str, role: str, days: int = 7, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    cfg, sectors = load_ranking(), load_sectors()
    row = conn.execute("select profile from groups where group_id=?", (group_id,)).fetchone()
    if not row or not row[0]:
        return []
    profile = json.loads(row[0])
    rows = conn.execute("select news_id, title, source, published_at, cluster_id, classification, origin, owner_group from news "
                        "where classification is not null and published_at >= ?",
                        ((now - timedelta(days=days)).isoformat(),)).fetchall()
    items, seen_clusters = [], set()
    for r in sorted(rows, key=lambda r: r["published_at"], reverse=True):
        cls = json.loads(r["classification"])
        if r["owner_group"] and r["owner_group"] != group_id:  # ручная новость видна только своей группе
            continue
        if not cls.get("is_business") or r["cluster_id"] in seen_clusters:
            continue
        seen_clusters.add(r["cluster_id"])
        pub = datetime.fromisoformat(r["published_at"])
        s = score_news(cls, pub, profile, role, cfg, sectors, bank_hit(conn, cls, cfg), now)
        if s.value < cfg["min_score"] and r["owner_group"] != group_id:  # добавленное пользователем показываем всегда
            continue
        items.append({"news_id": r["news_id"], "title": r["title"], "source": r["source"],
                      "published_at": r["published_at"], "score": s.value,
                      "components": [asdict(c) for c in s.components],
                      "impact_hint": impact_hint(cls, profile, sectors), "topics": cls.get("topics", [])})
    return sorted(items, key=lambda x: -x["score"])
