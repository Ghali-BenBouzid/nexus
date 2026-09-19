"""A chat model the tests script, so an agent's whole turn is deterministic.

``ScriptedModel`` answers from a list of replies, or from a function of what it
was sent, which is how a test drives an agent that branches: a researcher that
searches then submits, a supervisor that reads a report then answers.
"""

from collections.abc import Callable, Sequence
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool

Reply = Callable[[list[BaseMessage], list[str]], AIMessage]


def call(name: str, **args: Any) -> AIMessage:
    """An assistant turn that calls one tool."""
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": name}])


def says(text: str, *, usage: tuple[int, int] | None = None) -> AIMessage:
    """An assistant turn that just answers, optionally with token usage."""
    message = AIMessage(text)
    if usage:
        message.usage_metadata = {
            "input_tokens": usage[0],
            "output_tokens": usage[1],
            "total_tokens": sum(usage),
        }
        message.response_metadata = {
            "token_usage": {
                "prompt_tokens": usage[0],
                "completion_tokens": usage[1],
                "cost": 0.0001,
            },
            "model_name": "fake/model",
        }
    return message


class ScriptedModel(BaseChatModel):
    """Replays scripted replies. ``replies`` is consumed in order; ``respond``
    decides from the conversation and the tools it was given, for agents whose
    path depends on what came back."""

    replies: list[AIMessage] = []
    respond: Reply | None = None
    model_name: str = "fake/model"
    seen: list[list[BaseMessage]] = []
    bound_tools: list[list[str]] = []

    def __init__(self, replies: Sequence[AIMessage] | None = None, **kwargs: Any):
        super().__init__(**kwargs)
        self.replies = list(replies or [])
        self.seen = []
        self.bound_tools = []

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> Any:
        converted = [convert_to_openai_tool(tool) for tool in tools]
        return self.bind(tools=converted, **kwargs)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        names = [
            tool.get("function", {}).get("name") or tool.get("name", "")
            for tool in (kwargs.get("tools") or [])
        ]
        self.seen.append(list(messages))
        self.bound_tools.append(names)
        if self.respond is not None:
            message = self.respond(list(messages), names)
        elif self.replies:
            message = self.replies.pop(0)
        else:
            message = AIMessage("out of scripted replies")
        return ChatResult(generations=[ChatGeneration(message=message)])

    async def _agenerate(
        self, messages, stop=None, run_manager=None, **kwargs
    ) -> ChatResult:
        return self._generate(messages, stop, run_manager, **kwargs)
