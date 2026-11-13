"""Tools, tool permissions and audit events through the API (AGT-002, AGT-005, AGT-008, UX-023, ADR-0090).

A user reads what applies to each of their tools and their own audit
events; a tenant admin reads and sets each user's tool permissions. Row-level
security keeps both to the tenant, and audit events to their user (TEN-006).
"""

from __future__ import annotations

import datetime
import uuid
from typing import Annotated, Any, cast, get_args

from fastapi import APIRouter, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from sibillo_server import errors, schemas
from sibillo_server.auth import Authenticated, Engine
from sibillo_server.conversations import decode_cursor, encode_cursor
from sibillo_server.database import transaction
from sibillo_server.tool_policy import CLASSES, DECLARATIONS, Permissions, Setting, effective, has_external_effects

router = APIRouter()

TOOL_NAMES: tuple[str, ...] = get_args(schemas.ToolName.__value__)

type Limit = Annotated[int, Query(ge=1, le=100)]


async def permissions_of(connection: AsyncConnection, user_id: uuid.UUID) -> Permissions:
    """A user's tool permissions; row-level security shows a user only their own, and an admin their tenant's."""
    rows = (
        await connection.execute(
            text("SELECT subject_kind, subject, setting FROM tool_permissions WHERE user_id = :user"),
            {"user": user_id},
        )
    ).all()
    tools: dict[str, Setting] = {}
    classes: dict[str, Setting] = {}
    for row in rows:
        (tools if row.subject_kind == "tool" else classes)[str(row.subject)] = row.setting
    return Permissions(tools=tools, classes=classes)


def _permissions_out(permissions: Permissions) -> schemas.ToolPermissionsOut:
    return schemas.ToolPermissionsOut(tools=dict(permissions.tools), classes=dict(permissions.classes))


async def _tenant_user(connection: AsyncConnection, user_id: uuid.UUID) -> None:
    """The user, if they belong to the tenant; others' are reported as not found (TEN-006)."""
    row = (await connection.execute(text("SELECT 1 FROM users WHERE id = :id"), {"id": user_id})).one_or_none()
    if row is None:
        raise errors.not_found()


@router.get("/tenant/users/{user_id}/tool-permissions", response_model=schemas.ToolPermissionsOut)
async def get_tool_permissions(
    user_id: uuid.UUID, identity: Authenticated, engine: Engine
) -> schemas.ToolPermissionsOut:
    if not identity.tenant_admin:
        raise errors.permission_denied()
    async with transaction(engine, identity) as connection:
        await _tenant_user(connection, user_id)
        return _permissions_out(await permissions_of(connection, user_id))


@router.put("/tenant/users/{user_id}/tool-permissions", response_model=schemas.ToolPermissionsOut)
async def set_tool_permissions(
    user_id: uuid.UUID, body: schemas.ToolPermissions, identity: Authenticated, engine: Engine
) -> schemas.ToolPermissionsOut:
    if not identity.tenant_admin:
        raise errors.permission_denied()
    async with transaction(engine, identity) as connection:
        await _tenant_user(connection, user_id)
        await connection.execute(text("DELETE FROM tool_permissions WHERE user_id = :user"), {"user": user_id})
        settings = [("tool", name, setting) for name, setting in body.tools.items()] + [
            ("class", name, setting) for name, setting in body.classes.items()
        ]
        for kind, subject, setting in settings:
            await connection.execute(
                text(
                    "INSERT INTO tool_permissions (tenant_id, user_id, subject_kind, subject, setting, updated_at)"
                    " VALUES (:tenant, :user, :kind, :subject, :setting, now())"
                ),
                {
                    "tenant": identity.tenant_id,
                    "user": user_id,
                    "kind": kind,
                    "subject": subject,
                    "setting": setting,
                },
            )
        return _permissions_out(await permissions_of(connection, user_id))


@router.get("/tools", response_model=schemas.ToolList)
async def list_tools(identity: Authenticated, engine: Engine) -> schemas.ToolList:
    async with transaction(engine, identity) as connection:
        permissions = await permissions_of(connection, identity.user_id)
    items: list[schemas.ToolInfo] = []
    for name in TOOL_NAMES:
        declaration = DECLARATIONS[name]
        applied = effective(name, permissions)
        items.append(
            schemas.ToolInfo(
                name=cast(schemas.ToolName, name),
                classes=[c for c in CLASSES if c in declaration.classes],
                approval_default=declaration.approval_default,
                effective=applied.setting,
                permission=None
                if applied.subject is None
                else schemas.PermissionSource(setting=applied.setting, subject=applied.subject),
            )
        )
    return schemas.ToolList(items=items)


@router.get("/me/activity", response_model=schemas.ActivityPage)
async def list_activity(
    identity: Authenticated,
    engine: Engine,
    conversation_id: uuid.UUID | None = None,
    tool: Annotated[str | None, Query(max_length=100)] = None,
    cursor: str | None = None,
    limit: Limit = 50,
) -> schemas.ActivityPage:
    after: tuple[datetime.datetime, uuid.UUID] | None = None
    if cursor is not None:
        decoded: Any = decode_cursor(cursor)
        try:
            after = (datetime.datetime.fromisoformat(decoded[0]), uuid.UUID(decoded[1]))
        except (TypeError, ValueError, IndexError, KeyError):
            raise errors.invalid("cursor", "invalid") from None
    async with transaction(engine, identity) as connection:
        rows = (
            await connection.execute(
                text(
                    "SELECT a.id, a.tool, a.conversation_id, c.title AS conversation_title, a.run_id, a.tool_call_id,"
                    " a.outcome, a.scope, a.reason, a.attempts, a.created_at FROM audit_events a"
                    " LEFT JOIN conversations c ON c.id = a.conversation_id"
                    " WHERE (CAST(:conversation AS uuid) IS NULL OR a.conversation_id = CAST(:conversation AS uuid))"
                    " AND (CAST(:tool AS text) IS NULL OR a.tool = CAST(:tool AS text))"
                    " AND (CAST(:after_time AS timestamptz) IS NULL"
                    " OR (a.created_at, a.id) < (CAST(:after_time AS timestamptz), CAST(:after_id AS uuid)))"
                    " ORDER BY a.created_at DESC, a.id DESC LIMIT :limit"
                ),
                {
                    "conversation": conversation_id,
                    "tool": tool,
                    "after_time": None if after is None else after[0],
                    "after_id": None if after is None else after[1],
                    "limit": limit + 1,
                },
            )
        ).all()
    items = [
        schemas.AuditEvent(
            id=row.id,
            tool=row.tool,
            conversation_id=row.conversation_id,
            conversation_title=row.conversation_title,
            run_id=row.run_id,
            tool_call_id=row.tool_call_id,
            outcome=row.outcome,
            scope=row.scope,
            reason=row.reason,
            repeated=has_external_effects(row.tool) and row.attempts > 1,
            created_at=row.created_at,
        )
        for row in rows[:limit]
    ]
    next_cursor = None
    if len(rows) > limit:
        last = rows[limit - 1]
        next_cursor = encode_cursor([last.created_at.isoformat(), str(last.id)])
    return schemas.ActivityPage(items=items, next_cursor=next_cursor)
