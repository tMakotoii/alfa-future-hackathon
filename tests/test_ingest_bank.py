from app.ingest import search_bank


def test_bank_chunks_and_stale(db_with_bank):
    stale = {r[0] for r in db_with_bank.execute("select distinct doc_id from bank_chunks where stale=1")}
    assert stale == {"alfa_russian_steels_1к21previewupdate_15apr2021"}
    assert db_with_bank.execute("select max(length(text)) from bank_chunks").fetchone()[0] <= 1600


def test_every_doc_has_date(db_with_bank):
    assert db_with_bank.execute("select count(*) from bank_chunks where doc_date is null").fetchone()[0] == 0


def test_search_bank_finds_policy_rate(db_with_bank):
    hits = search_bank(db_with_bank, "ключевая ставка 14%")
    assert hits and hits[0]["doc_id"] in {"alfa-macro_insights-policy_rate_11sep", "бонд_бриф_14092026",
                                          "fi_strategy_3q26_22072026"}
    assert {"chunk_id", "doc_id", "doc_title", "doc_date", "page", "text", "stale", "rank"} <= hits[0].keys()


def test_search_bank_inflected_forms(db_with_bank):
    assert search_bank(db_with_bank, "ключевой ставки")


def test_search_bank_survives_fts_syntax(db_with_bank):
    assert isinstance(search_bank(db_with_bank, 'ставка" OR (NEAR'), list)
    assert search_bank(db_with_bank, "") == []
