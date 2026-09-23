"""The supervisor, with a scripted model: what it reaches for, what it writes,
and what code refuses to let through.

The supervisor has no route to assert any more, so what these pin is the part
that is not the model's judgement: a citation it invented never reaches the
user, the sources it kept are the ones it cited, its reply is streamed as it is
written, and a tool it has no business having is not offered.
"""

from app.agents.schemas import AgentEvent, Turn
from app.agents.sources import Sources
from app.agents.supervisor import Document, Output, respond
from app.agents.tools import SearchHit
from tests.agents.fakes import ScriptedModel, call, says, thinks


class FakeBackend:
    def __init__(self) -> None:
        self.searches: list[str] = []
        self.fetched: list[str] = []

    async def __aenter__(self) -> "FakeBackend":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def search(self, query: str, max_results: int) -> list[SearchHit]:
        self.searches.append(query)
        return [SearchHit(title="A", url="http://a", content="alpha")]

    async def extract(self, url: str) -> str:
        self.fetched.append(url)
        return "page text"


async def _respond(model, message="a message", **kwargs):
    return await respond(
        message,
        kwargs.pop("history", []),
        model=model,
        backend=kwargs.pop("backend", FakeBackend()),
        sources=kwargs.pop("sources", Sources()),
        **kwargs,
    )


def _search(query: str = "q"):
    return call("web_search", query=query, max_results=5)


async def test_it_answers_without_reaching_for_anything() -> None:
    model = ScriptedModel([says("It is blue.")])

    answer = await _respond(model)

    assert answer.text == "It is blue."
    assert answer.sources == []


async def test_it_searches_first_and_keeps_what_it_cited() -> None:
    model = ScriptedModel([_search("x"), says("Alpha is a thing.[1]")])
    backend = FakeBackend()

    answer = await _respond(model, backend=backend)

    assert backend.searches == ["x"]
    assert answer.text == "Alpha is a thing.[1]"
    assert [s.url for s in answer.sources] == ["http://a"]


async def test_a_citation_it_invented_never_reaches_the_user() -> None:
    # Nothing was retrieved, so no number can be real.
    model = ScriptedModel([says("Confidently wrong.[3]")])

    answer = await _respond(model)

    assert answer.text == "Confidently wrong."
    assert answer.sources == []


async def test_an_answer_that_cites_nothing_carries_no_source_list() -> None:
    # Unlike a report, where the sources are half the point, a chat answer that
    # cites nothing should not drag a list of pages behind it.
    model = ScriptedModel([_search(), says("I could not establish that.")])

    answer = await _respond(model)

    assert answer.sources == []


async def test_it_reads_a_document_by_id() -> None:
    documents = [Document(id=7, filename="paper.pdf", text="the paper says X")]
    model = ScriptedModel(
        [call("read_document", document_id=7), says("The paper says X.")]
    )

    answer = await _respond(model, documents=documents)

    assert answer.text == "The paper says X."
    # The file's text reached the model as tagged material, not as instructions.
    assert "<document" in str(model.seen[-1])


async def test_a_document_that_is_not_attached_is_refused_not_guessed() -> None:
    documents = [Document(id=7, filename="paper.pdf", text="x")]
    model = ScriptedModel(
        [call("read_document", document_id=99), says("That file is not here.")]
    )

    await _respond(model, documents=documents)

    assert "No document with id 99" in str(model.seen[-1])


async def test_tools_it_has_no_use_for_are_not_offered() -> None:
    # No documents means no read_document and no fact_check; nothing to point at.
    model = ScriptedModel([says("hi")])

    await _respond(model, start_fact_check=_never)

    offered = set(model.bound_tools[0])
    assert "read_document" not in offered
    assert "fact_check" not in offered
    assert {"web_search", "fetch_page", "research"} <= offered


async def test_a_document_brings_its_tools_with_it() -> None:
    model = ScriptedModel([says("hi")])

    await _respond(
        model,
        documents=[Document(id=1, filename="a.pdf", text="x")],
        outputs=[Output(id=2, title="A report", content="body")],
        start_fact_check=_never,
        start_deep_research=_never_deep,
    )

    offered = set(model.bound_tools[0])
    assert {"read_document", "fact_check", "read_report", "deep_research"} <= offered


async def test_a_background_run_is_started_once_and_not_waited_for() -> None:
    started: list[tuple[str, str, str]] = []

    async def start(question: str, title: str, goal: str) -> str:
        started.append((question, title, goal))
        return "Deep research has started."

    model = ScriptedModel(
        [
            call(
                "deep_research",
                question="all about X",
                title="About X",
                goal="an overview",
            ),
            says("I have started a deep run on that."),
        ]
    )

    answer = await _respond(model, start_deep_research=start)

    assert started == [("all about X", "About X", "an overview")]
    assert answer.text == "I have started a deep run on that."


async def test_the_thread_reaches_the_model_as_separate_turns() -> None:
    history = [Turn(role="user", content="first"), Turn(role="assistant", content="ok")]
    model = ScriptedModel([says("second")])

    await _respond(model, message="now this", history=history)

    kinds = [m.type for m in model.seen[0]]
    assert kinds == ["system", "human", "ai", "human"]


async def test_an_empty_answer_is_empty_not_invented() -> None:
    model = ScriptedModel([says("")])

    answer = await _respond(model)

    assert answer.text == ""


async def _never(document_id: int, focus: str) -> str:
    raise AssertionError("fact_check should not have been called")


async def _never_deep(question: str, title: str) -> str:
    raise AssertionError("deep_research should not have been called")


async def test_the_answer_is_emitted_as_it_is_written() -> None:
    """The reply reaches the browser a piece at a time, and the pieces put back
    together are exactly the reply. A turn that only arrives at the end is the
    thing streaming exists to stop."""
    model = ScriptedModel([thinks("Small talk. Keep it short.", "It is blue.")])
    seen: list[AgentEvent] = []

    answer = await _respond(model, emit=_record(seen))

    assert answer.text == "It is blue."
    assert _joined(seen, "token") == "It is blue."
    assert _joined(seen, "thought") == "Small talk. Keep it short."


async def test_a_sub_agents_tokens_never_reach_the_reply() -> None:
    """Researchers run on the same model object as the supervisor. Only the
    supervisor's own node is the answer being written, so only its tokens are
    streamed; a researcher's would otherwise interleave into the user's reply."""

    def reply(messages, tools):
        if "SubmitPlanArgs" in tools:
            return call("SubmitPlanArgs", sub_questions=["why is it blue?"])
        if "SubmitFindingArgs" in tools:
            return call(
                "SubmitFindingArgs",
                thought="a researcher thinking out loud",
                claims=[{"text": "a researcher talking", "cited_source_ids": []}],
                found_info=True,
            )
        if any(m.type == "tool" for m in messages):
            return says("Because of Rayleigh scattering.")
        return call("research", question="why is it blue?")

    model = ScriptedModel(respond=reply)
    seen: list[AgentEvent] = []

    answer = await _respond(model, emit=_record(seen))

    assert answer.text == "Because of Rayleigh scattering."
    assert _joined(seen, "token") == "Because of Rayleigh scattering."
    # Its thinking is its own too: a sub-agent's model node is called "model"
    # just like the supervisor's, so only the stage separates them.
    assert "researcher thinking out loud" not in _joined(seen, "thought")


def _joined(events: list[AgentEvent], type_: str) -> str:
    return "".join(e.message for e in events if e.type == type_).strip()


def _record(into: list[AgentEvent]):
    async def emit(event: AgentEvent) -> None:
        into.append(event)

    return emit


# --- steering a deep run that is still working -------------------------------


async def _never_steer(run_id: int, note: str) -> str:
    raise AssertionError("steer was not expected")


async def test_steering_exists_only_while_a_deep_run_is_working() -> None:
    """Additive by construction: with nothing running, a turn gets exactly the
    tools and the prompt it had before steering existed."""
    from app.agents.supervisor import _system_prompt

    idle = ScriptedModel([says("hi")])
    await _respond(idle, steer_deep_research=_never_steer, running=[])
    busy = ScriptedModel([says("hi")])
    running = [Output(id=7, title="Aviation weather", content="")]
    await _respond(busy, steer_deep_research=_never_steer, running=running)

    assert "steer_deep_research" not in idle.bound_tools[0]
    assert "steer_deep_research" in busy.bound_tools[0]
    assert _system_prompt("m", [], [], running=[]) == _system_prompt("m", [], [])
    prompt = _system_prompt("m", [], [], running=running)
    assert "<running>" in prompt and "id 7: Aviation weather" in prompt


async def test_a_change_of_mind_is_passed_to_the_running_run() -> None:
    steered: list[tuple[int, str]] = []

    async def steer(run_id: int, note: str) -> str:
        steered.append((run_id, note))
        return "Noted on the run."

    model = ScriptedModel(
        [
            call("steer_deep_research", run_id=7, note="Assume EASA, not FAA."),
            says("Done: the run will switch to EASA from its next step."),
        ]
    )

    answer = await _respond(
        model,
        "actually I fly in Europe",
        steer_deep_research=steer,
        running=[Output(id=7, title="Aviation weather", content="")],
        mode="deep",
    )

    assert steered == [(7, "Assume EASA, not FAA.")]
    # Steering counts as acting in deep mode: no "you started nothing" check.
    assert len(model.seen) == 2
    assert answer.text.startswith("Done")
