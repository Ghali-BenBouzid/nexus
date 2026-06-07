from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from jose import jwt

from app.core.config import settings


async def test_query_without_token(client: AsyncClient) -> None:
    response = await client.post(
        "/research/query", json={"prompt": "This is a test prompt"}
    )

    assert response.status_code == 401


async def test_query_invalid_token(client: AsyncClient) -> None:
    response = await client.post(
        "/research/query",
        headers={"Authorization": "Bearer invalid.garbage.token"},
        json={"prompt": "test prompt"},
    )

    assert response.status_code == 401


async def test_query_expired_token(client: AsyncClient) -> None:
    expired_payload = {"sub": "1", "exp": datetime.now(UTC) - timedelta(minutes=1)}

    token = jwt.encode(
        claims=expired_payload, key=settings.secret_key, algorithm=settings.algorithm
    )

    response = await client.post(
        "/research/query",
        headers={"Authorization": f"Bearer {token}"},
        json={"prompt": "test prompt"},
    )

    assert response.status_code == 401


async def test_query_success(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    response = await client.post(
        "/research/query",
        headers=auth_headers,
        json={"prompt": "This is a test prompt"},
    )

    assert response.status_code == 201
    assert response.json()["prompt"] == "This is a test prompt"
    assert response.json()["report"] is not None
    assert response.json()["report"] != ""
