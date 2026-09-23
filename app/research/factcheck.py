"""The fact-check job: one document, checked against the web, as a report.

It runs like a deep run does, in the background with its report landing in
Outputs, but it is not checkpointed: a fact check is one agent loop rather than
a fan-out, so there is no half-finished work worth resuming, and restarting one
would only re-bill the searching it had already paid for.
"""

import logging

from langchain_core.language_models import BaseChatModel

from app.agents.factcheck import fact_check
from app.agents.schemas import ResearchResult
from app.agents.tools import SearchBackend
from app.core.config import settings
from app.db import session as db_session
from app.models.document import Document
from app.models.query import Query
from app.research import repository
from app.research.service import Run, RunFailedError, run_query

logger = logging.getLogger(__name__)

GONE = "The document was removed before the fact check could read it."


async def run_fact_check_job(
    query_id: int,
    document_id: int,
    focus: str = "",
    *,
    model: BaseChatModel | None = None,
    backend: SearchBackend | None = None,
) -> None:
    """Check one document and save the report the check wrote."""
    async with db_session.SessionLocal() as db:
        query = await db.get(Query, query_id)
        if query is None:
            return
        user_id = query.user_id
        document = await db.get(Document, document_id)
        checking = (
            (document.filename, document.text)
            if document is not None and document.user_id == user_id
            else None
        )

    async def work(run: Run) -> None:
        if checking is None:
            raise RunFailedError(GONE)
        filename, text = checking
        report = await fact_check(
            text,
            filename=filename,
            model=run.model,
            backend=run.backend,
            sources=run.sources,
            middleware=run.middleware("fact_checker", run.emit),
            emit=run.emit,
            focus=focus,
            max_iters=settings.factcheck_max_iters,
            most_iters=settings.factcheck_most_iters,
        )
        result = ResearchResult(
            points=[],
            sources=report.sources,
            gaps=[],
            consulted_sources=list(run.sources.all),
        )
        async with db_session.SessionLocal() as db:
            await repository.complete_query(db, query_id, report, result)

    await run_query(
        query_id,
        user_id=user_id,
        work=work,
        model=model,
        backend=backend,
        timeout=settings.factcheck_timeout,
    )
