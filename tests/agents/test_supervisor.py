"""The supervisor, with a scripted model: what it reaches for, what it writes,
and what code refuses to let through.

The supervisor has no route to assert any more, so what these pin is the part
that is not the model's judgement: a citation it invented never reaches the
user, the sources it kept are the ones it cited, its reply is streamed as it is
written, and a tool it has no business having is not offered.
"""

import pytest
from langchain_core.messages import AIMessage

from app.agents import supervisor
from app.agents.schemas import AgentEvent, Turn
from app.agents.sources import Sources
from app.agents.supervisor import Document, Output, Running, respond
from app.agents.titles import StepTitles
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
    assert {"read_document", "fact_check", "read_report"} <= offered


async def test_a_deep_run_can_only_be_started_from_deep_mode() -> None:
    """A run of several minutes is the user's call: outside deep mode the
    supervisor can suggest one, and has no tool to start it."""
    answer_mode = ScriptedModel([says("hi")])
    deep_mode = ScriptedModel([says("hi"), says("hi")])

    await _respond(answer_mode, start_deep_research=_never_deep)
    await _respond(deep_mode, start_deep_research=_never_deep, mode="deep")

    assert "deep_research" not in answer_mode.bound_tools[0]
    assert "deep_research" in deep_mode.bound_tools[0]


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

    answer = await _respond(model, start_deep_research=start, mode="deep")

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


async def _never(document_id: int, title: str, focus: str) -> str:
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


async def test_the_thinking_is_shown_as_a_titled_step_never_as_itself(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The feed names each stretch of thinking in a few words. The scratchpad
    itself is never sent: streamed raw, it scrolled faster than anyone reads."""
    titler = ScriptedModel([says("Keeping it short")])
    _titled_by(titler, monkeypatch)
    thought = "Small talk, nothing to look up. I should keep the answer short and warm."
    seen: list[AgentEvent] = []

    await _respond(ScriptedModel([thinks(thought, "It is blue.")]), emit=_record(seen))

    kinds = [e.type for e in seen if e.type in ("step", "step_title", "token")]
    assert kinds[0] == "step" and "step_title" in kinds
    assert [e.message for e in seen if e.type == "step_title"] == ["Keeping it short"]
    assert all(thought not in e.message for e in seen)
    assert thought in titler.seen[0][-1].content


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


async def test_a_sub_agents_thinking_is_never_titled_as_the_supervisors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A researcher's model node is called "model" just like the supervisor's,
    so only the stage separates their thinking. The feed's steps are the
    supervisor's; a researcher's work shows as its own row."""

    def reply(messages, tools):
        if "SubmitPlanArgs" in tools:
            return call("SubmitPlanArgs", sub_questions=["why is it blue?"])
        if "SubmitFindingArgs" in tools:
            return call(
                "SubmitFindingArgs",
                thought="a researcher thinking out loud " * 10,
                claims=[{"text": "a researcher talking", "cited_source_ids": []}],
                found_info=True,
            )
        if any(m.type == "tool" for m in messages):
            return says("Because of Rayleigh scattering.")
        return call("research", question="why is it blue?")

    titler = ScriptedModel(respond=lambda messages, tools: says("Titled"))
    _titled_by(titler, monkeypatch)

    await _respond(ScriptedModel(respond=reply), emit=_record([]))

    read = " ".join(str(sent[-1].content) for sent in titler.seen)
    assert "researcher thinking out loud" not in read


def _titled_by(titler: ScriptedModel, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        supervisor,
        "step_titles",
        lambda model, emit, language: StepTitles(titler, emit, language),
    )


class PerQueryBackend(FakeBackend):
    """A different page for every query, so each search adds a source."""

    async def search(self, query: str, max_results: int) -> list[SearchHit]:
        self.searches.append(query)
        return [SearchHit(title=query, url=f"http://{query}", content=query)]


async def test_what_it_says_before_a_tool_call_is_kept_as_part_of_the_reply() -> None:
    """Words written alongside a tool call ("x first, now z") are the reply
    being written, not a draft of it. They are marked where they end, so the
    chat keeps them in place, and they stay in the reply, numbered with the
    rest of it: a source first cited there is [1] all the way down."""
    preamble = AIMessage(
        "x first.[2]",
        tool_calls=[{"name": "web_search", "args": {"query": "z"}, "id": "z"}],
    )
    model = ScriptedModel([_search("y"), _search("x"), preamble, says("Then y.[1]")])
    seen: list[AgentEvent] = []

    answer = await _respond(model, backend=PerQueryBackend(), emit=_record(seen))

    assert [e.message for e in seen if e.type == "said"] == ["x first.[2]"]
    assert answer.parts == ["x first.[1]", "Then y.[2]"]
    assert answer.text == "x first.[1]\n\nThen y.[2]"
    assert [s.url for s in answer.sources] == ["http://x", "http://y"]


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
    running = [Running(id=7, kind="deep", title="Aviation weather", stage="working")]
    await _respond(busy, steer_deep_research=_never_steer, running=running)
    checking = ScriptedModel([says("hi")])
    fact_check = [Running(id=8, kind="factcheck", title="Paper", stage="queued")]
    await _respond(checking, steer_deep_research=_never_steer, running=fact_check)

    assert "steer_deep_research" not in idle.bound_tools[0]
    assert "steer_deep_research" in busy.bound_tools[0]
    assert "steer_deep_research" not in checking.bound_tools[0]
    assert _system_prompt("m", [], [], running=[]) == _system_prompt("m", [], [])
    prompt = _system_prompt("m", [], [], running=running + fact_check)
    assert "deep research, id 7: Aviation weather (working)" in prompt
    assert "fact check, id 8: Paper (queued)" in prompt


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
        running=[Running(id=7, kind="deep", title="Aviation weather", stage="working")],
        mode="deep",
    )

    assert steered == [(7, "Assume EASA, not FAA.")]
    # Steering counts as acting in deep mode: no "you started nothing" check.
    assert len(model.seen) == 2
    assert answer.text.startswith("Done")
