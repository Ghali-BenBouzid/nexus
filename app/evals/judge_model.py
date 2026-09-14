"""The eval judge: a DeepEval model backed by OpenRouter.

DeepEval's metrics ask their judge for structured verdicts. This model sends each
prompt to OpenRouter with the metric's pydantic schema as a JSON schema, parses
the reply back into that schema, and keeps a running total of what judging cost.
"""

import asyncio
import re

import httpx
from deepeval.models import DeepEvalBaseLLM
from pydantic import BaseModel, ValidationError

from app.agents.retry import RetryPolicy, is_transient, retry_async
from app.core.config import settings

OPENROUTER_URL = "https://openrouter.ai/api/v1"
# A reply that wraps its JSON in prose or a code fence still carries one object.
_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)
_RETRY = RetryPolicy(max_attempts=4, base_delay=1.0, max_delay=20.0)


class JudgeOutputError(Exception):
    """The judge replied with nothing usable; a fresh generation usually fixes it."""


def _retryable(exc: Exception) -> bool:
    return isinstance(exc, JudgeOutputError) or is_transient(exc)


def _parse(content: str, schema: type[BaseModel]) -> BaseModel:
    try:
        return schema.model_validate_json(content)
    except ValidationError:
        match = _JSON_OBJECT.search(content)
        if match is None:
            raise JudgeOutputError("judge reply held no JSON object") from None
        try:
            return schema.model_validate_json(match.group(0))
        except ValidationError as exc:
            raise JudgeOutputError(
                f"judge reply did not fit {schema.__name__}"
            ) from exc


class JudgeModel(DeepEvalBaseLLM):
    def __init__(
        self,
        model: str | None = None,
        *,
        api_key: str | None = None,
        retry: RetryPolicy = _RETRY,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.api_key = api_key or settings.openrouter_api_key
        if not self.api_key:
            raise RuntimeError("The eval judge needs OPENROUTER_API_KEY.")
        self.retry = retry
        self.transport = transport
        self.cost_usd = 0.0
        super().__init__(model or settings.eval_judge_model)

    def load_model(self) -> "JudgeModel":
        return self

    def get_model_name(self) -> str:
        return self.name

    def supports_structured_outputs(self) -> bool:
        return True

    def supports_log_probs(self) -> bool:
        return False

    def generate(
        self, prompt: str, schema: type[BaseModel] | None = None
    ) -> str | BaseModel:
        # The metrics run async; this sync path exists only to satisfy the interface.
        return asyncio.run(self.a_generate(prompt, schema))

    async def a_generate(
        self, prompt: str, schema: type[BaseModel] | None = None
    ) -> str | BaseModel:
        payload: dict = {
            "model": self.name,
            "messages": [{"role": "user", "content": prompt}],
            # Verdicts need care, not long deliberation: keeps the judge fast and
            # cheap on reasoning models, and is ignored by the others.
            "reasoning": {"effort": "low"},
        }
        if schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": schema.__name__,
                    "schema": schema.model_json_schema(),
                },
            }
            # Only route to providers that honour the schema.
            payload["provider"] = {"require_parameters": True}

        async def attempt() -> str | BaseModel:
            content = await self._complete(payload)
            return content if schema is None else _parse(content, schema)

        return await retry_async(attempt, policy=self.retry, transient=_retryable)

    async def _complete(self, payload: dict) -> str:
        # ponytail: one client per call, simplest correct lifecycle; share a client
        # if judging thousands of cases makes the handshakes add up.
        async with httpx.AsyncClient(
            base_url=OPENROUTER_URL,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=120.0,
            transport=self.transport,
        ) as client:
            response = await client.post("/chat/completions", json=payload)
            response.raise_for_status()
            data = response.json()
        self.cost_usd += (data.get("usage") or {}).get("cost") or 0.0
        content = data["choices"][0]["message"].get("content")
        if not content:
            raise JudgeOutputError("judge returned an empty reply")
        return content
