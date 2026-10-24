"""REST API. group_id и role всегда берутся из сессии, а не из параметров запроса."""
import asyncio
import json
import os
import secrets
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from itsdangerous import BadSignature, URLSafeSerializer
from pydantic import BaseModel, Field

from app import jobs
from app.agent import new_trace_id, run_chat
from app.classify import classify_news
from app.db import connect
from app.llm import BudgetExhausted, LLMError
from app.metrics import compute_metrics
from app.news import add_manual
from app.rank import rank_feed

router = APIRouter(prefix="/api")
Role = Literal["CEO", "CFO", "TREASURER"]


def demo_mode() -> bool:
    return os.environ.get("DEMO_MODE", "1") == "1"


_KNOWN_SECRETS = {"", "change-me", "dev-secret"}
_RANDOM_SECRET = secrets.token_hex(32)


def _serializer() -> URLSafeSerializer:
    # известный секрет из примера позволил бы подделать cookie — тогда случайный на процесс (вход сбросится при рестарте)
    secret = os.environ.get("SESSION_SECRET", "")
    return URLSafeSerializer(_RANDOM_SECRET if secret in _KNOWN_SECRETS else secret, salt="session")


def get_conn():
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


def current_user(request: Request) -> dict:
    try:
        return _serializer().loads(request.cookies.get("session", ""))
    except BadSignature:
        raise HTTPException(401, "Требуется вход")


def _set_session(response: Response, user: dict) -> None:
    response.set_cookie("session", _serializer().dumps(user), httponly=True, samesite="lax")


def _profile(conn, group_id: str) -> dict:
    row = conn.execute("select profile from groups where group_id=? and is_target=1", (group_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Группа не найдена")
    return json.loads(row[0])


class LoginIn(BaseModel):
    login: str


class SwitchIn(BaseModel):
    group_id: str | None = None
    role: Role | None = None


@router.post("/login")
def login(body: LoginIn, response: Response, conn=Depends(get_conn)):
    row = conn.execute("select login, group_id, role from users where login=?", (body.login,)).fetchone()
    if not row:
        raise HTTPException(401, "Неизвестная учётная запись")
    user = dict(row)
    _set_session(response, user)
    return user


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie("session")
    return {"ok": True}


@router.get("/me")
def me(user=Depends(current_user), conn=Depends(get_conn)):
    p = _profile(conn, user["group_id"])
    f = p["features"]
    return {**user, "display_name": p["display_name"], "demo_mode": demo_mode(),
            "summary": {"revenue_total": f["revenue_total"]["value"], "n_companies": f["n_companies"]["value"],
                        "sector_mix": f["sector_mix"]["value"][:3], "regions": f["regions"]["value"][:3]}}


@router.get("/profile")
def profile(user=Depends(current_user), conn=Depends(get_conn)):
    return _profile(conn, user["group_id"])


@router.get("/feed")
def feed(impact: str | None = None, topic: str | None = None, days: int = 7,
         user=Depends(current_user), conn=Depends(get_conn)):
    items = rank_feed(conn, user["group_id"], user["role"], days=min(max(days, 1), 30))
    insights = {r["news_id"]: r for r in conn.execute(
        "select news_id, status, payload from insights where group_id=?", (user["group_id"],))}
    out = []
    for it in items:
        ins = insights.get(it["news_id"])
        headline, status = it["title"], "none"
        if ins:
            payload = json.loads(ins["payload"])
            status = ins["status"]
            headline = (payload.get("role_views", {}).get(user["role"], {}).get("headline")
                        or payload.get("headline") or it["title"])
            it["impact_hint"] = payload.get("impact", it["impact_hint"])
        if impact and it["impact_hint"] != impact:
            continue
        if topic and topic not in it["topics"]:
            continue
        out.append({**it, "headline": headline, "insight_status": status})
    return out


@router.get("/demo/groups")
def demo_groups(user=Depends(current_user), conn=Depends(get_conn)):
    if not demo_mode():
        raise HTTPException(403, "Демо-режим выключен")
    rows = conn.execute("select group_id, display_name, revenue_total, main_okved2 from groups where is_target=1 "
                        "order by display_name not like 'Группа «%', revenue_total desc")
    return [dict(r) for r in rows]


@router.post("/demo/switch")
def demo_switch(body: SwitchIn, response: Response, user=Depends(current_user), conn=Depends(get_conn)):
    if not demo_mode():
        raise HTTPException(403, "Демо-режим выключен")
    if body.group_id:
        _profile(conn, body.group_id)
    user = {**user, "group_id": body.group_id or user["group_id"], "role": body.role or user["role"]}
    _set_session(response, user)
    return user


# ---------- инсайты, трассы, чат, источники ----------

def llm_factory(request: Request):
    return request.app.state.llm_factory


def _insight_row(conn, insight_id: str, group_id: str):
    row = conn.execute("select * from insights where insight_id=? and group_id=?", (insight_id, group_id)).fetchone()
    if not row:
        raise HTTPException(404, "Инсайт не найден")
    return row


def _public(row) -> dict:
    payload = json.loads(row["payload"])
    payload.pop("gathered", None)
    return {**payload, "status": row["status"]}


def trace_group(conn, trace_id: str) -> str | None:
    row = conn.execute("select group_id from insights where trace_id=? union select i.group_id from chat_messages c "
                       "join insights i on i.insight_id = c.insight_id where c.trace_id=?", (trace_id, trace_id)).fetchone()
    return row[0] if row else jobs.trace_owner(trace_id)


def _steps(conn, trace_id: str, after: int = -1) -> list[dict]:
    rows = conn.execute("select idx, kind, name, input, output, tokens, cost_rub, ms, ts from trace_steps "
                        "where trace_id=? and idx>? order by idx", (trace_id, after))
    return [{**dict(r), "input": json.loads(r["input"]), "output": json.loads(r["output"])} for r in rows]


def _visible_news(conn, news_id: str, group_id: str):
    row = conn.execute("select * from news where news_id=?", (news_id,)).fetchone()
    if not row or (row["owner_group"] and row["owner_group"] != group_id):
        raise HTTPException(404, "Новость не найдена")
    return row


def _sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


@router.get("/insights/{news_id}")
def get_insight(news_id: str, user=Depends(current_user), conn=Depends(get_conn), make_llm=Depends(llm_factory)):
    _visible_news(conn, news_id, user["group_id"])
    status, ref = jobs.ensure_insight(connect, make_llm, user["group_id"], news_id)
    if status == "running":
        return JSONResponse({"trace_id": ref}, status_code=202)
    return _public(_insight_row(conn, ref, user["group_id"]))


@router.get("/traces/{trace_id}")
def get_trace(trace_id: str, user=Depends(current_user), conn=Depends(get_conn)):
    if trace_group(conn, trace_id) != user["group_id"]:
        raise HTTPException(404, "Трасса не найдена")
    return _steps(conn, trace_id)


@router.get("/traces/{trace_id}/stream")
async def stream_trace(trace_id: str, user=Depends(current_user)):
    conn = connect()
    if trace_group(conn, trace_id) != user["group_id"]:
        conn.close()
        raise HTTPException(404, "Трасса не найдена")

    async def events():
        last, waited = -1, 0.0
        try:
            while True:
                running = jobs.is_running(trace_id)
                for st in _steps(conn, trace_id, last):
                    last = st["idx"]
                    yield _sse("step", st)
                if not running or waited > 120:
                    row = conn.execute("select status from insights where trace_id=?", (trace_id,)).fetchone()
                    yield _sse("done", {"status": row[0] if row else ("timeout" if running else "done")})
                    return
                await asyncio.sleep(0.5)
                waited += 0.5
        finally:
            conn.close()

    return StreamingResponse(events(), media_type="text/event-stream")


class ChatIn(BaseModel):
    question: str = Field(min_length=1, max_length=1000)


@router.post("/insights/{insight_id}/chat")
def chat(insight_id: str, body: ChatIn, user=Depends(current_user), conn=Depends(get_conn),
         make_llm=Depends(llm_factory)):
    _insight_row(conn, insight_id, user["group_id"])
    trace_id = new_trace_id()
    try:
        ans = run_chat(conn, make_llm(conn), insight_id, user["login"], body.question, trace_id)
    except BudgetExhausted:
        raise HTTPException(503, "Дневной бюджет AI исчерпан — чат временно недоступен")
    except LLMError:
        raise HTTPException(503, "Модель временно недоступна, попробуйте позже")
    return {**ans.model_dump(), "trace_id": trace_id}


@router.get("/insights/{insight_id}/chat")
def chat_history(insight_id: str, user=Depends(current_user), conn=Depends(get_conn)):
    _insight_row(conn, insight_id, user["group_id"])
    rows = conn.execute("select role, content, trace_id, ts from chat_messages where insight_id=? and login=? "
                        "order by rowid", (insight_id, user["login"]))
    return [{**dict(r), "content": json.loads(r["content"])} for r in rows]


class FeedbackIn(BaseModel):
    verdict: Literal["up", "down"]
    reason: Literal["irrelevant", "wrong", "other"] | None = None
    comment: str | None = Field(None, max_length=1000)


@router.post("/insights/{insight_id}/feedback")
def feedback(insight_id: str, body: FeedbackIn, user=Depends(current_user), conn=Depends(get_conn)):
    _insight_row(conn, insight_id, user["group_id"])
    conn.execute("insert into feedback(insight_id, login, verdict, reason, comment) values (?,?,?,?,?)",
                 (insight_id, user["login"], body.verdict, body.reason, body.comment))
    conn.commit()
    return {"ok": True}


class ManualNewsIn(BaseModel):
    text: str | None = Field(None, max_length=200_000)
    url: str | None = Field(None, max_length=2000)


FALLBACK_CLASSIFICATION = {"is_business": True, "topics": ["other"], "okved2": [], "factors": [], "regions": ["RU"],
                           "entities": [], "facts": [], "sentiment": "neutral"}


@router.post("/news/manual")
def manual_news(body: ManualNewsIn, user=Depends(current_user), conn=Depends(get_conn), make_llm=Depends(llm_factory)):
    if not (body.text or "").strip() and not body.url:
        raise HTTPException(422, "Укажите текст новости или URL")
    try:
        news_id = add_manual(conn, text=body.text, url=body.url, owner_group=user["group_id"])
    except ValueError as e:
        raise HTTPException(422, str(e))
    classified = True
    if not conn.execute("select classification from news where news_id=?", (news_id,)).fetchone()[0]:
        try:
            classify_news(conn, make_llm(conn), news_id)
        except (LLMError, ValueError):
            classified = False  # без LLM новость всё равно попадает в ленту с минимальной классификацией
            title = conn.execute("select title from news where news_id=?", (news_id,)).fetchone()[0]
            fb = {**FALLBACK_CLASSIFICATION, "facts": [{"text": title, "confirmed": True}]}
            conn.execute("update news set classification=? where news_id=?", (json.dumps(fb, ensure_ascii=False), news_id))
            conn.commit()
    return {"news_id": news_id, "classified": classified}


@router.get("/sources/news/{news_id}")
def source_news(news_id: str, user=Depends(current_user), conn=Depends(get_conn)):
    row = _visible_news(conn, news_id, user["group_id"])
    return {**{k: row[k] for k in ("news_id", "source", "url", "published_at", "title", "body", "origin")}, "classification": json.loads(row["classification"]) if row["classification"] else None}


@router.get("/sources/bank/{doc_id}/{page}")
def source_bank(doc_id: str, page: int, user=Depends(current_user), conn=Depends(get_conn)):
    rows = conn.execute("select doc_title, doc_date, stale, text from bank_chunks where doc_id=? and page=? "
                        "order by chunk_id", (doc_id, page)).fetchall()
    if not rows:
        raise HTTPException(404, "Страница не найдена")
    return {"doc_id": doc_id, "page": page, "doc_title": rows[0]["doc_title"], "doc_date": rows[0]["doc_date"],
            "stale": bool(rows[0]["stale"]), "text": "\n\n".join(r["text"] for r in rows)}


@router.get("/metrics")
def metrics(user=Depends(current_user), conn=Depends(get_conn)):
    return compute_metrics(conn)
