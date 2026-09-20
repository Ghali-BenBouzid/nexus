"""The deep research job, and the checkpointer the deep graph runs over.

Deep research is the one run long enough that a deploy will land in the middle
of one, so it is the one run that is checkpointed. Every node completes into
Postgres; a worker that picks the run back up resumes from the last step that
finished, which is what keeps a redeploy from re-planning and re-paying for
researchers that already came back.

The user is not made to wait for it: the supervisor starts the run and says so,
the run goes on in the background, and its report turns up in Outputs.
"""

import logging

from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph.state import CompiledStateGraph
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from sqlalchemy.engine import make_url

from app.agents import deep
from app.agents.report import as_stored
from app.agents.research import Limits
from app.agents.tools import SearchBackend
from app.core.config import settings
from app.db import session as db_session
from app.models.query import Query
from app.research import repository
from app.research.service import Run, run_query

logger = logging.getLogger(__name__)

_graph: CompiledStateGraph | None = None
_pool: AsyncConnectionPool | None = None


def _conninfo() -> str:
    """The app's database URL, as psycopg (the checkpointer's driver) takes it."""
    url = make_url(settings.database_url).set(drivername="postgresql")
    if settings.database_ssl:
        url = url.update_query_dict({"sslmode": "require"})
    return url.render_as_string(hide_password=False)


async def open_graph(*, in_memory: bool = False) -> None:
    """Compile the deep graph over its checkpointer, once per process that runs
    jobs: the worker, or the API with JOB_QUEUE=inline. ``in_memory`` is for the
    tests, whose SQLite database the Postgres checkpointer cannot use."""
    global _graph, _pool
    if in_memory:
        _graph = deep.compile_graph(InMemorySaver(serde=deep.SERDE))
        return
    _pool = AsyncConnectionPool(
        _conninfo(),
        open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    )
    await _pool.open()
    checkpointer = AsyncPostgresSaver(_pool, serde=deep.SERDE)
    # Creates and migrates its own tables, outside Alembic. Idempotent.
    # ponytail: two workers booting at once can race here; the loser restarts.
    await checkpointer.setup()
    _graph = deep.compile_graph(checkpointer)


async def close_graph() -> None:
    global _graph, _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
    _graph = None


def get_graph() -> CompiledStateGraph:
    if _graph is None:
        raise RuntimeError("The deep research graph is not open (open_graph).")
    return _graph


async def run_deep_research_job(
    query_id: int,
    *,
    model: BaseChatModel | None = None,
    backend: SearchBackend | None = None,
) -> None:
    """Run (or resume) the deep research behind one query, and save its report.

    Takes only the id: a resume comes from the reaper, minutes after the
    conversation that asked for it, so everything the run needs is read off the
    row rather than carried through the queue.
    """
    async with db_session.SessionLocal() as db:
        query = await db.get(Query, query_id)
        if query is None:
            return
        user_id, question, title = query.user_id, query.prompt, query.title

    graph = get_graph()
    config = deep.run_config(query_id)

    async def work(run: Run) -> None:
        state = await graph.aget_state(config)
        if state.next:
            # A checkpoint with somewhere left to go: resume it rather than
            # paying for the steps that already finished.
            logger.info(
                "resuming deep research for query %s at %s", query_id, state.next
            )
        graph_input = None if state.next else {"question": question}
        final = await graph.ainvoke(
            graph_input,
            config,
            context=deep.Deps(
                model=run.model,
                backend=run.backend,
                emit=run.emit,
                middleware=run.middleware,
                limits=Limits.deep(),
            ),
            # Every node lands in the checkpointer, which is the whole point:
            # "exit" would checkpoint only at the end, and a run that crashed
            # would have nothing to come back to.
            durability="async",
        )
        report, result = final["report"], final["result"]
        async with db_session.SessionLocal() as db:
            await repository.complete_query(
                db, query_id, report, as_stored(result, report)
            )
        await _forget(query_id)

    logger.info("deep research starting for query %s (%s)", query_id, title)
    await run_query(
        query_id,
        user_id=user_id,
        work=work,
        model=model,
        backend=backend,
        timeout=settings.deep_timeout,
    )


async def _forget(query_id: int) -> None:
    """Drop a finished run's checkpoint: there is nothing left to resume."""
    try:
        await get_graph().checkpointer.adelete_thread(f"deep-{query_id}")
    except Exception:
        logger.exception("could not delete the checkpoint of query %s", query_id)
