from app.conversations.service import _MAX_REPORT_CHARS, _history
from app.models.conversation import Message, MessageRole
from app.models.query import Query


def _message(role: MessageRole, content: str = "", query_id: int | None = None):
    return Message(role=role, content=content, query_id=query_id)


def test_each_stored_message_becomes_its_own_turn() -> None:
    messages = [
        _message(MessageRole.user, "research the sky"),
        _message(MessageRole.assistant, "", query_id=1),
        _message(MessageRole.user, "what colour?"),
        _message(MessageRole.assistant, "Blue."),
    ]
    queries = {1: Query(prompt="why is the sky blue", report="Because of Rayleigh.")}

    turns = _history(messages, queries)

    assert [t.role for t in turns] == ["user", "assistant", "user", "assistant"]
    assert turns[0].content == "research the sky"
    assert turns[1].content == (
        '<report question="why is the sky blue">\nBecause of Rayleigh.\n</report>'
    )
    assert turns[3].content == "Blue."


def test_a_long_report_is_cut_and_says_where_the_rest_is() -> None:
    queries = {1: Query(prompt="q", report="x" * (_MAX_REPORT_CHARS + 500))}

    turn = _history([_message(MessageRole.assistant, "", query_id=1)], queries)[0]

    assert len(turn.content) < _MAX_REPORT_CHARS + 200
    assert "call read_reports for the full text" in turn.content
    assert turn.content.endswith("</report>")
