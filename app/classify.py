import json
import logging

from app.llm import BudgetExhausted, LLMError
from app.prompts import classify_system, wrap_untrusted
from app.schemas import Classification
from app.sectors import load_sectors

log = logging.getLogger(__name__)
MAX_INPUT = 1500
MAX_CONSECUTIVE_ERRORS = 3


def classify_news(conn, llm, news_id: str) -> Classification:
    row = conn.execute("select title, body from news where news_id=?", (news_id,)).fetchone()
    text = f"{row['title']}\n\n{(row['body'] or '')[:MAX_INPUT]}"
    res = llm.chat("classify", [{"role": "system", "content": classify_system()},
                                {"role": "user", "content": wrap_untrusted(text)}])
    c = Classification.model_validate(res.data or {})
    known = set(load_sectors()["factors"])
    c.factors = [f for f in c.factors if f.name in known]
    c.okved2 = list(dict.fromkeys(o.strip()[:2] for o in c.okved2 if o.strip()[:2].isdigit()))
    conn.execute("update news set classification=? where news_id=?",
                 (json.dumps(c.model_dump(), ensure_ascii=False), news_id))
    conn.commit()
    return c


def classify_pending(conn, llm, limit: int = 50) -> int:
    ids = [r[0] for r in conn.execute(
        "select news_id from news where classification is null order by published_at desc limit ?", (limit,))]
    done, errors = 0, 0
    for nid in ids:
        try:
            classify_news(conn, llm, nid)
            done, errors = done + 1, 0
        except BudgetExhausted:
            break
        except (LLMError, ValueError) as e:
            log.warning("классификация %s не удалась: %s", nid, e)
            errors += 1
            if errors >= MAX_CONSECUTIVE_ERRORS:  # модель недоступна — не жжём время до следующего цикла
                break
    return done
