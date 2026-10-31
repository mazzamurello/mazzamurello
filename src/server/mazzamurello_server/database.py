"""Database access as `mzm_app`, one transaction per unit of work (TEN-004, TEN-005).

Every transaction starts by setting the request context of the database
contract from the authenticated identity, with transaction-local settings, so
nothing of one request survives on a pooled connection. Transactions without
an identity have no context and reach rows only through the
pre-authentication functions.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine


@dataclass(frozen=True)
class Identity:
    """The authenticated user of a request, from its device session."""

    session_id: uuid.UUID
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    role: str
    instance_admin: bool

    @property
    def tenant_admin(self) -> bool:
        return self.role == "tenant_admin"


_SET_CONTEXT = text(
    "SELECT set_config('app.tenant_id', :tenant_id, true), set_config('app.user_id', :user_id, true),"
    " set_config('app.role', :role, true), set_config('app.instance_admin', :instance_admin, true)"
)

UNIQUE_VIOLATION = "23505"


def create_engine(database_url: str) -> AsyncEngine:
    _, _, rest = database_url.partition("://")
    return create_async_engine(
        f"postgresql+asyncpg://{rest}",
        # Timestamps are computed and returned in UTC, so that intervals such
        # as a session's 90 days are exact (ADR-0049).
        connect_args={"server_settings": {"timezone": "UTC", "application_name": "mazzamurello-api"}},
        pool_pre_ping=True,
    )


@asynccontextmanager
async def transaction(engine: AsyncEngine, identity: Identity | None) -> AsyncGenerator[AsyncConnection]:
    """A transaction with the request context of `identity`, committed when the block succeeds."""
    async with engine.begin() as connection:
        if identity is not None:
            await connection.execute(
                _SET_CONTEXT,
                {
                    "tenant_id": str(identity.tenant_id),
                    "user_id": str(identity.user_id),
                    "role": identity.role,
                    "instance_admin": "true" if identity.instance_admin else "false",
                },
            )
        yield connection


def sqlstate(error: DBAPIError) -> str | None:
    """The SQLSTATE of a database error, when the driver reports one."""
    code = getattr(error.orig, "sqlstate", None) or getattr(error.orig, "pgcode", None)
    return code if isinstance(code, str) else None
