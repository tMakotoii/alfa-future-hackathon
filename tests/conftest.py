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
