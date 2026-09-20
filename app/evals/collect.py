"""Run goldens through the real turn, and record everything it did.

A turn is now one agent with tools, so the harness drives exactly what
production drives: ``supervisor.respond`` with a recording search backend and a
usage callback on the model. What used to be read off a fixed pipeline is read
off the turn instead: which tools it reached for, what the researchers behind a
``research`` call searched and found, and the answer the user would see.

The two seams that make the inside of a tool visible are the stage context
variable (which tags every search with the researcher that made it) and
``on_research`` (which hands over each research run's full result). Neither
changes what the turn does, so a recorded run is the real one.
"""

import asyncio
import logging
import time
from datetime import UTC, datetime
from typing import Literal

from langchain_core.language_models import BaseChatModel

from app.agents.model import Progress
from app.agents.schemas import AgentEvent, ResearchResult
from app.agents.search_cache import CachingSearchBackend
from app.agents.sources import Sources
from app.agents.supervisor import respond
from app.agents.tools import SearchBackend
from app.core.config import settings
from app.evals.goldens import Golden
from app.evals.recording import RecordingSearchBackend, StageUsage
from app.evals.trace import ClaimRecord, ResearcherTrace, RunTrace, SourceRecord

logger = logging.getLogger(__name__)

# Agent events worth keeping on a researcher's trace: they explain a failure.
_NOTABLE_EVENTS = {"researcher_forced", "submit_invalid", "tool_error"}


async def collect_one(
    golden: Golden,
    *,
    model: BaseChatModel,
    backend: SearchBackend,
    until: Literal["plan"] | None = None,
) -> RunTrace:
    """Run one golden as a first message in a fresh conversation.

    Never raises: a failure is recorded on the trace. ``backend`` must already be
    open; each golden gets its own search cache, as each production job does.
    ``until="plan"`` stops the run once a plan exists, which exercises the
    supervisor's judgement and the planner without paying for any searching.
    """
    usage = StageUsage()
    model.callbacks = [usage]  # every call counted, agent or not
    trace = RunTrace(
        golden_id=golden.id,
        input=golden.input,
        run_date=datetime.now(UTC).date().isoformat(),
        model=getattr(model, "model_name", "unknown"),
        until=until,
    )
    recorder = RecordingSearchBackend(CachingSearchBackend(backend))
    started = time.monotonic()
    try:
        await _run(golden, trace, model, recorder, until)
    except asyncio.CancelledError:
        pass  # until="plan": cut once a plan existed
    except Exception as exc:  # noqa: BLE001 -- record it, never sink the suite
        logger.warning("golden %s failed", golden.id, exc_info=exc)
        trace.error = f"{type(exc).__name__}: {exc}"
    trace.seconds = round(time.monotonic() - started, 1)
    trace.usage = usage.usage
    trace.supervisor_searches = recorder.searches_by("supervisor")
    _attach_researchers(trace, recorder)
    return trace


async def _run(
    golden: Golden,
    trace: RunTrace,
    model: BaseChatModel,
    recorder: RecordingSearchBackend,
    until: str | None,
) -> None:
    lifecycle: list[AgentEvent] = []
    planned = asyncio.Event()

    async def emit(event: AgentEvent) -> None:
        if event.type == "tool_call":
            tool = (event.data or {}).get("tool")
            # Only the supervisor's own calls: a researcher's searches are its
            # own business and already recorded against it.
            if tool and (event.data or {}).get("agent") == "supervisor":
                trace.tools.append(str(tool))
        if event.type == "planner_done":
            trace.plan = list((event.data or {}).get("sub_questions") or [])
            planned.set()
        if event.type == "planner_start":
            trace.research_query = event.message.removeprefix("Planning: ")
        if event.type in _NOTABLE_EVENTS or event.type.startswith("researcher_"):
            lifecycle.append(event)

    def on_research(result: ResearchResult) -> None:
        _record_research(trace, result)

    def middleware(agent: str, own_emit=None, **data) -> list:
        """The same progress middleware production installs, which is where the
        tool calls the supervisor made come from."""
        return [Progress(own_emit or emit, agent=agent, **data)]

    turn = asyncio.ensure_future(
        respond(
            golden.input,
            [],  # every golden is a first message: no conversation before it
            model=model,
            backend=recorder,
            sources=Sources(),
            on_research=on_research,
            middleware=middleware,
            emit=emit,
            max_iters=settings.supervisor_max_iters,
        )
    )
    try:
        # ``until="plan"`` cuts the turn the moment a plan exists, from outside
        # rather than by raising inside a tool (where the agent loop would catch
        # it and answer anyway). Nothing has searched yet at that point, which is
        # the whole point: the supervisor's judgement and the plan, for the price
        # of two calls.
        answer = await _cut_at(turn, planned if until == "plan" else None)
    finally:
        trace.lifecycle = [f"{e.type}: {e.message}" for e in lifecycle]
    trace.reply = answer.text
    trace.sources = [SourceRecord(title=s.title, url=s.url) for s in answer.sources]


async def _cut_at(turn: "asyncio.Future", stop: asyncio.Event | None):
    """Await the turn, unless ``stop`` fires first, in which case cancel it."""
    if stop is None:
        return await asyncio.wait_for(turn, timeout=settings.global_timeout)
    waiting = asyncio.ensure_future(stop.wait())
    try:
        await asyncio.wait({turn, waiting}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        waiting.cancel()
    if not turn.done():
        turn.cancel()
        raise asyncio.CancelledError
    return turn.result()


def _record_research(trace: RunTrace, result: ResearchResult) -> None:
    """What one ``research`` call produced. A turn may research more than once,
    so the points and gaps accumulate."""
    trace.consolidated += [
        f"{point.sub_question}: {claim.text} "
        + "".join(f"[{n}]" for n in claim.source_ids)
        for point in result.points
        for claim in point.claims
    ]
    trace.gaps += result.gaps
    for point in result.points:
        trace.researchers.append(
            ResearcherTrace(
                sub_question=point.sub_question,
                found_info=True,
                claims=[
                    ClaimRecord(
                        text=claim.text,
                        source_urls=[
                            result.sources[n - 1].url
                            for n in claim.source_ids
                            if 1 <= n <= len(result.sources)
                        ],
                    )
                    for claim in point.claims
                ],
            )
        )
    for gap in result.gaps:
        trace.researchers.append(ResearcherTrace(sub_question=gap, found_info=False))


def _attach_researchers(trace: RunTrace, recorder: RecordingSearchBackend) -> None:
    """Give each researcher the searches and fetches it actually made. The stage
    marker is positional (``research-1``), and the plan is in the same order, so
    a researcher is matched by where its sub-question sits in the plan."""
    position = {question: index for index, question in enumerate(trace.plan, start=1)}
    for researcher in trace.researchers:
        index = position.get(researcher.sub_question)
        if index is None:
            continue
        marker = f"research-{index}"
        researcher.searches = recorder.searches_by(marker)
        researcher.fetches = recorder.fetches_by(marker)
