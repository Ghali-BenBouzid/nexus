"""Manage demo accounts from the command line. There is no signup page: each
visitor gets an account and an invite link from here.

    uv run python -m app.admin create "Jane Doe (Acme)" --budget 0.5 --days 14
    uv run python -m app.admin list
    uv run python -m app.admin update 7 --budget 1 --days 30 --new-link

It talks to whatever DATABASE_URL points at, so for production run it through
the host, e.g. ``railway run uv run python -m app.admin list``.
"""

import argparse
import asyncio

from app.auth import repository, service
from app.billing import repository as billing_repository
from app.billing.service import to_usd
from app.db import session as db_session


async def _create(args: argparse.Namespace) -> None:
    async with db_session.SessionLocal() as db:
        user, token = await service.create_demo_account(
            db, name=args.name, email=args.email, budget_usd=args.budget, days=args.days
        )
    print(f"Created account {user.id} ({user.name}).")
    print(service.invite_url(token))


async def _list(args: argparse.Namespace) -> None:
    async with db_session.SessionLocal() as db:
        users = await repository.list_users(db)
        spent = await billing_repository.spent_by_user(db)
    print(f"{'id':>4}  {'spent':>8}  {'budget':>8}  {'expires':<16}  name")
    for user in users:
        expires = (
            user.expires_at.strftime("%Y-%m-%d %H:%M") if user.expires_at else "never"
        )
        flag = " (expired)" if user.is_expired else ""
        spent_usd = f"${to_usd(spent.get(user.id, 0)):.4f}"
        budget_usd = f"${to_usd(user.budget_micro_usd):.2f}"
        print(
            f"{user.id:>4}  {spent_usd:>8}  {budget_usd:>8}"
            f"  {expires:<16}  {user.name}{flag}"
        )


async def _update(args: argparse.Namespace) -> None:
    async with db_session.SessionLocal() as db:
        user = await repository.get_user_by_id(db, args.id)
        if user is None:
            raise SystemExit(f"No account with id {args.id}.")
        token = await service.update_account(
            db, user, budget_usd=args.budget, days=args.days, new_link=args.new_link
        )
    print(f"Updated account {user.id} ({user.name}).")
    if token:
        print(service.invite_url(token))


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.admin")
    commands = parser.add_subparsers(dest="command", required=True)

    create = commands.add_parser("create", help="create an account and print its link")
    create.add_argument("name", help="who the invite is for")
    create.add_argument("--email", default=None)
    create.add_argument("--budget", type=float, default=None, help="USD")
    create.add_argument("--days", type=int, default=None, help="0 = never expires")
    create.set_defaults(run=_create)

    listing = commands.add_parser("list", help="accounts with spend and expiry")
    listing.set_defaults(run=_list)

    update = commands.add_parser("update", help="top up, extend or re-link")
    update.add_argument("id", type=int)
    update.add_argument("--budget", type=float, default=None, help="new total, USD")
    update.add_argument("--days", type=int, default=None, help="from now; 0 = never")
    update.add_argument(
        "--new-link", action="store_true", help="issue a new link; the old one dies"
    )
    update.set_defaults(run=_update)

    args = parser.parse_args()
    asyncio.run(args.run(args))


if __name__ == "__main__":
    main()
