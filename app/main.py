import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException

from app.db import connect, init_schema
from app.ingest import ensure_ingested

DEMO_MODE = os.environ.get("DEMO_MODE", "1") == "1"


@asynccontextmanager
async def lifespan(app: FastAPI):
    conn = connect()
    init_schema(conn)
    ensure_ingested(conn, Path("data"))
    conn.close()
    yield


app = FastAPI(title="Альфа Инсайт", lifespan=lifespan)


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/debug/profile/{group_id}")
def debug_profile(group_id: str):
    if not DEMO_MODE:
        raise HTTPException(404)
    row = connect().execute("select profile from groups where group_id=?", (group_id,)).fetchone()
    if not row or not row[0]:
        raise HTTPException(404, "Группа не найдена или не целевая")
    return json.loads(row[0])


@app.get("/api/debug/news")
def debug_news(limit: int = 50):
    if not DEMO_MODE:
        raise HTTPException(404)
    rows = connect().execute("select news_id, source, published_at, title, classification from news "
                             "order by published_at desc limit ?", (limit,)).fetchall()
    return [{**dict(r), "classification": json.loads(r["classification"]) if r["classification"] else None} for r in rows]
