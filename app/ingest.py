"""CSV кейса → таблицы companies / groups (+profile) / counterparties."""
import json
import logging
import re
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)
TARGET_REVENUE = 15e9

DEMO_GROUPS = {
    "group_134402_sb": "Группа «Опт-Импорт»",
    "group_134409_sb": "Группа «СтройГрупп»",
    "group_133141_sb": "Группа «АвтоХолдинг»",
}
_PREFIX = {"group_134402_sb": "opt", "group_134409_sb": "stroy", "group_133141_sb": "auto"}
DEMO_USERS = [(f"{p}-{r.lower()}", g, r) for g, p in _PREFIX.items() for r in ("CEO", "CFO", "TREASURER")]

PRODUCTS = {"rko": "p_rko", "guarantee": "p_gar", "credit": "p_loa", "leasing": "p_lea",
            "deposit": "p_dep", "payroll": "p_zpp", "factoring": "factoring"}

COLUMNS = {
    "SYNTHETIC_U": "uid", "GROUP_ID": "group_id", "MAINOKVED_CODE": "okved", "MAINOKVED_NAME": "okved_name",
    "REVENUE_COMPANY": "revenue", "REGION": "region", "CITY": "city", "CL_TYPE": "cl_type",
    "CL_PRODUCT_RKO_MARK": "p_rko", "CL_PRODUCT_GAR_MARK": "p_gar", "CL_PRODUCT_LOA_MARK": "p_loa",
    "CL_PRODUCT_LEA_MARK": "p_lea", "CL_PRODUCT_DEP_MARK": "p_dep", "CL_PRODUCT_ZPP_MARK": "p_zpp",
    "FTS_FLAG": "fts_flag", "FTS_COUNTRY_NAME": "fts_country", "FACTORING_MARK": "factoring",
    "NEGATIVEMARK": "negative", "COMPANY_AGE_YEARS_GRADATION": "age_grad",
    "AMOUNT_WORKERS_FNS_GRADATION": "workers_fns", "AMOUNT_WORKERS_SPARK_GRADATION": "workers_spark",
}
FLAGS = ["p_rko", "p_gar", "p_loa", "p_lea", "p_dep", "p_zpp", "fts_flag", "factoring", "negative"]


def _nn(v):
    return None if pd.isna(v) else v


def _csv(data_dir: Path, name: str) -> Path:
    """Полные данные кейса — .csv, демо-срез (scripts/make_demo_slice.py) — .csv.gz."""
    plain = data_dir / f"{name}.csv"
    return plain if plain.exists() else data_dir / f"{name}.csv.gz"


def _load_companies(data_dir: Path) -> tuple[pd.DataFrame, pd.Series]:
    raw = pd.read_csv(_csv(data_dir, "df_Uid_data_hack"), sep=";", dtype={"MAINOKVED_CODE": str})
    df = raw.rename(columns=COLUMNS)[list(COLUMNS.values())]
    dups = df[df.duplicated("uid")].groupby("group_id").size()
    df = df.drop_duplicates("uid").copy()
    df["okved2"] = df.okved.astype(str).str.split(".").str[0].where(df.okved.notna())
    df["revenue"] = df.revenue.fillna(0.0)
    for f in FLAGS:
        df[f] = df[f].astype("Int64")  # NaN остаётся NULL
    return df, dups


def _shares(s: pd.Series) -> list[dict]:
    total = s.sum()
    if not total:
        return []
    return [{"okved2": k, "share": round(v / total, 4)} for k, v in s.sort_values(ascending=False).head(5).items()]


def _concentration(amounts: pd.Series) -> tuple[float, float]:
    total = amounts.sum()
    if not total:
        return 0.0, 0.0
    sh = amounts / total
    return round(sh.sort_values(ascending=False).head(5).sum(), 4), round((sh ** 2).sum(), 4)


def build_profile(members: pd.DataFrame, cp_out: pd.DataFrame, cp_in: pd.DataFrame,
                  position: dict, display_name: str, dup_count: int = 0) -> dict:
    """members — строки companies группы; cp_* — агрегат по контрагенту (cp_uid, cp_okved2, amount)."""
    rev = members.revenue.sum()
    by_okved = members.groupby("okved2").revenue.sum()
    names = members.drop_duplicates("okved2").set_index("okved2").okved_name
    sector_mix = [{"okved2": d["okved2"], "name": _nn(names.get(d["okved2"])), "share": d["share"]}
                  for d in _shares(by_okved)]
    def rev_share(mask) -> float:
        return round(float(members.revenue[mask].sum() / rev), 4) if rev else 0.0

    products = {k: {"n": int(members[c].fillna(0).sum()), "revenue_share": rev_share(members[c].fillna(0) == 1)}
                for k, c in PRODUCTS.items()}
    fts = members[members.fts_flag.fillna(0) == 1]
    countries = sorted({c.strip().upper() for v in fts.fts_country.dropna() for c in str(v).split(",") if c.strip()})
    products["fts"] = {"n": len(fts), "revenue_share": rev_share(members.fts_flag.fillna(0) == 1),
                       "countries": countries}
    regions = members.groupby("region").revenue.sum().sort_values(ascending=False).index.tolist()
    t5o, hhio = _concentration(cp_out.amount)
    t5i, hhii = _concentration(cp_in.amount)

    gaps = []
    if dup_count:
        gaps.append(f"SYNTHETIC_U: {dup_count} дублей строк, взята первая")
    for col, label in [("workers_spark", "AMOUNT_WORKERS_SPARK_GRADATION"), ("workers_fns", "AMOUNT_WORKERS_FNS_GRADATION"),
                       ("region", "REGION"), ("okved", "MAINOKVED_CODE")]:
        miss = int(members[col].isna().sum())
        if miss == len(members):
            gaps.append(f"{label}: нет данных")
        elif miss:
            gaps.append(f"{label}: {miss} из {len(members)} пусто")
    if len(fts) and len(fts) - fts.fts_country.notna().sum():
        gaps.append(f"FTS_COUNTRY_NAME: {len(fts) - int(fts.fts_country.notna().sum())} из {len(fts)} пусто")
    flag_gaps = [c for c in FLAGS if members[c].isna().any()]
    if flag_gaps:
        gaps.append("флаги продуктов с пропусками (считаем как 0): " + ", ".join(flag_gaps))
    if cp_out.empty and cp_in.empty:
        gaps.append("платежи с внешними контрагентами: нет данных")

    return {
        "group_id": members.group_id.iat[0], "display_name": display_name,
        "features": {
            "revenue_total": {"value": float(rev), "src": "sum(df_Uid_data_hack.REVENUE_COMPANY)"},
            "n_companies": {"value": len(members), "src": "count(SYNTHETIC_U) by GROUP_ID"},
            "sector_mix": {"value": sector_mix, "src": "calc:revenue_by_okved2"},
            "products": {"value": products, "src": "CL_PRODUCT_*_MARK, FTS_FLAG, FTS_COUNTRY_NAME, FACTORING_MARK"},
            "sector_position": {"value": position, "src": "calc:rank_in_dataset", "confidence": "low",
                                "note": "оценка по выборке банка, не рыночная доля"},
            "counterparty_mix": {"value": {"out": _shares(cp_out.groupby("cp_okved2").amount.sum()),
                                           "in": _shares(cp_in.groupby("cp_okved2").amount.sum()),
                                           "top5_share_out": t5o, "hhi_out": hhio,
                                           "top5_share_in": t5i, "hhi_in": hhii},
                                 "src": "df_Uid_payment_hack, без внутригрупповых"},
            "regions": {"value": regions, "src": "REGION"},
            "negative_marks": {"value": int(members.negative.fillna(0).sum()), "src": "NEGATIVEMARK"},
        },
        "data_gaps": gaps,
    }


def ingest_clients(conn, data_dir: Path) -> None:
    data_dir = Path(data_dir)
    df, dups = _load_companies(data_dir)
    cols = ["uid", "group_id", "okved", "okved2", "okved_name", "revenue", "region", "city", "cl_type",
            "p_rko", "p_gar", "p_loa", "p_lea", "p_dep", "p_zpp", "fts_flag", "fts_country", "factoring",
            "negative", "age_grad", "workers_fns"]
    rows = [tuple(_nn(v) if not hasattr(v, "item") else v.item() for v in r)
            for r in df[cols].astype(object).itertuples(index=False)]
    conn.executemany(f"insert or replace into companies({','.join(cols)}) values ({','.join('?' * len(cols))})", rows)

    # группы: выручка, главный ОКВЭД-2, ранг в отрасли
    g = df.groupby("group_id").agg(revenue_total=("revenue", "sum"), n=("uid", "size"))
    main = (df.groupby(["group_id", "okved2"]).revenue.sum().reset_index()
            .sort_values("revenue").drop_duplicates("group_id", keep="last").set_index("group_id").okved2)
    g["main_okved2"] = main
    g["is_target"] = (g.revenue_total > TARGET_REVENUE).astype(int)
    g["rank"] = g.groupby("main_okved2").revenue_total.rank(ascending=False, method="min")
    g["of"] = g.groupby("main_okved2").revenue_total.transform("size")
    g["share_in_sample"] = g.revenue_total / g.groupby("main_okved2").revenue_total.transform("sum")
    targets = g[g.is_target == 1].sort_values("revenue_total", ascending=False)
    names = {gid: DEMO_GROUPS.get(gid, f"Группа №{i + 1}") for i, gid in enumerate(targets.index)}

    # платежи: только с участием целевых групп, без внутригрупповых
    pay = pd.read_csv(_csv(data_dir, "df_Uid_payment_hack"), sep=";")
    grp, okv = df.set_index("uid").group_id, df.set_index("uid").okved2
    pay["pg"], pay["bg"] = pay.PAYER.map(grp), pay.BENEFICIARY.map(grp)
    pay = pay[pay.pg != pay.bg]
    tset = set(targets.index)
    out = pay[pay.pg.isin(tset)].rename(columns={"pg": "group_id", "BENEFICIARY": "cp_uid"})
    inn = pay[pay.bg.isin(tset)].rename(columns={"bg": "group_id", "PAYER": "cp_uid"})
    cps = {}
    for direction, part in (("out", out), ("in", inn)):
        a = part.groupby(["group_id", "cp_uid"]).agg(amount=("PAY_AMT", "sum"), cnt=("PAY_CNT", "sum")).reset_index()
        a["cp_okved2"] = a.cp_uid.map(okv)
        cps[direction] = a
        top = a.sort_values("amount", ascending=False).groupby("group_id").head(10).copy()
        top["rank"] = top.groupby("group_id").amount.rank(ascending=False, method="first").astype(int)
        conn.executemany(
            "insert into counterparties(group_id,direction,cp_uid,cp_okved2,amount,cnt,rank) values (?,?,?,?,?,?,?)",
            [(r.group_id, direction, r.cp_uid, _nn(r.cp_okved2), float(r.amount), int(r.cnt), int(r.rank))
             for r in top.itertuples()])

    by_group = dict(tuple(df[df.group_id.isin(tset)].groupby("group_id")))
    cp_by = {d: dict(tuple(cps[d].groupby("group_id"))) for d in cps}
    empty = pd.DataFrame(columns=["cp_uid", "cp_okved2", "amount"])
    group_rows = []
    for gid, r in g.iterrows():
        profile = None
        if r.is_target:
            pos = {"okved2": r.main_okved2, "rank": int(r["rank"]), "of": int(r["of"]),
                   "share_in_sample": round(float(r.share_in_sample), 4)}
            profile = json.dumps(build_profile(by_group[gid], cp_by["out"].get(gid, empty), cp_by["in"].get(gid, empty),
                                               pos, names[gid], int(dups.get(gid, 0))), ensure_ascii=False)
        group_rows.append((gid, names.get(gid), float(r.revenue_total), int(r.n), _nn(r.main_okved2),
                           int(r.is_target), profile))
    conn.executemany("insert or replace into groups values (?,?,?,?,?,?,?)", group_rows)
    conn.commit()


BANK_DOCS = {
    "alfa-macro_insights-policy_rate_11sep": ("Ключевая ставка ЦБ РФ: ставка без изменения на 14,0%", date(2026, 9, 11)),
    "бонд_бриф_14092026": ("Бонд Бриф", date(2026, 9, 14)),
    "fi_strategy_3q26_22072026": ("Стратегия на долговом рынке, 3К26", date(2026, 7, 22)),
    "alfa_russian_steels_1к21previewupdate_15apr2021": ("Российские сталелитейщики: превью 1К21", date(2021, 4, 15)),
    "gold_digest_august26": ("Дайджест рынка золота, август 2026", date(2026, 8, 31)),
    "alfa-7m26": ("Макростатистика 7М26", date(2026, 9, 7)),
    "alfa-macro_stat1h26": ("Макростатистика 1П26", date(2026, 7, 31)),
    "alfa-consumption": ("Потребление на пике", date(2026, 8, 5)),
    "inflation_tracker_02": ("Инфляция 25–31 августа: основные выводы", date(2026, 9, 2)),
}
STALE_DAYS = 180
MAX_CHUNK = 1600
TARGET_CHUNK = 800


def _split(text: str) -> list[str]:
    if len(text) <= MAX_CHUNK:
        return [text]
    parts, cur = [], ""
    for para in re.split(r"\n\s*\n", text):
        while len(para) > TARGET_CHUNK:  # слишком длинный абзац — режем жёстко
            parts.append(para[:TARGET_CHUNK])
            para = para[TARGET_CHUNK:]
        if cur and len(cur) + len(para) + 2 > TARGET_CHUNK:
            parts.append(cur)
            cur = ""
        cur = f"{cur}\n\n{para}" if cur else para
    if cur:
        parts.append(cur)
    return parts


def ingest_bank(conn, corpus_path: Path, today: date | None = None) -> None:
    today = today or date.today()
    rows = []
    for line in Path(corpus_path).read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        title, d = BANK_DOCS.get(r["doc_id"], (r["doc_id"], None))
        stale = int(d is None or d < today - timedelta(days=STALE_DAYS))
        for i, chunk in enumerate(_split(r["text"])):
            cid = f"{r['doc_id']}#p{r['page']}" + (f"-{i}" if i else "")
            rows.append((cid, r["doc_id"], title, d.isoformat() if d else None, r["page"], chunk, stale))
    conn.executemany("insert or ignore into bank_chunks values (?,?,?,?,?,?,?)", rows)
    conn.commit()


def fts_query(text: str) -> str:
    """Свободный текст → безопасный FTS5-запрос: слова через OR, грубый стемминг префиксом."""
    terms = []
    for w in dict.fromkeys(re.findall(r"\w+", text.lower())):
        if w.isdigit():
            terms.append(f'"{w}"')
        elif len(w) >= 3:
            # ponytail: префикс 5 символов вместо морфологии; заменить на pymorphy, если поиск промахивается
            terms.append(f'"{w[:5]}"*' if len(w) > 5 else f'"{w}"*')
    return " OR ".join(terms)


def search_bank(conn, query: str, k: int = 5) -> list[dict]:
    q = fts_query(query)
    if not q:
        return []
    rows = conn.execute(
        "select c.*, bm25(bank_fts) as rank from bank_fts join bank_chunks c on c.rowid = bank_fts.rowid "
        "where bank_fts match ? order by rank limit ?", (q, k)).fetchall()
    return [dict(r) for r in rows]


def ensure_ingested(conn, data_root: Path = Path("data")) -> None:
    data_root = Path(data_root)
    if not conn.execute("select 1 from bank_chunks limit 1").fetchone():
        ingest_bank(conn, data_root / "ocr" / "corpus.jsonl")
    if conn.execute("select 1 from groups limit 1").fetchone():
        return
    clients = data_root / "Классы данных для решения задачи"
    if not (clients / "df_Uid_data_hack.csv").exists():
        clients = data_root / "demo"  # нет полных CSV — демо-срез из репозитория
        if not (clients / "df_Uid_data_hack.csv.gz").exists():
            raise RuntimeError("Положите данные кейса в data/Классы данных для решения задачи/")
        log.warning("Полных данных кейса нет — загружаю демо-срез data/demo (3 демо-группы)")
    ingest_clients(conn, clients)
