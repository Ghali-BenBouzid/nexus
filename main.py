import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import jobs
from app.auth.router import router as auth_router
from app.conversations.router import router as conversations_router
from app.core.config import settings
from app.db import session as db_session
from app.observability import configure_tracing
from app.research import repository
from app.research import service as research_service
from app.research.router import router as research_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Turn on LangSmith tracing if it is configured (no-op otherwise). Done before
    # serving so every request's agent run is captured.
    configure_tracing()
    if settings.job_queue == "inline":
        # Inline jobs run in this process, so a query still running from before a
        # restart is orphaned: fail it (best-effort: a DB blip at boot must not
        # stop the app). With a worker, a restart here touches no job; the worker
        # reaps its own dead runs by their heartbeat.
        try:
            async with db_session.SessionLocal() as db:
                reaped = await repository.reap_interrupted_queries(db)
            if reaped:
                logger.warning("failed %d query(ies) interrupted by a restart", reaped)
        except Exception:
            logger.exception("startup reaping of interrupted queries failed")
        # Only a process that runs jobs needs the graph and its checkpointer.
        await research_service.open_graph()
    await jobs.open_queue()
    yield
    await jobs.close_queue()
    await research_service.close_graph()


app = FastAPI(lifespan=lifespan)

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
