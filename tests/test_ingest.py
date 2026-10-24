import json


def profile(db, gid):
    return json.loads(db.execute("select profile from groups where group_id=?", (gid,)).fetchone()[0])


def test_only_target_groups_flagged(db):
    rows = dict(db.execute("select group_id, is_target from groups").fetchall())
    assert rows["G1"] == 1 and rows["G2"] == 1 and rows["G3"] == 0


def test_intragroup_payments_excluded(db):
    cps = db.execute("select cp_uid from counterparties where group_id='G1'").fetchall()
    assert cps and all(not r[0].startswith("U_G1") for r in cps)


def test_counterparty_directions(db):
    rows = {(r["direction"], r["cp_uid"], r["cp_okved2"]) for r in db.execute("select * from counterparties where group_id='G1'")}
    assert rows == {("out", "U_X1", "24"), ("in", "U_X2", "10")}


def test_profile_products_and_gaps(db):
    p = profile(db, "G1")
    assert p["features"]["products"]["value"]["leasing"]["n"] == 2
    assert p["features"]["products"]["value"]["fts"]["countries"] == ["КИТАЙ", "ТУРЦИЯ"]
    assert any("дубл" in g for g in p["data_gaps"])
    assert p["features"]["sector_position"]["confidence"] == "low"
    assert p["features"]["counterparty_mix"]["value"]["out"] == [{"okved2": "24", "share": 1.0}]


def test_empty_group_still_has_profile(db):  # Review Focus 3
    p = profile(db, "G2")
    assert p["features"]["products"]["value"]["credit"]["n"] == 0
    assert p["features"]["regions"]["value"] == []
    assert p["data_gaps"]
