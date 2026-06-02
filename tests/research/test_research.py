from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from jose import jwt

from app.core.config import settings


def test_query_without_token(client: TestClient) -> None:
    response = client.post("/research/query", json={"prompt": "This is a test prompt"})

    assert response.status_code == 401


def test_query_invalid_token(client: TestClient) -> None:
    response = client.post(
        "/research/query",
        headers={"Authorization": "Bearer invalid.garbage.token"},
        json={"prompt": "test prompt"},
    )

    assert response.status_code == 401


def test_query_expired_token(client: TestClient) -> None:
    expired_payload = {"sub": "1", "exp": datetime.now(UTC) - timedelta(minutes=1)}

    token = jwt.encode(
        claims=expired_payload, key=settings.secret_key, algorithm=settings.algorithm
    )

    response = client.post(
        "/research/query",
        headers={"Authorization": f"Bearer {token}"},
        json={"prompt": "test prompt"},
    )

    assert response.status_code == 401


def test_query_success(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.post(
        "/research/query",
        headers=auth_headers,
        json={"prompt": "This is a test prompt"},
    )

    assert response.status_code == 201
    assert response.json()["prompt"] == "This is a test prompt"
    assert response.json()["report"] is not None
    assert response.json()["report"] != ""
