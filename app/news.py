"""Сбор новостей: RSS, ручной ввод, снапшот; дедуп и кластеризация одного события."""
import hashlib
import html
import json
import logging
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import feedparser
import httpx
import yaml

log = logging.getLogger(__name__)
MAX_BODY = 20_000
CLUSTER_JACCARD = 0.5
CLUSTER_WINDOW = timedelta(hours=48)


@dataclass
class NewsItem:
    source: str
    url: str
    published_at: datetime
    title: str
    body: str
    origin: str


def load_sources(path: str = "config/sources.yaml") -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def clean_html(text: str) -> str:
    text = re.sub(r"<!--.*?-->", " ", text or "", flags=re.S)
    text = re.sub(r"<(script|style)\b.*?</\1>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def norm_title(title: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", title.lower())).strip()


def _shingles(s: str) -> set[str]:
    return {s[i:i + 3] for i in range(max(len(s) - 2, 1))}


def _as_utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def fetch_rss(source: dict, client: httpx.Client) -> list[NewsItem]:
    r = client.get(source["url"], follow_redirects=True)
    r.raise_for_status()
    feed = feedparser.parse(r.content)
    items = []
    for e in feed.entries:
        body = (e.get("content") or [{}])[0].get("value") or e.get("summary", "")
        when = e.get("published") or e.get("updated")
        try:
            published = _as_utc(parsedate_to_datetime(when)) if when else datetime.now(timezone.utc)
        except (TypeError, ValueError):
            published = datetime.now(timezone.utc)
        title = clean_html(e.get("title", ""))
        if title:
            items.append(NewsItem(source["id"], e.get("link", ""), published, title,
                                  clean_html(body)[:MAX_BODY], "rss"))
    return items


def upsert_news(conn, items: list[NewsItem]) -> list[str]:
    """Вставляет новые новости, возвращает их news_id; дубли по нормализованному заголовку пропускаются."""
    new_ids = []
    for it in items:
        nt = norm_title(it.title)
        h = hashlib.sha1(nt.encode()).hexdigest()
        if conn.execute("select 1 from news where hash=?", (h,)).fetchone():
            continue
        news_id = "n" + h[:10]
        pub = _as_utc(it.published_at)
        cluster_id, sh = news_id, _shingles(nt)
        near = conn.execute("select news_id, cluster_id, title from news where published_at between ? and ?",
                            ((pub - CLUSTER_WINDOW).isoformat(), (pub + CLUSTER_WINDOW).isoformat()))
        for row in near:
            other = _shingles(norm_title(row["title"]))
            if len(sh & other) / len(sh | other) >= CLUSTER_JACCARD:
                cluster_id = row["cluster_id"]
                break
        conn.execute("insert into news(news_id, source, url, published_at, title, body, hash, cluster_id, origin) "
                     "values (?,?,?,?,?,?,?,?,?)",
                     (news_id, it.source, it.url, pub.isoformat(), it.title, it.body[:MAX_BODY], h, cluster_id, it.origin))
        new_ids.append(news_id)
    conn.commit()
    return new_ids


def fetch_all(conn, cfg: dict, client: httpx.Client | None = None) -> int:
    client = client or httpx.Client(timeout=15, headers={"User-Agent": cfg.get("user_agent", "Mozilla/5.0")})
    total = 0
    for src in cfg["sources"]:
        try:
            total += len(upsert_news(conn, fetch_rss(src, client)))
        except Exception as e:  # источник недоступен — пропускаем, остальные продолжают
            log.warning("RSS %s недоступен: %s", src["id"], e)
    return total


def load_snapshot(conn, path: Path) -> int:
    items = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            d = json.loads(line)
            items.append(NewsItem(d["source"], d["url"], datetime.fromisoformat(d["published_at"]),
                                  d["title"], d["body"], "snapshot"))
    return len(upsert_news(conn, items))


def snapshot_line(item: NewsItem) -> str:
    d = asdict(item)
    d["published_at"] = item.published_at.isoformat()
    d.pop("origin")
    return json.dumps(d, ensure_ascii=False)


def add_manual(conn, text: str | None = None, url: str | None = None, client: httpx.Client | None = None,
               owner_group: str | None = None) -> str:
    if url:
        try:
            r = (client or httpx.Client(timeout=15, follow_redirects=True)).get(url)
            r.raise_for_status()
        except (httpx.HTTPError, httpx.InvalidURL, ValueError) as e:
            raise ValueError(f"Не удалось загрузить URL: {e}") from e
        m = re.search(r"<title[^>]*>(.*?)</title>", r.text, re.S | re.I)
        title = clean_html(m.group(1)) if m else ""
        body = " ".join(clean_html(p) for p in re.findall(r"<p\b[^>]*>(.*?)</p>", r.text, re.S | re.I))
        text = f"{title}\n{body}".strip()
    text = (text or "").strip()
    if not text:
        raise ValueError("Пустой текст новости")
    title, _, rest = text.partition("\n")
    title = title.strip()[:200]
    item = NewsItem("manual", url or "", datetime.now(timezone.utc), title, (rest.strip() or text)[:MAX_BODY], "manual")
    ids = upsert_news(conn, [item])
    if ids:
        conn.execute("update news set owner_group=? where news_id=?", (owner_group, ids[0]))
        conn.commit()
        return ids[0]
    h = hashlib.sha1(norm_title(title).encode()).hexdigest()
    return conn.execute("select news_id from news where hash=?", (h,)).fetchone()[0]
