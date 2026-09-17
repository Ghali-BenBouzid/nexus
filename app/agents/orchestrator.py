"""The research pipeline, as a LangGraph graph.

    START ─┬─ supervisor ─┬─ answer ──────────────────────────────────────── END
           │              ├─ compose ─────────────────────────── write ──── END
           │              └─ research ─┐                           ▲
           └───────────────────────── plan ── approve ══ researcher × N ── consolidate
                                        ▲        │ (Send, one per sub-question)
                                        └────────┘ revise

A turn in a conversation enters at the supervisor. A one-shot run (POST
/research/query) enters at plan and approves its own plan. Everywhere else,
approve pauses the graph (``interrupt``) until the user confirms or revises the
plan. The checkpointer keeps the paused state, so a later job resumes it.

The nodes only adapt the agents (supervisor, planner, researcher, consolidator,
writer), which stay framework-free. What a run needs but must not be stored (the
provider, the search backend, the emit sink, the stop check, the limits) comes
in through the runtime context, ``Deps``.
"""

import asyncio
import logging
import operator
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime
from langgraph.types import Command, Send, interrupt
from pydantic import ValidationError

from app.agents import supervisor
from app.agents.consolidator import consolidate, merge_results
from app.agents.narration import ThinkingProvider
from app.agents.planner import plan
from app.agents.provider import LLMProvider, ProviderCreditsError
from app.agents.researcher import research
from app.agents.schemas import AgentEvent, Finding, Report, ResearchResult, Turn
from app.agents.tools import FetchPage, SearchBackend, WebSearch
from app.agents.writer import write
from app.core.config import settings

Emit = Callable[[AgentEvent], Awaitable[None]]
ShouldCancel = Callable[[], bool]

logger = logging.getLogger(__name__)


class OrchestratorError(Exception):
    """The run failed at the system level (every researcher hard-failed)."""


class OrchestratorCancelledError(OrchestratorError):
    """The run was cancelled (the user stopped it). A subclass of
    OrchestratorError so the job's existing handling resolves the status."""


# --- state ------------------------------------------------------------------


class PriorReport(TypedDict):
    """A finished report earlier in the conversation."""

    prompt: str
    report: str
    result: dict | None  # its stored ResearchResult, what compose merges


class Outcome(TypedDict):
    """What one researcher came back with, in plan order."""

    index: int
    sub_question: str
    finding: Finding | None  # None: the researcher failed, a gap in the report


class ResearchState(TypedDict, total=False):
    # A conversation turn starts with these three.
    message: str
    history: list[Turn]  # the thread before the message, one entry per turn
    prior: list[PriorReport]
    # A one-shot run starts with prompt and auto_approve.
    prompt: str  # the research query, or the compose instructions
    auto_approve: bool
    # The supervisor's decision.
    route: Literal["answer", "compose", "research"]
    title: str
    reply: str
    # Planning and the user's review of the plan.
    plan: list[str]
    feedback: str
    # Research, then the report.
    findings: Annotated[list[Outcome], operator.add]  # one entry per researcher
    result: ResearchResult
    guidance: str  # how to shape a composed report
    report: Report


class ResearcherTask(TypedDict):
    """What approve sends each researcher: its own slice of the work."""

    index: int
    total: int
    sub_question: str
    deadline: float  # wall clock (time.time()) by which to submit


class Review(TypedDict):
    """The user's answer to a proposed plan, what resumes the paused graph."""

    approved: bool
    feedback: str


async def _noop(event: AgentEvent) -> None:
    return None


def _setting(name: str) -> Any:
    return field(default_factory=lambda: getattr(settings, name))


@dataclass
class Deps:
    """The runtime context: what the nodes need that is not state. Never
    checkpointed, so every run (a resume too) passes its own."""

    provider: LLMProvider
    backend: SearchBackend
    emit: Emit = _noop
    should_cancel: ShouldCancel = lambda: False
    cap: int = _setting("cap")
    planner_retry_cap: int = _setting("planner_retry_cap")
    supervisor_max_iters: int = _setting("supervisor_max_iters")
    max_iters: int = _setting("max_iters")
    per_researcher_timeout: float = _setting("per_researcher_timeout")
    research_budget: float = _setting("research_budget")
    writer_timeout: float = _setting("writer_timeout")


def _tagged(emit: Emit, **data: Any) -> Emit:
    """An emit that stamps ``data`` on every event, so what happens inside one
    researcher (its model calls, its searches) says which researcher it was. With
    researchers running at once, the live UI could not tell otherwise."""

    async def tagged(event: AgentEvent) -> None:
        await emit(event.model_copy(update={"data": {**(event.data or {}), **data}}))

    return tagged


# --- nodes ------------------------------------------------------------------


async def supervisor_node(state: ResearchState, runtime: Runtime[Deps]) -> dict:
    deps = runtime.context
    prior = state.get("prior", [])
    decision = await supervisor.decide(
        state["message"],
        state.get("history", []),
        provider=ThinkingProvider(deps.provider, deps.emit, agent="supervisor"),
        backend=deps.backend,
        reports=[(r["prompt"], r["report"]) for r in prior],
        emit=deps.emit,
        max_iters=deps.supervisor_max_iters,
    )
    if decision.action == "answer":
        return {"route": "answer", "reply": decision.reply}
    if decision.action == "compose" and prior:
        instructions = decision.instructions or state["message"]
        return {"route": "compose", "prompt": instructions, "title": decision.title}
    # research, and compose with nothing to merge
    query = decision.query or state["message"]
    return {"route": "research", "prompt": query, "title": decision.title}


async def plan_node(state: ResearchState, runtime: Runtime[Deps]) -> dict:
    deps = runtime.context
    sub_questions = await plan(
        state["prompt"],
        provider=ThinkingProvider(deps.provider, deps.emit, agent="planner"),
        emit=deps.emit,
        cap=deps.cap,
        retry_cap=deps.planner_retry_cap,
        feedback=state.get("feedback"),
    )
    return {"plan": sub_questions}


async def approve_node(state: ResearchState, runtime: Runtime[Deps]) -> Command:
    deps = runtime.context
    if not state.get("auto_approve"):
        # Pauses the run here. When the user answers, the node runs again from
        # the top and interrupt() returns their Review instead of pausing.
        review: Review = interrupt({"plan": state["plan"]})
        if not review["approved"]:
            return Command(goto="plan", update={"feedback": review["feedback"]})
    if deps.should_cancel():
        raise OrchestratorCancelledError("research was stopped")

    # One shared deadline, as wall-clock time so it means the same in every task.
    deadline = time.time() + deps.research_budget
    sub_questions = state["plan"]
    return Command(
        goto=[
            Send(
                "researcher",
                ResearcherTask(
                    index=index,
                    total=len(sub_questions),
                    sub_question=sub_question,
                    deadline=deadline,
                ),
            )
            for index, sub_question in enumerate(sub_questions, start=1)
        ]
    )


async def researcher_node(task: ResearcherTask, runtime: Runtime[Deps]) -> dict:
    """One researcher. A failure or a timeout becomes a gap in the report; only
    running out of credits fails the run, since every other call would too."""
    deps = runtime.context
    index, sub_question = task["index"], task["sub_question"]
    lifecycle = {"index": index, "total": task["total"], "sub_question": sub_question}
    own_emit = _tagged(deps.emit, index=index, total=task["total"])
    await deps.emit(
        AgentEvent(
            type="researcher_start",
            message=f"Researching: {sub_question}",
            data=lifecycle,
        )
    )
    try:
        finding = await asyncio.wait_for(
            research(
                sub_question,
                provider=ThinkingProvider(deps.provider, own_emit, agent="researcher"),
                tools=[
                    WebSearch(backend=deps.backend),
                    FetchPage(backend=deps.backend),
                ],
                emit=own_emit,
                should_cancel=deps.should_cancel,
                max_iters=deps.max_iters,
                deadline=time.monotonic() + (task["deadline"] - time.time()),
            ),
            timeout=deps.per_researcher_timeout,
        )
    except ProviderCreditsError:
        raise
    except Exception as exc:
        # Log the real cause; the event is only a user-facing summary.
        logger.warning(
            "researcher failed for sub-question %r: %s: %s",
            sub_question,
            type(exc).__name__,
            exc,
            exc_info=exc,
        )
        await deps.emit(
            AgentEvent(
                type="researcher_failed",
                message=f"Could not research: {sub_question}",
                data=lifecycle,
            )
        )
        finding = None
    else:
        await deps.emit(
            AgentEvent(
                type="researcher_done",
                message=f"Done: {sub_question}",
                data={**lifecycle, "found_info": finding.found_info},
            )
        )
    return {
        "findings": [Outcome(index=index, sub_question=sub_question, finding=finding)]
    }


async def consolidate_node(state: ResearchState, runtime: Runtime[Deps]) -> dict:
    # Researchers bail early on a stop (each becomes a gap), so check here, before
    # spending the write on a run the user already stopped.
    if runtime.context.should_cancel():
        raise OrchestratorCancelledError("research was stopped")
    outcomes = sorted(state["findings"], key=lambda outcome: outcome["index"])
    findings = [o["finding"] for o in outcomes if o["finding"] is not None]
    if not findings:
        raise OrchestratorError("all researchers failed")
    failed = [o["sub_question"] for o in outcomes if o["finding"] is None]
    return {"result": consolidate(findings, failed)}


async def compose_node(state: ResearchState) -> dict:
    """Merge the conversation's reports into one result, for a longer report. No
    web search: the sources already gathered keep their citations."""
    results: list[ResearchResult] = []
    for prior in state["prior"]:
        if not prior["result"]:
            continue
        try:
            results.append(ResearchResult(**prior["result"]))
        except ValidationError:
            logger.warning("skipping an unreadable result for %r", prior["prompt"])
    if not results:
        raise OrchestratorError("There were no reports to compose.")
    return {"result": merge_results(results), "guidance": state["prompt"]}


async def write_node(state: ResearchState, runtime: Runtime[Deps]) -> dict:
    deps = runtime.context
    report = await write(
        state["result"],
        provider=ThinkingProvider(deps.provider, deps.emit, agent="writer"),
        emit=deps.emit,
        guidance=state.get("guidance", ""),
        timeout=deps.writer_timeout,
    )
    return {"report": report}


# --- the graph --------------------------------------------------------------


def _entry(state: ResearchState) -> str:
    return "supervisor" if "message" in state else "plan"


def _after_supervisor(state: ResearchState) -> str:
    return {"answer": END, "compose": "compose", "research": "plan"}[state["route"]]


def build_graph() -> StateGraph:
    graph = StateGraph(ResearchState, context_schema=Deps)
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("plan", plan_node)
    graph.add_node("approve", approve_node, destinations=("plan", "researcher"))
    graph.add_node("researcher", researcher_node)
    graph.add_node("consolidate", consolidate_node)
    graph.add_node("compose", compose_node)
    graph.add_node("write", write_node)

    graph.add_conditional_edges(START, _entry, ["supervisor", "plan"])
    graph.add_conditional_edges(
        "supervisor", _after_supervisor, [END, "compose", "plan"]
    )
    graph.add_edge("plan", "approve")
    graph.add_edge("researcher", "consolidate")  # waits for every researcher
    graph.add_edge("consolidate", "write")
    graph.add_edge("compose", "write")
    graph.add_edge("write", END)
    return graph


# The state classes a checkpoint may hold. Only these are rebuilt when a paused
# run is loaded; anything else in a checkpoint stays data.
SERDE = JsonPlusSerializer(
    allowed_msgpack_modules=[Finding, ResearchResult, Report, Turn]
)


def compile_graph(checkpointer: BaseCheckpointSaver) -> CompiledStateGraph:
    return build_graph().compile(checkpointer=checkpointer, name="research")


def run_config(query_id: int) -> RunnableConfig:
    """One thread per query: the plan pause and its resume share it."""
    return {
        "configurable": {"thread_id": str(query_id)},
        "max_concurrency": settings.max_concurrency,  # researchers at once
        "metadata": {"query_id": query_id},  # ties the LangSmith trace to the row
    }
