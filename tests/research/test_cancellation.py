import asyncio

from httpx import AsyncClient

import app.research.service as research_service
from app.db import session as db_session
from app.models.query import Query, QueryStatus
from app.research import repository as research_repository
from tests.research.test_research import FakeBackend, RoleModel


async def _make_pending_query(
    client: AsyncClient, auth_headers: dict[str, str]
) -> tuple[int, int]:
    me = await client.get("/auth/me", headers=auth_headers)
    user_id = me.json()["id"]
    async with db_session.SessionLocal() as db:
        query = await research_repository.create_pending_query(
            db=db, user_id=user_id, prompt="a question"
        )
        return query.id, user_id


async def _stop(query_id: int) -> None:
    """What the stop endpoint does. It may run in the API while the job runs on a
    worker, so the stop is only a status change the job has to notice."""
    async with db_session.SessionLocal() as db:
        await research_repository.fail_query(db, query_id, research_repository.STOPPED)


async def _read(query_id: int) -> Query:
    async with db_session.SessionLocal() as db:
        query = await db.get(Query, query_id)
        assert query is not None
        return query


async def _eventually(check, timeout: float = 5.0) -> bool:
    """Wait until ``check()`` holds. A heartbeat runs on the clock, and a busy
    machine can take longer than any fixed sleep, so poll against a deadline."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not check():
        if loop.time() > deadline:
            return False
        await asyncio.sleep(0.01)
    return True


class _StopWhile(RoleModel):
    """Like RoleModel, but the user stops the run while the agent whose system
    prompt mentions ``agent`` is calling the model."""

    query_id: int = 0
    agent: str = ""

    def __init__(self, sub_questions, query_id: int, agent: str, **kwargs) -> None:
        super().__init__(sub_questions, **kwargs)
        self.query_id = query_id
        self.agent = agent

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        if self.agent in str(messages[0].content or ""):
            await _stop(self.query_id)
        return self._generate(messages, stop, run_manager, **kwargs)


async def test_a_stop_during_planning_wins_over_the_run(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    # The job may not notice the stop until its next heartbeat, so what has to
    # hold is that the run cannot complete over it: a stopped query stays stopped
    # however far the agents got before they saw it.
    qid, user_id = await _make_pending_query(client, auth_headers)

    await research_service.run_research_job(
        qid,
        "a question",
        user_id=user_id,
        model=_StopWhile(["q1"], qid, "research planner"),
        backend=FakeBackend(),
    )

    query = await _read(qid)
    assert query.status == QueryStatus.failed
    assert query.error == "Research was stopped."
    assert query.report is None


async def test_a_stop_during_the_write_keeps_the_run_stopped(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    # A stop landing in the uncancellable write tail must still keep the finished
    # report from being saved as a completed run.
    qid, user_id = await _make_pending_query(client, auth_headers)

    await research_service.run_research_job(
        qid,
        "a question",
        user_id=user_id,
        model=_StopWhile(["q1"], qid, "writing the report"),
        backend=FakeBackend(),
    )

    query = await _read(qid)
    assert query.status == QueryStatus.failed
    assert query.report is None


class _SlowWriter(_StopWhile):
    """The user stops the run while the writer's model call is still going, as
    with a reasoning model that thinks for minutes."""

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        if self.agent in str(messages[0].content or ""):
            await _stop(self.query_id)
            await asyncio.sleep(60)
        return self._generate(messages, stop, run_manager, **kwargs)


async def test_a_stop_cancels_the_model_call_in_flight(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch
) -> None:
    # The stop must end the writer's call, not let it finish a report (billed)
    # that the stopped run then throws away.
    monkeypatch.setattr(research_service, "HEARTBEAT_SECONDS", 0.01)
    qid, user_id = await _make_pending_query(client, auth_headers)

    await asyncio.wait_for(
        research_service.run_research_job(
            qid,
            "a question",
            user_id=user_id,
            model=_SlowWriter(["q1"], qid, "writing the report"),
            backend=FakeBackend(),
        ),
        timeout=5,
    )

    async with db_session.SessionLocal() as db:
        events = await research_repository.list_events(db, qid, after_id=0)
    assert "writer_start" in [e.type for e in events]
    assert "writer_done" not in [e.type for e in events]
    query = await _read(qid)
    assert query.status == QueryStatus.failed
    assert query.error == "Research was stopped."


async def test_a_job_stopped_while_queued_does_nothing(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    qid, user_id = await _make_pending_query(client, auth_headers)
    await _stop(qid)

    await research_service.run_research_job(
        qid,
        "a question",
        user_id=user_id,
        model=RoleModel(["q1"]),
        backend=FakeBackend(),
    )

    query = await _read(qid)
    assert query.status == QueryStatus.failed
    assert query.report is None
    async with db_session.SessionLocal() as db:
        events = await research_repository.list_events(db, qid, after_id=0)
    assert events == []  # nothing ran at all


async def test_a_running_job_sees_a_stop_on_its_next_heartbeat(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch
) -> None:
    monkeypatch.setattr(research_service, "HEARTBEAT_SECONDS", 0.01)
    qid, _ = await _make_pending_query(client, auth_headers)
    async with db_session.SessionLocal() as db:
        assert await research_repository.mark_running(db, qid)

    async with research_service.job_liveness(qid) as live:
        await asyncio.sleep(0.05)
        assert not live.stopped
        await _stop(qid)
        assert await _eventually(lambda: live.stopped)
