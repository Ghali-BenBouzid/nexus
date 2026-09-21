"""A chat model the tests script, so an agent's whole turn is deterministic.

``ScriptedModel`` answers from a list of replies, or from a function of what it
was sent, which is how a test drives an agent that branches: a researcher that
searches then submits, a supervisor that reads a report then answers.
"""

from collections.abc import Callable, Sequence
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool

from app.agents.model import STAGE_KEY
from app.observability import STAGE

Reply = Callable[[list[BaseMessage], list[str]], AIMessage]


def call(name: str, *, thought: str = "", **args: Any) -> AIMessage:
    """An assistant turn that calls one tool, having thought about it first."""
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": name}],
        additional_kwargs={"reasoning": thought} if thought else {},
    )


def thinks(thought: str, text: str) -> AIMessage:
    """An assistant turn that thought before it answered."""
    return AIMessage(text, additional_kwargs={"reasoning": thought})


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

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        """The scripted reply a word at a time, so a test can watch a turn
        arrive the way the browser does. Thinking comes first when the reply
        carries any, because that is the order a reasoning model sends it in,
        and usage rides the last chunk, as a provider sends it: a streamed call
        that reports none is a call nobody is billed for.

        Every chunk is stamped with the stage that produced it, as the real
        model stamps its own, because that is how a caller tells its own chunks
        from a sub-agent's."""
        result = self._generate(messages, stop, run_manager, **kwargs)
        message = result.generations[0].message
        here = {STAGE_KEY: STAGE.get()}
        for thought in (message.additional_kwargs or {}).get("reasoning", "").split():
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content="",
                    additional_kwargs={"reasoning": thought + " ", **here},
                )
            )
        text = message.text if isinstance(message.content, str) else ""
        if text:
            for word in text.split(" ")[:-1]:
                yield ChatGenerationChunk(
                    message=AIMessageChunk(content=word + " ", additional_kwargs=here)
                )
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content=text.split(" ")[-1], additional_kwargs=here
                )
            )
        else:
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content=message.content,
                    tool_calls=message.tool_calls,
                    additional_kwargs=here,
                )
            )
        yield ChatGenerationChunk(
            message=AIMessageChunk(
                content="",
                additional_kwargs=here,
                usage_metadata=message.usage_metadata,
                response_metadata=message.response_metadata,
            )
        )
