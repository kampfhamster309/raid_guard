from fastapi import FastAPI

app = FastAPI(title="raid_guard backend")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "backend"}
