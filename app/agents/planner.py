"""The planner: turns one research question into the sub-questions researchers
will answer, one each.

One forced call, with room to fix itself. An empty, malformed or over-cap plan is
fed back so the model can correct it inside the retry budget; after that, an
over-cap plan is clamped rather than thrown away, and only a plan that never
arrived at all is a failure.
"""

from collections.abc import Awaitable, Callable

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from pydantic import ValidationError

from app.agents.language import detect_language
from app.agents.schemas import AgentEvent
from app.agents.tools import SubmitPlanArgs
from app.observability import traced_step
from app.prompts import render
from app.prompts.common import today
from app.prompts.planner import PROMPT

Emit = Callable[[AgentEvent], Awaitable[None]]

_SUBMIT = "SubmitPlanArgs"  # the schema's name is the tool's name to the model


class PlannerError(Exception):
    """The planner could not produce a usable plan (system failure)."""


async def _noop(event: AgentEvent) -> None:
    return None


@traced_step("plan")
async def plan(
    prompt: str,
    *,
    model: BaseChatModel,
    emit: Emit = _noop,
    cap: int,
    retry_cap: int,
    feedback: str | None = None,
) -> list[str]:
    """Decompose a prompt into at most ``cap`` sub-questions.

    ``feedback`` carries a reason to plan differently than last time.
    """
    messages = _prompt_messages(prompt, cap=cap, feedback=feedback)
    bound = model.bind_tools([SubmitPlanArgs], tool_choice="any")
    await emit(AgentEvent(type="planner_start", message=f"Planning: {prompt}"))

    sub_questions: list[str] = []
    for _ in range(retry_cap + 1):
        # The live feed shows who is waiting on the model. The agents get this
        # from middleware; a plain call says so itself.
        await emit(
            AgentEvent(
                type="thinking",
                message="Planner is thinking",
                data={"agent": "planner"},
            )
        )
        reply = await bound.ainvoke(messages)
        sub_questions = _parse(reply)  # [] when empty or malformed

        if sub_questions and len(sub_questions) <= cap:
            await emit(
                AgentEvent(
                    type="planner_done",
                    message=f"{len(sub_questions)} sub-questions",
                    # the feed shows the plan up front, and how many researchers
                    # are about to run
                    data={"total": len(sub_questions), "sub_questions": sub_questions},
                )
            )
            return sub_questions

        _feed_back(messages, reply, _why(sub_questions, cap))

    # Retries exhausted: an over-cap plan is still a plan, so clamp it.
    if sub_questions:
        await emit(AgentEvent(type="planner_clamped", message=f"Clamped to {cap}"))
        return sub_questions[:cap]
    raise PlannerError("planner could not produce a usable plan")


def _prompt_messages(
    prompt: str, *, cap: int, feedback: str | None
) -> list[BaseMessage]:
    rendered = render(
        PROMPT,
        query=prompt,
        cap=cap,
        today=today(),
        feedback=(feedback or "").strip(),
        language=detect_language(prompt) or "",
    )
    return [
        HumanMessage(m.content or "")
        if m.role == "user"
        else SystemMessage(m.content or "")
        for m in rendered
    ]


def _why(sub_questions: list[str], cap: int) -> str:
    if not sub_questions:
        return (
            "The plan was empty or malformed. Call the tool again with a non-empty "
            "list of clear, complementary sub-questions."
        )
    return (
        f"Rejected: {len(sub_questions)} sub-questions exceeds the limit of {cap}. "
        f"Consolidate to at most {cap} without losing coverage, then submit again."
    )


def _feed_back(messages: list[BaseMessage], reply: AIMessage, why: str) -> None:
    """Record the model's turn and answer it. A forced tool call must be answered
    as a tool result; if it did not call the tool at all, a plain nudge does."""
    messages.append(reply)
    if reply.tool_calls:
        messages.append(
            ToolMessage(content=why, tool_call_id=reply.tool_calls[0]["id"] or _SUBMIT)
        )
    else:
        messages.append(HumanMessage(why))


def _parse(reply: AIMessage) -> list[str]:
    """The sub-questions, or [] when the call was missing or malformed, so the
    caller can feed that back and let it try again."""
    for call in reply.tool_calls or []:
        try:
            parsed = SubmitPlanArgs(**call["args"])
        except ValidationError:
            continue
        return [q.strip() for q in parsed.sub_questions if q.strip()]
    return []
