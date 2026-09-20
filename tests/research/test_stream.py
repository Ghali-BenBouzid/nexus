"""The live feed as a stream: what crosses the bus, and what the endpoint sends.

The tests run with ``JOB_QUEUE=inline``, so the bus is its in-process
implementation. That is the same code path the endpoint and the sink use in
production; only the transport under ``publish`` differs.
"""

import asyncio
import json

from httpx import AsyncClient

from app.agents.schemas import AgentEvent
from app.db import session as db_session
from app.models.query import Query
from app.research import bus, router
from app.research import repository as research_repository
from app.research.service import EventSink
from tests.accounts import login_as


async def test_a_token_is_published_but_never_stored(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Tokens and thoughts are fragments of text that is persisted whole when the
    turn ends. Storing them would be hundreds of rows saying what one row says."""
    query_id = await _query(client, auth_headers)
    sink = EventSink(query_id)
    seen: list[AgentEvent] = []

    async with bus.subscribe(query_id) as live:
        watching = asyncio.create_task(_collect(live, seen, count=3))
        await asyncio.sleep(0)
        await sink(AgentEvent(type="thinking", message="Supervisor is thinking"))
        await sink(AgentEvent(type="thought", message="let me see"))
        await sink(AgentEvent(type="token", message="Hello"))
        await asyncio.wait_for(watching, timeout=5)

    assert [event.type for event in seen] == ["thinking", "thought", "token"]
    assert await _stored(query_id) == ["thinking"]


async def test_the_feed_replays_what_was_missed_then_follows_along(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """A browser that arrives late must still see the run's stages, so the feed
    drains the durable events before joining the bus.

    Driven directly rather than over HTTP: a test client cannot produce events
    while it is holding a response open, and producing them live is the one
    behaviour worth proving here."""
    query_id = await _query(client, auth_headers)
    await EventSink(query_id)(AgentEvent(type="thinking", message="already happened"))

    frames = await _drive(query_id, produce=_token_then_done)

    assert [frame["type"] for frame in frames] == ["thinking", "token", "done"]
    assert frames[0]["message"] == "already happened"
    assert frames[1]["message"] == "Hi"
    # The replayed event carries the durable cursor; a live one has none to carry.
    assert frames[0]["id"] > 0
    assert "id" not in frames[1]


async def test_the_feed_resumes_from_where_a_client_left_off(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """A reconnecting browser passes the last cursor it saw, and must not be
    sent the stages it has already drawn."""
    query_id = await _query(client, auth_headers)
    sink = EventSink(query_id)
    await sink(AgentEvent(type="thinking", message="first"))
    await sink(AgentEvent(type="tool_call", message="second"))
    already = (await _events(query_id))[0].id

    frames = await _drive(query_id, produce=_done, after=already)

    assert [frame["message"] for frame in frames] == ["second", ""]


async def test_a_finished_run_is_not_waited_on(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Nothing will ever be published for a run that already ended, so the
    stream must close rather than hold the connection open."""
    query_id = await _query(client, auth_headers)
    await EventSink(query_id)(AgentEvent(type="thinking", message="worked"))
    async with db_session.SessionLocal() as db:
        await research_repository.complete_answer(db, query_id, "done")

    async with client.stream(
        "GET", f"/research/query/{query_id}/stream", headers=auth_headers
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        frames = [
            json.loads(line[len("data: ") :])
            async for line in response.aiter_lines()
            if line.startswith("data: ")
        ]

    assert [frame["type"] for frame in frames] == ["thinking", "done"]


async def test_another_users_run_is_not_streamable(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    query_id = await _query(client, auth_headers)
    stranger = await login_as(client, "Someone else")

    response = await client.get(f"/research/query/{query_id}/stream", headers=stranger)

    assert response.status_code == 404


# --- helpers ----------------------------------------------------------------


async def _query(client: AsyncClient, auth_headers: dict[str, str]) -> int:
    me = await client.get("/auth/me", headers=auth_headers)
    async with db_session.SessionLocal() as db:
        query = await research_repository.create_pending_query(
            db=db, user_id=me.json()["id"], prompt="a question"
        )
        await research_repository.mark_running(db, query.id)
        return query.id


async def _events(query_id: int):
    async with db_session.SessionLocal() as db:
        return await research_repository.list_events(
            db=db, query_id=query_id, after_id=0
        )


async def _stored(query_id: int) -> list[str]:
    return [event.type for event in await _events(query_id)]


async def _drive(query_id: int, *, produce, after: int = 0) -> list[dict]:
    """Read the feed to its end while ``produce`` publishes into it."""
    frames: list[dict] = []
    async with db_session.SessionLocal() as db:
        query = await db.get(Query, query_id)
        assert query is not None
        producing = asyncio.create_task(produce(query_id))
        async for frame in router.feed(db, query, after=after):
            if frame.startswith("data: "):
                frames.append(json.loads(frame[len("data: ") :]))
        await producing
    return frames


async def _collect(live, into: list[AgentEvent], *, count: int) -> None:
    async for event in live:
        if event is None:
            continue  # a keep-alive tick, not an event
        into.append(event)
        if len(into) == count:
            return


async def _token_then_done(query_id: int) -> None:
    # The subscription only exists once the feed has drained the stored events,
    # so let it get that far before anything is published.
    await asyncio.sleep(0.05)
    await EventSink(query_id)(AgentEvent(type="token", message="Hi"))
    await bus.publish(query_id, AgentEvent(type=bus.DONE, message=""))


async def _done(query_id: int) -> None:
    await asyncio.sleep(0.05)
    await bus.publish(query_id, AgentEvent(type=bus.DONE, message=""))
