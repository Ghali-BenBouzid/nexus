from collections.abc import Awaitable, Callable

from pydantic import ValidationError

from app.agents.provider import LLMProvider, LLMResponse, Message
from app.agents.schemas import AgentEvent
from app.agents.tools import SubmitPlan, SubmitPlanArgs

Emit = Callable[[AgentEvent], Awaitable[None]]


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
    cap: int,
    retry_cap: int,
) -> list[str]:
    """Decompose a prompt into <=cap sub-questions via a forced submit_plan call.

    Resilient to model fumbles: an empty, malformed, or over-cap plan is fed back
    so the model can fix it within the retry budget (mirrors how the researcher
    handles a malformed submit_finding). After retries: clamp an over-cap plan to
    the floor, or raise PlannerError if nothing usable ever came back.
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
        sub_questions = _parse_plan(response)  # [] on empty or malformed

        if sub_questions and len(sub_questions) <= cap:
            await emit(
                AgentEvent(
                    type="planner_done",
                    message=f"{len(sub_questions)} sub-questions",
                    # the feed shows the plan up front and learns how many
                    # researchers are about to run
                    data={
                        "total": len(sub_questions),
                        "sub_questions": sub_questions,
                    },
                )
            )
            return sub_questions

        # Not usable yet: tell the model what's wrong and let it try again.
        if not sub_questions:
            feedback = (
                "The plan was empty or malformed. Call submit_plan with a "
                "non-empty list of clear, complementary sub-questions."
            )
        else:
            feedback = (
                f"Rejected: {len(sub_questions)} sub-questions exceeds the limit "
                f"of {cap}. Consolidate to at most {cap} without losing coverage, "
                "then call submit_plan again."
            )
        _append_feedback(messages, response, submit.name, feedback)

    # Retries exhausted: clamp an over-cap plan to the floor; otherwise fail.
    if sub_questions:
        await emit(AgentEvent(type="planner_clamped", message=f"Clamped to {cap}"))
        return sub_questions[:cap]
    raise PlannerError("planner could not produce a usable plan")


def _append_feedback(
    messages: list[Message], response: LLMResponse, tool_name: str, feedback: str
) -> None:
    """Record the model's turn and reply to it. A forced submit_plan turn must be
    answered as a function-response; if the model didn't call the tool at all,
    fall back to a plain user nudge (no call to answer)."""
    messages.append(_assistant_message(response))
    if response.tool_calls:
        messages.append(
            Message(
                role="tool",
                tool_call_id=response.tool_calls[0].id,
                name=tool_name,
                content=feedback,
            )
        )
    else:
        messages.append(Message(role="user", content=feedback))


def _assistant_message(response: LLMResponse) -> Message:
    return Message(
        role="assistant",
        content=response.text,
        tool_calls=response.tool_calls,
    )


def _parse_plan(response: LLMResponse) -> list[str]:
    # Empty or malformed both return [] so the caller can feed it back and retry.
    if not response.tool_calls:
        return []
    try:
        parsed = SubmitPlanArgs(**response.tool_calls[0].args)
    except ValidationError:
        return []
    return [question.strip() for question in parsed.sub_questions if question.strip()]
