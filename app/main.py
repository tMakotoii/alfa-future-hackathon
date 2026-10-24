import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException

from app.api import demo_mode, router
from app.db import connect, init_schema
from app.ingest import DEMO_USERS, ensure_ingested


@asynccontextmanager
async def lifespan(app: FastAPI):
    conn = connect()
    init_schema(conn)
    ensure_ingested(conn, Path("data"))
    conn.executemany("insert or ignore into users values (?,?,?)", DEMO_USERS)
    conn.commit()
    conn.close()
    yield


app = FastAPI(title="Альфа Инсайт", lifespan=lifespan)
app.include_router(router)


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/debug/profile/{group_id}")
def debug_profile(group_id: str):
    if not demo_mode():
        raise HTTPException(404)
    row = connect().execute("select profile from groups where group_id=?", (group_id,)).fetchone()
    if not row or not row[0]:
        raise HTTPException(404, "Группа не найдена или не целевая")
    return json.loads(row[0])


@app.get("/api/debug/news")
def debug_news(limit: int = 50):
    if not demo_mode():
        raise HTTPException(404)
    rows = connect().execute("select news_id, source, published_at, title, classification from news "
                             "order by published_at desc limit ?", (limit,)).fetchall()
    return [{**dict(r), "classification": json.loads(r["classification"]) if r["classification"] else None} for r in rows]
