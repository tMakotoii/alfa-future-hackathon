from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from app.db import connect, init_schema
from app.news import NewsItem, add_manual, fetch_rss, load_snapshot, upsert_news

NOW = datetime.now(timezone.utc)


@pytest.fixture
def db(tmp_path):
    c = connect(str(tmp_path / "n.db"))
    init_schema(c)
    return c


def mock_client(path):
    data = Path(path).read_bytes()
    return httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=data)))


def failing_client():
    def boom(request):
        raise httpx.ConnectError("down")
    return httpx.Client(transport=httpx.MockTransport(boom))


def cluster_of(db, news_id):
    return db.execute("select cluster_id from news where news_id=?", (news_id,)).fetchone()[0]


def test_fetch_rss_parses_fixture():
    items = fetch_rss({"id": "cbr", "url": "https://x/rss"}, mock_client("tests/fixtures/rss_cbr.xml"))
    assert len(items) == 3 and items[0].title and items[0].published_at.tzinfo is not None
    assert "<p>" not in items[0].body and "&nbsp;" not in items[0].body and items[0].body


def test_dedup_and_cluster(db):
    a = NewsItem("rbc", "u1", NOW, "ЦБ сохранил ключевую ставку на уровне 14%", "", "rss")
    b = NewsItem("interfax", "u2", NOW, "ЦБ сохранил ключевую ставку на уровне 14 %", "", "rss")
    c = NewsItem("tass", "u3", NOW, "Банк России оставил ключевую ставку 14% без изменений", "", "rss")
    d = NewsItem("finmarket", "u4", NOW, "ЦБ сохранил ключевую ставку на уровне 14% годовых", "", "rss")
    ids = upsert_news(db, [a, a, b, c, d])
    assert len(ids) == 3  # a и b — один hash
    id_a, id_c, id_d = ids
    assert cluster_of(db, id_a) == cluster_of(db, id_d)
    assert cluster_of(db, id_c) != cluster_of(db, id_a)
    assert upsert_news(db, [a]) == []


def test_manual_validation(db):  # Review Focus 4
    with pytest.raises(ValueError):
        add_manual(db, text="   ")
    with pytest.raises(ValueError):
        add_manual(db, url="http://unreachable", client=failing_client())
    nid = add_manual(db, text="x" * 50_000)
    assert len(db.execute("select body from news where news_id=?", (nid,)).fetchone()[0]) <= 20_000


def test_manual_url_extracts_text(db):
    html = "<html><head><title>Пошлины на импорт</title></head><body><p>Правительство повысило пошлины.</p></body></html>"
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=html)))
    nid = add_manual(db, url="https://example.org/a", client=client)
    row = db.execute("select title, body, origin from news where news_id=?", (nid,)).fetchone()
    assert row["title"] == "Пошлины на импорт" and "пошлины" in row["body"] and row["origin"] == "manual"


def test_manual_duplicate_returns_same_id(db):
    assert add_manual(db, text="ЦБ поднял ставку\nподробности") == add_manual(db, text="ЦБ поднял ставку\nподробности")


def test_snapshot_loads(db, tmp_path):
    p = tmp_path / "s.jsonl"
    p.write_text('{"source":"cbr","url":"u","published_at":"2026-10-23T10:00:00+00:00","title":"T1","body":"B"}\n',
                 encoding="utf-8")
    assert load_snapshot(db, p) == 1
    assert db.execute("select origin from news").fetchone()[0] == "snapshot"
