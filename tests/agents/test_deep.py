"""The deep run's loop: a lead that reads what came back and decides again."""

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver

from app.agents import deep
from app.core.config import settings
from tests.agents.fakes import ScriptedModel, call, says
from tests.research.test_research import FakeBackend


def _finding(messages: list[BaseMessage]) -> AIMessage:
    question = str(messages[-1].content)
    return call(
        "SubmitFindingArgs",
        claims=[{"text": f"about {question}", "cited_source_ids": []}],
        found_info=True,
    )


async def _run(lead, *, cap: int = 12, notes=None) -> tuple[dict, ScriptedModel]:
    """Run a whole deep graph with ``lead`` deciding each turn: it gets the
    lead's conversation and returns its reply."""

    def respond(messages: list[BaseMessage], tools: list[str]) -> AIMessage:
        if "WriteReportArgs" in tools:  # the lead, offered both or only this
            return lead(messages)
        if "SubmitFindingArgs" in tools:
            return _finding(messages)
        return says("THE REPORT")

    model = ScriptedModel(respond=respond)
    graph = deep.compile_graph(InMemorySaver(serde=deep.SERDE))
    limits = deep.Limits.deep()
    limits.cap = cap
    final = await graph.ainvoke(
        {"question": "everything about X"},
        {"configurable": {"thread_id": "t"}},
        context=deep.Deps(
            model=model,
            backend=FakeBackend(),
            limits=limits,
            **({"notes": notes} if notes else {}),
        ),
    )
    return final, model


def _rounds(messages: list[BaseMessage]) -> int:
    return sum(isinstance(m, ToolMessage) for m in messages)


async def test_the_lead_goes_back_for_what_the_first_round_left_open() -> None:
    def lead(messages):
        if _rounds(messages) == 0:
            return call(
                "DispatchResearchersArgs", reasoning="wide", sub_questions=["a", "b"]
            )
        if _rounds(messages) == 1:
            # It reads the first round before choosing the second.
            assert "about a" in str(messages[-1].content)
            return call(
                "DispatchResearchersArgs",
                reasoning="a and b disagree",
                sub_questions=["why a and b disagree"],
            )
        return call("WriteReportArgs", reasoning="covered", outline="a, then b")

    final, model = await _run(lead)

    indexes = [o["index"] for o in final["findings"]]
    assert sorted(indexes) == [1, 2, 3]  # three researchers, never the same row
    assert [len(r["sub_questions"]) for r in final["rounds"]] == [2, 1]
    assert final["report"].content == "THE REPORT"
    claims = [c.text for p in final["result"].points for c in p.claims]
    assert "about why a and b disagree" in claims  # the second round is reported
    writer = model.seen[-1]
    assert "a, then b" in str(writer[-1].content)  # the outline shapes the report


async def test_a_lead_that_never_stops_is_stopped_and_still_reports(
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "deep_max_rounds", 3)

    def lead(messages):
        if "This is your last step" in str(messages[-1].content):
            return call("WriteReportArgs", reasoning="out", outline="short, 3 parts")
        return call(
            "DispatchResearchersArgs",
            reasoning="more",
            sub_questions=[f"q{_rounds(messages)}"],
        )

    final, model = await _run(lead)

    assert len(final["rounds"]) == 3
    assert final["report"].content == "THE REPORT"
    # Out of budget, the lead is told it is its last step and can only write,
    # so the report still follows its outline.
    assert model.bound_tools[-2] == ["WriteReportArgs"]
    assert "short, 3 parts" in str(model.seen[-1][-1].content)


async def test_the_lead_cannot_report_before_anything_was_researched() -> None:
    def lead(messages):
        if isinstance(messages[-1], ToolMessage) and "Nothing has been" in str(
            messages[-1].content
        ):
            return call("DispatchResearchersArgs", reasoning="ok", sub_questions=["a"])
        if _rounds(messages) == 0:
            return call("WriteReportArgs", reasoning="I know this", outline="")
        return call("WriteReportArgs", reasoning="covered", outline="")

    final, _ = await _run(lead)

    assert [r["sub_questions"] for r in final["rounds"]] == [["a"]]


async def test_an_oversized_round_is_sent_back_then_clamped() -> None:
    def lead(messages):
        if _rounds(messages) == 0:
            return call(
                "DispatchResearchersArgs",
                reasoning="everything",
                sub_questions=["a", "b", "c"],
            )
        return call("WriteReportArgs", reasoning="covered", outline="")

    final, model = await _run(lead, cap=2)

    assert final["rounds"][0]["sub_questions"] == ["a", "b"]
    refusals = [
        m
        for m in model.seen[2]
        if isinstance(m, ToolMessage) and "exceeds the limit" in str(m.content)
    ]
    assert refusals  # it was asked to choose before anything was cut


# --- steering: what the user says to a run while it works -------------------


def _notes_from(read: int, notes: list[str]):
    """A note reader that returns nothing until its ``read``-th call, as if the
    user wrote in at that moment. The lead reads twice a turn (before it
    decides, and after, to catch a note that landed meanwhile) and the writer
    once, so read 3 is the start of the lead's second turn and read 5 the
    writer, when the lead took two turns."""
    reads = [0]

    async def reader() -> list[str]:
        reads[0] += 1
        return notes if reads[0] >= read else []

    return reader


async def test_a_note_sent_while_running_reaches_the_lead_before_its_next_step() -> (
    None
):
    seen_by_lead: list[list[str]] = []

    def lead(messages):
        seen_by_lead.append([str(m.content) for m in messages])
        if _rounds(messages) == 0:
            return call("DispatchResearchersArgs", reasoning="faa", sub_questions=["a"])
        if _rounds(messages) == 1:
            return call(
                "DispatchResearchersArgs", reasoning="easa", sub_questions=["b"]
            )
        return call("WriteReportArgs", reasoning="done", outline="short")

    # The note turns up after the first round went out.
    final, _ = await _run(lead, notes=_notes_from(3, ["Assume EASA, not FAA."]))

    first, second, third = seen_by_lead
    assert not any("Assume EASA" in m for m in first)
    # Read before the second decision, after the first round's findings.
    assert "Assume EASA, not FAA." in second[-1]
    assert "overrides anything it contradicts" in second[-1]
    assert [r["notes_seen"] for r in final["rounds"]] == [0, 1]
    # On the next turn it is replayed where it arrived: between round one's
    # findings and round two's dispatch, once, not again at the end.
    note_at = next(i for i, m in enumerate(third) if "Assume EASA" in m)
    assert "about a" in third[note_at - 1]
    assert sum("Assume EASA" in m for m in third) == 1


async def test_a_note_sent_after_the_research_reaches_the_writer() -> None:
    def lead(messages):
        if _rounds(messages) == 0:
            return call("DispatchResearchersArgs", reasoning="go", sub_questions=["a"])
        return call("WriteReportArgs", reasoning="done", outline="short")

    # Nothing until the lead has already decided to write.
    final, model = await _run(lead, notes=_notes_from(5, ["Keep it to one page."]))

    writer = str(model.seen[-1][-1].content)
    assert "Keep it to one page." in writer
    assert "after the research was done" in writer
    assert final["notes_seen"] == 0


def test_without_notes_the_lead_reads_what_it_always_did() -> None:
    """Steering is additive: a run nobody writes to gives the lead exactly the
    conversation it had before steering existed."""
    rounds = [deep.Round(reasoning="r", sub_questions=["a"], deadline=0.0)]
    findings = [deep.Outcome(index=1, round=1, sub_question="a", finding=None)]
    left = deep.Left(rounds=1, researchers=1, seconds=600)

    before = deep._conversation("q", rounds, findings, cap=3, left=left)
    after = deep._conversation("q", rounds, findings, cap=3, left=left, notes=[])

    assert [m.content for m in before] == [m.content for m in after]


async def test_a_note_sent_while_the_lead_decides_is_not_a_round_late() -> None:
    """Live, a correction sent seconds after the run started arrived while the
    lead was choosing its first round, and that round went on the old
    assumption. The lead now decides again before anything goes out."""
    reads = [0]

    async def notes() -> list[str]:
        reads[0] += 1
        return [] if reads[0] == 1 else ["Assume EASA, not FAA."]

    def lead(messages):
        said = " ".join(str(m.content) for m in messages)
        if _rounds(messages) == 0:
            topic = "easa" if "Assume EASA" in said else "faa"
            return call(
                "DispatchResearchersArgs", reasoning=topic, sub_questions=[topic]
            )
        return call("WriteReportArgs", reasoning="done", outline="short")

    final, _ = await _run(lead, notes=notes)

    assert [r["sub_questions"] for r in final["rounds"]] == [["easa"]]
    assert final["rounds"][0]["notes_seen"] == 1
