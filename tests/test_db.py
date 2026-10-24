from fastapi.testclient import TestClient

from app.db import connect, init_schema
from app.main import app


def test_schema_creates_all_tables(tmp_path):
    conn = connect(str(tmp_path / "t.db"))
    init_schema(conn)
    init_schema(conn)  # идемпотентно
    names = {r[0] for r in conn.execute("select name from sqlite_master")}
    assert {"companies", "groups", "counterparties", "users", "bank_chunks", "bank_fts", "news", "news_fts",
            "insights", "trace_steps", "llm_calls", "llm_cache", "feedback", "chat_messages"} <= names


def test_health():
    assert TestClient(app).get("/api/health").json() == {"ok": True}
