import json
import time

from app.llm import BudgetExhausted, LLMResult, parse_json


class FakeLLM:
    """Тот же интерфейс, что app.llm.LLM.chat; ответы берутся по purpose из сценария (последний повторяется)."""

    def __init__(self, script: dict[str, list], raise_budget: bool = False, conn=None, delay: float = 0.0):
        self.script = {k: list(v) for k, v in script.items()}
        self.raise_budget, self.conn, self.delay = raise_budget, conn, delay
        self.calls: list[tuple[str, list[dict]]] = []
        self.last_messages: list[dict] = []

    def chat(self, purpose, messages, *, json_mode=True, trace_id=None, aliases=None) -> LLMResult:
        if self.raise_budget:
            raise BudgetExhausted("fake")
        self.calls.append((purpose, messages))
        self.last_messages = messages
        if self.delay:
            time.sleep(self.delay)
        queue = self.script.get(purpose)
        if not queue:
            raise AssertionError(f"FakeLLM: нет ответа для {purpose}")
        answer = queue.pop(0) if len(queue) > 1 else queue[0]
        text = answer if isinstance(answer, str) else json.dumps(answer, ensure_ascii=False)
        data = (answer if isinstance(answer, dict) else parse_json(text)) if json_mode else None
        if self.conn is not None:
            self.conn.execute("insert into llm_calls(model, purpose, prompt_tokens, completion_tokens, cost_rub, "
                              "cache_hit, trace_id) values ('fake', ?, 10, 10, 0.01, 0, ?)", (purpose, trace_id))
            self.conn.commit()
        return LLMResult(text, data, "fake", 10, 10, 0.01, False)
