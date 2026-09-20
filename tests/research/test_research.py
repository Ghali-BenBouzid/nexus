from datetime import UTC, datetime, timedelta

import jwt
from httpx import AsyncClient
from langchain_core.outputs import ChatGeneration, ChatResult
from sqlalchemy import select

from app.agents.model import OUT_OF_CREDITS
from app.agents.provider import ProviderCreditsError
from app.agents.tools import SearchHit
from app.billing import repository as billing_repository
from app.billing.service import BUDGET_EXHAUSTED, to_micro_usd
from app.core.config import settings
from app.db import session as db_session
from app.models.usage import LLMUsage
from app.research.dependencies import get_model, get_search_backend
from main import app
from tests.accounts import login_as
from tests.agents.fakes import ScriptedModel, call, says

# --- fakes for the background pipeline (no network) -------------------------


class RoleModel(ScriptedModel):
    """Stands in for every agent, dispatching on the tools each was given."""

    sub_questions: list[str] = []
    usage: tuple[int, int] | None = None

    def __init__(self, sub_questions=None, usage=None, **kwargs):
        super().__init__(**kwargs)
        self.sub_questions = list(sub_questions or [])
        self.usage = usage

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        names = {
            tool.get("function", {}).get("name") or tool.get("name", "")
            for tool in (kwargs.get("tools") or [])
        }
        if "SubmitPlanArgs" in names:
            reply = call("SubmitPlanArgs", sub_questions=self.sub_questions)
        elif "SubmitFindingArgs" in names:
            reply = call(
                "SubmitFindingArgs",
                claims=[{"text": "an answer", "cited_source_ids": []}],
                found_info=True,
            )
        else:
            reply = says("FINAL REPORT", usage=self.usage)
        return ChatResult(generations=[ChatGeneration(message=reply)])


class FakeBackend:
    async def __aenter__(self) -> "FakeBackend":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def search(self, query: str, max_results: int) -> list:
        return []

    async def extract(self, url: str) -> str:
        return ""


def _use_fake_pipeline(sub_questions: list[str], **kwargs) -> None:
    app.dependency_overrides[get_model] = lambda: RoleModel(sub_questions, **kwargs)
    app.dependency_overrides[get_search_backend] = FakeBackend


# --- auth guards ------------------------------------------------------------


async def test_query_without_token(client: AsyncClient) -> None:
    response = await client.post("/research/query", json={"prompt": "p"})
    assert response.status_code == 401


async def test_query_invalid_token(client: AsyncClient) -> None:
    response = await client.post(
        "/research/query",
        headers={"Authorization": "Bearer invalid.garbage.token"},
        json={"prompt": "p"},
    )
    assert response.status_code == 401


async def test_query_expired_token(client: AsyncClient) -> None:
    expired = {"sub": "1", "exp": datetime.now(UTC) - timedelta(minutes=1)}
    token = jwt.encode(expired, key=settings.secret_key, algorithm=settings.algorithm)
    response = await client.post(
        "/research/query",
        headers={"Authorization": f"Bearer {token}"},
        json={"prompt": "p"},
    )
    assert response.status_code == 401


# --- lifecycle --------------------------------------------------------------


async def test_create_returns_202_pending_then_completes(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    _use_fake_pipeline(sub_questions=["q1"])

    response = await client.post(
        "/research/query", headers=auth_headers, json={"prompt": "a prompt"}
    )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "pending"
    assert body["prompt"] == "a prompt"

    # the background job runs to completion during the request cycle
    detail = await client.get(f"/research/query/{body['id']}", headers=auth_headers)
    assert detail.status_code == 200
    assert detail.json()["status"] == "complete"
    assert detail.json()["report"] == "FINAL REPORT"
    # detail reads sources/gaps/provenance from the persisted ResearchResult dump
    assert detail.json()["gaps"] == []
    assert detail.json()["sources"] == []
    assert detail.json()["consulted_sources"] == []


async def test_a_run_shows_signs_of_life(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    # The live UI needs two signals: which agent is waiting on the model (a
    # "thinking" event before every call) and whether the job is alive at all.
    _use_fake_pipeline(sub_questions=["q1", "q2"])
    created = await client.post(
        "/research/query", headers=auth_headers, json={"prompt": "a prompt"}
    )
    query_id = created.json()["id"]

    detail = await client.get(f"/research/query/{query_id}", headers=auth_headers)
    events = await client.get(
        f"/research/query/{query_id}/events", headers=auth_headers
    )

    assert detail.json()["seconds_since_heartbeat"] is not None
    thinking = [e["data"] for e in events.json() if e["type"] == "thinking"]
    assert {"agent": "planner"} in thinking
    assert {"agent": "researcher", "index": 1, "total": 2} in thinking
    assert {"agent": "researcher", "index": 2, "total": 2} in thinking
    assert {"agent": "writer"} in thinking


class _ProvenanceModel(ScriptedModel):
    """Searches once (consulting two sources) then cites only the first, so the
    consulted set is a strict superset of the cited set."""

    agent_calls: int = 0

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        names = {
            tool.get("function", {}).get("name") or tool.get("name", "")
            for tool in (kwargs.get("tools") or [])
        }
        if "SubmitPlanArgs" in names:
            reply = call("SubmitPlanArgs", sub_questions=["q1"])
        elif "SubmitFindingArgs" in names:
            self.agent_calls += 1
            reply = (
                call("web_search", query="q", max_results=5)
                if self.agent_calls == 1
                else call(
                    "SubmitFindingArgs",
                    claims=[{"text": "ans", "cited_source_ids": [1]}],
                    found_info=True,
                )
            )
        else:
            reply = says("REPORT [1]")
        return ChatResult(generations=[ChatGeneration(message=reply)])


class _ProvenanceBackend:
    async def __aenter__(self) -> "_ProvenanceBackend":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def search(self, query: str, max_results: int) -> list[SearchHit]:
        return [
            SearchHit(title="Cited", url="http://cited", content="c"),
            SearchHit(title="Extra", url="http://extra", content="e"),
        ]

    async def extract(self, url: str) -> str:
        return ""


async def test_detail_provenance_is_opt_in_and_excludes_cited(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    app.dependency_overrides[get_model] = lambda: _ProvenanceModel()
    app.dependency_overrides[get_search_backend] = _ProvenanceBackend

    created = await client.post(
        "/research/query", headers=auth_headers, json={"prompt": "p"}
    )
    query_id = created.json()["id"]

    detail = await client.get(f"/research/query/{query_id}", headers=auth_headers)
    body = detail.json()
    assert body["status"] == "complete"
    assert [s["url"] for s in body["sources"]] == ["http://cited"]
    # default: provenance is withheld
    assert body["consulted_sources"] == []

    # opt-in: provenance is the consulted set MINUS the cited set, so the cited
    # source never appears twice.
    prov = await client.get(
        f"/research/query/{query_id}?include_provenance=true", headers=auth_headers
    )
    assert [s["url"] for s in prov.json()["consulted_sources"]] == ["http://extra"]


async def test_events_endpoint_tails_the_live_feed(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    _use_fake_pipeline(sub_questions=["q1", "q2"])

    created = await client.post(
        "/research/query", headers=auth_headers, json={"prompt": "a prompt"}
    )
    query_id = created.json()["id"]

    events = await client.get(
        f"/research/query/{query_id}/events", headers=auth_headers
    )
    assert events.status_code == 200
    body = events.json()

    types = [e["type"] for e in body]
    assert "planner_start" in types
    assert "researcher_start" in types
    assert "writer_done" in types

    # the persisted events carry the structured index/total the feed renders
    starts = [e for e in body if e["type"] == "researcher_start"]
    indices = {(e["data"]["index"], e["data"]["total"]) for e in starts}
    assert indices == {(1, 2), (2, 2)}

    planner_done = next(e for e in body if e["type"] == "planner_done")
    assert planner_done["data"]["total"] == 2

    # ids are a monotonic cursor: asking for events after the last id yields none
    last_id = body[-1]["id"]
    tail = await client.get(
        f"/research/query/{query_id}/events?after={last_id}", headers=auth_headers
    )
    assert tail.json() == []


async def test_events_endpoint_hidden_from_other_users(client: AsyncClient) -> None:
    owner = await login_as(client, "owner2@test.com")
    other = await login_as(client, "other2@test.com")
    _use_fake_pipeline(sub_questions=["q1"])

    created = await client.post(
        "/research/query", headers=owner, json={"prompt": "secret"}
    )
    query_id = created.json()["id"]

    response = await client.get(f"/research/query/{query_id}/events", headers=other)
    assert response.status_code == 404


async def test_get_other_users_query_returns_404(client: AsyncClient) -> None:
    owner = await login_as(client, "owner@test.com")
    other = await login_as(client, "other@test.com")
    _use_fake_pipeline(sub_questions=["q1"])

    created = await client.post(
        "/research/query", headers=owner, json={"prompt": "secret"}
    )
    query_id = created.json()["id"]

    response = await client.get(f"/research/query/{query_id}", headers=other)
    assert response.status_code == 404


async def test_list_returns_only_callers_queries(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    _use_fake_pipeline(sub_questions=["q1"])
    await client.post("/research/query", headers=auth_headers, json={"prompt": "one"})
    await client.post("/research/query", headers=auth_headers, json={"prompt": "two"})

    response = await client.get("/research/query", headers=auth_headers)

    assert response.status_code == 200
    prompts = {q["prompt"] for q in response.json()}
    assert prompts == {"one", "two"}


async def test_cancel_endpoint_hidden_from_other_users(client: AsyncClient) -> None:
    owner = await login_as(client, "cancel-owner@test.com")
    other = await login_as(client, "cancel-other@test.com")
    _use_fake_pipeline(sub_questions=["q1"])

    created = await client.post(
        "/research/query", headers=owner, json={"prompt": "secret"}
    )
    query_id = created.json()["id"]

    response = await client.post(f"/research/query/{query_id}/cancel", headers=other)
    assert response.status_code == 404


async def test_cancel_endpoint_idempotent_on_terminal_query(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    _use_fake_pipeline(sub_questions=["q1"])
    created = await client.post(
        "/research/query", headers=auth_headers, json={"prompt": "p"}
    )
    query_id = created.json()["id"]

    # the job already completed in the request cycle, so cancel is a safe no-op
    response = await client.post(
        f"/research/query/{query_id}/cancel", headers=auth_headers
    )
    assert response.status_code == 204


# --- cost guard: per-account dollar budget ----------------------------------


async def _spend(client: AsyncClient, headers: dict[str, str], usd: float) -> None:
    """Record spend against the account, as MeteredProvider does after a call."""
    me = await client.get("/auth/me", headers=headers)
    async with db_session.SessionLocal() as db:
        await billing_repository.add_usage(
            db,
            user_id=me.json()["id"],
            query_id=None,
            model="m",
            input_tokens=1,
            output_tokens=1,
            cost_micro_usd=to_micro_usd(usd),
        )


async def test_research_is_refused_once_the_budget_is_spent(
    client: AsyncClient,
) -> None:
    headers = await login_as(client, "spender", budget_usd=0.10)
    _use_fake_pipeline(sub_questions=["q1"])

    await _spend(client, headers, 0.04)
    ok = await client.post("/research/query", headers=headers, json={"prompt": "a"})
    assert ok.status_code == 202

    await _spend(client, headers, 0.06)
    blocked = await client.post(
        "/research/query", headers=headers, json={"prompt": "b"}
    )
    assert blocked.status_code == 402
    assert blocked.json()["detail"] == BUDGET_EXHAUSTED


async def test_budget_is_per_account(client: AsyncClient) -> None:
    _use_fake_pipeline(sub_questions=["q1"])
    first = await login_as(client, "a", budget_usd=0.01)
    await _spend(client, first, 0.01)
    blocked = await client.post("/research/query", headers=first, json={"prompt": "a"})
    assert blocked.status_code == 402

    second = await login_as(client, "b", budget_usd=0.01)
    ok = await client.post("/research/query", headers=second, json={"prompt": "b"})
    assert ok.status_code == 202


def _priced(message):
    """A reply that reports its cost, the way OpenRouter does."""
    message.usage_metadata = {
        "input_tokens": 100,
        "output_tokens": 20,
        "total_tokens": 120,
    }
    message.response_metadata = {
        "token_usage": {"prompt_tokens": 100, "completion_tokens": 20, "cost": 0.001},
        "model_name": "fake/model",
    }
    return message


class _PricedModel(RoleModel):
    """The fake pipeline, with every call reporting a cost."""

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        result = super()._generate(messages, stop, run_manager, **kwargs)
        _priced(result.generations[0].message)
        return result


async def test_every_model_call_is_billed_to_the_run(client: AsyncClient) -> None:
    headers = await login_as(client, "billed", budget_usd=0.5)
    app.dependency_overrides[get_model] = lambda: _PricedModel(["q1"])
    app.dependency_overrides[get_search_backend] = FakeBackend

    created = await client.post(
        "/research/query", headers=headers, json={"prompt": "p"}
    )
    query_id = created.json()["id"]

    # planner + one researcher + writer = three billed calls, all tied to the run
    async with db_session.SessionLocal() as db:
        rows = (await db.execute(select(LLMUsage))).scalars().all()
    assert [row.query_id for row in rows] == [query_id] * 3
    assert all(row.cost_micro_usd == 1_000 for row in rows)

    me = (await client.get("/auth/me", headers=headers)).json()
    assert me["spent_usd"] == 0.003
    assert me["remaining_usd"] == 0.497


class _BrokeModel(ScriptedModel):
    """A key that has run out of credits."""

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        raise ProviderCreditsError(OUT_OF_CREDITS)


async def test_out_of_credits_fails_the_run_with_a_clear_message(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    app.dependency_overrides[get_model] = lambda: _BrokeModel()
    app.dependency_overrides[get_search_backend] = FakeBackend

    created = await client.post(
        "/research/query", headers=auth_headers, json={"prompt": "p"}
    )
    detail = await client.get(
        f"/research/query/{created.json()['id']}", headers=auth_headers
    )

    assert detail.json()["status"] == "failed"
    assert detail.json()["error"] == OUT_OF_CREDITS
    assert detail.json()["stopped"] is False
