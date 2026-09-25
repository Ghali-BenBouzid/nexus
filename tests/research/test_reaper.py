from datetime import UTC, datetime, timedelta

from httpx import AsyncClient

from app.db import session as db_session
from app.models.query import Query, QueryKind, QueryStatus
from app.research import repository


async def test_only_running_queries_with_a_stale_heartbeat_are_reaped(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    # A worker that died leaves its query running with a heartbeat that stopped.
    # A live job keeps beating, and a queued one has not started yet: both stay.
    me = await client.get("/auth/me", headers=auth_headers)
    now = datetime.now(UTC)
    async with db_session.SessionLocal() as db:
        rows = {
            "dead": Query(
                user_id=me.json()["id"],
                prompt="p",
                status=QueryStatus.running,
                heartbeat_at=now - timedelta(seconds=300),
            ),
            "alive": Query(
                user_id=me.json()["id"],
                prompt="p",
                status=QueryStatus.running,
                heartbeat_at=now - timedelta(seconds=5),
            ),
            "queued": Query(
                user_id=me.json()["id"], prompt="p", status=QueryStatus.pending
            ),
        }
        db.add_all(rows.values())
        await db.commit()
        ids = {name: query.id for name, query in rows.items()}

        reaped = await repository.reap_stalled_queries(db, stale_after_seconds=90)

    assert reaped == 1
    async with db_session.SessionLocal() as db:
        dead = await db.get(Query, ids["dead"])
        assert dead.status == QueryStatus.failed
        assert dead.error == repository.STOPPED_RESPONDING
        assert (await db.get(Query, ids["alive"])).status == QueryStatus.running
        assert (await db.get(Query, ids["queued"])).status == QueryStatus.pending


async def test_a_stalled_deep_run_is_handed_back_instead_of_failed(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    # Deep research is the one run that is checkpointed, so a worker that died
    # mid-run leaves work worth resuming. Failing it would throw away minutes of
    # research already paid for.
    me = await client.get("/auth/me", headers=auth_headers)
    stale = datetime.now(UTC) - timedelta(seconds=300)
    async with db_session.SessionLocal() as db:
        rows = {
            "deep": Query(
                user_id=me.json()["id"],
                prompt="p",
                kind=QueryKind.deep_research,
                status=QueryStatus.running,
                heartbeat_at=stale,
            ),
            "chat": Query(
                user_id=me.json()["id"],
                prompt="p",
                kind=QueryKind.chat,
                status=QueryStatus.running,
                heartbeat_at=stale,
            ),
        }
        db.add_all(rows.values())
        await db.commit()
        ids = {name: query.id for name, query in rows.items()}

        resumable = await repository.stalled_deep_runs(db, stale_after_seconds=90)
        reaped = await repository.reap_stalled_queries(db, stale_after_seconds=90)

    assert resumable == [ids["deep"]]
    assert reaped == 1  # the chat turn, and only it

    async with db_session.SessionLocal() as db:
        deep = await db.get(Query, ids["deep"])
        chat = await db.get(Query, ids["chat"])
    assert deep.status == QueryStatus.running  # still ours to resume
    assert chat.status == QueryStatus.failed


async def test_a_deep_run_resumes_from_its_checkpoint(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch
) -> None:
    # The claim a deploy mid-run rests on: the researchers that already came back
    # are not run again.
    from app.research import deep as research_deep
    from app.research import service as research_service
    from tests.conversations.test_background_runs import _StartsDeepResearch
    from tests.research.test_research import FakeBackend

    me = await client.get("/auth/me", headers=auth_headers)
    async with db_session.SessionLocal() as db:
        query = await repository.create_pending_query(
            db=db,
            user_id=me.json()["id"],
            prompt="everything about X",
            title="All of X",
            kind=QueryKind.deep_research,
        )
        query_id = query.id

    crashing = _StartsDeepResearch()
    original = crashing._generate
    calls: list[int] = []

    def counted(messages, stop=None, run_manager=None, **kwargs):
        calls.append(1)
        if len(calls) > 3:  # the lead, then two researchers, then die
            raise RuntimeError("the worker went away")
        return original(messages, stop, run_manager, **kwargs)

    monkeypatch.setattr(crashing, "_generate", counted)
    monkeypatch.setattr(
        research_service, "models_for", lambda *_: (crashing, crashing, crashing)
    )
    monkeypatch.setattr(research_service, "get_search_backend", FakeBackend)

    await research_deep.run_deep_research_job(query_id)
    async with db_session.SessionLocal() as db:
        assert (await db.get(Query, query_id)).status == QueryStatus.failed

    # A worker picks it back up. The first round and both its researchers are
    # checkpointed, so only the lead's verdict and the write are left: two more
    # calls, not five.
    resumed = _StartsDeepResearch()
    after: list[int] = []
    resumed_generate = resumed._generate

    def counted_again(messages, stop=None, run_manager=None, **kwargs):
        after.append(1)
        return resumed_generate(messages, stop, run_manager, **kwargs)

    monkeypatch.setattr(resumed, "_generate", counted_again)
    monkeypatch.setattr(
        research_service, "models_for", lambda *_: (resumed, resumed, resumed)
    )
    async with db_session.SessionLocal() as db:
        await repository.set_status(db, query_id, QueryStatus.pending)
    await research_deep.run_deep_research_job(query_id)

    async with db_session.SessionLocal() as db:
        done = await db.get(Query, query_id)
    assert done.status == QueryStatus.complete
    assert done.report == "THE DEEP REPORT"
    assert len(after) == 2  # the lead and the write, nothing that already ran
