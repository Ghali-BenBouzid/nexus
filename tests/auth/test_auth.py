from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from jose import jwt

from app.core.config import settings


def test_register_success(client: TestClient) -> None:
    response = client.post(
        "/auth/register", json={"email": "test@test.com", "password": "secret"}
    )

    assert response.status_code == 201
    assert response.json()["email"] == "test@test.com"
    assert "id" in response.json()
    assert isinstance(response.json()["id"], int)
    assert "hashed_password" not in response.json()  # security check


def test_register_conflict(client: TestClient) -> None:
    client.post("/auth/register", json={"email": "test@test.com", "password": "secret"})

    response = client.post(
        "/auth/register", json={"email": "test@test.com", "password": "secret"}
    )

    assert response.status_code == 409


def test_login_success(client: TestClient) -> None:
    client.post("/auth/register", json={"email": "test@test.com", "password": "secret"})

    response = client.post(
        "/auth/login", data={"username": "test@test.com", "password": "secret"}
    )

    assert response.status_code == 200
    assert isinstance(response.json()["access_token"], str)
    assert response.json()["token_type"] == "bearer"


def test_login_invalid_email(client: TestClient) -> None:
    client.post("/auth/register", json={"email": "test@test.com", "password": "secret"})

    response = client.post(
        "/auth/login", data={"username": "invalid_test@test.com", "password": "secret"}
    )

    assert response.status_code == 401


def test_login_invalid_password(client: TestClient) -> None:
    client.post("/auth/register", json={"email": "test@test.com", "password": "secret"})

    response = client.post(
        "/auth/login", data={"username": "test@test.com", "password": "invalid_secret"}
    )

    assert response.status_code == 401


def test_me_valid_token(client: TestClient) -> None:
    client.post("/auth/register", json={"email": "test@test.com", "password": "secret"})

    login_response = client.post(
        "/auth/login", data={"username": "test@test.com", "password": "secret"}
    )

    token = login_response.json()["access_token"]

    response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json()["email"] == "test@test.com"


def test_me_no_token(client: TestClient) -> None:
    response = client.get("/auth/me")

    assert response.status_code == 401


def test_me_invalid_token(client: TestClient) -> None:
    response = client.get(
        "/auth/me", headers={"Authorization": "Bearer invalid.garbage.token"}
    )

    assert response.status_code == 401


def test_me_expired_token(client: TestClient) -> None:
    expired_payload = {"sub": "1", "exp": datetime.now(UTC) - timedelta(minutes=1)}

    token = jwt.encode(
        claims=expired_payload, key=settings.secret_key, algorithm=settings.algorithm
    )

    response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401
