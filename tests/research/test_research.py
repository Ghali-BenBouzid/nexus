from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from jose import jwt

from app.agents.provider import LLMResponse, Message, ToolCall
from app.agents.tools import SearchHit
from app.core.config import settings
from app.research.dependencies import get_provider, get_search_backend
from main import app

# --- fakes for the background pipeline (no network) -------------------------


class RoleProvider:
    def __init__(self, sub_questions: list[str]) -> None:
        self.sub_questions = sub_questions

    async def __aenter__(self) -> "RoleProvider":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def generate(
        self, messages: list[Message], tools: object = None, tool_choice: str = "auto"
    ) -> LLMResponse:
        system = messages[0].content or ""
        if "controller of a research assistant" in system:
            return LLMResponse(
                tool_calls=[
                    ToolCall(
                        id="d",
                        name="research",
                        args={"query": "research", "title": "Research Topic"},
                    )
                ]
            )
        if "research planner" in system:
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
            return LLMResponse(
                tool_calls=[
                    ToolCall(
                        id="f",
                        name="submit_finding",
                        args={
                            "claims": [{"text": "an answer", "cited_source_ids": []}],
                            "found_info": True,
                        },
                    )
                ]
            )
        return LLMResponse(text="FINAL REPORT")


class FakeBackend:
    async def __aenter__(self) -> "FakeBackend":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def search(self, query: str, max_results: int) -> list:
        return []

    async def extract(self, url: str) -> str:
        return ""


def _use_fake_pipeline(sub_questions: list[str]) -> None:
    app.dependency_overrides[get_provider] = lambda: RoleProvider(sub_questions)
    app.dependency_overrides[get_search_backend] = FakeBackend


async def _register_and_headers(client: AsyncClient, email: str) -> dict[str, str]:
    await client.post("/auth/register", json={"email": email, "password": "secret"})
    response = await client.post(
        "/auth/login", data={"username": email, "password": "secret"}
    )
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


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


class _ProvenanceProvider:
    """Searches once (consulting two sources) then cites only the first, so the
    consulted set is a strict superset of the cited set."""

    def __init__(self) -> None:
        self.agent_calls = 0

    async def __aenter__(self) -> "_ProvenanceProvider":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def generate(
        self, messages: list[Message], tools: object = None, tool_choice: str = "auto"
    ) -> LLMResponse:
        system = messages[0].content or ""
        if "research planner" in system:
            return LLMResponse(
                tool_calls=[
                    ToolCall(id="p", name="submit_plan", args={"sub_questions": ["q1"]})
                ]
            )
        if "research agent" in system:
            self.agent_calls += 1
            if self.agent_calls == 1:
                return LLMResponse(
                    tool_calls=[
                        ToolCall(
                            id="s",
                            name="web_search",
                            args={"query": "q", "max_results": 5},
                        )
                    ]
                )
            return LLMResponse(
                tool_calls=[
                    ToolCall(
                        id="f",
                        name="submit_finding",
                        args={
                            "claims": [{"text": "ans", "cited_source_ids": [0]}],
                            "found_info": True,
                        },
                    )
                ]
            )
        return LLMResponse(text="REPORT [1]")


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
    app.dependency_overrides[get_provider] = _ProvenanceProvider
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
    owner = await _register_and_headers(client, "owner2@test.com")
    other = await _register_and_headers(client, "other2@test.com")
    _use_fake_pipeline(sub_questions=["q1"])

    created = await client.post(
        "/research/query", headers=owner, json={"prompt": "secret"}
    )
    query_id = created.json()["id"]

    response = await client.get(f"/research/query/{query_id}/events", headers=other)
    assert response.status_code == 404


async def test_get_other_users_query_returns_404(client: AsyncClient) -> None:
    owner = await _register_and_headers(client, "owner@test.com")
    other = await _register_and_headers(client, "other@test.com")
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
    owner = await _register_and_headers(client, "cancel-owner@test.com")
    other = await _register_and_headers(client, "cancel-other@test.com")
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
