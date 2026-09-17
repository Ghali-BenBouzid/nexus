import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.agents.provider import Message
from app.prompts import LOCK, PROMPTS, fingerprint, render, version

_SAMPLE = "a < b & 'c'"


def _variables(prompt, value: str = _SAMPLE) -> dict:
    """Every variable the prompt takes, filled with ``value``. A messages
    placeholder takes a list of messages, not a string."""
    placeholders = {
        m.variable_name for m in prompt.messages if hasattr(m, "variable_name")
    }
    return {
        name: [] if name in placeholders else value for name in prompt.input_variables
    }


@pytest.mark.parametrize("name", PROMPTS)
def test_a_prompt_text_change_comes_with_a_version_bump(name: str) -> None:
    locked = json.loads(LOCK.read_text())[name]
    prompt = PROMPTS[name]
    assert (
        fingerprint(prompt) == locked["sha256"] or version(prompt) != locked["version"]
    ), f"{name}: the text changed. Bump metadata['version'], then run the lock"
    assert (
        fingerprint(prompt) == locked["sha256"] and version(prompt) == locked["version"]
    ), f"{name}: the lock is out of date, run `python -m app.prompts`"


@pytest.mark.parametrize("name", PROMPTS)
def test_variables_are_inserted_as_is(name: str) -> None:
    # Mustache's double braces HTML-escape a value: user text must use triple ones.
    prompt = PROMPTS[name]
    messages = render(prompt, **_variables(prompt))
    assert [m.role for m in messages] == ["system", "user"]
    assert any(_SAMPLE in (m.content or "") for m in messages)
    assert not any("&lt;" in (m.content or "") for m in messages)


@pytest.mark.parametrize("name", PROMPTS)
def test_every_system_prompt_states_today(name: str) -> None:
    # Without the date, models treat their training cutoff as the present: a
    # current-events report came back presenting 2024 as the latest year.
    prompt = PROMPTS[name]
    variables = _variables(prompt, "x")
    system = render(prompt, **{**variables, "today": "Thursday, September 17, 2026"})
    assert "Today's date is Thursday, September 17, 2026" in (system[0].content or "")


@pytest.mark.parametrize("name", PROMPTS)
def test_a_missing_variable_fails_loudly(name: str) -> None:
    with pytest.raises(KeyError):
        render(PROMPTS[name])


@pytest.mark.parametrize("name", PROMPTS)
def test_the_language_directive_appears_only_when_detected(name: str) -> None:
    prompt = PROMPTS[name]
    empty = _variables(prompt, "x")

    def system(language: str) -> str:
        messages: list[Message] = render(prompt, **{**empty, "language": language})
        return messages[0].content or ""

    assert "Write your entire response in French" in system("French")
    assert "IMPORTANT" not in system("")
    # A fixed example language primed small models toward it ("if French, write
    # in French"): the templates themselves must not name one.
    assert "French" not in system("")


def test_optional_sections_render_only_when_given() -> None:
    planner = PROMPTS["planner"]
    first = render(planner, query="Q", cap=3, feedback="", language="", today="T")[
        1
    ].content
    revised = render(
        planner, query="Q", cap=3, feedback="shorter", language="", today="T"
    )
    assert first == "Q"
    assert revised[1].content == (
        "Q\n\nYour previous plan was rejected. Revise it based on this feedback "
        "from the user: shorter"
    )


def test_the_conversation_arrives_as_real_messages() -> None:
    # It used to be one user message holding the whole thread, so the user's words
    # and the app's labels looked alike to the model.
    messages = render(
        PROMPTS["supervisor"],
        today="T",
        language="",
        message="and now?",
        history=[HumanMessage("first question"), AIMessage("an answer")],
    )

    assert [(m.role, m.content) for m in messages[1:]] == [
        ("user", "first question"),
        ("assistant", "an answer"),
        ("user", "and now?"),
    ]
