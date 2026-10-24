def good_insight_for(group_id="G", news_id="n1", trace_id="t"):
    """Валидный по §3.4 инсайт: проходит все инварианты."""
    return {
        "insight_id": f"ins_{group_id}_{news_id}", "group_id": group_id, "news_id": news_id, "trace_id": trace_id,
        "impact": "risk",
        "headline": "Удешевление кредитов приостановлено — нагрузка по лизингу не снизится",
        "event": {"title": "ЦБ сохранил ставку 14%", "date": "2026-09-11",
                  "facts": [{"text": "ЦБ сохранил ключевую ставку 14%", "origin": "fact", "source_ids": [news_id]}]},
        "relevance": {"score": 0.8, "components": [{"name": "products", "value": 0.3, "evidence": "лизинг"}]},
        "affected_members": [{"uid": "U_1", "alias": "Участник 1", "reason": "лизинг"}],
        "why_it_matters": [
            {"text": "41 компания группы платит по лизингу с плавающей ставкой", "origin": "ai",
             "source_ids": [news_id, "f:products.leasing"]},
            {"text": "Поставщики в стройке чувствительны к ставке", "origin": "ai",
             "source_ids": ["f:counterparty_mix.out"]}],
        "impacts": [{"type": "risk", "text": "Стоимость обслуживания долга останется высокой", "horizon": "3–6 мес",
                     "confidence": "med", "origin": "bank", "source_ids": ["b:policy#p2"]}],
        "bank_view": {"available": True, "items": [{"text": "Риторика ЦБ стала жёстче", "origin": "bank",
                                                    "source_ids": ["b:policy#p1"], "doc_date": "2026-09-11",
                                                    "stale": False}]},
        "actions": [{"text": "Сравнить фиксированную и плавающую ставку по лизингу", "product": "refinancing"}],
        "role_views": {r: {"headline": f"{r}: нагрузка не снизится", "focus": ["долг"]}
                       for r in ("CEO", "CFO", "TREASURER")},
        "caveats": [],
        "sources": [{"id": news_id, "type": "news", "ref": "https://example.org"},
                    {"id": "b:policy#p1", "type": "bank_analytics", "ref": "Ключевая ставка, стр. 1"},
                    {"id": "b:policy#p2", "type": "bank_analytics", "ref": "Ключевая ставка, стр. 2"},
                    {"id": "f:products.leasing", "type": "client_data", "ref": "CL_PRODUCT_LEA_MARK"},
                    {"id": "f:counterparty_mix.out", "type": "client_data", "ref": "df_Uid_payment_hack"}],
    }


def good_insight():
    return good_insight_for()
