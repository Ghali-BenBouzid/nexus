"""The prompts the agents send, as versioned LangChain prompt templates.

Each agent has one ``ChatPromptTemplate`` (a system and a user message) whose
``metadata["version"]`` names the text it holds. ``versions.lock`` pins each
version to a hash of the template text, and a test fails when the text changes
without a bump, so a version number always means one exact prompt. Run
``python -m app.prompts`` after bumping to update the lock.

Templates use mustache so optional parts (``{{#feedback}}...{{/feedback}}``) stay
in the prompt. Variables use triple braces: double braces HTML-escape the value,
which would turn a user's "a < b" into "a &lt; b".

What stays in code: tool schemas (the code parses what the model sends back),
the loop's nudges and retry messages, and the renders of the conversation and
the findings (data formats, not wording).
"""

import hashlib
import json
from pathlib import Path
from typing import Any

from langchain_core.prompts import ChatPromptTemplate

from app.agents.provider import Message
from app.observability import record_metadata
from app.prompts import planner, researcher, supervisor, writer

PROMPTS: dict[str, ChatPromptTemplate] = {
    p.name: p
    for p in (supervisor.PROMPT, planner.PROMPT, researcher.PROMPT, writer.PROMPT)
}
LOCK = Path(__file__).with_name("versions.lock")

_ROLES = {"system": "system", "human": "user"}


def version(prompt: ChatPromptTemplate) -> int:
    return prompt.metadata["version"]


def versions() -> dict[str, int]:
    """Every prompt's version, for recording what an eval run used."""
    return {name: version(p) for name, p in PROMPTS.items()}


def fingerprint(prompt: ChatPromptTemplate) -> str:
    """A hash of the template text, what the lock pins a version to."""
    parts = [[m.__class__.__name__, m.prompt.template] for m in prompt.messages]
    return hashlib.sha256(json.dumps(parts).encode()).hexdigest()


def render(prompt: ChatPromptTemplate, **variables: Any) -> list[Message]:
    """The prompt's messages with ``variables`` filled in. A missing variable
    raises, so a template and its caller can't drift apart silently. Tags the
    current trace with the prompt and its version."""
    record_metadata(**{f"prompt_{prompt.name}": version(prompt)})
    return [
        Message(role=_ROLES[m.type], content=m.content)
        for m in prompt.invoke(variables).to_messages()
    ]
