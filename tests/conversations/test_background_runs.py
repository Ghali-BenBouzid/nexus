"""The two runs that outlive the turn that started them.

Deep research and a fact check are not answers: they are work the supervisor
kicks off and reports back on later. What these pin is that the turn does not
wait for them, that each becomes an artifact of its own with its own live feed,
that an account with nothing left to spend cannot start one, and that a document
can start a fact check without any conversation at all.
"""

import asyncio

import pytest
import pytest_asyncio
from httpx import AsyncClient
from langchain_core.outputs import ChatGeneration, ChatResult

from app import jobs
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
        if "SubmitPlanArgs" in names:
            reply = call("SubmitPlanArgs", sub_questions=["q1", "q2"])
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
                "deep_research", question="everything about X", title="All of X"
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
        "/conversations", headers=auth_headers, json={"prompt": "go deep on X"}
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
        "/conversations", headers=auth_headers, json={"prompt": "go deep on X"}
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

    await client.post("/conversations", headers=headers, json={"prompt": "go deep"})
    await drain()

    assert (await client.get("/research/artifacts", headers=headers)).json() == []


class _FactChecker(ScriptedModel):
    """A fact checker that searches once, then writes its verdict."""

    searched: bool = False

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        if not self.searched:
            self.searched = True
            reply = call("web_search", query="is it true", max_results=5)
        else:
            reply = says("## The claim\n\n**Contradicted**. The sources disagree.[1]")
        return ChatResult(generations=[ChatGeneration(message=reply)])


class _SourceBackend(FakeBackend):
    async def search(self, query: str, max_results: int) -> list[SearchHit]:
        return [SearchHit(title="A source", url="https://s.example", content="no")]


async def test_a_document_can_be_fact_checked_from_its_own_button(
    client: AsyncClient, auth_headers: dict[str, str], document, monkeypatch
) -> None:
    _use(lambda: _FactChecker(), _SourceBackend, monkeypatch=monkeypatch)

    started = await client.post(
        f"/documents/{document['id']}/fact-check",
        headers=auth_headers,
        json={"focus": "the numbers"},
    )

    assert started.status_code == 202
    assert started.json()["kind"] == "fact_check"
    await drain()

    report = await client.get(
        f"/research/query/{started.json()['id']}", headers=auth_headers
    )
    body = report.json()
    assert body["status"] == "complete"
    assert "Contradicted" in body["report"]
    # the sources it cited are the ones it really retrieved
    assert [s["url"] for s in body["sources"]] == ["https://s.example"]


async def test_someone_elses_document_cannot_be_fact_checked(
    client: AsyncClient, document
) -> None:
    other = await login_as(client, "not-the-owner@test.com")

    response = await client.post(
        f"/documents/{document['id']}/fact-check", headers=other
    )

    assert response.status_code == 404


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
    return uploaded.json()
