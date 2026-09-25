"""A question the supervisor asks, and the answer that comes back.

The question rides on the assistant message it ended; the answer is an ordinary
user message whose text is what the supervisor reads, and whose pairs are what
the thread draws as a card. What these pin is that both survive the round trip,
and that a typed "2" still means something the turn after.
"""

from httpx import AsyncClient
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from app.conversations.service import format_answers
from app.research.dependencies import get_model, get_search_backend
from main import app
from tests.agents.fakes import ScriptedModel, says
from tests.research.test_research import FakeBackend

TOPIC = {"question": "Which topic?", "options": ["History", "Science"]}
LEVEL = {"question": "How hard?", "options": ["Easy", "Hard"]}


class _Asks(ScriptedModel):
    """Asks on its first turn, answers on every turn after."""

    text: str = "Two quick questions."

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.seen.append(list(messages))
        if len(self.seen) == 1:
            reply = AIMessage(
                content=self.text,
                tool_calls=[
                    {
                        "name": "ask_user",
                        "args": {"questions": [TOPIC, LEVEL]},
                        "id": "a",
                    }
                ],
            )
        else:
            reply = says("Got it.")
        return ChatResult(generations=[ChatGeneration(message=reply)])


async def _ask(client: AsyncClient, headers: dict[str, str], model: _Asks) -> str:
    app.dependency_overrides[get_model] = lambda: model
    app.dependency_overrides[get_search_backend] = FakeBackend
    created = await client.post(
        "/conversations", headers=headers, json={"prompt": "quiz me"}
    )
    return created.json()["id"]


async def test_the_question_rides_on_the_reply_that_asked_it(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    cid = await _ask(client, auth_headers, _Asks())

    detail = (await client.get(f"/conversations/{cid}", headers=auth_headers)).json()
    turn = detail["messages"][1]
    assert turn["content"] == "Two quick questions."
    assert turn["ask"] == [TOPIC, LEVEL]
    # The live path reads the finished turn off its query, not the thread.
    query = (
        await client.get(f"/research/query/{turn['query_id']}", headers=auth_headers)
    ).json()
    assert query["ask"] == [TOPIC, LEVEL]
    assert detail["messages"][0]["ask"] is None
    # What it was asked in, so a reopened thread answers in the same mode.
    assert turn["query"]["mode"] == "answer"


async def test_a_typed_answer_still_maps_to_the_options(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    # Asked with no text beside it: the question alone is still a turn.
    model = _Asks(text="")
    cid = await _ask(client, auth_headers, model)

    await client.post(
        f"/conversations/{cid}/messages", headers=auth_headers, json={"content": "2"}
    )

    replayed = model.seen[-1]
    asked = next(m for m in replayed if isinstance(m, AIMessage))
    assert "1. Which topic?" in asked.text
    assert "2) Science" in asked.text
    assert replayed[-1].content == "2"


def test_answers_read_as_one_message() -> None:
    text = format_answers(
        [
            {"question": "Which topic?", "answer": "History"},
            {"question": "How hard?", "answer": None},
        ]
    )

    assert text == "Which topic?\n→ History\n\nHow hard?\n→ (skipped)"


async def test_answers_from_the_panel_arrive_as_one_message(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    model = _Asks()
    cid = await _ask(client, auth_headers, model)
    pairs = [
        {"question": "Which topic?", "answer": "History"},
        {"question": "How hard?", "answer": None},
    ]

    sent = await client.post(
        f"/conversations/{cid}/messages",
        headers=auth_headers,
        # The server writes the text from the pairs, whatever the client sent.
        json={"content": "ignored", "answers": pairs},
    )

    user = sent.json()["messages"][2]
    assert user["ask"] == pairs
    assert user["content"] == format_answers(pairs)
    last = model.seen[-1][-1]
    assert isinstance(last, HumanMessage)
    assert last.content == format_answers(pairs)
