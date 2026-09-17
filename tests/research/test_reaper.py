from datetime import UTC, datetime, timedelta

from httpx import AsyncClient

from app.db import session as db_session
from app.models.query import Query, QueryStatus
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
