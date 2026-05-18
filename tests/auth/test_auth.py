from fastapi.testclient import TestClient


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
        "/auth/login", json={"email": "test@test.com", "password": "secret"}
    )

    assert response.status_code == 200
    assert isinstance(response.json()["access_token"], str)
    assert response.json()["token_type"] == "bearer"


def test_login_invalid_email(client: TestClient) -> None:
    client.post("/auth/register", json={"email": "test@test.com", "password": "secret"})
    response = client.post(
        "/auth/login", json={"email": "invalid_test@test.com", "password": "secret"}
    )

    assert response.status_code == 401


def test_login_invalid_password(client: TestClient) -> None:
    client.post("/auth/register", json={"email": "test@test.com", "password": "secret"})
    response = client.post(
        "/auth/login", json={"email": "test@test.com", "password": "invalid_secret"}
    )

    assert response.status_code == 401
