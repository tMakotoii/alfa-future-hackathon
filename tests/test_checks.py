import pytest

from app.schemas import ChatAnswer, Insight, Source, check_chat, check_invariants
from tests.factories import good_insight


def codes(d):
    return {p.code for p in check_invariants(Insight.model_validate(d))}


def test_good_insight_passes():
    assert check_invariants(Insight(**good_insight())) == []


def _single_factor(d):
    d["why_it_matters"] = d["why_it_matters"][:1]
    d["why_it_matters"][0]["source_ids"] = ["n1"]
    d["impacts"][0]["source_ids"] = ["b:policy#p2"]
    d["bank_view"]["items"][0]["source_ids"] = ["b:policy#p1"]


@pytest.mark.parametrize("mutate,code", [
    (lambda d: d["why_it_matters"][0]["source_ids"].append("n99"), "unknown_source"),
    (lambda d: d["event"]["facts"][0].update(source_ids=["b:policy#p1"]), "fact_not_news"),
    (lambda d: d["bank_view"]["items"][0].update(source_ids=["n1"]), "bank_not_bank"),
    (lambda d: d["bank_view"].update(available=False), "bank_view_inconsistent"),
    (lambda d: d["bank_view"].update(items=[]), "bank_view_inconsistent"),
    (_single_factor, "single_factor"),
    (lambda d: d["role_views"].pop("TREASURER"), "missing_role"),
    (lambda d: d["bank_view"]["items"][0].update(stale=True), "stale_without_caveat"),
    (lambda d: d["why_it_matters"][1].update(source_ids=[]), "no_source"),
])
def test_invariant_violations(mutate, code):
    d = good_insight()
    mutate(d)
    assert code in codes(d)


def test_bank_view_must_be_explicit():
    d = good_insight()
    del d["bank_view"]["available"]
    with pytest.raises(ValueError):
        Insight.model_validate(d)


def test_fact_may_cite_client_data():
    d = good_insight()
    d["why_it_matters"][0].update(origin="fact", source_ids=["f:products.leasing"])
    assert "fact_not_news" not in codes(d)


def test_check_chat():
    sources = [Source(id="n1", type="news", ref="u"), Source(id="b:x#p1", type="bank_analytics", ref="x")]
    ok = ChatAnswer.model_validate({"claims": [{"text": "a", "origin": "bank", "source_ids": ["b:x#p1"]}]})
    bad = ChatAnswer.model_validate({"claims": [{"text": "a", "origin": "bank", "source_ids": ["n1", "zz"]}]})
    assert check_chat(ok, sources) == []
    assert {p.code for p in check_chat(bad, sources)} == {"bank_not_bank", "unknown_source"}
