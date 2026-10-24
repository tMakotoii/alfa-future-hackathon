"""Демо-срез данных кейса для запуска без полных CSV: data/demo/*.csv.gz.

Компании — все строки (на них считается позиция в отрасли), но только колонки, которые читает app/ingest.py.
Платежи — только с участием компаний трёх демо-групп. Пересборка: python -m uv run python scripts/make_demo_slice.py
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.ingest import COLUMNS, DEMO_GROUPS  # noqa: E402

SRC, DST = Path("data/Классы данных для решения задачи"), Path("data/demo")
DST.mkdir(exist_ok=True)

companies = pd.read_csv(SRC / "df_Uid_data_hack.csv", sep=";", dtype={"MAINOKVED_CODE": str}, usecols=list(COLUMNS))
uids = set(companies[companies.GROUP_ID.isin(DEMO_GROUPS)].SYNTHETIC_U)
payments = pd.read_csv(SRC / "df_Uid_payment_hack.csv", sep=";")
payments = payments[payments.PAYER.isin(uids) | payments.BENEFICIARY.isin(uids)]

companies.to_csv(DST / "df_Uid_data_hack.csv.gz", sep=";", index=False)
payments.to_csv(DST / "df_Uid_payment_hack.csv.gz", sep=";", index=False)
for f in sorted(DST.iterdir()):
    print(f, f"{f.stat().st_size / 1e6:.1f} МБ")
