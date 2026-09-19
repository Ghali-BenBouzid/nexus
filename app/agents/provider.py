"""What a model call can fail with, and the message shape our prompts render to.

The calls themselves are LangChain's now (see ``app.agents.model``); what stayed
here is the vocabulary the rest of the app speaks: two errors a user may be shown,
and the plain message a rendered prompt produces before it becomes a chat message.
"""

from typing import Literal

from pydantic import BaseModel


class ProviderError(Exception):
    """A model call failed. Carries no SDK detail, so a leaked API key cannot ride
    along; the original is chained through ``__cause__``."""


class ProviderCreditsError(ProviderError):
    """The provider refused the call for lack of credits (HTTP 402, or a key that
    reached its limit). Retrying cannot help until it is topped up, and the
    message is safe to show."""


class Message(BaseModel):
    """One rendered prompt message. Prompts render to these, and each agent turns
    them into the chat messages its model expects."""

    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
