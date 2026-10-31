"""Users and tenants (AUTH-001, AUTH-002, TEN-001).

Which rows each request reaches is decided by row-level security from the
request context; the role checks here only choose between `403` and trying.
"""

from __future__ import annotations

import base64
import binascii
import uuid
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Query, status
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from mazzamurello_server import errors, schemas
from mazzamurello_server.auth import USER_COLUMNS, Authenticated, Engine, user_response
from mazzamurello_server.credentials import hash_password, uuid7
from mazzamurello_server.database import UNIQUE_VIOLATION, sqlstate, transaction

router = APIRouter()

type Limit = Annotated[int, Query(ge=1, le=100)]
type Cursor = Annotated[str | None, Query()]


def _encode_cursor(last_id: uuid.UUID) -> str:
    return base64.urlsafe_b64encode(last_id.bytes).decode().rstrip("=")


def _decode_cursor(cursor: str | None) -> uuid.UUID:
    """The identifier after which the page starts; the nil UUID for the first page."""
    if cursor is None:
        return uuid.UUID(int=0)
    try:
        return uuid.UUID(bytes=base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
    except (binascii.Error, ValueError):
        raise errors.ApiError(422, "request.validation_failed", "Validation failed") from None


def _page[T](rows: list[Any], limit: int, item: Callable[[Any], T]) -> tuple[list[T], str | None]:
    """Identifiers are time-ordered UUIDs, so pages follow creation order."""
    items = [item(row) for row in rows[:limit]]
    return items, (_encode_cursor(rows[limit - 1].id) if len(rows) > limit else None)


def _tenant(row: Any) -> schemas.Tenant:
    return schemas.Tenant(id=row.id, name=row.name, created_at=row.created_at)


_INSERT_USER = text(
    "INSERT INTO users (id, tenant_id, username, display_name, password_hash, role, instance_admin, created_at)"
    " VALUES (:id, :tenant_id, :username, :display_name, :password_hash, :role, false, now())"
)


@router.post("/tenant/users", status_code=status.HTTP_201_CREATED, response_model=schemas.User)
async def create_user(body: schemas.CreateUserRequest, identity: Authenticated, engine: Engine) -> schemas.User:
    if not identity.tenant_admin:
        raise errors.permission_denied()
    password_hash = await hash_password(body.password)
    user_id = uuid7()
    try:
        async with transaction(engine, identity) as connection:
            await connection.execute(
                _INSERT_USER,
                {
                    "id": user_id,
                    "tenant_id": identity.tenant_id,
                    "username": body.username,
                    "display_name": body.display_name,
                    "password_hash": password_hash,
                    "role": body.role,
                },
            )
            row = (
                await connection.execute(text(f"SELECT {USER_COLUMNS} FROM users WHERE id = :id"), {"id": user_id})  # noqa: S608
            ).one()
    except DBAPIError as error:
        if sqlstate(error) == UNIQUE_VIOLATION:
            raise errors.conflict() from None
        raise
    return user_response(row)


@router.get("/tenant/users", response_model=schemas.UserPage)
async def list_users(
    identity: Authenticated, engine: Engine, cursor: Cursor = None, limit: Limit = 50
) -> schemas.UserPage:
    # Row-level security limits the rows to the user's tenant.
    async with transaction(engine, identity) as connection:
        rows = (
            await connection.execute(
                text(f"SELECT {USER_COLUMNS} FROM users WHERE id > :after ORDER BY id LIMIT :limit"),  # noqa: S608
                {"after": _decode_cursor(cursor), "limit": limit + 1},
            )
        ).all()
    items, next_cursor = _page(list(rows), limit, user_response)
    return schemas.UserPage(items=items, next_cursor=next_cursor)


@router.post("/instance/tenants", status_code=status.HTTP_201_CREATED, response_model=schemas.Tenant)
async def create_tenant(body: schemas.CreateTenantRequest, identity: Authenticated, engine: Engine) -> schemas.Tenant:
    if not identity.instance_admin:
        raise errors.permission_denied()
    password_hash = await hash_password(body.admin.password)
    tenant_id = uuid7()
    try:
        # The tenant and its first admin are created together, or neither is.
        async with transaction(engine, identity) as connection:
            row = (
                await connection.execute(
                    text(
                        "INSERT INTO tenants (id, name, created_at) VALUES (:id, :name, now())"
                        " RETURNING id, name, created_at"
                    ),
                    {"id": tenant_id, "name": body.name},
                )
            ).one()
            await connection.execute(
                _INSERT_USER,
                {
                    "id": uuid7(),
                    "tenant_id": tenant_id,
                    "username": body.admin.username,
                    "display_name": body.admin.display_name,
                    "password_hash": password_hash,
                    "role": body.admin.role,
                },
            )
    except DBAPIError as error:
        if sqlstate(error) == UNIQUE_VIOLATION:
            raise errors.conflict() from None
        raise
    return _tenant(row)


@router.get("/instance/tenants", response_model=schemas.TenantPage)
async def list_tenants(
    identity: Authenticated, engine: Engine, cursor: Cursor = None, limit: Limit = 50
) -> schemas.TenantPage:
    if not identity.instance_admin:
        raise errors.permission_denied()
    async with transaction(engine, identity) as connection:
        rows = (
            await connection.execute(
                text("SELECT id, name, created_at FROM tenants WHERE id > :after ORDER BY id LIMIT :limit"),
                {"after": _decode_cursor(cursor), "limit": limit + 1},
            )
        ).all()
    items, next_cursor = _page(list(rows), limit, _tenant)
    return schemas.TenantPage(items=items, next_cursor=next_cursor)
