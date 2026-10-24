"""Единственная точка выхода к LLM: маскирование, кэш, учёт ₽, лестница бюджета, ретраи, fallback."""
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone, date
from typing import Literal

import httpx
import yaml


class LLMError(Exception):
    pass


class BudgetExhausted(LLMError):
    pass


@dataclass
class LLMResult:
    text: str
    data: dict | None
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_rub: float
    cache_hit: bool


def load_models(path: str = "config/models.yaml") -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def parse_json(text: str) -> dict:
    """Достаёт первый JSON-объект из ответа модели (в т.ч. из ```-ограды или текста вокруг)."""
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1)
    start = text.find("{")
    while start != -1:
        try:
            obj, _ = json.JSONDecoder().raw_decode(text[start:])
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
        start = text.find("{", start + 1)
    raise ValueError("в ответе нет JSON-объекта")


def _today_utc() -> date:
    return datetime.now(timezone.utc).date()


def spent_today(conn, today: date | None = None) -> float:
    d = (today or _today_utc()).isoformat()
    return conn.execute("select coalesce(sum(cost_rub), 0) from llm_calls where date(ts) = ?", (d,)).fetchone()[0]


def budget_level(conn, budget_rub: float, today: date | None = None) -> Literal["normal", "fallback", "cache_only"]:
    share = spent_today(conn, today) / budget_rub if budget_rub > 0 else 1.0
    return "normal" if share < 0.7 else "fallback" if share < 0.9 else "cache_only"


def _replace(text: str, mapping: dict[str, str]) -> str:
    for k in sorted(mapping, key=len, reverse=True):
        text = text.replace(k, mapping[k])
    return text


class LLM:
    def __init__(self, conn, cfg: dict, transport: httpx.BaseTransport | None = None, budget_rub: float | None = None):
        self.conn, self.cfg = conn, cfg
        self.budget = budget_rub if budget_rub is not None else float(os.environ.get("DAILY_BUDGET_RUB", 500))
        self.client = httpx.Client(
            base_url=os.environ.get("LLM_BASE_URL", "http://llm.invalid/v1"), transport=transport,
            timeout=cfg.get("timeout_s", 60),
            headers={"Authorization": f"Bearer {os.environ.get('LLM_API_KEY', '')}"})

    def _log(self, model, purpose, pt, ct, cost, cache_hit, trace_id):
        self.conn.execute("insert into llm_calls(model, purpose, prompt_tokens, completion_tokens, cost_rub, cache_hit, "
                          "trace_id) values (?,?,?,?,?,?,?)", (model, purpose, pt, ct, cost, int(cache_hit), trace_id))
        self.conn.commit()

    def _post(self, model: str, messages: list[dict], json_mode: bool) -> tuple[str, int, int]:
        body = {"model": model, "messages": messages, "temperature": 0.2}
        if json_mode and self.cfg.get("response_format_json"):
            body["response_format"] = {"type": "json_object"}
        backoff = self.cfg.get("backoff_s", [1, 2])
        for attempt in range(self.cfg.get("retries", 2) + 1):
            try:
                r = self.client.post("/chat/completions", json=body)
                if r.status_code < 500 and r.status_code != 429:
                    r.raise_for_status()
                    j = r.json()
                    u = j.get("usage") or {}
                    return j["choices"][0]["message"]["content"] or "", u.get("prompt_tokens", 0), u.get("completion_tokens", 0)
            except (httpx.TransportError, KeyError, ValueError):
                pass
            except httpx.HTTPStatusError as e:
                raise LLMError(f"{model}: HTTP {e.response.status_code}") from e
            if attempt < len(backoff):
                time.sleep(backoff[attempt])
        raise LLMError(f"{model}: недоступна")

    def _cost(self, model, pt, ct) -> float:
        p = self.cfg.get("prices_rub_per_1k", {}).get(model, {"in": 0, "out": 0})
        return round(pt / 1000 * p["in"] + ct / 1000 * p["out"], 6)

    def chat(self, purpose: str, messages: list[dict], *, json_mode: bool = True, trace_id: str | None = None,
             aliases: dict[str, str] | None = None) -> LLMResult:
        aliases = aliases or {}
        unmask = {v: k for k, v in aliases.items()}
        masked = [{**m, "content": _replace(m["content"], aliases)} for m in messages]
        level = budget_level(self.conn, self.budget)
        p = self.cfg["purposes"][purpose]
        models = [p["fallback"]] if level == "fallback" else [p["model"], p["fallback"]]
        last_err = None
        for model in models:
            key = hashlib.sha256((model + json.dumps(masked, sort_keys=True, ensure_ascii=False)).encode()).hexdigest()
            row = self.conn.execute("select response from llm_cache where key=?", (key,)).fetchone()
            if row:
                text = _replace(row[0], unmask)
                self._log(model, purpose, 0, 0, 0.0, True, trace_id)
                return LLMResult(text, parse_json(text) if json_mode else None, model, 0, 0, 0.0, True)
            if level == "cache_only":
                continue
            try:
                raw, pt, ct = self._post(model, masked, json_mode)
                data = None
                if json_mode:
                    try:
                        data = parse_json(raw)
                    except ValueError:
                        retry = masked + [{"role": "assistant", "content": raw},
                                          {"role": "user", "content": "Верни только валидный JSON-объект без пояснений."}]
                        raw, pt2, ct2 = self._post(model, retry, json_mode)
                        pt, ct = pt + pt2, ct + ct2
                        data = parse_json(raw)
            except (LLMError, ValueError) as e:
                last_err = e
                continue
            cost = self._cost(model, pt, ct)
            self.conn.execute("insert or replace into llm_cache values (?, ?)", (key, raw))
            self._log(model, purpose, pt, ct, cost, False, trace_id)
            text = _replace(raw, unmask)
            if data is not None:
                data = parse_json(text)
            return LLMResult(text, data, model, pt, ct, cost, False)
        if level == "cache_only":
            raise BudgetExhausted("дневной бюджет LLM исчерпан")
        raise LLMError(str(last_err))
