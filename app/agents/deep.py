"""Deep research: the wide run, as a graph that survives a restart.

A normal research run is one fan-out and lives in ``asyncio``. This one is a
LangGraph graph for one reason: it takes minutes, and minutes is long enough
that a deploy will land in the middle of one. Every node completes into the
checkpointer, so a worker that picks the run back up starts from the last step
that finished instead of re-planning and re-paying for researchers that already
came back.

    plan ── researcher × N ── write ── END
             (Send, one per sub-question)

What a run needs but must not be checkpointed (the model, the search backend,
the event sink, the middleware) comes in through the runtime context, so every
resume passes its own.
"""

import logging
import operator
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Annotated, Any, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime
from langgraph.types import Send

from app.agents.planner import plan
from app.agents.report import write_report
from app.agents.research import Limits, Middleware, consolidate, research_task
from app.agents.schemas import AgentEvent, Finding, Report, ResearchResult, Source
from app.agents.sources import Sources
from app.agents.tools import SearchBackend
from app.core.config import settings
from app.prompts.deep import PROMPT as DEEP_PLANNER

logger = logging.getLogger(__name__)

Emit = Callable[[AgentEvent], Awaitable[None]]


class DeepError(Exception):
    """The run failed at the system level (every researcher hard-failed)."""


class Outcome(TypedDict):
    """What one researcher came back with, in plan order."""

    index: int
    sub_question: str
    finding: Finding | None  # None: the researcher failed, a gap in the report


class DeepState(TypedDict, total=False):
    question: str
    plan: list[str]
    deadline: float  # wall clock, so it means the same after a resume
    findings: Annotated[list[Outcome], operator.add]
    result: ResearchResult
    report: Report


class Task(TypedDict):
    """What the fan-out sends each researcher: its own slice of the work."""

    index: int
    total: int
    sub_question: str
    deadline: float


async def _noop(event: AgentEvent) -> None:
    return None


def _no_middleware(agent: str, emit: Emit | None = None, **data: Any) -> list:
    return []


@dataclass
class Deps:
    """The runtime context: what the nodes need that is not state."""

    model: BaseChatModel
    backend: SearchBackend
    emit: Emit = _noop
    middleware: Middleware = _no_middleware
    limits: Limits = field(default_factory=Limits.deep)


async def plan_node(state: DeepState, runtime: Runtime[Deps]) -> dict:
    deps = runtime.context
    sub_questions = await plan(
        state["question"],
        model=deps.model,
        emit=deps.emit,
        cap=deps.limits.cap,
        retry_cap=settings.planner_retry_cap,
        prompt=DEEP_PLANNER,
    )
    # Fixed here, not in the fan-out, so a resumed run does not hand its
    # researchers a fresh full budget every time it restarts.
    return {"plan": sub_questions, "deadline": time.time() + deps.limits.budget}


def _fan_out(state: DeepState) -> list[Send]:
    sub_questions = state["plan"]
    return [
        Send(
            "researcher",
            Task(
                index=index,
                total=len(sub_questions),
                sub_question=sub_question,
                deadline=state["deadline"],
            ),
        )
        for index, sub_question in enumerate(sub_questions, start=1)
    ]


async def researcher_node(task: Task, runtime: Runtime[Deps]) -> dict:
    deps = runtime.context
    finding = await research_task(
        task["index"],
        task["total"],
        task["sub_question"],
        model=deps.model,
        backend=deps.backend,
        emit=deps.emit,
        middleware=deps.middleware,
        limits=deps.limits,
        deadline=task["deadline"],
    )
    return {
        "findings": [
            Outcome(
                index=task["index"],
                sub_question=task["sub_question"],
                finding=finding,
            )
        ]
    }


async def write_node(state: DeepState, runtime: Runtime[Deps]) -> dict:
    deps = runtime.context
    outcomes = sorted(state["findings"], key=lambda outcome: outcome["index"])
    if all(outcome["finding"] is None for outcome in outcomes):
        raise DeepError("Every researcher failed, so there was nothing to report.")
    # The registry is rebuilt here rather than carried through the run: each
    # finding brought its own sources, so the numbering is a pure function of
    # the findings and comes out the same on a resume.
    result = consolidate([outcome["finding"] for outcome in outcomes], Sources())
    report = await write_report(
        result,
        model=deps.model,
        emit=deps.emit,
        timeout=settings.writer_timeout,
    )
    return {"result": result, "report": report}


def build_graph() -> StateGraph:
    graph = StateGraph(DeepState, context_schema=Deps)
    graph.add_node("plan", plan_node)
    graph.add_node("researcher", researcher_node)
    graph.add_node("write", write_node)
    graph.add_edge(START, "plan")
    graph.add_conditional_edges("plan", _fan_out, ["researcher"])
    graph.add_edge("researcher", "write")  # waits for every researcher
    graph.add_edge("write", END)
    return graph


# The classes a checkpoint may hold. Only these are rebuilt when a paused run is
# loaded; anything else in a checkpoint stays data.
SERDE = JsonPlusSerializer(
    allowed_msgpack_modules=[Finding, ResearchResult, Report, Source]
)


def compile_graph(checkpointer: BaseCheckpointSaver) -> CompiledStateGraph:
    return build_graph().compile(checkpointer=checkpointer, name="deep_research")


def run_config(query_id: int) -> RunnableConfig:
    """One thread per deep run, so a resume finds where it stopped."""
    return {
        "configurable": {"thread_id": f"deep-{query_id}"},
        "max_concurrency": settings.deep_concurrency,
        "metadata": {"query_id": query_id},  # ties the LangSmith trace to the row
    }
