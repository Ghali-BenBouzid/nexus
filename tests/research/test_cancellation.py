import asyncio

from httpx import AsyncClient

import app.research.service as research_service
from app.db import session as db_session
from app.models.query import Query, QueryStatus
from app.research import repository as research_repository
from tests.research.test_research import FakeBackend, RoleProvider, _use_fake_pipeline


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
        await research_repository.fail_query(db, query_id, "Research was stopped.")


async def _read(query_id: int) -> Query:
    async with db_session.SessionLocal() as db:
        query = await db.get(Query, query_id)
        assert query is not None
        return query


class _StopWhile(RoleProvider):
    """Like RoleProvider, but the user stops the run while the agent whose system
    prompt mentions ``agent`` is calling the model."""

    def __init__(self, sub_questions: list[str], query_id: int, agent: str) -> None:
        super().__init__(sub_questions)
        self.query_id = query_id
        self.agent = agent

    async def generate(self, messages, tools=None, tool_choice="auto"):
        if self.agent in (messages[0].content or ""):
            await _stop(self.query_id)
        return await super().generate(messages, tools, tool_choice)


async def test_a_stop_during_planning_wins_over_the_plan(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    # The proposed plan must not re-surface for confirmation after a stop.
    qid, user_id = await _make_pending_query(client, auth_headers)

    await research_service.run_plan_job(
        qid,
        "a question",
        user_id=user_id,
        provider=_StopWhile(["q1"], qid, "research planner"),
    )

    query = await _read(qid)
    assert query.status == QueryStatus.failed
    assert query.error == "Research was stopped."
    assert query.plan is None


async def test_a_stop_during_the_write_keeps_the_run_stopped(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    # A stop landing in the uncancellable write tail must still keep the finished
    # report from being saved as a completed run.
    qid, user_id = await _make_pending_query(client, auth_headers)

    await research_service.run_research_from_plan_job(
        qid,
        ["q1"],
        user_id=user_id,
        provider=_StopWhile(["q1"], qid, "research writer"),
        backend=FakeBackend(),
    )

    query = await _read(qid)
    assert query.status == QueryStatus.failed
    assert query.report is None


async def test_a_job_stopped_while_queued_does_nothing(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    qid, user_id = await _make_pending_query(client, auth_headers)
    await _stop(qid)

    await research_service.run_plan_job(
        qid, "a question", user_id=user_id, provider=RoleProvider(["q1"])
    )

    query = await _read(qid)
    assert query.status == QueryStatus.failed
    assert query.plan is None


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
        await asyncio.sleep(0.05)
        assert live.stopped


async def test_cancel_resolves_an_awaiting_plan_query(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    # Stopping a turn paused for plan confirmation must reconcile the backend, not
    # leave it awaiting_plan (which a reload would rehydrate as still live).
    _use_fake_pipeline(sub_questions=["q1"])
    created = await client.post(
        "/conversations", headers=auth_headers, json={"prompt": "topic"}
    )
    query_id = created.json()["messages"][1]["query_id"]
    detail = await client.get(f"/research/query/{query_id}", headers=auth_headers)
    assert detail.json()["status"] == "awaiting_plan"

    cancel = await client.post(
        f"/research/query/{query_id}/cancel", headers=auth_headers
    )
    assert cancel.status_code == 204

    after = await client.get(f"/research/query/{query_id}", headers=auth_headers)
    assert after.json()["status"] == "failed"
    # confirm is now rejected (no plan awaiting)
    confirm = await client.post(
        f"/research/query/{query_id}/confirm", headers=auth_headers
    )
    assert confirm.status_code == 409
