import uuid

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
    """A supervisor that answers straight away, reaching for no tool."""

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        reply = says("Answer from the report.")
        return ChatResult(generations=[ChatGeneration(message=reply)])


async def test_a_turn_answers_in_the_conversation(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    _use_fake_pipeline(sub_questions=["q1"])

    created = await client.post(
        "/conversations", headers=auth_headers, json={"prompt": "first question"}
    )
    assert created.status_code == 201
    body = created.json()

    # a turn is a user message + the assistant message its run fills in
    roles = [m["role"] for m in body["messages"]]
    assert roles == ["user", "assistant"]
    assert body["messages"][0]["content"] == "first question"
    assert body["messages"][1]["query_id"] is not None

    # the job ran after the response: the answer lands on the message itself,
    # and there is no report artifact, because an ordinary turn does not make one
    detail = await client.get(f"/conversations/{body['id']}", headers=auth_headers)
    assert detail.json()["title"] == "first question"
    turn = detail.json()["messages"][1]
    assert turn["query"]["status"] == "complete"
    assert turn["query"]["report"] is None
    assert turn["content"] == turn["query"]["reply"]
    assert detail.json()["artifacts"] == []


class _ResearchingModel(ScriptedModel):
    """A supervisor that researches once, then answers from what came back."""

    researched: bool = False

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        names = {
            tool.get("function", {}).get("name") or tool.get("name", "")
            for tool in (kwargs.get("tools") or [])
        }
        if "SubmitPlanArgs" in names:
            reply = call("SubmitPlanArgs", sub_questions=["q1"])
        elif "SubmitFindingArgs" in names:
            reply = call(
                "SubmitFindingArgs",
                claims=[{"text": "a finding", "cited_source_ids": []}],
                found_info=True,
            )
        elif not self.researched:
            self.researched = True
            reply = call("research", question="what about this")
            reply.content = "Let me look into it."
        else:
            reply = says("Here is what the research found.")
        return ChatResult(generations=[ChatGeneration(message=reply)])


async def test_a_turn_that_researches_still_answers_inline(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    # Research is a tool, not a route: its findings come back to the supervisor,
    # which writes the answer into the conversation. No artifact, no approval.
    app.dependency_overrides[get_model] = lambda: _ResearchingModel()
    app.dependency_overrides[get_search_backend] = FakeBackend

    created = await client.post(
        "/conversations", headers=auth_headers, json={"prompt": "research this"}
    )
    conversation_id = created.json()["id"]

    detail = await client.get(f"/conversations/{conversation_id}", headers=auth_headers)
    turn = detail.json()["messages"][1]["query"]
    assert turn["status"] == "complete"
    # what it said before researching stays in the reply, as its own part
    assert turn["reply_parts"] == [
        "Let me look into it.",
        "Here is what the research found.",
    ]
    assert turn["reply"] == "Let me look into it.\n\nHere is what the research found."
    assert turn["report"] is None
    assert detail.json()["artifacts"] == []

    # the researchers really ran, and the feed shows them
    events = await client.get(
        f"/research/query/{turn_id(detail)}/events", headers=auth_headers
    )
    assert "researcher_done" in [e["type"] for e in events.json()]

    # a reloaded thread gets the feed as a finished turn shows it: where each
    # part ended and what the team did, but not a researcher's passing thoughts
    feed = turn["events"]
    assert {"said", "researcher_done"} <= {e["type"] for e in feed}
    assert "thinking" not in {e["type"] for e in feed}
    assert not [e for e in feed if e["type"] == "tool_call" and "index" in e["data"]]


def turn_id(detail) -> int:
    return detail.json()["messages"][1]["query_id"]


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


async def test_a_follow_up_can_answer_without_researching_again(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
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


async def test_a_conversation_is_named_by_an_id_that_gives_nothing_away(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Integer ids counted up across every account and were the URL: /chat/26
    told anyone how many chats everyone had, and the next was one guess away.
    Outside the database, a conversation is a random UUID and nothing else."""
    _use_fake_pipeline(sub_questions=["q1"])

    created = await client.post(
        "/conversations", headers=auth_headers, json={"prompt": "hello"}
    )
    public_id = created.json()["id"]
    [listed] = (await client.get("/conversations", headers=auth_headers)).json()

    assert uuid.UUID(public_id).version == 4
    assert listed["id"] == public_id
    ok = await client.get(f"/conversations/{public_id}", headers=auth_headers)
    assert ok.status_code == 200
    # The row's own integer key is not a way in.
    guessed = await client.get("/conversations/1", headers=auth_headers)
    assert guessed.status_code in (404, 422)


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
