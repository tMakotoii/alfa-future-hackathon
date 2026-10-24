"""LLM-черновик отраслевых чувствительностей → config/sectors.draft.yaml (сверить и перенести в sectors.yaml руками)."""
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.db import connect  # noqa: E402
from app.llm import LLM, load_models  # noqa: E402
from app.sectors import load_sectors  # noqa: E402

conn = connect()
codes = sorted({r[0] for r in conn.execute(
    "select main_okved2 from groups where is_target=1 union select cp_okved2 from counterparties") if r[0]})
factors = load_sectors()["factors"]
llm = LLM(conn, load_models())
out = {}
for i in range(0, len(codes), 10):
    batch = codes[i:i + 10]
    res = llm.chat("sectors", [
        {"role": "system", "content": "Ты отраслевой аналитик российского корпоративного банка."},
        {"role": "user", "content": f"Для кодов ОКВЭД-2 {batch} оцени, как РОСТ каждого фактора влияет на компании отрасли, "
                                    f"по шкале от -1 до 1 (только значимые, |x|>=0.2). Факторы: {factors}. Верни JSON "
                                    '{"<код>": {"name": "...", "sensitivity": {"<фактор>": число}, "rationale": "1 фраза"}}'}])
    out.update(res.data or {})
    print(batch, "ok")
Path("config/sectors.draft.yaml").write_text(yaml.safe_dump({"sectors": out}, allow_unicode=True, sort_keys=True),
                                              encoding="utf-8")
print("записано", len(out), "отраслей в config/sectors.draft.yaml")
