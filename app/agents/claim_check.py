"""The check on a reply that could claim a background run nobody started.

The prompt says a deep run or a fact check exists only once its tool has
started it, and the supervisor still told users "deep research is now running"
without ever calling deep_research. This catches that, and only that.

It used to send back every reply in a run mode that started nothing, on the
chance it made the claim. That cost a second call to the main model on every
greeting and every question back to the user, and it read a true "your run is
still going" as a false claim: the supervisor, told to call the tool, started a
second copy of a run that was already working. Now a small model reads the
reply first, and only a reply that really claims a new run is sent back.
"""

import asyncio
import logging
from typing import Any

from langchain.agents.middleware import AgentMiddleware, hook_config
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.model import PacedChatOpenAI
from app.agents.report import text_of
from app.core.config import settings

logger = logging.getLogger(__name__)

# The tool that starts each mode's run, and what to call the run.
STARTERS = {
    "deep": ("deep_research", "deep research run"),
    "factcheck": ("fact_check", "fact check"),
}

# A verdict slower than this lets the reply through: the check guards against a
# rare mistake, and must not hold up every turn when the small model is slow.
TIMEOUT = 10.0

PROMPT = (
    "You check one reply an AI research assistant is about to send. Answer "
    "with one word, yes or no.\n\n"
    "Answer yes only if the reply tells the user that a new {run} has been "
    "started, is starting, or is now underway. Answer no to everything else, "
    "including: saying that a run listed as already running is still going; "
    "asking whether to start one or what it should cover; offering to start "
    "one; saying one will start once the user answers; greetings; any answer "
    "that does not mention a {run}. The reply can be in any language."
)


def claim_judge(model: BaseChatModel) -> BaseChatModel | None:
    """The small model that reads the reply, or None when the check is off.

    A copy of the turn's own model with another name, like the step titler, so
    its call is billed to the same account as the turn."""
    name = settings.claim_check_model
    if not name or not isinstance(model, PacedChatOpenAI):
        return None
    return model.model_copy(
        update={
            "model_name": name,
            "extra_body": None,
            "pacing": None,
            "max_tokens": 3,
            "temperature": 0,
            "streaming": False,
        }
    )


class RunClaimCheck(AgentMiddleware):
    """In a mode that starts a background run, a reply that claims a new run
    when none was started in this turn is sent back once, with that fact.

    Whether to start a run stays the supervisor's call: this only makes sure a
    reply that says a run started is backed by one. Everything else, a greeting,
    a question back, a run that is already going, goes out as it was written.
    """

    def __init__(self, mode: str, judge: BaseChatModel, running: list[str]) -> None:
        super().__init__()
        self.tool, self.run = STARTERS[mode]
        self.judge = judge
        self.running = running
        self.checked = False

    @hook_config(can_jump_to=["model"])
    async def aafter_model(self, state, runtime) -> dict[str, Any] | None:
        messages = state["messages"]
        if self.checked or not messages or getattr(messages[-1], "tool_calls", None):
            return None
        turn = []
        for message in reversed(messages):
            if isinstance(message, HumanMessage):
                break
            turn.append(message)
        # A run started or steered in this turn backs whatever the reply says.
        acted = {self.tool, "steer_deep_research"}
        if any(getattr(m, "name", None) in acted for m in turn):
            return None
        reply = text_of(messages[-1]).strip()
        if not reply or not await self._claims(reply):
            return None
        self.checked = True
        logger.info("run claim check: the reply claimed a %s never started", self.run)
        return {
            "jump_to": "model",
            "messages": [
                HumanMessage(
                    f"(A check from Nexus, not from the user.) Your reply tells "
                    f"the user a new {self.run} has started, but none was started "
                    f"in this turn: {self.tool} was not called. Call {self.tool} "
                    "now if you meant to start one. Otherwise write the reply "
                    "again without that claim."
                )
            ],
        }

    async def _claims(self, reply: str) -> bool:
        """Whether the reply says a new run started. Any failure is a no: a
        reply held back by a broken check is worse than the rare false claim."""
        running = "\n".join(f"- {title}" for title in self.running) or "none"
        try:
            verdict = await asyncio.wait_for(
                self.judge.ainvoke(
                    [
                        SystemMessage(PROMPT.format(run=self.run)),
                        HumanMessage(
                            f"Runs already running:\n{running}\n\n"
                            f"The reply:\n<reply>\n{reply}\n</reply>"
                        ),
                    ]
                ),
                TIMEOUT,
            )
        except Exception:  # noqa: BLE001 -- the check failing is not the turn failing
            logger.warning("run claim check failed; the reply goes out", exc_info=True)
            return False
        return text_of(verdict).strip().lower().startswith("yes")
