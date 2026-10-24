"""Фоновые задачи: один запуск агента на (группа, новость), фоновый цикл сбора и предрасчёта."""
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Literal

from app.agent import Trace, new_trace_id, rule_only_insight, run_insight
from app.classify import classify_pending
from app.ingest import DEMO_GROUPS
from app.llm import budget_level
from app.news import fetch_all, load_snapshot
from app.rank import rank_feed

log = logging.getLogger(__name__)
_lock = threading.Lock()
_inflight: dict[tuple[str, str], str] = {}  # (group_id, news_id) -> trace_id
_owner: dict[str, str] = {}  # trace_id -> group_id для ещё не сохранённых трасс
_user_pool = ThreadPoolExecutor(max_workers=2)  # запросы пользователей не ждут фоновый предрасчёт
_bg_pool = ThreadPoolExecutor(max_workers=1)


def is_running(trace_id: str) -> bool:
    with _lock:
        return trace_id in _inflight.values()


def trace_owner(trace_id: str) -> str | None:
    return _owner.get(trace_id)


def _run(conn_factory, llm_factory, group_id: str, news_id: str, trace_id: str) -> None:
    conn = conn_factory()
    try:
        run_insight(conn, llm_factory(conn), group_id, news_id, trace_id)
    except Exception as e:  # агент не должен ронять пул: карточка без AI лучше, чем ничего
        log.exception("агент упал на %s/%s", group_id, news_id)
        Trace(conn, trace_id).step("revise", "error", {}, {"error": str(e)[:500]})
        try:
            rule_only_insight(conn, group_id, news_id, trace_id)
        except Exception:
            log.exception("rule-only тоже упал")
    finally:
        with _lock:
            _inflight.pop((group_id, news_id), None)
        conn.close()


def ensure_insight(conn_factory: Callable, llm_factory: Callable, group_id: str, news_id: str,
                   background: bool = False) -> tuple[Literal["ready", "running"], str]:
    with _lock:
        if (group_id, news_id) in _inflight:
            return "running", _inflight[(group_id, news_id)]
        conn = conn_factory()
        row = conn.execute("select insight_id from insights where group_id=? and news_id=?", (group_id, news_id)).fetchone()
        conn.close()
        if row:
            return "ready", row[0]
        trace_id = new_trace_id()
        _inflight[(group_id, news_id)] = trace_id
        _owner[trace_id] = group_id
    (_bg_pool if background else _user_pool).submit(_run, conn_factory, llm_factory, group_id, news_id, trace_id)
    return "running", trace_id


def wait_idle(timeout: float = 30) -> None:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        with _lock:
            if not _inflight:
                return
        time.sleep(0.05)


def background_cycle(conn_factory: Callable, llm_factory: Callable, sources_cfg: dict, budget_rub: float) -> None:
    conn = conn_factory()
    try:
        fetch_all(conn, sources_cfg)
        since = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
        if conn.execute("select count(*) from news where published_at >= ?", (since,)).fetchone()[0] \
                < sources_cfg.get("snapshot_min_recent", 20):
            load_snapshot(conn, Path("data/news_snapshot.jsonl"))
        llm = llm_factory(conn)
        classify_pending(conn, llm)
        if budget_level(conn, budget_rub) != "normal":
            return
        for group_id in DEMO_GROUPS:
            for item in rank_feed(conn, group_id, "CFO")[:5]:
                ensure_insight(conn_factory, llm_factory, group_id, item["news_id"], background=True)
    finally:
        conn.close()


def start_background(conn_factory: Callable, llm_factory: Callable, sources_cfg: dict, budget_rub: float) -> None:
    def loop():
        while True:
            try:
                background_cycle(conn_factory, llm_factory, sources_cfg, budget_rub)
            except Exception:
                log.exception("фоновый цикл")
            time.sleep(sources_cfg.get("interval_min", 30) * 60)

    threading.Thread(target=loop, daemon=True, name="background").start()
