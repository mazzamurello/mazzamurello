"""Alembic environment: migrations run as `mzm_owner`, never as the application role (TEN-004).

The database URL comes only from `MZM_DATABASE_URL`, in the form
`postgresql://USER:PASSWORD@HOST:PORT/DATABASE`; the driver is chosen here
(specs/contracts/test-harness.md).
"""

from __future__ import annotations

import asyncio
import os

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

URL_VARIABLE = "MZM_DATABASE_URL"


def _url() -> str:
    url = os.environ.get(URL_VARIABLE)
    if not url:
        raise RuntimeError(f"{URL_VARIABLE} is not set")
    scheme, separator, rest = url.partition("://")
    if not separator or scheme not in ("postgresql", "postgres"):
        raise RuntimeError(f"{URL_VARIABLE} must be a postgresql:// URL")
    return f"postgresql+asyncpg://{rest}"


def _run_migrations(connection: Connection) -> None:
    # Each migration commits on its own, so a failure leaves the database at
    # the last revision that completed.
    context.configure(connection=connection, transaction_per_migration=True)
    with context.begin_transaction():
        context.run_migrations()


async def _main() -> None:
    engine = create_async_engine(_url(), poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(_run_migrations)
            await connection.commit()
    finally:
        await engine.dispose()


if context.is_offline_mode():
    raise RuntimeError("offline migrations are not supported: run them against the database")
asyncio.run(_main())
