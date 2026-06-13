from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from jose import jwt

from app.core.config import settings
from app.core.limiter import limiter


async def test_register_success(client: AsyncClient) -> None:
    response = await client.post(
        "/auth/register", json={"email": "test@test.com", "password": "secret"}
    )

    assert response.status_code == 201
    assert response.json()["email"] == "test@test.com"
    assert "id" in response.json()
    assert isinstance(response.json()["id"], int)
    assert "hashed_password" not in response.json()  # security check


async def test_register_conflict(client: AsyncClient) -> None:
    await client.post(
        "/auth/register", json={"email": "test@test.com", "password": "secret"}
    )

    response = await client.post(
        "/auth/register", json={"email": "test@test.com", "password": "secret"}
    )

    assert response.status_code == 409


async def test_login_success(client: AsyncClient) -> None:
    await client.post(
        "/auth/register", json={"email": "test@test.com", "password": "secret"}
    )

    response = await client.post(
        "/auth/login", data={"username": "test@test.com", "password": "secret"}
    )

    assert response.status_code == 200
    assert isinstance(response.json()["access_token"], str)
    assert response.json()["token_type"] == "bearer"


async def test_login_invalid_email(client: AsyncClient) -> None:
    await client.post(
        "/auth/register", json={"email": "test@test.com", "password": "secret"}
    )

    response = await client.post(
        "/auth/login", data={"username": "invalid_test@test.com", "password": "secret"}
    )

    assert response.status_code == 401


async def test_login_invalid_password(client: AsyncClient) -> None:
    await client.post(
        "/auth/register", json={"email": "test@test.com", "password": "secret"}
    )

    response = await client.post(
        "/auth/login", data={"username": "test@test.com", "password": "invalid_secret"}
    )

    assert response.status_code == 401


async def test_me_valid_token(client: AsyncClient) -> None:
    await client.post(
        "/auth/register", json={"email": "test@test.com", "password": "secret"}
    )

    login_response = await client.post(
        "/auth/login", data={"username": "test@test.com", "password": "secret"}
    )

    token = login_response.json()["access_token"]

    response = await client.get(
        "/auth/me", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    assert response.json()["email"] == "test@test.com"


async def test_me_no_token(client: AsyncClient) -> None:
    response = await client.get("/auth/me")

    assert response.status_code == 401


async def test_me_invalid_token(client: AsyncClient) -> None:
    response = await client.get(
        "/auth/me", headers={"Authorization": "Bearer invalid.garbage.token"}
    )

    assert response.status_code == 401


async def test_me_expired_token(client: AsyncClient) -> None:
    expired_payload = {"sub": "1", "exp": datetime.now(UTC) - timedelta(minutes=1)}

    token = jwt.encode(
        claims=expired_payload, key=settings.secret_key, algorithm=settings.algorithm
    )

    response = await client.get(
        "/auth/me", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 401


# --- abuse guard: per-IP registration throttle ------------------------------


async def test_register_is_rate_limited_per_ip(client: AsyncClient) -> None:
    # The limiter is disabled for the rest of the suite (see conftest); enable it
    # here to check that one IP can only register so many accounts before a 429,
    # while a different IP keeps its own allowance. Distinct X-Forwarded-For values
    # also exercise the proxy-aware key (the real client behind Cloudflare/Railway).
    original = settings.register_rate_limit
    settings.register_rate_limit = "2/hour"
    limiter.enabled = True
    try:
        ip_a = {"X-Forwarded-For": "203.0.113.7"}
        for i in range(2):
            ok = await client.post(
                "/auth/register",
                headers=ip_a,
                json={"email": f"a{i}@test.com", "password": "secret"},
            )
            assert ok.status_code == 201
        blocked = await client.post(
            "/auth/register",
            headers=ip_a,
            json={"email": "a2@test.com", "password": "secret"},
        )
        assert blocked.status_code == 429

        # A different client IP has its own bucket and is unaffected.
        other = await client.post(
            "/auth/register",
            headers={"X-Forwarded-For": "198.51.100.9"},
            json={"email": "b@test.com", "password": "secret"},
        )
        assert other.status_code == 201
    finally:
        settings.register_rate_limit = original
        limiter.enabled = False
