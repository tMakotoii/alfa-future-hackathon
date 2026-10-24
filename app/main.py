from fastapi import FastAPI

app = FastAPI(title="Альфа Инсайт")


@app.get("/api/health")
def health():
    return {"ok": True}
