from httpx import AsyncClient

from app.auth import service
from app.db import session as db_session


async def login_as(
    client: AsyncClient, name: str = "Test user", **account: object
) -> dict[str, str]:
    """Create a demo account the way the admin CLI does, redeem its invite link the
    way the frontend does, and return the resulting auth header. ``account``
    passes through to ``create_demo_account`` (budget_usd, days, email)."""
    async with db_session.SessionLocal() as db:
        _, token = await service.create_demo_account(db, name=name, **account)
    response = await client.post("/auth/invite", json={"token": token})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}
