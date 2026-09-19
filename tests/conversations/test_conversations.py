import httpx
from httpx import AsyncClient
from langchain_core.outputs import ChatGeneration, ChatResult

from app.agents.model import OUT_OF_CREDITS
from app.agents.provider import ProviderError
from app.billing.service import BUDGET_EXHAUSTED
from app.research.dependencies import get_model, get_search_backend
from app.research.service import PROVIDER_DOWN
from main import app
from tests.accounts import login_as
from tests.agents.fakes import ScriptedModel, call, says
from tests.research.test_research import FakeBackend, _use_fake_pipeline


class _AnswerModel(ScriptedModel):
    """A supervisor that always answers from what the conversation holds."""

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        reply = call("Decision", action="answer", reply="Answer from the report.")
        return ChatResult(generations=[ChatGeneration(message=reply)])


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

    # the routing job ran after the response: it named the report (and the
    # conversation), planned, and paused the turn for confirmation
    detail = await client.get(f"/conversations/{body['id']}", headers=auth_headers)
    assert detail.json()["title"] == "Research Topic"
    awaiting = detail.json()["messages"][1]["query"]
    assert awaiting["title"] == "Research Topic"
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

    app.dependency_overrides[get_model] = lambda: _AnswerModel()
    followed = await client.post(
        f"/conversations/{conversation_id}/messages",
        headers=auth_headers,
        json={"content": "what did the report say?"},
    )

    assert followed.status_code == 200
    # the turn is tracked by a query like any other; it ends with the reply
    detail = await client.get(f"/conversations/{conversation_id}", headers=auth_headers)
    last = detail.json()["messages"][-1]
    assert last["role"] == "assistant"
    assert last["content"] == "Answer from the report."
    assert last["query"]["status"] == "complete"
    assert last["query"]["reply"] == "Answer from the report."
    assert last["query"]["report"] is None


class _ComposeModel(ScriptedModel):
    """A supervisor that merges the conversation's reports, then the writer."""

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        names = {
            tool.get("function", {}).get("name") or tool.get("name", "")
            for tool in (kwargs.get("tools") or [])
        }
        reply = (
            call(
                "Decision",
                action="compose_report",
                instructions="merge them into one",
                title="Combined Report",
            )
            if "Decision" in names
            else says("MERGED REPORT")
        )
        return ChatResult(generations=[ChatGeneration(message=reply)])


async def test_supervisor_composes_a_merged_report(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    # First message researches and completes; the follow-up asks to merge, so the
    # supervisor composes a NEW report artifact (no new research run).
    _use_fake_pipeline(sub_questions=["q1"])
    created = await client.post(
        "/conversations", headers=auth_headers, json={"prompt": "first"}
    )
    conversation_id = created.json()["id"]
    query_id = created.json()["messages"][1]["query_id"]
    await client.post(f"/research/query/{query_id}/confirm", headers=auth_headers)

    app.dependency_overrides[get_model] = lambda: _ComposeModel()
    followed = await client.post(
        f"/conversations/{conversation_id}/messages",
        headers=auth_headers,
        json={"content": "merge the reports into a longer one"},
    )
    last = followed.json()["messages"][-1]
    assert last["role"] == "assistant"
    assert last["query_id"] is not None  # compose carries a report artifact

    # the compose job ran during the request cycle and produced the merged report
    detail = await client.get(f"/conversations/{conversation_id}", headers=auth_headers)
    composed = detail.json()["messages"][-1]["query"]
    assert composed["status"] == "complete"
    assert composed["report"] == "MERGED REPORT"
    assert composed["title"] == "Combined Report"


async def test_conversation_hidden_from_other_users(client: AsyncClient) -> None:
    owner = await login_as(client, "conv-owner@test.com")
    other = await login_as(client, "conv-other@test.com")
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


async def test_spent_budget_refuses_the_message_up_front(client: AsyncClient) -> None:
    # Every message costs at least a routing call, so even a would-be answer is
    # refused, and no empty conversation is left behind in the sidebar.
    headers = await login_as(client, "broke", budget_usd=0)
    _use_fake_pipeline(sub_questions=["q1"])

    created = await client.post(
        "/conversations", headers=headers, json={"prompt": "research this"}
    )

    assert created.status_code == 402
    assert created.json()["detail"] == BUDGET_EXHAUSTED
    assert (await client.get("/conversations", headers=headers)).json() == []


class _DownModel(ScriptedModel):
    """A provider that is not answering at all."""

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        raise ProviderError("LLM request failed")


async def test_a_provider_outage_fails_the_turn_with_a_clear_message(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    _use_fake_pipeline(sub_questions=["q1"])
    created = await client.post(
        "/conversations", headers=auth_headers, json={"prompt": "first"}
    )
    conversation_id = created.json()["id"]

    app.dependency_overrides[get_model] = lambda: _DownModel()
    followed = await client.post(
        f"/conversations/{conversation_id}/messages",
        headers=auth_headers,
        json={"content": "and then?"},
    )

    # Routing runs off the request, so the message is accepted and its turn then
    # fails with a message the user can act on.
    assert followed.status_code == 200
    detail = await client.get(f"/conversations/{conversation_id}", headers=auth_headers)
    turn = detail.json()["messages"][-1]["query"]
    assert turn["status"] == "failed"
    assert turn["error"] == PROVIDER_DOWN


async def test_a_key_over_its_credit_limit_tells_the_user_credits_ran_out(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    # OpenRouter's real answer once the demo key reaches its credit limit. It is a
    # 403, not a 402, and it used to reach the user as "provider not responding".
    app.dependency_overrides[get_model] = lambda: _KeyLimitModel()
    app.dependency_overrides[get_search_backend] = FakeBackend
    created = await client.post(
        "/conversations", headers=auth_headers, json={"prompt": "first"}
    )

    assert created.status_code == 201
    detail = await client.get(
        f"/conversations/{created.json()['id']}", headers=auth_headers
    )
    turn = detail.json()["messages"][1]["query"]
    assert turn["status"] == "failed"
    assert turn["error"] == OUT_OF_CREDITS


class _KeyLimitModel(ScriptedModel):
    """OpenRouter's real answer once the demo key reaches its credit limit: a 403,
    not a 402, which used to reach the user as "provider not responding"."""

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
        response = httpx.Response(
            403, text="Key limit exceeded (total limit).", request=request
        )
        raise httpx.HTTPStatusError("403", request=request, response=response)
