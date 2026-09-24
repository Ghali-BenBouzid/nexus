"""The two runs that outlive the turn that started them.

Deep research and a fact check are not answers: they are work the supervisor
kicks off and reports back on later. What these pin is that the turn does not
wait for them, that each becomes an artifact of its own with its own live feed,
that an account with nothing left to spend cannot start one, and that the
composer's mode never starts one behind the supervisor's back.
"""

import asyncio
import re

import pytest
import pytest_asyncio
from httpx import AsyncClient
from langchain_core.messages import ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from app import jobs
from app.agents import supervisor
from app.agents.tools import SearchHit
from app.core.config import settings
from app.documents import storage
from app.research import service as research_service
from app.research.dependencies import get_model, get_search_backend
from main import app
from tests.accounts import login_as
from tests.agents.fakes import ScriptedModel, call, says
from tests.documents.test_parser import _pdf
from tests.research.test_research import FakeBackend, _use_fake_pipeline


async def drain() -> None:
    """Wait for the background runs the turn started. On Redis these are queued
    for a worker; inline they are tasks, and a test has to let them finish."""
    for _ in range(50):
        pending = [task for task in jobs._spawned if not task.done()]
        if not pending:
            await asyncio.sleep(0)
            return
        results = await asyncio.gather(*pending, return_exceptions=True)
        for result in results:
            if isinstance(result, BaseException):
                raise result


class _StartsDeepResearch(ScriptedModel):
    """A supervisor that starts a deep run, plus the agents of the run itself."""

    started: bool = False
    cost_usd: float = 0.0
    claims_each: int = 1

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        names = {
            tool.get("function", {}).get("name") or tool.get("name", "")
            for tool in (kwargs.get("tools") or [])
        }
        if "DispatchResearchersArgs" in names:
            # The lead: one round, then satisfied once its findings are back.
            if any(isinstance(m, ToolMessage) for m in messages):
                reply = call("WriteReportArgs", reasoning="covered", outline="")
            else:
                reply = call(
                    "DispatchResearchersArgs",
                    reasoning="start wide",
                    sub_questions=["q1", "q2"],
                )
        elif "SubmitSelectionArgs" in names:
            # One call over every researcher's claims at once, numbered straight
            # through: 1-3 came from the first, 4-6 from the second.
            reply = call("SubmitSelectionArgs", keep=[1, 4])
        elif "SubmitFindingArgs" in names:
            reply = call(
                "SubmitFindingArgs",
                claims=[
                    {"text": f"a deep finding {n}", "cited_source_ids": []}
                    for n in range(self.claims_each)
                ],
                found_info=True,
            )
        elif "deep_research" in names and not self.started:
            self.started = True
            reply = call(
                "deep_research",
                question="everything about X",
                title="All of X",
                goal="to decide whether X is worth learning",
            )
        elif "deep_research" in names:
            reply = says("I have started a deep run; it will appear in Outputs.")
        else:
            reply = says("THE DEEP REPORT")
        if self.cost_usd:
            reply.usage_metadata = {
                "input_tokens": 1,
                "output_tokens": 1,
                "total_tokens": 2,
            }
            reply.response_metadata = {
                "token_usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "cost": self.cost_usd,
                },
                "model_name": "fake/model",
            }
        return ChatResult(generations=[ChatGeneration(message=reply)])


def _judged(monkeypatch, verdict: str) -> ScriptedModel:
    """The small model that reads a reply for a claimed run, giving ``verdict``.
    The real one is a copy of the turn's model, which a fake cannot make."""
    judge = ScriptedModel(respond=lambda messages, tools: says(verdict))
    monkeypatch.setattr(supervisor, "claim_judge", lambda model: judge)
    return judge


def _use(model_factory, backend_factory=FakeBackend, monkeypatch=None) -> None:
    """The fakes for a turn, and for the background runs it starts.

    A background run takes only ids through the queue and builds its own model,
    which is right on a worker and is why the request's override does not reach
    it. Inline, that build is what the tests have to stand in for.
    """
    app.dependency_overrides[get_model] = model_factory
    app.dependency_overrides[get_search_backend] = backend_factory
    if monkeypatch is not None:
        monkeypatch.setattr(research_service, "get_model", model_factory)
        monkeypatch.setattr(research_service, "get_search_backend", backend_factory)


async def test_a_deep_run_becomes_its_own_artifact(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch
) -> None:
    _use(lambda: _StartsDeepResearch(), monkeypatch=monkeypatch)

    created = await client.post(
        "/conversations",
        headers=auth_headers,
        json={"prompt": "go deep on X", "mode": "deep"},
    )
    conversation_id = created.json()["id"]

    # the turn itself answered without waiting for the run
    detail = await client.get(f"/conversations/{conversation_id}", headers=auth_headers)
    turn = detail.json()["messages"][1]["query"]
    assert turn["status"] == "complete"
    assert "Outputs" in turn["reply"]

    await drain()

    artifacts = await client.get("/research/artifacts", headers=auth_headers)
    assert artifacts.status_code == 200
    [artifact] = artifacts.json()
    assert artifact["kind"] == "deep_research"
    assert artifact["title"] == "All of X"
    # the lead reads what the run is for, so it knows how deep to go
    assert artifact["prompt"].endswith(
        "What it is for: to decide whether X is worth learning"
    )
    assert artifact["conversation_id"] == conversation_id
    assert artifact["status"] == "complete"

    # it is a run like any other: its report and its live feed are readable
    report = await client.get(f"/research/query/{artifact['id']}", headers=auth_headers)
    assert report.json()["report"] == "THE DEEP REPORT"
    events = await client.get(
        f"/research/query/{artifact['id']}/events", headers=auth_headers
    )
    assert "researcher_done" in [e["type"] for e in events.json()]

    # and the conversation that started it lists it
    after = await client.get(f"/conversations/{conversation_id}", headers=auth_headers)
    assert [a["title"] for a in after.json()["artifacts"]] == ["All of X"]


async def test_a_deep_report_is_written_from_curated_findings(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch
) -> None:
    """Researchers never see each other's work, so a deep run chooses what the
    report is built from before it writes a word. Under the cap there is nothing
    to choose, so the cap is lowered here to put the step in the way."""
    monkeypatch.setattr(settings, "deep_claim_cap", 1)
    _use(lambda: _StartsDeepResearch(claims_each=3), monkeypatch=monkeypatch)

    created = await client.post(
        "/conversations",
        headers=auth_headers,
        json={"prompt": "go deep on X", "mode": "deep"},
    )
    await drain()

    artifacts = await client.get("/research/artifacts", headers=auth_headers)
    [artifact] = artifacts.json()
    events = await client.get(
        f"/research/query/{artifact['id']}/events", headers=auth_headers
    )
    curated = [e for e in events.json() if e["type"] == "curated"]
    assert curated, "the run wrote its report without choosing what went into it"
    # Two researchers, three claims each, curated in one pass over all six.
    assert curated[0]["data"] == {"kept": 2, "total": 6}
    assert created.status_code == 201


async def test_a_run_is_not_started_with_nothing_left_to_spend(
    client: AsyncClient, monkeypatch
) -> None:
    # The budget is checked when the message arrives, but a turn can spend the
    # rest of it before it gets to the tool. A run nobody can pay for must not be
    # queued at all: the first call here costs more than the account has left.
    headers = await login_as(client, "nearly-broke", budget_usd=0.005)
    _use(lambda: _StartsDeepResearch(cost_usd=0.01), monkeypatch=monkeypatch)

    await client.post(
        "/conversations", headers=headers, json={"prompt": "go deep", "mode": "deep"}
    )
    await drain()

    assert (await client.get("/research/artifacts", headers=headers)).json() == []


class _FactChecker(ScriptedModel):
    """A fact checker that lists its claim, confirms it after the review,
    searches once, then writes its verdict."""

    step: int = 0

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        claims = [{"claim": "it is true", "passage": "it is true"}]
        self.step += 1
        if self.step <= 2:
            reply = call(
                "submit_claims", claims=claims, left_out=[], confirmed=self.step == 2
            )
        elif self.step == 3:
            reply = call("web_search", query="is it true", max_results=5)
        else:
            reply = says("## The claim\n\n**Contradicted**. The sources disagree.[1]")
        return ChatResult(generations=[ChatGeneration(message=reply)])


class _SourceBackend(FakeBackend):
    async def search(self, query: str, max_results: int) -> list[SearchHit]:
        return [SearchHit(title="A source", url="https://s.example", content="no")]


class _ChecksInThread(_FactChecker):
    """A supervisor that starts a fact check on the attached file, plus the
    fact checker it starts. The supervisor is the one offered fact_check."""

    started: bool = False

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        names = {
            tool.get("function", {}).get("name") or tool.get("name", "")
            for tool in (kwargs.get("tools") or [])
        }
        if "fact_check" not in names:
            return super()._generate(messages, stop, run_manager, **kwargs)
        if not self.started:
            self.started = True
            document_id = int(
                re.search(r"id (\d+)", str(messages[0].content)).group(1)  # type: ignore[union-attr]
            )
            reply = call(
                "fact_check",
                document_id=document_id,
                title="Vérification : le rapport",
                focus="the numbers",
            )
        else:
            reply = says("I have started a fact check; it will appear in Outputs.")
        return ChatResult(generations=[ChatGeneration(message=reply)])


async def test_fact_check_mode_is_the_supervisors_to_answer(
    client: AsyncClient, auth_headers: dict[str, str], document, monkeypatch
) -> None:
    """Fact check mode used to skip the thread: the browser started the check
    itself and wrote a canned line where the answer goes. The supervisor now
    holds the thread in every mode, so it is the one that starts the check and
    says so."""
    _use(lambda: _ChecksInThread(), _SourceBackend, monkeypatch=monkeypatch)

    sent = await client.post(
        f"/conversations/{document['conversation_id']}/messages",
        headers=auth_headers,
        json={"content": "check the numbers", "mode": "factcheck"},
    )
    assert sent.status_code == 200, sent.text
    await drain()

    detail = await client.get(
        f"/conversations/{document['conversation_id']}", headers=auth_headers
    )
    reply = detail.json()["messages"][-1]["query"]["reply"]
    assert reply.startswith("I have started a fact check")
    [artifact] = (await client.get("/research/artifacts", headers=auth_headers)).json()
    assert artifact["kind"] == "fact_check"
    assert artifact["title"] == "Vérification : le rapport"  # the supervisor's words
    body = (
        await client.get(f"/research/query/{artifact['id']}", headers=auth_headers)
    ).json()
    assert body["status"] == "complete"
    assert "Contradicted" in body["report"]
    # the sources it cited are the ones it really retrieved
    assert [s["url"] for s in body["sources"]] == ["https://s.example"]


@pytest.fixture
def _bucket(monkeypatch):
    files: dict[str, bytes] = {}

    async def put(key: str, data: bytes, media_type: str) -> None:
        files[key] = data

    async def delete(key: str) -> None:
        files.pop(key, None)

    monkeypatch.setattr(storage, "available", lambda: True)
    monkeypatch.setattr(storage, "put", put)
    monkeypatch.setattr(storage, "delete", delete)
    return files


@pytest_asyncio.fixture
async def document(client: AsyncClient, auth_headers: dict[str, str], _bucket) -> dict:
    """A conversation with one uploaded PDF in it."""
    _use_fake_pipeline(sub_questions=["q1"])
    conversation = await client.post(
        "/conversations", headers=auth_headers, json={"prompt": "hello"}
    )
    uploaded = await client.post(
        f"/conversations/{conversation.json()['id']}/documents",
        files={"file": ("claims.pdf", _pdf(pages=1), "application/pdf")},
        headers=auth_headers,
    )
    assert uploaded.status_code == 201, uploaded.text
    return {**uploaded.json(), "conversation_id": conversation.json()["id"]}


class _JustGreets(ScriptedModel):
    """A supervisor that answers and never reaches for a tool: what a greeting
    gets. Records which tools it was offered, so a test can tell that deep
    research was available and simply not used."""

    offered: set[str] = set()

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.offered = {
            tool.get("function", {}).get("name") or tool.get("name", "")
            for tool in (kwargs.get("tools") or [])
        }
        return ChatResult(
            generations=[ChatGeneration(message=says("Hi. What should I research?"))]
        )


async def test_deep_mode_lets_the_supervisor_start_the_run(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch
) -> None:
    """In deep mode the supervisor still holds the thread. It is the one that
    starts the run, and the thread gets its words rather than a fixed line."""
    _use(lambda: _StartsDeepResearch(), monkeypatch=monkeypatch)

    created = await client.post(
        "/conversations",
        headers=auth_headers,
        json={"prompt": "go deep on X", "mode": "deep"},
    )
    conversation_id = created.json()["id"]
    await drain()

    [artifact] = (await client.get("/research/artifacts", headers=auth_headers)).json()
    assert artifact["kind"] == "deep_research"
    assert artifact["conversation_id"] == conversation_id

    detail = await client.get(f"/conversations/{conversation_id}", headers=auth_headers)
    turn = detail.json()["messages"][1]["query"]
    # A real turn, with a query behind it, answered by the supervisor.
    assert turn is not None
    assert "Outputs" in turn["reply"]


async def test_a_greeting_in_deep_mode_starts_nothing(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch
) -> None:
    """The bug this replaces: with the mode on, "hi" started a ten-minute run,
    and so did "don't start a deep research". The mode now informs a decision
    instead of making it, so a message that is not a subject gets an answer and
    no run at all."""
    model = _JustGreets()
    _use(lambda: model, monkeypatch=monkeypatch)
    _judged(monkeypatch, "no")

    created = await client.post(
        "/conversations", headers=auth_headers, json={"prompt": "hi", "mode": "deep"}
    )
    await drain()

    # The tool was there to use, and the supervisor chose not to.
    assert "deep_research" in model.offered
    assert (await client.get("/research/artifacts", headers=auth_headers)).json() == []
    detail = await client.get(
        f"/conversations/{created.json()['id']}", headers=auth_headers
    )
    assert detail.json()["messages"][1]["query"]["reply"].startswith("Hi.")


class _ClaimsARunItNeverStarted(_StartsDeepResearch):
    """A supervisor that says a deep run is underway without calling the tool,
    as the live model did, and calls it once told no run exists."""

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        told = any("was not called" in str(m.content) for m in messages)
        names = {
            tool.get("function", {}).get("name") or tool.get("name", "")
            for tool in (kwargs.get("tools") or [])
        }
        if "deep_research" in names and not told and not self.started:
            reply = says("A deep research run on this is now underway.")
            return ChatResult(generations=[ChatGeneration(message=reply)])
        return super()._generate(messages, stop, run_manager, **kwargs)


async def test_a_run_announced_but_never_started_is_caught(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch
) -> None:
    """Told in its prompt that a run exists only once its tool has started it,
    the supervisor still announced runs it never started. Ending a deep-mode
    turn without a run now sends the reply back once, with that fact."""
    _use(lambda: _ClaimsARunItNeverStarted(), monkeypatch=monkeypatch)
    judge = _judged(monkeypatch, "yes")

    await client.post(
        "/conversations",
        headers=auth_headers,
        json={"prompt": "go deep on X", "mode": "deep"},
    )
    await drain()

    [artifact] = (await client.get("/research/artifacts", headers=auth_headers)).json()
    assert artifact["kind"] == "deep_research"
    assert "now underway" in str(judge.seen[0][-1].content)


def test_the_mode_is_told_to_the_supervisor_and_nothing_else_is() -> None:
    """The mode reaches the agent as context, beside the attachments, and only
    when it is on: an ordinary turn must read exactly as it did before."""
    from app.agents.supervisor import _system_prompt

    deep = _system_prompt("anything", [], [], mode="deep")
    check = _system_prompt("anything", [], [], mode="factcheck")
    off = _system_prompt("anything", [], [])

    assert "<mode>" in deep and "deep research mode" in deep
    assert "<mode>" in check and "fact check mode" in check
    assert "<mode>" not in off


class _LeadWaits(_StartsDeepResearch):
    """A deep run whose lead does not decide until ``go`` is set, so the run is
    still working when the test stops it. Left to run, the fake finished before
    the stop arrived on a fast CI runner, and a stop after the end is a no-op."""

    go: asyncio.Event | None = None

    async def _wait_if_lead(self, kwargs) -> None:
        names = {
            tool.get("function", {}).get("name") or tool.get("name", "")
            for tool in (kwargs.get("tools") or [])
        }
        if "DispatchResearchersArgs" in names and self.go is not None:
            await self.go.wait()

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        await self._wait_if_lead(kwargs)
        return await super()._agenerate(messages, stop, run_manager, **kwargs)

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        await self._wait_if_lead(kwargs)
        async for chunk in super()._astream(messages, stop, run_manager, **kwargs):
            yield chunk


async def test_a_deep_run_from_deep_mode_is_stoppable(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch
) -> None:
    """A deep run costs minutes and money, so the user has to be able to call it
    off. It is an ordinary query however it was started, and Outputs is where
    its id is found."""
    go = asyncio.Event()
    _use(lambda: _LeadWaits(go=go), monkeypatch=monkeypatch)

    await client.post(
        "/conversations",
        headers=auth_headers,
        json={"prompt": "go deep on X", "mode": "deep"},
    )
    [artifact] = (await client.get("/research/artifacts", headers=auth_headers)).json()

    stopped = await client.post(
        f"/research/query/{artifact['id']}/cancel", headers=auth_headers
    )
    assert stopped.status_code == 204
    go.set()
    await drain()

    detail = await client.get(f"/research/query/{artifact['id']}", headers=auth_headers)
    assert detail.json()["stopped"] is True


class _Hears(ScriptedModel):
    """A supervisor that remembers the last thing the user said to it."""

    heard: str = ""

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.heard = str(messages[-1].content)
        return ChatResult(generations=[ChatGeneration(message=says("Got the file."))])


async def test_a_file_is_a_message_on_its_own(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch, _bucket
) -> None:
    """Someone who only wants a document read has nothing to type, and making
    them type a word to send it made "the message is optional" untrue."""
    model = _Hears()
    _use(lambda: model, monkeypatch=monkeypatch)
    conversation = await client.post(
        "/conversations", headers=auth_headers, json={"prompt": ""}
    )
    conversation_id = conversation.json()["id"]
    uploaded = await client.post(
        f"/conversations/{conversation_id}/documents",
        files={"file": ("claims.pdf", _pdf(pages=1), "application/pdf")},
        headers=auth_headers,
    )

    sent = await client.post(
        f"/conversations/{conversation_id}/messages",
        headers=auth_headers,
        json={"content": "", "document_ids": [uploaded.json()["id"]]},
    )
    assert sent.status_code == 200, sent.text
    await drain()

    detail = (
        await client.get(f"/conversations/{conversation_id}", headers=auth_headers)
    ).json()
    # The thread shows the file and nothing else: no invented words from the user.
    user, answer = detail["messages"]
    assert user["content"] == ""
    assert [d["filename"] for d in user["documents"]] == ["claims.pdf"]
    # The supervisor is told plainly what arrived, not handed an empty turn.
    assert "claims.pdf" in model.heard
    assert answer["query"]["reply"] == "Got the file."
    # A chat is named after what it is about.
    assert detail["title"] == "claims.pdf"


async def test_a_message_with_neither_text_nor_a_file_is_refused(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch
) -> None:
    _use(lambda: _Hears(), monkeypatch=monkeypatch)
    conversation = await client.post(
        "/conversations", headers=auth_headers, json={"prompt": ""}
    )

    sent = await client.post(
        f"/conversations/{conversation.json()['id']}/messages",
        headers=auth_headers,
        json={"content": "   "},
    )

    assert sent.status_code == 422


# --- steering a deep run that is still working -------------------------------


async def _running_deep_run(client: AsyncClient, headers: dict[str, str]):
    """A conversation with a deep run in it that is still working, as the
    thread sees it minutes after the run was started. Returns the
    conversation's public id, its row id, and the run's id."""
    import uuid

    from sqlalchemy import select

    from app.db import session as db_session
    from app.models.conversation import Conversation
    from app.models.query import QueryKind, QueryStatus
    from app.research import repository as research_repository

    _use(lambda: _JustGreets())
    created = await client.post(
        "/conversations", headers=headers, json={"prompt": "hi"}
    )
    await drain()
    public_id = created.json()["id"]
    async with db_session.SessionLocal() as db:
        conversation = (
            await db.execute(
                select(Conversation).where(
                    Conversation.public_id == uuid.UUID(public_id)
                )
            )
        ).scalar_one()
        run = await research_repository.create_pending_query(
            db,
            conversation.user_id,
            "VFR weather for a student pilot",
            "Aviation weather",
            kind=QueryKind.deep_research,
            conversation_id=conversation.id,
        )
        await research_repository.set_status(db, run.id, QueryStatus.running)
    return public_id, conversation.id, run.id


class _Steers(ScriptedModel):
    """A supervisor that passes the user's change of mind to the running run,
    and says only what the tool told it."""

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        names = {
            tool.get("function", {}).get("name") or tool.get("name", "")
            for tool in (kwargs.get("tools") or [])
        }
        done = [m for m in messages if isinstance(m, ToolMessage)]
        if "steer_deep_research" in names and not done:
            run_id = int(
                re.search(r"id (\d+): Aviation", str(messages[0].content)).group(1)
            )  # type: ignore[union-attr]
            reply = call("steer_deep_research", run_id=run_id, note="Assume EASA.")
        else:
            reply = says("Passed on: the run switches to EASA from its next step.")
        return ChatResult(generations=[ChatGeneration(message=reply)])


async def test_a_running_deep_run_is_steered_from_the_thread(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch
) -> None:
    """The user changes their mind while a deep run works. The supervisor sees
    the run, passes the change to it, and no second run is started."""
    from app.db import session as db_session
    from app.research import repository as research_repository

    public_id, _, run_id = await _running_deep_run(client, auth_headers)
    _use(lambda: _Steers(), monkeypatch=monkeypatch)

    await client.post(
        f"/conversations/{public_id}/messages",
        headers=auth_headers,
        json={"content": "actually I fly in France, not the US", "mode": "deep"},
    )
    await drain()

    async with db_session.SessionLocal() as db:
        assert await research_repository.list_notes(db, run_id) == ["Assume EASA."]
    artifacts = (await client.get("/research/artifacts", headers=auth_headers)).json()
    assert [a["id"] for a in artifacts] == [run_id]  # steered, not started again
    detail = await client.get(f"/conversations/{public_id}", headers=auth_headers)
    assert detail.json()["messages"][-1]["query"]["reply"].startswith("Passed on")


async def test_a_note_says_honestly_how_much_it_can_still_change(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    from app.agents.schemas import AgentEvent
    from app.conversations.service import STEERED_LATE, STEERED_NEXT, _steerer
    from app.db import session as db_session
    from app.models.query import QueryStatus
    from app.research import repository as research_repository

    _, conversation_id, run_id = await _running_deep_run(client, auth_headers)
    steer = _steerer(conversation_id)

    assert await steer(run_id, "Assume EASA.") == STEERED_NEXT
    assert "was empty" in await steer(run_id, "   ")
    # Another conversation's run is not this one's to change.
    assert "belongs to this conversation" in await _steerer(conversation_id + 999)(
        run_id, "x"
    )
    # Once the lead has stopped, a note only reaches the writer, and says so.
    async with db_session.SessionLocal() as db:
        await research_repository.add_event(
            db, run_id, AgentEvent(type="lead_done", message="Covered")
        )
    assert await steer(run_id, "Keep it short.") == STEERED_LATE
    # A finished run cannot be changed at all.
    async with db_session.SessionLocal() as db:
        await research_repository.set_status(db, run_id, QueryStatus.complete)
    assert "no longer running" in await steer(run_id, "Anything.")

    async with db_session.SessionLocal() as db:
        notes = await research_repository.list_notes(db, run_id)
    assert notes == ["Assume EASA.", "Keep it short."]


class _ObeysTheCheck(ScriptedModel):
    """A supervisor that greets, and starts a deep run on the question it has
    when told its reply claimed a run nothing started: what the live model did
    on a "hi" sent while a run was already going."""

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        told = any("was not called" in str(m.content) for m in messages)
        refused = [m for m in messages if isinstance(m, ToolMessage)]
        if told and not refused:
            reply = call(
                "deep_research", question="VFR weather", title="Again", goal="x"
            )
        else:
            reply = says("Hi! Your research on aviation weather is still running.")
        return ChatResult(generations=[ChatGeneration(message=reply)])


async def test_a_greeting_while_a_deep_run_works_starts_no_second_run(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch
) -> None:
    """The bug: deep mode stays on after a run starts, and a "hi" got a true
    "your run is still going", which the run check read as a claim nothing
    backed and sent back, and the supervisor started the same run again."""
    public_id, _, run_id = await _running_deep_run(client, auth_headers)
    _use(lambda: _ObeysTheCheck(), monkeypatch=monkeypatch)
    judge = _judged(monkeypatch, "no")

    await client.post(
        f"/conversations/{public_id}/messages",
        headers=auth_headers,
        json={"content": "hi", "mode": "deep"},
    )
    await drain()

    artifacts = (await client.get("/research/artifacts", headers=auth_headers)).json()
    assert [a["id"] for a in artifacts] == [run_id]
    detail = await client.get(f"/conversations/{public_id}", headers=auth_headers)
    assert detail.json()["messages"][-1]["query"]["reply"].startswith("Hi!")
    # The small model read the reply knowing the run was already going.
    assert "Aviation weather" in str(judge.seen[0][-1].content)


class _Remembers(_StartsDeepResearch):
    """Starts a deep run, and keeps the last thing it was shown."""

    last: str = ""

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.last = str(messages[-1].content)
        return super()._generate(messages, stop, run_manager, **kwargs)


async def test_only_one_deep_run_works_at_a_time_in_a_conversation(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch
) -> None:
    """Held in code, not asked of the model: a supervisor that calls the tool
    anyway is told nothing started and which run is still going."""
    public_id, _, run_id = await _running_deep_run(client, auth_headers)
    model = _Remembers()
    _use(lambda: model, monkeypatch=monkeypatch)

    await client.post(
        f"/conversations/{public_id}/messages",
        headers=auth_headers,
        json={"content": "now go deep on Y", "mode": "deep"},
    )
    await drain()

    artifacts = (await client.get("/research/artifacts", headers=auth_headers)).json()
    assert [a["id"] for a in artifacts] == [run_id]
    assert "Nothing was started" in model.last
