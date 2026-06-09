from collections.abc import Awaitable, Callable

from app.agents.provider import LLMProvider, LLMResponse, Message
from app.agents.schemas import AgentEvent
from app.agents.tools import SubmitPlan, SubmitPlanArgs

Emit = Callable[[AgentEvent], Awaitable[None]]

DEFAULT_CAP = 5
DEFAULT_RETRY_CAP = 2


class PlannerError(Exception):
    """The planner could not produce a usable plan (system failure)."""


async def _noop(event: AgentEvent) -> None:
    return None


def _system_prompt(cap: int) -> str:
    return (
        "You are a research planner. Decompose the user's question into a small "
        "set of complementary, non-overlapping sub-questions that together cover "
        f"it exhaustively. Use at most {cap} sub-questions. Call submit_plan with "
        "the list."
    )


async def plan(
    prompt: str,
    *,
    provider: LLMProvider,
    emit: Emit = _noop,
    cap: int = DEFAULT_CAP,
    retry_cap: int = DEFAULT_RETRY_CAP,
) -> list[str]:
    """Decompose a prompt into <=cap sub-questions via a forced submit_plan call.

    Enforces the cap with a feedback loop (re-ask the model to consolidate) plus
    a clamp backstop. An empty plan is a planner failure.
    """
    submit = SubmitPlan()
    messages = [
        Message(role="system", content=_system_prompt(cap)),
        Message(role="user", content=prompt),
    ]
    await emit(AgentEvent(type="planner_start", message=f"Planning: {prompt}"))

    sub_questions: list[str] = []
    for _ in range(retry_cap + 1):
        response = await provider.generate(
            messages, tools=[submit], tool_choice=submit.name
        )
        sub_questions = _parse_plan(response)
        if not sub_questions:
            raise PlannerError("planner returned no sub-questions")
        if len(sub_questions) <= cap:
            await emit(
                AgentEvent(
                    type="planner_done",
                    message=f"{len(sub_questions)} sub-questions",
                )
            )
            return sub_questions

        # Too many: respond to the submit_plan call asking it to consolidate, retry.
        messages.append(_assistant_message(response))
        messages.append(
            Message(
                role="tool",
                tool_call_id=response.tool_calls[0].id,
                name=submit.name,
                content=(
                    f"Rejected: {len(sub_questions)} sub-questions exceeds the limit "
                    f"of {cap}. Consolidate to at most {cap} without losing coverage, "
                    "then call submit_plan again."
                ),
            )
        )

    # Still over after retries: clamp as the guaranteed floor.
    await emit(AgentEvent(type="planner_clamped", message=f"Clamped to {cap}"))
    return sub_questions[:cap]


def _assistant_message(response: LLMResponse) -> Message:
    return Message(
        role="assistant",
        content=response.text,
        tool_calls=response.tool_calls,
    )


def _parse_plan(response: LLMResponse) -> list[str]:
    if not response.tool_calls:
        return []
    parsed = SubmitPlanArgs(**response.tool_calls[0].args)
    return [question.strip() for question in parsed.sub_questions if question.strip()]
