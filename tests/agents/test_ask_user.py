"""ask_user: the supervisor puts questions to the user and the turn ends there.

The answer comes back as the user's next message, so all this pins is the turn
itself: what it says, which questions it carries, and that a malformed call is
sent back to be fixed rather than shown.
"""

from langchain_core.messages import AIMessage, ToolMessage

from app.agents.sources import Sources
from app.agents.supervisor import respond
from tests.agents.fakes import ScriptedModel, says
from tests.agents.test_supervisor import FakeBackend

TOPIC = {"question": "Which topic?", "options": ["History", "Science"]}
LEVEL = {"question": "How hard?", "options": ["Easy", "Hard"]}


def asks(text: str, *questions: dict, id: str = "ask") -> AIMessage:
    return AIMessage(
        content=text,
        tool_calls=[
            {"name": "ask_user", "args": {"questions": list(questions)}, "id": id}
        ],
    )


async def _respond(model):
    return await respond(
        "quiz me", [], model=model, backend=FakeBackend(), sources=Sources()
    )


async def test_asking_ends_the_turn_with_the_reply_and_the_questions() -> None:
    model = ScriptedModel([asks("Two quick questions.", TOPIC, LEVEL)])

    answer = await _respond(model)

    assert answer.text == "Two quick questions."
    assert answer.ask == [TOPIC, LEVEL]
    assert len(model.seen) == 1  # nothing after the question


async def test_a_question_with_no_reply_text_still_reaches_the_user() -> None:
    answer = await _respond(ScriptedModel([asks("", TOPIC)]))

    assert answer.text == ""
    assert answer.ask == [TOPIC]


async def test_a_malformed_question_is_sent_back_to_be_fixed() -> None:
    one_option = {"question": "Which topic?", "options": ["History"]}
    model = ScriptedModel(
        [asks("Pick one.", one_option, id="a"), asks("Pick one.", TOPIC, id="b")]
    )

    answer = await _respond(model)

    errors = [m for m in model.seen[1] if isinstance(m, ToolMessage)]
    assert errors and "options" in errors[-1].content
    assert answer.ask == [TOPIC]


async def test_a_turn_that_asks_nothing_carries_no_questions() -> None:
    answer = await _respond(ScriptedModel([says("Hello.")]))

    assert answer.ask is None


async def test_asking_beside_another_tool_still_ends_with_the_questions() -> None:
    both = AIMessage(
        content="Let me check, then ask.",
        tool_calls=[
            {"name": "web_search", "args": {"query": "q", "max_results": 5}, "id": "s"},
            {"name": "ask_user", "args": {"questions": [TOPIC]}, "id": "a"},
        ],
    )
    model = ScriptedModel([both])

    answer = await _respond(model)

    assert answer.text == "Let me check, then ask."
    assert answer.ask == [TOPIC]
    assert len(model.seen) == 1
