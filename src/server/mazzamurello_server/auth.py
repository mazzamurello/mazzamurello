"""Login, device sessions and logout (AUTH-001, AUTH-004, AUTH-006, ADR-0025, ADR-0049).

Before a session is verified there is no request context: the login and the
token check go through the pre-authentication functions of the database
contract. Everything after runs with the context of the session's user.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from mazzamurello_server import errors, schemas
from mazzamurello_server.credentials import new_token, token_hash, uuid7, verify_password
from mazzamurello_server.database import Identity, transaction
from mazzamurello_server.network import source_address

router = APIRouter()

USER_COLUMNS = "id, tenant_id, username, display_name, role, instance_admin, created_at"


def engine_of(request: Request) -> AsyncEngine:
    engine = request.app.state.engine
    if not isinstance(engine, AsyncEngine):
        raise RuntimeError("the database engine is not started")
    return engine


type Engine = Annotated[AsyncEngine, Depends(engine_of)]


async def authenticate(request: Request, engine: Engine) -> Identity:
    """The identity of the request's device session; anything else is unauthenticated."""
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise errors.unauthenticated()
    async with transaction(engine, None) as connection:
        row = (
            await connection.execute(
                text(
                    "SELECT session_id, user_id, tenant_id, role, instance_admin FROM auth_find_session(:token_hash)"
                    " WHERE NOT revoked AND expires_at > now()"
                ),
                {"token_hash": token_hash(token.strip())},
            )
        ).one_or_none()
        if row is None:
            raise errors.unauthenticated()
        # The session is in use: renew it (ADR-0049).
        await connection.execute(text("SELECT auth_touch_session(:session_id)"), {"session_id": row.session_id})
    return Identity(row.session_id, row.user_id, row.tenant_id, row.role, row.instance_admin)


type Authenticated = Annotated[Identity, Depends(authenticate)]


def user_response(row: Any) -> schemas.User:
    return schemas.User(
        id=row.id,
        tenant_id=row.tenant_id,
        username=row.username,
        display_name=row.display_name,
        role=row.role,
        instance_admin=row.instance_admin,
        created_at=row.created_at,
    )


@router.post("/auth/login", status_code=status.HTTP_201_CREATED, response_model=schemas.LoginResponse)
async def login(body: schemas.LoginRequest, request: Request, engine: Engine) -> schemas.LoginResponse:
    async with transaction(engine, None) as connection:
        account = (
            await connection.execute(
                text(
                    "SELECT user_id, tenant_id, password_hash, role, instance_admin, disabled"
                    " FROM auth_find_login(:username)"
                ),
                {"username": body.username},
            )
        ).one_or_none()
    password_matches = await verify_password(account.password_hash if account else None, body.password)
    succeeded = account is not None and password_matches and not account.disabled

    source = source_address(
        request.client.host if request.client else None,
        request.headers.get("x-forwarded-for"),
        request.app.state.configuration.trusted_proxies,
    )
    async with transaction(engine, None) as connection:
        limit = (
            await connection.execute(
                text(
                    "SELECT allowed, retry_after_seconds FROM auth_record_login_attempt(:username, :source, :success)"
                ),
                {"username": body.username, "source": source, "success": succeeded},
            )
        ).one()
    # The answer to a refused attempt does not depend on the password (ADR-0047).
    if not limit.allowed:
        raise errors.rate_limited(limit.retry_after_seconds)
    if not succeeded or account is None:
        raise errors.invalid_credentials()

    identity = Identity(uuid7(), account.user_id, account.tenant_id, account.role, account.instance_admin)
    token = new_token()
    async with transaction(engine, identity) as connection:
        session = (
            await connection.execute(
                text(
                    "INSERT INTO device_sessions (id, tenant_id, user_id, token_hash, device_name, created_at,"
                    " last_used_at, expires_at)"
                    " VALUES (:id, :tenant_id, :user_id, :token_hash, :device_name, now(), now(),"
                    " now() + interval '90 days')"
                    " RETURNING id, device_name, created_at, last_used_at, expires_at"
                ),
                {
                    "id": identity.session_id,
                    "tenant_id": identity.tenant_id,
                    "user_id": identity.user_id,
                    "token_hash": token_hash(token),
                    "device_name": body.device_name,
                },
            )
        ).one()
        user = (
            await connection.execute(text(f"SELECT {USER_COLUMNS} FROM users WHERE id = :id"), {"id": identity.user_id})  # noqa: S608
        ).one()
    return schemas.LoginResponse(
        token=token,
        session=schemas.DeviceSession(
            id=session.id,
            device_name=session.device_name,
            created_at=session.created_at,
            last_used_at=session.last_used_at,
            expires_at=session.expires_at,
            current=True,
        ),
        user=user_response(user),
    )


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def logout(identity: Authenticated, engine: Engine) -> Response:
    async with transaction(engine, identity) as connection:
        await connection.execute(
            text("UPDATE device_sessions SET revoked_at = now() WHERE id = :id"), {"id": identity.session_id}
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=schemas.User)
async def get_me(identity: Authenticated, engine: Engine) -> schemas.User:
    async with transaction(engine, identity) as connection:
        row = (
            await connection.execute(text(f"SELECT {USER_COLUMNS} FROM users WHERE id = :id"), {"id": identity.user_id})  # noqa: S608
        ).one_or_none()
    if row is None:
        raise errors.unauthenticated()
    return user_response(row)


@router.get("/me/sessions", response_model=schemas.DeviceSessionList)
async def list_my_sessions(identity: Authenticated, engine: Engine) -> schemas.DeviceSessionList:
    # Row-level security limits the rows to the user's own sessions.
    async with transaction(engine, identity) as connection:
        rows = (
            await connection.execute(
                text(
                    "SELECT id, device_name, created_at, last_used_at, expires_at FROM device_sessions"
                    " WHERE revoked_at IS NULL AND expires_at > now() ORDER BY created_at, id"
                )
            )
        ).all()
    return schemas.DeviceSessionList(
        items=[
            schemas.DeviceSession(
                id=row.id,
                device_name=row.device_name,
                created_at=row.created_at,
                last_used_at=row.last_used_at,
                expires_at=row.expires_at,
                current=row.id == identity.session_id,
            )
            for row in rows
        ]
    )


@router.delete("/me/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def revoke_my_session(session_id: uuid.UUID, identity: Authenticated, engine: Engine) -> Response:
    async with transaction(engine, identity) as connection:
        result = await connection.execute(
            text("UPDATE device_sessions SET revoked_at = now() WHERE id = :id AND revoked_at IS NULL"),
            {"id": session_id},
        )
    # Another user's session is invisible, so it is reported as not found (TEN-006).
    if result.rowcount == 0:
        raise errors.not_found()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
