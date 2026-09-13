from datetime import datetime

from pydantic import BaseModel


class InviteRedeem(BaseModel):
    token: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class Account(BaseModel):
    """The signed-in demo account, with where its budget stands."""

    id: int
    name: str
    expires_at: datetime | None
    budget_usd: float
    spent_usd: float
    remaining_usd: float
