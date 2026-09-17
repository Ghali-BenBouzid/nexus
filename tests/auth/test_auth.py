from datetime import UTC, datetime, timedelta

import jwt
from httpx import AsyncClient

from app.auth import repository, service
from app.core.config import settings
from app.db import session as db_session
from tests.accounts import login_as


async def _expire(user_id: int) -> None:
    async with db_session.SessionLocal() as db:
        user = await repository.get_user_by_id(db, user_id)
        user.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        await db.commit()


# --- invite links -----------------------------------------------------------


async def test_invite_link_signs_in_and_shows_the_budget(client: AsyncClient) -> None:
    headers = await login_as(client, "Jane (Acme)", budget_usd=0.25)

    me = await client.get("/auth/me", headers=headers)

    assert me.status_code == 200
    body = me.json()
    assert body["name"] == "Jane (Acme)"
    assert body["budget_usd"] == 0.25
    assert body["spent_usd"] == 0
    assert body["remaining_usd"] == 0.25
    assert body["expires_at"] is not None  # default access window applies


async def test_unknown_invite_token_is_rejected(client: AsyncClient) -> None:
    response = await client.post("/auth/invite", json={"token": "not-a-real-token"})

    assert response.status_code == 401
    assert response.json()["detail"] == service.INVALID_INVITE


async def test_expired_account_cannot_redeem_its_link(client: AsyncClient) -> None:
    async with db_session.SessionLocal() as db:
        user, token = await service.create_demo_account(db, name="late")
    await _expire(user.id)

    response = await client.post("/auth/invite", json={"token": token})

    assert response.status_code == 403
    assert response.json()["detail"] == service.ACCESS_EXPIRED


async def test_account_expiring_mid_session_is_locked_out(client: AsyncClient) -> None:
    headers = await login_as(client, "short visit")
    me = await client.get("/auth/me", headers=headers)
    await _expire(me.json()["id"])

    # the access token itself is still valid; the account's expiry wins anyway
    response = await client.get("/auth/me", headers=headers)

    assert response.status_code == 403


async def test_account_with_zero_days_never_expires(client: AsyncClient) -> None:
    headers = await login_as(client, "forever", days=0)

    me = await client.get("/auth/me", headers=headers)

    assert me.json()["expires_at"] is None


async def test_new_link_revokes_the_old_one(client: AsyncClient) -> None:
    async with db_session.SessionLocal() as db:
        user, old_token = await service.create_demo_account(db, name="relinked")
        new_token = await service.update_account(db, user, new_link=True)

    old = await client.post("/auth/invite", json={"token": old_token})
    new = await client.post("/auth/invite", json={"token": new_token})

    assert old.status_code == 401
    assert new.status_code == 200


async def test_public_signup_and_password_login_are_gone(client: AsyncClient) -> None:
    register = await client.post(
        "/auth/register", json={"email": "a@b.c", "password": "x"}
    )
    login = await client.post("/auth/login", data={"username": "a", "password": "x"})

    assert register.status_code == 404
    assert login.status_code == 404


# --- access tokens ----------------------------------------------------------


async def test_me_no_token(client: AsyncClient) -> None:
    response = await client.get("/auth/me")

    assert response.status_code == 401


async def test_me_invalid_token(client: AsyncClient) -> None:
    response = await client.get(
        "/auth/me", headers={"Authorization": "Bearer invalid.garbage.token"}
    )

    assert response.status_code == 401


async def test_me_expired_token(client: AsyncClient) -> None:
    expired = {"sub": "1", "exp": datetime.now(UTC) - timedelta(minutes=1)}
    token = jwt.encode(expired, key=settings.secret_key, algorithm=settings.algorithm)

    response = await client.get(
        "/auth/me", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 401
