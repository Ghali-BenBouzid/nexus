"""Deep research: a lead agent and its researchers, as a graph that survives a
restart.

A normal research run plans once and answers. A deep run is led. The lead sends
a round of researchers, reads what they bring back, and decides what that
changes: a gap to go back for, a disagreement to settle, an angle nobody took.
It sends the next round, or calls the subject covered and hands over an outline.
That decision is the lead's own (app.prompts.deep says what to weigh); the graph
only gives it room to loop and a ceiling to loop under.

    lead ──> researcher × N ──> lead ──> ... ──> write ── END
         (Send, one per sub-question)       (curate, then the report)

It is a LangGraph graph because it takes minutes, and minutes is long enough
that a deploy will land in the middle of one. Every node completes into the
checkpointer, so a worker that picks the run back up starts from the last step
that finished instead of re-paying for researchers that already came back.

The lead's memory is its rounds, kept as plain data: what it reasoned, what it
sent, what came back. Its conversation is rebuilt from them every turn, so a
resumed lead reads exactly what it would have read.

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
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime
from langgraph.types import Send
from pydantic import ValidationError

from app.agents.curate import curate
from app.agents.planner import feed_back, prompt_messages
from app.agents.report import write_report
from app.agents.research import Limits, Middleware, consolidate, research_task
from app.agents.schemas import AgentEvent, Finding, Report, ResearchResult, Source
from app.agents.sources import Sources
from app.agents.tools import (
    DispatchResearchersArgs,
    SearchBackend,
    WriteReportArgs,
)
from app.core.config import settings
from app.observability import stage, traced_step
from app.prompts.deep import PROMPT as LEAD

logger = logging.getLogger(__name__)

Emit = Callable[[AgentEvent], Awaitable[None]]

_DISPATCH = "DispatchResearchersArgs"  # the schema's name is the tool's name
_WRITE = "WriteReportArgs"
# A round with less than this left of the window would be cut off before its
# researchers read anything.
_MIN_ROUND_SECONDS = 90.0

Decision = DispatchResearchersArgs | WriteReportArgs


class DeepError(Exception):
    """The run failed at the system level (no plan, or every researcher failed)."""


class Round(TypedDict):
    """One of the lead's turns that sent researchers out."""

    reasoning: str
    sub_questions: list[str]
    deadline: float  # wall clock, when this round's researchers must submit


class Outcome(TypedDict):
    """What one researcher came back with."""

    index: int  # across the whole run, so researchers of different rounds differ
    round: int
    sub_question: str
    finding: Finding | None  # None: the researcher failed


class DeepState(TypedDict, total=False):
    question: str
    window: float  # wall clock end of research, so it means the same after a resume
    rounds: Annotated[list[Round], operator.add]
    findings: Annotated[list[Outcome], operator.add]
    outline: str  # set once the lead is done researching; how to shape the report
    result: ResearchResult
    report: Report


class Task(TypedDict):
    """What the fan-out sends each researcher: its own slice of the work."""

    index: int
    total: int
    round: int
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


@dataclass
class Left:
    """What the run has left to spend, as the lead is told it."""

    rounds: int
    researchers: int
    seconds: float

    @property
    def spent(self) -> bool:
        return (
            self.rounds <= 0
            or self.researchers <= 0
            or self.seconds < _MIN_ROUND_SECONDS
        )

    def __str__(self) -> str:
        return (
            f"Left: {max(self.rounds, 0)} rounds, {max(self.researchers, 0)} "
            f"researchers, {max(int(self.seconds // 60), 0)} minutes."
        )


async def lead_node(state: DeepState, runtime: Runtime[Deps]) -> dict:
    deps = runtime.context
    # Fixed on the first turn and checkpointed, so a resumed run does not hand
    # itself a fresh window every time it restarts.
    window = state.get("window") or time.time() + settings.deep_research_window
    rounds = state.get("rounds", [])
    findings = state.get("findings", [])
    left = Left(
        rounds=settings.deep_max_rounds - len(rounds),
        researchers=settings.deep_max_researchers - len(findings),
        seconds=window - time.time(),
    )
    if rounds and left.spent:
        await deps.emit(
            AgentEvent(type="lead_done", message="Out of budget: writing the report")
        )
        return {"window": window, "outline": ""}

    decision = await lead(
        state["question"],
        rounds,
        findings,
        model=deps.model,
        emit=deps.emit,
        cap=min(deps.limits.cap, left.researchers),
        left=left,
    )
    if isinstance(decision, WriteReportArgs):
        return {"window": window, "outline": decision.outline}
    deadline = min(time.time() + deps.limits.budget, window)
    round_ = Round(
        reasoning=decision.reasoning,
        sub_questions=decision.sub_questions,
        deadline=deadline,
    )
    return {"window": window, "rounds": [round_]}


@traced_step("lead")
async def lead(
    question: str,
    rounds: list[Round],
    findings: list[Outcome],
    *,
    model: BaseChatModel,
    emit: Emit = _noop,
    cap: int,
    left: Left,
    retry_cap: int = 2,
) -> Decision:
    """The lead's next move: another round of sub-questions, or the report.

    A malformed or over-cap call is fed back to be fixed, as the planner's is.
    Past the retries an over-cap round is clamped; a lead that still has no
    usable answer writes from what it has, unless it has nothing at all.
    """
    messages = _conversation(question, rounds, findings, cap=cap, left=left)
    bound = model.bind_tools(
        [DispatchResearchersArgs, WriteReportArgs], tool_choice="any"
    )
    first = not rounds
    if first:
        await emit(AgentEvent(type="planner_start", message=f"Planning: {question}"))

    over_cap: DispatchResearchersArgs | None = None
    with stage("lead"):
        for _ in range(retry_cap + 1):
            await emit(
                AgentEvent(
                    type="thinking",
                    message="The lead is thinking",
                    data={"agent": "planner"},
                )
            )
            reply = await bound.ainvoke(messages)
            decision = _parse(reply)
            why = _why(decision, cap, first)
            if decision is not None and why is None:
                await _announce(emit, decision, len(rounds) + 1)
                return decision
            if isinstance(decision, DispatchResearchersArgs) and decision.sub_questions:
                over_cap = decision
            feed_back(messages, reply, why)

    if over_cap is not None:
        await emit(AgentEvent(type="planner_clamped", message=f"Clamped to {cap}"))
        clamped = over_cap.model_copy(
            update={"sub_questions": over_cap.sub_questions[:cap]}
        )
        await _announce(emit, clamped, len(rounds) + 1)
        return clamped
    if first:
        raise DeepError("The lead could not produce a plan.")
    logger.warning("the lead gave no usable decision; writing from what it has")
    return WriteReportArgs(reasoning="", outline="")


def _conversation(
    question: str,
    rounds: list[Round],
    findings: list[Outcome],
    *,
    cap: int,
    left: Left,
) -> list[BaseMessage]:
    """The lead's conversation so far: its prompt, then every round as the tool
    call it made and the findings that answered it. Only the latest result says
    what is left, since only that one is still true."""
    messages = prompt_messages(LEAD, question, cap=cap)
    for number, round_ in enumerate(rounds, start=1):
        call_id = f"round-{number}"
        messages.append(
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": _DISPATCH,
                        "args": {
                            "reasoning": round_["reasoning"],
                            "sub_questions": round_["sub_questions"],
                        },
                        "id": call_id,
                    }
                ],
            )
        )
        body = render_round([o for o in findings if o["round"] == number])
        if number == len(rounds):
            body += f"\n\n{left}"
        messages.append(ToolMessage(content=body, tool_call_id=call_id))
    return messages


def render_round(outcomes: list[Outcome]) -> str:
    """One round's findings as the lead reads them: every claim, and how many
    sources stand behind it, since how well a point is backed is part of what
    the lead weighs. The sources themselves stay out: it never cites."""
    lines: list[str] = []
    for outcome in sorted(outcomes, key=lambda o: o["index"]):
        lines.append(f"## {outcome['sub_question']}")
        finding = outcome["finding"]
        if finding is None:
            lines.append("(the researcher failed)")
        elif not finding.found_info or not finding.claims:
            lines.append("(found nothing relevant)")
        for claim in finding.claims if finding else []:
            backing = len(claim.source_ids)
            lines.append(f"- {claim.text} ({backing} source{'s' * (backing != 1)})")
        lines.append("")
    return "\n".join(lines).strip()


def _parse(reply: AIMessage) -> Decision | None:
    for call in reply.tool_calls or []:
        schema = {_DISPATCH: DispatchResearchersArgs, _WRITE: WriteReportArgs}.get(
            call["name"]
        )
        if schema is None:
            continue
        try:
            decision = schema(**call["args"])
        except ValidationError:
            continue
        if isinstance(decision, DispatchResearchersArgs):
            questions = [q.strip() for q in decision.sub_questions if q.strip()]
            decision = decision.model_copy(update={"sub_questions": questions})
        return decision
    return None


def _why(decision: Decision | None, cap: int, first: bool) -> str | None:
    """What is wrong with the decision, fed back to the lead; None if nothing."""
    if decision is None:
        return (
            "That was not a valid call. Call dispatch_researchers with a non-empty "
            "list of sub-questions, or write_report."
        )
    if isinstance(decision, WriteReportArgs):
        if first:
            return "Nothing has been researched yet. Dispatch the first round."
        return None
    if not decision.sub_questions:
        return "The round was empty. Send at least one sub-question."
    if len(decision.sub_questions) > cap:
        return (
            f"Rejected: {len(decision.sub_questions)} sub-questions exceeds the "
            f"limit of {cap}. Keep the ones that matter most, then call again."
        )
    return None


async def _announce(emit: Emit, decision: Decision, number: int) -> None:
    if isinstance(decision, WriteReportArgs):
        await emit(
            AgentEvent(
                type="lead_done",
                message="Covered: writing the report",
                data={"reasoning": decision.reasoning},
            )
        )
        return
    data = {
        "round": number,
        "total": len(decision.sub_questions),
        "sub_questions": decision.sub_questions,
        "reasoning": decision.reasoning,
    }
    # The first round is the plan, as every run's feed and the evals read it.
    kind = "planner_done" if number == 1 else "lead_round"
    await emit(
        AgentEvent(
            type=kind,
            message=f"Round {number}: {len(decision.sub_questions)} sub-questions",
            data=data,
        )
    )


def _next(state: DeepState) -> list[Send] | str:
    """Where the lead's decision goes: to the report, or out to researchers."""
    if "outline" in state:
        return "write"
    rounds = state["rounds"]
    round_ = rounds[-1]
    offset = len(state.get("findings", []))
    total = offset + len(round_["sub_questions"])
    return [
        Send(
            "researcher",
            Task(
                index=offset + number,
                total=total,
                round=len(rounds),
                sub_question=sub_question,
                deadline=round_["deadline"],
            ),
        )
        for number, sub_question in enumerate(round_["sub_questions"], start=1)
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
                round=task["round"],
                sub_question=task["sub_question"],
                finding=finding,
            )
        ]
    }


async def write_node(state: DeepState, runtime: Runtime[Deps]) -> dict:
    deps = runtime.context
    outcomes = sorted(state.get("findings", []), key=lambda outcome: outcome["index"])
    if all(outcome["finding"] is None for outcome in outcomes):
        raise DeepError("Every researcher failed, so there was nothing to report.")
    # The registry is rebuilt here rather than carried through the run: each
    # finding brought its own sources, so the numbering is a pure function of
    # the findings and comes out the same on a resume.
    result = consolidate([outcome["finding"] for outcome in outcomes], Sources())
    # Choose before writing. Researchers never saw each other's work, so what
    # they hand over overlaps, and the writer is the wrong agent to prune it.
    result = await curate(
        result,
        model=deps.model,
        emit=deps.emit,
        cap=settings.deep_claim_cap,
        timeout=settings.deep_curate_timeout,
    )
    report = await write_report(
        result,
        model=deps.model,
        emit=deps.emit,
        guidance=state.get("outline", ""),
        timeout=settings.deep_writer_timeout,
    )
    return {"result": result, "report": report}


def build_graph() -> StateGraph:
    graph = StateGraph(DeepState, context_schema=Deps)
    graph.add_node("lead", lead_node)
    graph.add_node("researcher", researcher_node)
    graph.add_node("write", write_node)
    graph.add_edge(START, "lead")
    graph.add_conditional_edges("lead", _next, ["researcher", "write"])
    graph.add_edge("researcher", "lead")  # waits for every researcher in the round
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
