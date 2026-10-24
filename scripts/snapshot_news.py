"""Сохраняет текущие RSS-новости в data/news_snapshot.jsonl (fallback для офлайн-демо)."""
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.news import fetch_rss, load_sources, snapshot_line  # noqa: E402

cfg = load_sources()
client = httpx.Client(timeout=20, headers={"User-Agent": cfg["user_agent"]})
lines = []
for src in cfg["sources"]:
    try:
        items = fetch_rss(src, client)
    except Exception as e:
        print(f"{src['id']}: ошибка {e}")
        continue
    print(f"{src['id']}: {len(items)}")
    lines += [snapshot_line(i) for i in items]
Path("data/news_snapshot.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
print("итого", len(lines))
