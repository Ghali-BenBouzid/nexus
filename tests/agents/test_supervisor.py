"""The supervisor, with a scripted model: which move it commits to, what it may
read first, and what happens when it commits to nothing.
"""

from app.agents.schemas import Turn
from app.agents.supervisor import decide
from app.agents.tools import SearchHit
from tests.agents.fakes import ScriptedModel, call, says

DECIDE = "Decision"  # the decision schema's name, as the model sees the tool


class FakeBackend:
    def __init__(self) -> None:
        self.searches: list[str] = []

    async def __aenter__(self) -> "FakeBackend":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def search(self, query: str, max_results: int) -> list[SearchHit]:
        self.searches.append(query)
        return [SearchHit(title="A", url="http://a", content="alpha")]

    async def extract(self, url: str) -> str:
        return "page text"


async def _decide(model, *, reports=None, message="a message", history=None, **kwargs):
    return await decide(
        message,
        history or [],
        model=model,
        backend=kwargs.pop("backend", FakeBackend()),
        reports=reports or [],
        **kwargs,
    )


async def test_it_can_send_researchers() -> None:
    model = ScriptedModel(
        [call(DECIDE, action="research", query="what is X", title="About X")]
    )

    decision = await _decide(model, message="tell me about X")

    assert decision.action == "research"
    assert decision.query == "what is X"
    assert decision.title == "About X"  # the supervisor names the report


async def test_it_can_answer_from_what_is_already_there() -> None:
    model = ScriptedModel([call(DECIDE, action="answer", reply="It is blue.")])

    decision = await _decide(model)

    assert decision.action == "answer"
    assert decision.reply == "It is blue."


async def test_it_can_merge_the_conversations_reports() -> None:
    model = ScriptedModel(
        [call(DECIDE, action="compose_report", instructions="merge", title="Combined")]
    )

    decision = await _decide(model, reports=[("q1", "report one"), ("q2", "two")])

    assert decision.action == "compose"
    assert decision.instructions == "merge"
    assert decision.title == "Combined"


async def test_it_reads_the_full_reports_before_merging_them() -> None:
    # The conversation only carries excerpts, so merging starts with a read.
    model = ScriptedModel(
        [
            call("read_reports"),
            call(DECIDE, action="compose_report", instructions="merge both"),
        ]
    )

    decision = await _decide(model, reports=[("q1", "the full text of report one")])

    assert decision.action == "compose"
    read = [m for turn in model.seen for m in turn if m.type == "tool"]
    assert "the full text of report one" in read[0].content


async def test_it_can_check_one_fact_before_answering() -> None:
    backend = FakeBackend()
    model = ScriptedModel(
        [
            call("web_search", query="price of X", max_results=3),
            call(DECIDE, action="answer", reply="About ten euros."),
        ]
    )

    decision = await _decide(model, backend=backend)

    assert decision.action == "answer"
    assert backend.searches == ["price of X"]


async def test_an_empty_answer_becomes_research_rather_than_a_blank_reply() -> None:
    model = ScriptedModel([call(DECIDE, action="answer", reply="   ")])

    decision = await _decide(model, message="what is X?")

    assert decision.action == "research"
    assert decision.query == "what is X?"


async def test_a_supervisor_that_never_commits_researches_the_message() -> None:
    # Out of rounds without a decision: doing the work beats a hollow answer.
    model = ScriptedModel(respond=lambda messages, tools: says("thinking out loud"))

    decision = await _decide(model, message="tell me", max_iters=2)

    assert decision.action == "research"
    assert decision.query == "tell me"


async def test_the_thread_reaches_the_model_as_separate_messages() -> None:
    # It used to arrive as one user message holding the rendered thread, where the
    # user's words and a report excerpt were indistinguishable.
    model = ScriptedModel([call(DECIDE, action="answer", reply="Blue.")])

    await _decide(
        model,
        message="what colour?",
        history=[
            Turn(role="user", content="research the sky"),
            Turn(
                role="assistant", content='<report question="sky">it is blue</report>'
            ),
        ],
    )

    sent = model.seen[0]
    assert [(m.type, m.content) for m in sent[-3:]] == [
        ("human", "research the sky"),
        ("ai", '<report question="sky">it is blue</report>'),
        ("human", "what colour?"),
    ]
