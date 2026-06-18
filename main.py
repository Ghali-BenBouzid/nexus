import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.auth.router import router as auth_router
from app.conversations.router import router as conversations_router
from app.core.config import settings
from app.core.limiter import limiter
from app.db import session as db_session
from app.observability import configure_tracing
from app.research import repository
from app.research.router import router as research_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Turn on LangSmith tracing if it is configured (no-op otherwise). Done before
    # serving so every request's agent run is captured.
    configure_tracing()
    # Clean up jobs orphaned by a previous restart (best-effort: a DB blip at boot
    # must not stop the app from starting).
    try:
        async with db_session.SessionLocal() as db:
            reaped = await repository.reap_interrupted_queries(db)
        if reaped:
            logger.warning("failed %d query(ies) interrupted by a restart", reaped)
    except Exception:
        logger.exception("startup reaping of interrupted queries failed")
    yield


app = FastAPI(lifespan=lifespan)

# slowapi reads the limiter off app.state and turns a tripped limit into a 429.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

if settings.cors_origin_list:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(auth_router)
app.include_router(research_router)
app.include_router(conversations_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
