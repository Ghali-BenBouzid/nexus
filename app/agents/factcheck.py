"""The fact checker: an agent that reads a document and tests it against the web.

It is a sub-agent in both directions. The supervisor can call it as a tool when
a conversation turns on whether a document is right, and the user can start it
from a button on the document itself. Either way it does the same thing: pick
the claims the document rests on, search for what independent sources say, and
write its own report.

It starts by writing down what it will check, with submit_claims, and gets a
review back: every passage of the document has to map to a claim or be set
aside with a reason. It cannot search until it confirms the list, so the claims
are chosen once, on purpose, rather than wherever the searching happens to go.

Its report is its final message rather than a second call to a writer: by then
it has read everything it is going to read, and asking a separate model to
re-say it would only add a hop and a chance to drift from what was actually
found.
"""

import logging
from collections.abc import Awaitable, Callable

from langchain.agents import create_agent
from langchain.agents.middleware import (
    AgentMiddleware,
    ModelCallLimitMiddleware,
    ToolCallRequest,
)
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import StructuredTool

from app.agents.citations import finalize
from app.agents.language import detect_language
from app.agents.model import Deadline, LastStep
from app.agents.report import text_of
from app.agents.schemas import AgentEvent, Report
from app.agents.sources import Sources
from app.agents.tools import (
    SearchBackend,
    SubmitClaimsArgs,
    retrieval_tools,
    tagged,
)
from app.observability import traced_step
from app.prompts import render
from app.prompts.common import today
from app.prompts.factcheck import PROMPT

logger = logging.getLogger(__name__)

Emit = Callable[[AgentEvent], Awaitable[None]]

NOTHING_CHECKED = (
    "The fact check produced nothing readable. The document may hold no "
    "checkable claims, or the run was cut short."
)


async def _noop(event: AgentEvent) -> None:
    return None


@traced_step("fact_check")
async def fact_check(
    text: str,
    *,
    filename: str,
    model: BaseChatModel,
    backend: SearchBackend,
    sources: Sources,
    middleware: list[AgentMiddleware] | None = None,
    emit: Emit = _noop,
    focus: str = "",
    max_iters: int = 12,
    most_iters: int = 40,
    deadline: float | None = None,
) -> Report:
    """Check ``text`` against the web and write the report."""
    await emit(
        AgentEvent(
            type="factcheck_start",
            message=f"Fact-checking {filename}",
            data={"agent": "fact_checker", "document": filename},
        )
    )
    # The steps grow with the claims it confirms, up to most_iters: a fixed
    # budget ran out before the last claims of a long document were checked.
    limit = ModelCallLimitMiddleware(run_limit=max_iters, exit_behavior="end")
    last = LastStep(
        max_iters,
        "This is your last step: there are no more searches after it. "
        "Write your verdicts now from what you have already found, and "
        "say which claims you could not check.",
    )
    claims = ClaimsFirst(limit, last, floor=max_iters, ceiling=most_iters)
    agent = create_agent(
        model=model,
        tools=retrieval_tools(backend, sources, emit=emit, agent="fact_checker"),
        system_prompt=_system_prompt(text, focus),
        middleware=[
            *(middleware or []),
            # Out of time or out of rounds means write the report from what it
            # has read, not fail: the searching is already paid for.
            Deadline(deadline),
            claims,
            last,
            limit,
        ],
    )
    state = await agent.ainvoke(
        {"messages": [("user", _document(text, filename, focus))]}
    )
    written = _last_text(state.get("messages", []))
    await emit(
        AgentEvent(
            type="factcheck_done",
            message=f"Fact check written for {filename}",
            data={"agent": "fact_checker", "document": filename},
        )
    )
    if not written.strip():
        logger.warning("the fact checker for %s produced no report", filename)
        return Report(content=NOTHING_CHECKED, sources=[])

    content, cited, stripped = finalize(written, sources.all)
    if stripped:
        logger.warning("stripped unbacked citation markers %s", stripped)
    return Report(content=content, sources=cited)


REVIEW = """\
Review this list before you check anything. Go through the document passage by \
passage, and find for each one the claim that covers it or its entry in \
left_out.
- A passage that asserts something checkable and has neither is a missing claim.
- Two claims the same evidence would settle are one claim. Keep them apart only \
when one could hold while the other fails.
- Each claim says what the document says, no stronger and no weaker.
- left_out holds only passages with nothing in them to check, each with why.
Then call submit_claims again with the list as it should be, revised or \
unchanged, and confirmed set to true."""

NOT_YET = (
    "Nothing can be searched yet: list the claims with submit_claims and "
    "confirm the list first."
)


class ClaimsFirst(AgentMiddleware):
    """The fact checker's claim list: the submit_claims tool, the review it
    answers with, and the gate that holds every other tool until the list is
    confirmed. Confirming sets the step budget from the number of claims."""

    def __init__(
        self,
        limit: ModelCallLimitMiddleware,
        last: LastStep,
        *,
        floor: int,
        ceiling: int,
    ) -> None:
        super().__init__()
        self.limit = limit
        self.last = last
        self.floor = floor
        self.ceiling = ceiling
        self.reviewed = False
        self.confirmed = False
        self.tools = [
            StructuredTool.from_function(
                coroutine=self.submit,
                name="submit_claims",
                description=(
                    "Set down the claims this fact check will test, mapped to "
                    "the document, before any searching. Answers with a review "
                    "to do, then confirms the list once it is final."
                ),
                args_schema=SubmitClaimsArgs,
            )
        ]

    async def submit(self, claims: list, left_out: list, confirmed: bool) -> str:
        # The first list is always reviewed, whatever it says about itself.
        if not (confirmed and self.reviewed):
            self.reviewed = True
            return REVIEW
        self.confirmed = True
        # ponytail: two steps a claim (a search, a read) and four for the list
        # and the report. Searches for several claims can share a step, so it
        # leaves slack; count real steps if long documents still run short.
        steps = min(self.ceiling, max(self.floor, 2 * len(claims) + 4))
        self.limit.run_limit = steps
        self.last.limit = steps
        return (
            f"The list is confirmed: {len(claims)} claims. Check each of them, "
            "most important first, and give every one a verdict in the report."
        )

    async def awrap_tool_call(self, request: ToolCallRequest, handler) -> ToolMessage:
        call = request.tool_call
        if call["name"] != "submit_claims" and not self.confirmed:
            return ToolMessage(NOT_YET, tool_call_id=call["id"], name=call["name"])
        return await handler(request)


def _system_prompt(text: str, focus: str) -> str:
    messages = render(
        PROMPT,
        document="",
        focus=focus.strip(),
        today=today(),
        language=detect_language(text[:2000]) or "",
    )
    return messages[0].content or ""


def _document(text: str, filename: str, focus: str) -> str:
    """The document as the checker receives it: tagged as material to read, with
    the user's focus outside the tag so a document cannot pose as one."""
    block = tagged("document", text, filename=filename)
    if focus.strip():
        return f"{block}\n\nThe user asked you to focus on: {focus.strip()}"
    return block


def _last_text(messages: list) -> str:
    """The report: the last thing the agent wrote that was not a tool call."""
    for message in reversed(messages):
        if isinstance(message, AIMessage) and not message.tool_calls:
            text = text_of(message)
            if text.strip():
                return text
    return ""
