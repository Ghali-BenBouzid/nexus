from fastapi import FastAPI

from app.auth.router import router as auth_router
from app.research.router import router as research_router

app = FastAPI()
app.include_router(auth_router)
app.include_router(research_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
