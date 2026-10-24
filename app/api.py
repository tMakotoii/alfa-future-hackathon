"""REST API. group_id и role всегда берутся из сессии, а не из параметров запроса."""
import json
import os
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from itsdangerous import BadSignature, URLSafeSerializer
from pydantic import BaseModel

from app.db import connect
from app.rank import rank_feed

router = APIRouter(prefix="/api")
Role = Literal["CEO", "CFO", "TREASURER"]


def demo_mode() -> bool:
    return os.environ.get("DEMO_MODE", "1") == "1"


def _serializer() -> URLSafeSerializer:
    return URLSafeSerializer(os.environ.get("SESSION_SECRET", "dev-secret"), salt="session")


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
