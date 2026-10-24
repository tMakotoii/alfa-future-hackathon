import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException

from app import jobs
from app.api import router
from app.db import connect, init_schema
from app.ingest import DEMO_USERS, ensure_ingested
from app.llm import LLM, load_models
from app.news import load_snapshot, load_sources

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    conn = connect()
    init_schema(conn)
    ensure_ingested(conn, Path("data"))
    conn.executemany("insert or ignore into users values (?,?,?)", DEMO_USERS)
    conn.commit()
    models = load_models()
    if not hasattr(app.state, "llm_factory"):
        app.state.llm_factory = lambda c: LLM(c, models)
    if os.environ.get("BACKGROUND", "1") == "1":
        load_snapshot(conn, Path("data/news_snapshot.jsonl"))  # лента не пустая с первой минуты
        jobs.start_background(connect, app.state.llm_factory, load_sources(),
                              float(os.environ.get("DAILY_BUDGET_RUB", 500)))
    conn.close()
    yield


app = FastAPI(title="Альфа Инсайт", lifespan=lifespan)
app.include_router(router)


@app.get("/api/health")
def health():
    return {"ok": True}


DIST = Path("web/dist").resolve()
if DIST.exists():  # собранный фронтенд: статика + SPA-fallback на index.html
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404)
        f = (DIST / path).resolve()
        return FileResponse(f if f.is_file() and f.is_relative_to(DIST) else DIST / "index.html")
