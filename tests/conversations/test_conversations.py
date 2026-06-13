from httpx import AsyncClient

from app.agents.provider import LLMResponse, ToolCall
from app.research.dependencies import get_provider
from main import app
from tests.research.test_research import _register_and_headers, _use_fake_pipeline


class _AnswerProvider:
    """Supervisor that always routes to a direct answer (no research)."""

    async def __aenter__(self) -> "_AnswerProvider":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def generate(self, messages, tools=None, tool_choice="auto") -> LLMResponse:
        return LLMResponse(
            tool_calls=[
                ToolCall(
                    id="d",
                    name="submit_decision",
                    args={"action": "answer", "reply": "Answer from the report."},
                )
            ]
        )


async def test_create_conversation_plans_then_confirms(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    _use_fake_pipeline(sub_questions=["q1"])

    created = await client.post(
        "/conversations", headers=auth_headers, json={"prompt": "first question"}
    )
    assert created.status_code == 201
    body = created.json()

    # a research turn is a user message + an assistant message carrying the query
    roles = [m["role"] for m in body["messages"]]
    assert roles == ["user", "assistant"]
    assert body["messages"][0]["content"] == "first question"
    query_id = body["messages"][1]["query_id"]
    assert query_id is not None

    # human-in-the-loop: the plan job ran and the turn is awaiting confirmation
    detail = await client.get(f"/conversations/{body['id']}", headers=auth_headers)
    awaiting = detail.json()["messages"][1]["query"]
    assert awaiting["status"] == "awaiting_plan"
    assert awaiting["plan"] == ["q1"]

    # confirm the plan -> the research runs -> complete
    confirm = await client.post(
        f"/research/query/{query_id}/confirm", headers=auth_headers
    )
    assert confirm.status_code == 204
    final = await client.get(f"/conversations/{body['id']}", headers=auth_headers)
    finished = final.json()["messages"][1]["query"]
    assert finished["status"] == "complete"
    assert finished["report"] == "FINAL REPORT"


async def test_revise_replans_and_stays_awaiting(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    _use_fake_pipeline(sub_questions=["q1"])
    created = await client.post(
        "/conversations", headers=auth_headers, json={"prompt": "topic"}
    )
    query_id = created.json()["messages"][1]["query_id"]

    revise = await client.post(
        f"/research/query/{query_id}/revise",
        headers=auth_headers,
        json={"feedback": "go deeper on safety"},
    )
    assert revise.status_code == 204

    detail = await client.get(f"/research/query/{query_id}", headers=auth_headers)
    assert detail.json()["status"] == "awaiting_plan"
    assert detail.json()["plan"] == ["q1"]


async def test_confirm_rejected_when_not_awaiting_plan(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    _use_fake_pipeline(sub_questions=["q1"])
    created = await client.post(
        "/conversations", headers=auth_headers, json={"prompt": "topic"}
    )
    query_id = created.json()["messages"][1]["query_id"]
    await client.post(f"/research/query/{query_id}/confirm", headers=auth_headers)

    # already confirmed (running/complete) -> a second confirm is a 409
    second = await client.post(
        f"/research/query/{query_id}/confirm", headers=auth_headers
    )
    assert second.status_code == 409


async def test_followup_message_appends_to_thread(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    _use_fake_pipeline(sub_questions=["q1"])
    created = await client.post(
        "/conversations", headers=auth_headers, json={"prompt": "first"}
    )
    conversation_id = created.json()["id"]

    followed = await client.post(
        f"/conversations/{conversation_id}/messages",
        headers=auth_headers,
        json={"content": "go deeper"},
    )
    assert followed.status_code == 200
    messages = followed.json()["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant", "user", "assistant"]
    assert messages[2]["content"] == "go deeper"


async def test_list_conversations_newest_first(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    _use_fake_pipeline(sub_questions=["q1"])
    first = await client.post(
        "/conversations", headers=auth_headers, json={"prompt": "older"}
    )
    second = await client.post(
        "/conversations", headers=auth_headers, json={"prompt": "newer"}
    )

    listed = await client.get("/conversations", headers=auth_headers)
    ids = [c["id"] for c in listed.json()]
    assert ids[:2] == [second.json()["id"], first.json()["id"]]


async def test_supervisor_answers_from_context_without_research(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    # First message researches; the follow-up is routed to a direct answer, so it
    # produces an assistant message with a reply and NO research run.
    _use_fake_pipeline(sub_questions=["q1"])
    created = await client.post(
        "/conversations", headers=auth_headers, json={"prompt": "first"}
    )
    conversation_id = created.json()["id"]

    app.dependency_overrides[get_provider] = _AnswerProvider
    followed = await client.post(
        f"/conversations/{conversation_id}/messages",
        headers=auth_headers,
        json={"content": "what did the report say?"},
    )

    last = followed.json()["messages"][-1]
    assert last["role"] == "assistant"
    assert last["query_id"] is None
    assert last["content"] == "Answer from the report."


async def test_conversation_hidden_from_other_users(client: AsyncClient) -> None:
    owner = await _register_and_headers(client, "conv-owner@test.com")
    other = await _register_and_headers(client, "conv-other@test.com")
    _use_fake_pipeline(sub_questions=["q1"])

    created = await client.post(
        "/conversations", headers=owner, json={"prompt": "secret"}
    )
    conversation_id = created.json()["id"]

    assert (
        await client.get(f"/conversations/{conversation_id}", headers=other)
    ).status_code == 404
    assert (
        await client.post(
            f"/conversations/{conversation_id}/messages",
            headers=other,
            json={"content": "x"},
        )
    ).status_code == 404
