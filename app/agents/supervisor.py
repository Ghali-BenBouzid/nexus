"""The supervisor: a thin controller that decides how to handle a user message in
a conversation, instead of always running research.

Given the conversation so far (including reports already produced) and the latest
message, it routes to one of:

- ``research`` — run a fresh web search; it also rewrites the message into a
  self-contained research query, folding in the user's intent and context.
- ``answer`` — reply directly from the reports already in the conversation
  (a question about a report, a summary, a clarification), with no new search.

The decision is a forced ``submit_decision`` call (the same structured-output
pattern as the planner/researcher). When the model is unsure or malformed, it
falls back to ``research`` on the raw message: doing the work is the safer default
than a hollow answer.
"""

from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from app.agents.provider import LLMProvider, LLMResponse, Message
from app.agents.tools import BaseToolSpec


class SupervisorDecision(BaseModel):
    action: Literal["research", "answer"]
    query: str = ""  # the self-contained research query when action == research
    reply: str = ""  # the chat reply when action == answer


class DecisionArgs(BaseModel):
    action: Literal["research", "answer"] = Field(
        description="research = run a new web search; answer = reply from the "
        "reports already in the conversation"
    )
    query: str = Field(
        default="",
        description="when action=research: a clear, self-contained research "
        "question capturing what to find, folding in the user's request and the "
        "relevant context from the conversation",
    )
    reply: str = Field(
        default="",
        description="when action=answer: the reply, grounded only in the reports "
        "already in the conversation",
    )


class SubmitDecision(BaseToolSpec):
    name = "submit_decision"
    description = "Decide how to handle the user's latest message."
    args_model = DecisionArgs


_SYSTEM_PROMPT = (
    "You are the controller of a research assistant. You see the conversation so "
    "far, including any reports already produced, and must decide how to handle "
    "the user's latest message. Call submit_decision.\n"
    "- If it needs new or deeper information, a new topic, or a change that needs "
    "fresh research, choose action='research' and write a clear, self-contained "
    "research question that folds in the user's request and the relevant context.\n"
    "- If it can be answered from the reports already in the conversation (a "
    "question about a report, a summary, a clarification, a follow-up that the "
    "existing material already covers), choose action='answer' and write the "
    "answer, grounded only in those reports. Never invent facts.\n"
    "When in doubt, prefer research."
)


def _parse(response: LLMResponse, message: str) -> SupervisorDecision:
    if not response.tool_calls:
        return SupervisorDecision(action="research", query=message)
    try:
        args = DecisionArgs(**response.tool_calls[0].args)
    except ValidationError:
        return SupervisorDecision(action="research", query=message)
    if args.action == "answer" and args.reply.strip():
        return SupervisorDecision(action="answer", reply=args.reply.strip())
    return SupervisorDecision(action="research", query=args.query.strip() or message)


async def decide(
    message: str, context: str, *, provider: LLMProvider
) -> SupervisorDecision:
    """Route the latest message. ``context`` is the rendered conversation so far
    (prior messages + reports). The provider must already be open."""
    submit = SubmitDecision()
    messages = [
        Message(role="system", content=_SYSTEM_PROMPT),
        Message(
            role="user",
            content=f"{context}\n\nLatest message from the user:\n{message}",
        ),
    ]
    response = await provider.generate(
        messages, tools=[submit], tool_choice=submit.name
    )
    return _parse(response, message)
