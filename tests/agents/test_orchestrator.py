import pytest
from langchain_core.outputs import ChatGeneration, ChatResult
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
from app.agents.schemas import AgentEvent
from tests.agents.fakes import ScriptedModel, call, says


class FakeBackend:
    async def search(self, query: str, max_results: int) -> list:
        return []

    async def extract(self, url: str) -> str:
        return ""


class RoleModel(ScriptedModel):
    """One model standing in for every agent, dispatching on the tools each was
    given rather than on prompt wording, which changes as prompts improve. A
    single scripted queue could not do this: researchers run concurrently."""

    sub_questions: list[str] = []
    fail: set[str] = set()
    decision: dict | None = None  # the supervisor's move, on a conversation turn
    planner_prompts: list[str] = []
    writer_prompts: list[str] = []

    def __init__(self, sub_questions=None, fail=None, decision=None, **kwargs):
        super().__init__(**kwargs)
        self.sub_questions = list(sub_questions or [])
        self.fail = set(fail or ())
        self.decision = decision
        self.planner_prompts = []
        self.writer_prompts = []

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        names = {
            tool.get("function", {}).get("name") or tool.get("name", "")
            for tool in (kwargs.get("tools") or [])
        }
        last = messages[-1].content or ""
        if "Decision" in names:
            reply = call("Decision", **(self.decision or {"action": "research"}))
        elif "SubmitPlanArgs" in names:
            self.planner_prompts.append(last)
            reply = call("SubmitPlanArgs", sub_questions=self.sub_questions)
        elif "SubmitFindingArgs" in names:
            if last in self.fail:
                raise RuntimeError(f"researcher boom: {last}")
            reply = call(
                "SubmitFindingArgs",
                claims=[{"text": f"answer to {last}", "cited_source_ids": []}],
                found_info=True,
            )
        else:
            self.writer_prompts.append(last)
            reply = says("FINAL REPORT")
        return ChatResult(generations=[ChatGeneration(message=reply)])


def _graph():
    return compile_graph(InMemorySaver(serde=SERDE))


async def _one_shot(model: RoleModel, **deps) -> dict:
    """A one-shot run: plan, research, write."""
    return await _graph().ainvoke(
        {"prompt": "big question", "auto_approve": True},
        run_config(1),
        context=Deps(model=model, backend=FakeBackend(), **deps),
    )


async def test_run_full_pipeline() -> None:
    state = await _one_shot(RoleModel(sub_questions=["q1", "q2"]))

    assert state["report"].content == "FINAL REPORT"
    assert state["report"].failed_subquestions == []
    # the structured artifact carries one point per answered sub-question
    assert [p.sub_question for p in state["result"].points] == ["q1", "q2"]
    assert state["result"].gaps == []


async def test_run_degrades_on_partial_failure() -> None:
    state = await _one_shot(RoleModel(sub_questions=["q1", "q2"], fail={"q2"}))

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
        RoleModel(sub_questions=["q1", "q2"]), emit=emit, research_budget=0.0
    )

    assert state["report"].content == "FINAL REPORT"
    forced = [e.message for e in events if e.type == "researcher_forced"]
    assert forced == ["Time budget reached", "Time budget reached"]


async def test_run_raises_when_all_researchers_fail() -> None:
    with pytest.raises(OrchestratorError):
        await _one_shot(RoleModel(sub_questions=["q1", "q2"], fail={"q1", "q2"}))


async def test_run_emits_indexed_researcher_lifecycle() -> None:
    # The live feed needs per-researcher index/total to render "researcher k/N".
    events: list[AgentEvent] = []

    async def collect(event: AgentEvent) -> None:
        events.append(event)

    await _one_shot(RoleModel(sub_questions=["q1", "q2"], fail={"q2"}), emit=collect)

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
        await _one_shot(RoleModel(sub_questions=["q1"]), should_cancel=lambda: True)


# --- a conversation turn ----------------------------------------------------

_RESEARCH = {"action": "research", "query": "rq", "title": "T"}


def _turn(prior: list | None = None) -> dict:
    return {"message": "tell me", "history": [], "prior": prior or []}


async def test_a_turn_pauses_on_the_plan_until_the_user_confirms() -> None:
    graph = _graph()
    model = RoleModel(sub_questions=["q1"], decision=_RESEARCH)
    deps = Deps(model=model, backend=FakeBackend())

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
    assert "go deeper" in model.planner_prompts[-1]

    # a confirm, in a later run (a later job), researches and writes
    done = await graph.ainvoke(
        Command(resume=Review(approved=True, feedback="")), run_config(1), context=deps
    )
    assert "__interrupt__" not in done
    assert done["report"].content == "FINAL REPORT"


async def test_a_turn_the_supervisor_answers_ends_without_research() -> None:
    answer = {"action": "answer", "reply": "From the report."}
    model = RoleModel(sub_questions=["q1"], decision=answer)

    state = await _graph().ainvoke(
        _turn(), run_config(1), context=Deps(model=model, backend=FakeBackend())
    )

    assert state["route"] == "answer"
    assert state["reply"] == "From the report."
    assert "plan" not in state and model.planner_prompts == []


async def test_compose_merges_earlier_reports_without_new_research() -> None:
    compose = {
        "action": "compose_report",
        **{"instructions": "merge them", "title": "Both"},
    }
    model = RoleModel(sub_questions=["q1"], decision=compose)
    earlier = {
        "points": [{"sub_question": "old q", "claims": [{"text": "a fact"}]}],
        "sources": [],
        "gaps": [],
    }

    state = await _graph().ainvoke(
        _turn([{"prompt": "old", "report": "OLD", "result": earlier}]),
        run_config(1),
        context=Deps(model=model, backend=FakeBackend()),
    )

    assert state["report"].content == "FINAL REPORT"
    assert model.planner_prompts == []  # no plan, no research
    assert "a fact" in model.writer_prompts[0]
    assert "merge them" in model.writer_prompts[0]


async def test_compose_with_no_earlier_report_researches_instead() -> None:
    compose = {"action": "compose_report", **{"instructions": "x"}}
    model = RoleModel(sub_questions=["q1"], decision=compose)

    state = await _graph().ainvoke(
        _turn(), run_config(1), context=Deps(model=model, backend=FakeBackend())
    )

    assert state["route"] == "research"
    assert "__interrupt__" in state  # it planned and waits for the user
