from httpx import AsyncClient

from tests.research.test_research import _register_and_headers, _use_fake_pipeline


async def test_create_conversation_starts_research(
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
    assistant = body["messages"][1]
    assert assistant["query_id"] is not None

    # the background job completes during the request cycle, so the thread now
    # carries the finished report
    detail = await client.get(f"/conversations/{body['id']}", headers=auth_headers)
    finished = detail.json()["messages"][1]
    assert finished["query"]["status"] == "complete"
    assert finished["query"]["report"] == "FINAL REPORT"


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
