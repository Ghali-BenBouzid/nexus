"""The check on a reply claiming a background run nobody started: a small model
reads the reply, and only a real claim sends it back."""

import pytest

from app.agents import supervisor
from app.agents.claim_check import claim_judge
from app.agents.model import PacedChatOpenAI
from app.agents.sources import Sources
from app.agents.supervisor import Running, respond
from app.core.config import settings
from tests.agents.fakes import ScriptedModel, call, says
from tests.agents.test_supervisor import FakeBackend


def _judge(monkeypatch, *verdicts: str) -> ScriptedModel:
    judge = ScriptedModel([says(v) for v in verdicts])
    monkeypatch.setattr(supervisor, "claim_judge", lambda model: judge)
    return judge


async def _deep(model, running=None) -> str:
    async def start(question: str, title: str, brief: str) -> str:
        return "Deep research has started."

    answer = await respond(
        "a message",
        [],
        model=model,
        backend=FakeBackend(),
        sources=Sources(),
        start_deep_research=start,
        mode="deep",
        running=running,
    )
    return answer.text


async def test_a_reply_that_claims_nothing_goes_out_as_written(monkeypatch) -> None:
    judge = _judge(monkeypatch, "no")
    model = ScriptedModel([says("Hi! What should the report be for?")])

    assert await _deep(model) == "Hi! What should the report be for?"
    assert len(model.seen) == 1  # no second call to the main model
    assert len(judge.seen) == 1


async def test_a_claimed_run_is_sent_back_once(monkeypatch) -> None:
    judge = _judge(monkeypatch, "yes", "yes")
    model = ScriptedModel(
        [says("Your deep run is now underway."), says("I have not started it yet.")]
    )

    assert await _deep(model) == "I have not started it yet."
    assert "none was started in this turn" in str(model.seen[1][-1].content)
    assert len(judge.seen) == 1  # once a turn, never a loop


async def test_the_judge_is_told_what_is_already_running(monkeypatch) -> None:
    judge = _judge(monkeypatch, "no")
    running = [Running(id=7, kind="deep", title="Aviation weather", stage="working")]

    await _deep(ScriptedModel([says("Still going.")]), running=running)

    assert "- Aviation weather" in str(judge.seen[0][-1].content)


async def test_a_started_run_is_not_judged(monkeypatch) -> None:
    judge = _judge(monkeypatch, "yes")
    model = ScriptedModel(
        [
            call("deep_research", question="X", title="X", brief={"goal": "learn X"}),
            says("Deep research on X has started."),
        ]
    )

    assert await _deep(model) == "Deep research on X has started."
    assert judge.seen == []


async def test_a_broken_judge_lets_the_reply_through(monkeypatch) -> None:
    class Broken(ScriptedModel):
        async def _agenerate(self, *args, **kwargs):
            raise RuntimeError("provider down")

    monkeypatch.setattr(supervisor, "claim_judge", lambda model: Broken())
    model = ScriptedModel([says("Your deep run is now underway.")])

    assert await _deep(model) == "Your deep run is now underway."
    assert len(model.seen) == 1


@pytest.mark.parametrize("name", ["", None])
def test_the_check_is_off_without_a_small_model(monkeypatch, name) -> None:
    monkeypatch.setattr(settings, "claim_check_model", name)
    model = PacedChatOpenAI(model="x", api_key="k")

    assert claim_judge(model) is None


def test_the_judge_is_a_small_copy_of_the_turns_model() -> None:
    judge = claim_judge(PacedChatOpenAI(model="big/model", api_key="k"))

    assert judge is not None
    assert judge.model_name == settings.claim_check_model
    assert claim_judge(ScriptedModel()) is None
