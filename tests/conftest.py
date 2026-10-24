from pathlib import Path

import pytest

from app.db import connect, init_schema

FIXTURES = Path(__file__).parent / "fixtures"
REAL_CLIENTS = Path("data/Классы данных для решения задачи")


@pytest.fixture
def db(tmp_path):
    from app.ingest import ingest_clients
    conn = connect(str(tmp_path / "t.db"))
    init_schema(conn)
    ingest_clients(conn, FIXTURES / "clients")
    return conn


@pytest.fixture
def db_with_bank(tmp_path):
    from datetime import date
    from app.ingest import ingest_bank
    conn = connect(str(tmp_path / "b.db"))
    init_schema(conn)
    ingest_bank(conn, Path("data/ocr/corpus.jsonl"), today=date(2026, 10, 24))
    return conn


@pytest.fixture(scope="session")
def real_db_path(tmp_path_factory):
    from app.ingest import ensure_ingested
    path = tmp_path_factory.mktemp("real") / "r.db"
    conn = connect(str(path))
    init_schema(conn)
    ensure_ingested(conn, Path("data"))
    conn.close()
    return path


@pytest.fixture(scope="session")
def real_db(real_db_path):
    return connect(str(real_db_path))


def seed_fixture_news(conn, published_at=None):
    """Вставляет классифицированные фикстурные новости (tests/fixtures/classified_news.json)."""
    import json
    from datetime import datetime, timezone
    published_at = (published_at or datetime.now(timezone.utc)).isoformat()
    for n in json.load(open(FIXTURES / "classified_news.json", encoding="utf-8")):
        conn.execute("insert or ignore into news(news_id, source, url, published_at, title, body, hash, cluster_id, origin,"
                     " classification) values (?,?,?,?,?,?,?,?,?,?)",
                     (n["news_id"], n["source"], "https://example.org/" + n["news_id"], published_at, n["title"],
                      n["title"] + ". Подробности события.", n["news_id"], n["news_id"], "rss",
                      json.dumps(n["classification"], ensure_ascii=False)))
    conn.commit()


@pytest.fixture
def api_db(real_db_path, tmp_path, monkeypatch):
    """Копия реальной БД + фикстурные новости; DB_PATH указывает на неё."""
    import sqlite3
    path = tmp_path / "api.db"
    src, dst = sqlite3.connect(real_db_path), sqlite3.connect(path)
    src.backup(dst)
    src.close(); dst.close()
    monkeypatch.setenv("DB_PATH", str(path))
    monkeypatch.setenv("SESSION_SECRET", "test")
    conn = connect(str(path))
    seed_fixture_news(conn)
    return conn


def _client(monkeypatch, demo: str):
    from fastapi.testclient import TestClient
    from app.main import app
    monkeypatch.setenv("DEMO_MODE", demo)
    return TestClient(app)


@pytest.fixture
def client(api_db, monkeypatch):
    with _client(monkeypatch, "1") as c:
        yield c


@pytest.fixture
def client_no_demo(api_db, monkeypatch):
    with _client(monkeypatch, "0") as c:
        yield c


@pytest.fixture
def real_db_news(api_db):
    """Копия реальной БД с фикстурными новостями (своя на тест)."""
    return api_db
