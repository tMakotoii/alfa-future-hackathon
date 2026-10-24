#!/usr/bin/env python3
"""
Офлайн-OCR аналитики Альфа-Банка (PDF-сканы без текстового слоя) — без LLM и без токенов.

Требования: poppler-utils (pdftoppm), tesseract-ocr + языки rus, eng
  Ubuntu/Debian/WSL:  sudo apt install poppler-utils tesseract-ocr tesseract-ocr-rus
  Windows:            choco install poppler tesseract  (и rus.traineddata в tessdata)

Запуск:
  python scripts/ocr_analytics.py --src "data/Аналитические материалы" --out data/ocr

Результат:
  data/ocr/<документ>.md   — текст с маркерами страниц <!-- page N -->
  data/ocr/corpus.jsonl    — {"doc_id","file","page","text","chars"} по одной странице на строку
Повторный запуск пропускает уже распознанные страницы (кэш в data/ocr/.cache).
"""
import argparse, json, os, re, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def slug(name: str) -> str:
    return re.sub(r"[^\w\-]+", "_", name, flags=re.UNICODE).strip("_").lower()


def clean(text: str) -> str:
    text = text.replace("\f", "")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)  # переносы слов
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def ocr_page(png: Path, lang: str) -> str:
    txt = png.with_suffix(".txt")
    if not txt.exists() or txt.stat().st_size == 0:
        subprocess.run(["tesseract", str(png), str(png.with_suffix("")), "-l", lang, "--psm", "3"],
                       check=True, capture_output=True, env={**os.environ, "OMP_THREAD_LIMIT": "1"})
    return txt.read_text(encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="data/Аналитические материалы")
    ap.add_argument("--out", default="data/ocr")
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--lang", default="rus+eng")
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 2)
    ap.add_argument("--cache", default=None, help="папка для PNG и сырого текста (по умолчанию <out>/.cache)")
    a = ap.parse_args()

    src, out = Path(a.src), Path(a.out)
    cache = Path(a.cache) if a.cache else out / ".cache"
    out.mkdir(parents=True, exist_ok=True)
    pdfs = sorted(src.glob("*.pdf"))
    if not pdfs:
        sys.exit(f"Нет PDF в {src}")

    jobs = []
    for pdf in pdfs:
        d = cache / pdf.stem
        d.mkdir(parents=True, exist_ok=True)
        if not list(d.glob("p-*.png")):
            print(f"render {pdf.name}", flush=True)
            subprocess.run(["pdftoppm", "-r", str(a.dpi), "-png", str(pdf), str(d / "p")], check=True)
        jobs += [(pdf, png) for png in sorted(d.glob("p-*.png"))]

    print(f"OCR {len(jobs)} страниц, workers={a.workers}", flush=True)
    with ThreadPoolExecutor(a.workers) as ex:
        texts = list(ex.map(lambda j: ocr_page(j[1], a.lang), jobs))

    by_doc = {}
    for (pdf, png), t in zip(jobs, texts):
        page = int(re.search(r"p-0*(\d+)", png.stem).group(1))
        by_doc.setdefault(pdf, []).append((page, clean(t)))

    with open(out / "corpus.jsonl", "w", encoding="utf-8") as jf:
        for pdf, pages in by_doc.items():
            pages.sort()
            doc_id = slug(pdf.stem)
            md = [f"# {pdf.stem}\n", f"<!-- source: {pdf.name}; OCR tesseract {a.lang}, {a.dpi} dpi -->\n"]
            for page, t in pages:
                md.append(f"\n<!-- page {page} -->\n\n{t}\n")
                jf.write(json.dumps({"doc_id": doc_id, "file": pdf.name, "page": page,
                                     "text": t, "chars": len(t)}, ensure_ascii=False) + "\n")
            (out / f"{doc_id}.md").write_text("".join(md), encoding="utf-8")
            print(f"  {doc_id}.md: {len(pages)} стр., {sum(len(t) for _, t in pages)} симв.")
    print("OK")


if __name__ == "__main__":
    main()
