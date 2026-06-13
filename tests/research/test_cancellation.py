from httpx import AsyncClient

import app.research.service as research_service
from app.db import session as db_session
from app.models.query import Query, QueryStatus
from app.research import repository as research_repository
from tests.research.test_research import FakeBackend, RoleProvider, _use_fake_pipeline


async def _make_pending_query(client: AsyncClient, auth_headers: dict[str, str]) -> int:
    me = await client.get("/auth/me", headers=auth_headers)
    user_id = me.json()["id"]
    async with db_session.SessionLocal() as db:
        query = await research_repository.create_pending_query(
            db=db, user_id=user_id, prompt="a question"
        )
        return query.id


async def test_run_plan_job_clears_a_pending_cancel(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    # A stop that arrives while planning is in flight must win over the proposed
    # plan, and must not leave a stale cancel id behind (which would silently abort
    # the next confirmed run for this query).
    qid = await _make_pending_query(client, auth_headers)
    research_service._cancel_requested.add(qid)

    await research_service.run_plan_job(
        qid, "a question", provider=RoleProvider(["q1"])
    )

    async with db_session.SessionLocal() as db:
        query = await db.get(Query, qid)
        assert query is not None
        # failed, not awaiting_plan: the paused plan never re-surfaces
        assert query.status == QueryStatus.failed
        assert query.plan is None
    assert qid not in research_service._cancel_requested


class _CancelDuringWriteProvider(RoleProvider):
    """Like RoleProvider, but a stop lands during the final write step, i.e. after
    the orchestrator's last cancel checkpoint (the uncancellable consolidate/write
    tail)."""

    def __init__(self, sub_questions: list[str], query_id: int) -> None:
        super().__init__(sub_questions)
        self.query_id = query_id

    async def generate(self, messages, tools=None, tool_choice="auto"):
        response = await super().generate(messages, tools, tool_choice)
        if "research writer" in (messages[0].content or ""):
            research_service._cancel_requested.add(self.query_id)
        return response


async def test_research_job_does_not_complete_a_late_cancel(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    # A stop landing during the write tail must still stop the finished report from
    # being saved as a completed run.
    qid = await _make_pending_query(client, auth_headers)

    await research_service.run_research_from_plan_job(
        qid,
        ["q1"],
        provider=_CancelDuringWriteProvider(["q1"], qid),
        backend=FakeBackend(),
    )

    async with db_session.SessionLocal() as db:
        query = await db.get(Query, qid)
        assert query is not None
        assert query.status == QueryStatus.failed
        assert query.report is None
    assert qid not in research_service._cancel_requested


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
