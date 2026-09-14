import json

import httpx
from deepeval.test_case import LLMTestCase
from pydantic import BaseModel

from app.agents.retry import RetryPolicy
from app.evals.judge_model import JudgeModel
from app.evals.scoring import REPORT_DEPTH

NO_BACKOFF = RetryPolicy(max_attempts=3, base_delay=0.0, max_delay=0.0)


class Verdict(BaseModel):
    score: int
    reason: str


def _reply(content: str, cost: float = 0.001) -> httpx.Response:
    return httpx.Response(
        200,
        json={"choices": [{"message": {"content": content}}], "usage": {"cost": cost}},
    )


def _judge(
    handler, *, params: tuple[str, ...] = ("reasoning", "structured_outputs")
) -> JudgeModel:
    """A judge whose chat calls go to ``handler``, on a model whose provider
    supports ``params`` (what OpenRouter's endpoints lookup reports)."""

    def route(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/endpoints"):
            endpoints = [{"supported_parameters": list(params)}]
            return httpx.Response(200, json={"data": {"endpoints": endpoints}})
        return handler(request)

    return JudgeModel(
        "judge/model",
        api_key="k",
        retry=NO_BACKOFF,
        transport=httpx.MockTransport(route),
    )


async def test_reasoning_is_only_requested_from_models_that_support_it() -> None:
    # With require_parameters, asking a model without reasoning (Mistral Small,
    # Qwen instruct) for it left no provider: every judgment failed with 404.
    sent: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return _reply('{"score": 1, "reason": "r"}')

    await _judge(handler).a_generate("rate", schema=Verdict)
    await _judge(handler, params=("structured_outputs",)).a_generate("rate", Verdict)

    assert sent[0]["reasoning"] == {"effort": "low"}
    assert "reasoning" not in sent[1]


async def test_a_failed_lookup_leaves_reasoning_out() -> None:
    sent: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(503)
        sent.append(json.loads(request.content))
        return _reply('{"score": 1, "reason": "r"}')

    judge = JudgeModel(
        "judge/model", api_key="k", transport=httpx.MockTransport(handler)
    )

    verdict = await judge.a_generate("rate", schema=Verdict)

    assert verdict == Verdict(score=1, reason="r")
    assert "reasoning" not in sent[0]


async def test_structured_verdict_is_parsed_into_the_schema_and_costed() -> None:
    sent: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        sent.update(json.loads(request.content))
        return _reply('{"score": 4, "reason": "grounded"}', cost=0.0021)

    judge = _judge(handler)
    verdict = await judge.a_generate("rate this", schema=Verdict)

    assert verdict == Verdict(score=4, reason="grounded")
    assert judge.cost_usd == 0.0021
    assert sent["model"] == "judge/model"
    assert sent["response_format"]["json_schema"]["name"] == "Verdict"
    assert sent["provider"] == {"require_parameters": True}


class Item(BaseModel):
    verdict: str
    reason: str | None = None  # optional, like DeepEval's verdict reasons
    default: str = "kept"  # a field that happens to be named like the keyword


class Items(BaseModel):
    items: list[Item]


async def test_the_schema_is_sent_in_the_strict_form_openai_requires() -> None:
    # OpenRouter routes gpt judges to OpenAI/Azure, which reject a nested schema
    # unless every object is closed and lists all its properties as required.
    sent: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        sent.update(json.loads(request.content))
        return _reply('{"items": [{"verdict": "yes", "reason": null, "default": "x"}]}')

    verdict = await _judge(handler).a_generate("rate", schema=Items)

    assert verdict == Items(items=[Item(verdict="yes", reason=None, default="x")])
    spec = sent["response_format"]["json_schema"]
    assert spec["strict"] is True
    schema = spec["schema"]
    text = json.dumps(schema)
    assert "$ref" not in text and "$defs" not in text
    assert schema["additionalProperties"] is False
    item = schema["properties"]["items"]["items"]
    assert item["additionalProperties"] is False
    assert item["required"] == ["verdict", "reason", "default"]
    assert "default" not in item["properties"]["reason"]  # the keyword is dropped
    assert "default" in item["properties"]  # the field is not


async def test_json_wrapped_in_a_code_fence_still_parses() -> None:
    judge = _judge(lambda r: _reply('```json\n{"score": 2, "reason": "thin"}\n```'))

    assert await judge.a_generate("rate", schema=Verdict) == Verdict(
        score=2, reason="thin"
    )


async def test_an_unusable_reply_is_retried() -> None:
    replies = iter(["I think it is fine.", '{"score": 5, "reason": "ok"}'])
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return _reply(next(replies))

    judge = _judge(handler)

    assert await judge.a_generate("rate", schema=Verdict) == Verdict(
        score=5, reason="ok"
    )
    assert len(calls) == 2
    assert judge.cost_usd == 0.002  # both attempts were billed


async def test_plain_text_is_returned_as_is_without_a_schema() -> None:
    judge = _judge(lambda r: _reply("hello"))

    assert await judge.a_generate("hi") == "hello"


async def test_a_real_deepeval_metric_scores_through_the_judge() -> None:
    # Answer whatever schema the metric asks for with a plausible verdict, so this
    # exercises DeepEval's own prompt -> schema -> score path end to end.
    def handler(request: httpx.Request) -> httpx.Response:
        schema = json.loads(request.content)["response_format"]["json_schema"]["schema"]
        fields = schema.get("properties", {})
        verdict = {
            name: ("reasoned" if spec.get("type") == "string" else 8)
            for name, spec in fields.items()
        }
        return _reply(json.dumps(verdict))

    metric = REPORT_DEPTH(_judge(handler))
    await metric.a_measure(
        LLMTestCase(input="How does X work?", actual_output="X works via Y in 2024."),
        _show_indicator=False,
    )

    assert metric.score is not None and 0.0 <= metric.score <= 1.0
    assert metric.reason
