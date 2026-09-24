"""The feed's step titles: when a stretch of thinking is named, and what a
titler that fails costs (nothing but the title)."""

import asyncio

from app.agents.schemas import AgentEvent
from app.agents.titles import FIRST_TITLE_AT, RETITLE_EVERY, StepTitles, clean
from tests.agents.fakes import ScriptedModel, says


def _titles(*replies: str) -> tuple[StepTitles, list[AgentEvent], ScriptedModel]:
    seen: list[AgentEvent] = []

    async def emit(event: AgentEvent) -> None:
        seen.append(event)

    titler = ScriptedModel([says(r) for r in replies])
    return StepTitles(titler, emit, "English"), seen, titler


def _steps(seen: list[AgentEvent]) -> list[tuple[str, int, str]]:
    return [(e.type, e.data["step"], e.message) for e in seen]


async def test_a_step_is_announced_at_once_and_named_when_it_has_said_enough() -> None:
    """The step lands in the feed the moment thinking starts, ahead of the tool
    call it leads to; its title follows without holding anything up."""
    titles, seen, _ = _titles("Weighing the costs")

    await titles.think("call-1", "x" * 10)
    assert _steps(seen) == [("step", 1, "Thinking")]

    await titles.think("call-1", "x" * FIRST_TITLE_AT)
    await titles.close()
    assert _steps(seen) == [
        ("step", 1, "Thinking"),
        ("step_title", 1, "Weighing the costs"),
    ]


async def test_a_long_stretch_is_renamed_as_it_goes() -> None:
    titles, seen, titler = _titles("Reading the question", "Comparing the prices")

    await titles.think("call-1", "a" * FIRST_TITLE_AT)
    await asyncio.sleep(0)  # the first title lands before the model says more
    await titles.think("call-1", "b" * RETITLE_EVERY)
    await titles.close()

    assert [m for t, _, m in _steps(seen) if t == "step_title"] == [
        "Reading the question",
        "Comparing the prices",
    ]
    # Each title reads the latest thinking, which is what it should describe.
    assert titler.seen[1][-1].content.endswith("b" * 100)


async def test_a_short_thought_is_still_named_when_it_ends() -> None:
    titles, seen, _ = _titles("Saying hello")

    await titles.think("call-1", "Small talk.")
    await titles.end()
    await titles.close()

    assert _steps(seen) == [("step", 1, "Thinking"), ("step_title", 1, "Saying hello")]


async def test_each_model_call_is_its_own_step() -> None:
    titles, seen, _ = _titles("Planning a search", "Writing the answer")

    await titles.think("call-1", "first")
    await titles.think("call-2", "second")
    await titles.close()

    assert [(t, s) for t, s, _ in _steps(seen)] == [
        ("step", 1),
        ("step", 2),
        ("step_title", 1),
        ("step_title", 2),
    ]


async def test_a_titler_that_fails_costs_the_title_and_nothing_else() -> None:
    seen: list[AgentEvent] = []

    async def emit(event: AgentEvent) -> None:
        seen.append(event)

    broken = ScriptedModel(respond=lambda messages, tools: 1 / 0)
    titles = StepTitles(broken, emit, "English")

    await titles.think("call-1", "x" * FIRST_TITLE_AT)
    await titles.close()

    assert [e.type for e in seen] == ["step"]


def test_a_title_comes_back_as_one_clean_line() -> None:
    assert (
        clean('"Weighing the running costs."\nExtra line')
        == "Weighing the running costs"
    )
    assert clean("**Checking subsidies**") == "Checking subsidies"
    assert clean("   ") == ""


async def test_a_french_turn_is_titled_from_a_french_prompt() -> None:
    """Asked in English for a French title, a small model writes participles
    ("Comparant les prix"); asked in French, it writes the noun phrase a French
    interface uses ("Comparaison des prix")."""
    titler = ScriptedModel([says("Comparaison des prix")])

    async def emit(event: AgentEvent) -> None:
        pass

    titles = StepTitles(titler, emit, "French")
    await titles.think("call-1", "x" * FIRST_TITLE_AT)
    await titles.close()

    assert "français" in titler.seen[0][0].content


def test_a_title_in_title_case_is_put_back_in_sentence_case() -> None:
    """A proper noun keeps its capital because the model's own reasoning uses
    it; a word that is only capitalised in the title loses it."""
    reasoning = (
        "Mitsubishi lists the Ecodan range; the COP at -15C is in the datasheet."
    )
    assert (
        clean("Reviewing Mitsubishi's Specs", reasoning)
        == "Reviewing Mitsubishi's specs"
    )
    assert clean("Checking The COP Values", reasoning) == "Checking the COP values"
    assert clean("Summarizing Findings", "") == "Summarizing findings"


def test_sentence_case_reaches_inside_words_and_spares_acronyms() -> None:
    assert clean("Recherche coûts d'Installation PAC air-Eau", "") == (
        "Recherche coûts d'installation PAC air-eau"
    )
    assert clean("Checking MaPrimeRénov' Rules", "") == "Checking MaPrimeRénov' rules"
