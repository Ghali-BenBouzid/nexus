"""The live feed's pipe from the worker to the browser.

The model call happens in the worker; the browser holds a connection to the API.
They are different processes, so an agent event has to cross one before it can
be shown. It already crosses through Postgres, which is what makes the feed
survive a reload, but a row per token is the wrong shape for a token: hundreds
of inserts to carry text that is already being persisted whole at the end.

So events take both paths. Durable ones are written to ``query_events`` as
before and also published here; tokens are published only. The API subscribes to
the query's channel and forwards each event down an SSE response.

Redis is the pipe, because arq already runs on it and the client is already a
dependency. With ``JOB_QUEUE=inline`` there is no worker to cross from and no
Redis to cross through, so an in-process fan-out stands in, the same way
``app.jobs`` runs a job in the API process in that mode.
"""

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import redis.asyncio as redis

from app.agents.schemas import AgentEvent
from app.core.config import settings

logger = logging.getLogger(__name__)

# One channel per query: a subscriber wants one run's feed, never all of them.
_CHANNEL = "nexus:events:{}"
# Sent when a run reaches a terminal state, so a subscriber stops waiting rather
# than holding the connection open until it times out.
DONE = "done"
# How long a subscriber waits for a frame before yielding to its caller so the
# endpoint can send a keep-alive. Proxies close a stream that goes quiet.
IDLE_SECONDS = 15.0

_client: redis.Redis | None = None
# Inline mode only: the subscribers of each query, fed directly.
_local: dict[int, set[asyncio.Queue]] = {}


def _inline() -> bool:
    return settings.job_queue != "redis"


async def open_bus() -> None:
    """Connect once, at startup. Both processes call it: the worker publishes,
    the API subscribes."""
    global _client
    if _inline():
        return
    _client = redis.from_url(settings.redis_url)


async def close_bus() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def publish(query_id: int, event: AgentEvent) -> None:
    """Send one event to whoever is watching this query.

    Nobody may be watching, which is normal and not an error: the run carries on
    whether or not a browser is attached. A failure here is logged and swallowed
    for the same reason the durable feed's is, since losing a frame of progress
    must never lose the run.
    """
    if _inline():
        for queue in list(_local.get(query_id, ())):
            queue.put_nowait(event)
        return
    if _client is None:
        return
    try:
        await _client.publish(_CHANNEL.format(query_id), event.model_dump_json())
    except Exception:
        logger.warning("could not publish an event for query %s", query_id)


@contextlib.asynccontextmanager
async def subscribe(query_id: int) -> AsyncIterator[AsyncIterator[AgentEvent | None]]:
    """Watch one query's feed for as long as the caller stays in the block.

    Yields an iterator of events that also yields ``None`` whenever it has been
    idle for ``IDLE_SECONDS``, which is the caller's cue to send a keep-alive.
    The subscription is always released on the way out, including when the
    browser vanishes mid-stream and the generator is closed from under us.
    """
    if _inline():
        queue: asyncio.Queue = asyncio.Queue()
        _local.setdefault(query_id, set()).add(queue)
        try:
            yield _drain(queue)
        finally:
            watchers = _local.get(query_id, set())
            watchers.discard(queue)
            if not watchers:
                _local.pop(query_id, None)
        return

    if _client is None:
        raise RuntimeError("The event bus is not open (open_bus at startup).")
    pubsub = _client.pubsub()
    await pubsub.subscribe(_CHANNEL.format(query_id))
    try:
        yield _listen(pubsub)
    finally:
        with contextlib.suppress(Exception):
            await pubsub.aclose()


async def _drain(queue: asyncio.Queue) -> AsyncIterator[AgentEvent | None]:
    while True:
        try:
            yield await asyncio.wait_for(queue.get(), timeout=IDLE_SECONDS)
        except TimeoutError:
            yield None


async def _listen(pubsub: Any) -> AsyncIterator[AgentEvent | None]:
    while True:
        message = await pubsub.get_message(
            ignore_subscribe_messages=True, timeout=IDLE_SECONDS
        )
        if message is None:
            yield None
            continue
        event = _decode(message.get("data"))
        if event is not None:
            yield event


def _decode(data: Any) -> AgentEvent | None:
    """One published frame back into an event. A frame we cannot read is dropped
    rather than killing the stream that carries every other one."""
    try:
        return AgentEvent(**json.loads(data))
    except Exception:
        logger.warning("dropped an unreadable event frame")
        return None
