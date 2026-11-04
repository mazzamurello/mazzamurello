"""Costs from the cost ledger: per run, per conversation and over rolling periods (MOD-007, ADR-0042, ADR-0073)."""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from fastapi import APIRouter
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from mazzamurello_server import schemas
from mazzamurello_server.auth import Authenticated, Engine
from mazzamurello_server.database import transaction

router = APIRouter()

# The cost of the conversation of a `conversations` row, per currency, as JSON.
CONVERSATION_COST = (
    "(SELECT coalesce(jsonb_agg(jsonb_build_object('amount', t.total::text, 'currency', t.currency)), '[]')"
    " FROM (SELECT l.currency, sum(l.cost) AS total FROM usage_ledger l"
    " WHERE l.conversation_id = conversations.id AND l.cost IS NOT NULL GROUP BY l.currency) t) AS cost"
)


def amount(value: Decimal | str) -> str:
    """A decimal as the contract writes it: no exponent, no trailing zeros."""
    number = Decimal(value).normalize()
    return format(number, "f") if number != 0 else "0"


def money(totals: Any) -> list[schemas.Money]:
    """Totals per currency, from JSON or rows of `(currency, total)`."""
    items: list[Any] = json.loads(totals) if isinstance(totals, str) else list(totals or [])
    result: list[schemas.Money] = []
    for item in items:
        if isinstance(item, dict):
            entry: dict[str, Any] = item  # pyright: ignore[reportUnknownVariableType]
            result.append(schemas.Money(amount=amount(str(entry["amount"])), currency=str(entry["currency"])))
        else:
            currency, total = item
            result.append(schemas.Money(amount=amount(total), currency=str(currency)))
    return sorted(result, key=lambda entry: entry.currency)


async def run_costs(connection: AsyncConnection, run_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, list[schemas.Money]]:
    """The cost of each run's answer, per currency, compaction included; titles count for the conversation only."""
    rows = (
        await connection.execute(
            text(
                "SELECT run_id, currency, sum(cost) AS total FROM usage_ledger"
                # A title is the conversation's, not its first answer's (CNV-006).
                " WHERE run_id = ANY(:ids) AND cost IS NOT NULL AND purpose <> 'title' GROUP BY run_id, currency"
            ),
            {"ids": list(run_ids)},
        )
    ).all()
    costs: dict[uuid.UUID, list[schemas.Money]] = {run_id: [] for run_id in run_ids}
    for row in rows:
        costs[row.run_id].append(schemas.Money(amount=amount(row.total), currency=row.currency))
    return costs


@router.get("/me/usage", response_model=schemas.Usage)
async def usage(identity: Authenticated, engine: Engine) -> schemas.Usage:
    """The user's spend over the last 24 hours and 30 days; row-level security keeps it theirs."""
    async with transaction(engine, identity) as connection:
        periods: dict[str, list[schemas.Money]] = {}
        for name, hours in (("last_24_hours", 24), ("last_30_days", 30 * 24)):
            rows = (
                await connection.execute(
                    text(
                        "SELECT currency, sum(cost) FROM usage_ledger WHERE cost IS NOT NULL"
                        " AND created_at > now() - make_interval(hours => :hours) GROUP BY currency"
                    ),
                    {"hours": hours},
                )
            ).all()
            periods[name] = money([tuple(row) for row in rows])
        unpriced = (
            await connection.execute(
                text("SELECT count(*) FROM usage_ledger WHERE cost IS NULL AND created_at > now() - interval '30 days'")
            )
        ).scalar_one()
    return schemas.Usage(
        last_24_hours=periods["last_24_hours"], last_30_days=periods["last_30_days"], unpriced_requests=unpriced
    )
