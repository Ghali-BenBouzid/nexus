import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.agents.orchestrator import (
    SERDE,
    Deps,
    OrchestratorCancelledError,
    OrchestratorError,
    Review,
    compile_graph,
    run_config,
)
from app.agents.provider import LLMResponse, Message, ToolCall
from app.agents.schemas import AgentEvent


class FakeBackend:
    async def search(self, query: str, max_results: int) -> list:
        return []

    async def extract(self, url: str) -> str:
        return ""


class RoleProvider:
    """A fake provider that dispatches on the system prompt, so it works under the
    concurrent fan-out (unlike a single scripted queue). ``route`` is the
    supervisor's tool call, when a test starts from a conversation turn."""

    def __init__(
        self,
        sub_questions: list[str],
        fail: set[str] | None = None,
        route: ToolCall | None = None,
    ) -> None:
        self.sub_questions = sub_questions
        self.fail = fail or set()
        self.route = route
        self.planner_prompts: list[str] = []
        self.writer_prompts: list[str] = []

    async def generate(
        self,
        messages: list[Message],
        tools: object = None,
        tool_choice: str = "auto",
    ) -> LLMResponse:
        system = messages[0].content or ""
        if "controller of a research assistant" in system:
            return LLMResponse(tool_calls=[self.route])
        if "research planner" in system:
            self.planner_prompts.append(messages[1].content or "")
            return LLMResponse(
                tool_calls=[
                    ToolCall(
                        id="p",
                        name="submit_plan",
                        args={"sub_questions": self.sub_questions},
                    )
                ]
            )
        if "research agent" in system:
            sub_question = messages[1].content or ""
            if sub_question in self.fail:
                raise RuntimeError(f"researcher boom: {sub_question}")
            return LLMResponse(
                tool_calls=[
                    ToolCall(
                        id="f",
                        name="submit_finding",
                        args={
                            "claims": [
                                {
                                    "text": f"answer to {sub_question}",
                                    "cited_source_ids": [],
                                }
                            ],
                            "found_info": True,
                        },
                    )
                ]
            )
        self.writer_prompts.append(messages[1].content or "")
        return LLMResponse(text="FINAL REPORT")


def _graph():
    return compile_graph(InMemorySaver(serde=SERDE))


async def _one_shot(provider: RoleProvider, **deps) -> dict:
    """A one-shot run: plan, research, write, with no pause for the plan."""
    return await _graph().ainvoke(
        {"prompt": "big question", "auto_approve": True},
        run_config(1),
        context=Deps(provider=provider, backend=FakeBackend(), **deps),
    )


async def test_run_full_pipeline() -> None:
    state = await _one_shot(RoleProvider(sub_questions=["q1", "q2"]))

    assert state["report"].content == "FINAL REPORT"
    assert state["report"].failed_subquestions == []
    # the structured artifact carries one point per answered sub-question
    assert [p.sub_question for p in state["result"].points] == ["q1", "q2"]
    assert state["result"].gaps == []


async def test_run_degrades_on_partial_failure() -> None:
    state = await _one_shot(RoleProvider(sub_questions=["q1", "q2"], fail={"q2"}))

    # survivor produced a report; the failed sub-question is reported as a gap
    assert state["report"].content == "FINAL REPORT"
    assert state["report"].failed_subquestions == ["q2"]
    assert [p.sub_question for p in state["result"].points] == ["q1"]


async def test_run_writes_a_report_when_the_research_budget_runs_out() -> None:
    # Past the budget, each researcher submits what it has instead of searching
    # on, so a slow model still gets a report written instead of a timeout.
    events: list[AgentEvent] = []

    async def emit(event: AgentEvent) -> None:
        events.append(event)

    state = await _one_shot(
        RoleProvider(sub_questions=["q1", "q2"]), emit=emit, research_budget=0.0
    )

    assert state["report"].content == "FINAL REPORT"
    forced = [e.message for e in events if e.type == "researcher_forced"]
    assert forced == ["Time budget reached", "Time budget reached"]


async def test_run_raises_when_all_researchers_fail() -> None:
    with pytest.raises(OrchestratorError):
        await _one_shot(RoleProvider(sub_questions=["q1", "q2"], fail={"q1", "q2"}))


async def test_run_emits_indexed_researcher_lifecycle() -> None:
    # The live feed needs per-researcher index/total to render "researcher k/N".
    events: list[AgentEvent] = []

    async def collect(event: AgentEvent) -> None:
        events.append(event)

    await _one_shot(RoleProvider(sub_questions=["q1", "q2"], fail={"q2"}), emit=collect)

    starts = {
        (e.data["index"], e.data["total"], e.data["sub_question"])
        for e in events
        if e.type == "researcher_start"
    }
    assert starts == {(1, 2, "q1"), (2, 2, "q2")}

    done = [e for e in events if e.type == "researcher_done"]
    assert [e.data["sub_question"] for e in done] == ["q1"]
    assert done[0].data["index"] == 1 and done[0].data["total"] == 2

    failed = [e for e in events if e.type == "researcher_failed"]
    assert [e.data["sub_question"] for e in failed] == ["q2"]
    assert failed[0].data["index"] == 2 and failed[0].data["total"] == 2


async def test_run_aborts_when_cancelled() -> None:
    # The stop is checked once the plan is approved, so the run stops before any
    # researcher fan-out.
    with pytest.raises(OrchestratorCancelledError):
        await _one_shot(RoleProvider(sub_questions=["q1"]), should_cancel=lambda: True)


# --- a conversation turn ----------------------------------------------------

_RESEARCH = ToolCall(id="d", name="research", args={"query": "rq", "title": "T"})


def _turn(prior: list | None = None) -> dict:
    return {"message": "tell me", "conversation": "", "prior": prior or []}


async def test_a_turn_pauses_on_the_plan_until_the_user_confirms() -> None:
    graph = _graph()
    provider = RoleProvider(sub_questions=["q1"], route=_RESEARCH)
    deps = Deps(provider=provider, backend=FakeBackend())

    paused = await graph.ainvoke(_turn(), run_config(1), context=deps)

    # the supervisor chose research, the planner ran, then the run paused
    assert paused["prompt"] == "rq" and paused["title"] == "T"
    [pending] = paused["__interrupt__"]
    assert pending.value == {"plan": ["q1"]}
    assert "report" not in paused

    # a revise re-plans with the user's feedback and pauses again
    revised = await graph.ainvoke(
        Command(resume=Review(approved=False, feedback="go deeper")),
        run_config(1),
        context=deps,
    )
    assert "__interrupt__" in revised
    assert "go deeper" in provider.planner_prompts[-1]

    # a confirm, in a later run (a later job), researches and writes
    done = await graph.ainvoke(
        Command(resume=Review(approved=True, feedback="")), run_config(1), context=deps
    )
    assert "__interrupt__" not in done
    assert done["report"].content == "FINAL REPORT"


async def test_a_turn_the_supervisor_answers_ends_without_research() -> None:
    answer = ToolCall(id="a", name="answer", args={"reply": "From the report."})
    provider = RoleProvider(sub_questions=["q1"], route=answer)

    state = await _graph().ainvoke(
        _turn(), run_config(1), context=Deps(provider=provider, backend=FakeBackend())
    )

    assert state["route"] == "answer"
    assert state["reply"] == "From the report."
    assert "plan" not in state and provider.planner_prompts == []


async def test_compose_merges_earlier_reports_without_new_research() -> None:
    compose = ToolCall(
        id="c",
        name="compose_report",
        args={"instructions": "merge them", "title": "Both"},
    )
    provider = RoleProvider(sub_questions=["q1"], route=compose)
    earlier = {
        "points": [{"sub_question": "old q", "claims": [{"text": "a fact"}]}],
        "sources": [],
        "gaps": [],
    }

    state = await _graph().ainvoke(
        _turn([{"prompt": "old", "report": "OLD", "result": earlier}]),
        run_config(1),
        context=Deps(provider=provider, backend=FakeBackend()),
    )

    assert state["report"].content == "FINAL REPORT"
    assert provider.planner_prompts == []  # no plan, no research
    assert "a fact" in provider.writer_prompts[0]
    assert "merge them" in provider.writer_prompts[0]


async def test_compose_with_no_earlier_report_researches_instead() -> None:
    compose = ToolCall(id="c", name="compose_report", args={"instructions": "x"})
    provider = RoleProvider(sub_questions=["q1"], route=compose)

    state = await _graph().ainvoke(
        _turn(), run_config(1), context=Deps(provider=provider, backend=FakeBackend())
    )

    assert state["route"] == "research"
    assert "__interrupt__" in state  # it planned and waits for the user
