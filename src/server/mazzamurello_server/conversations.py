"""Conversations and their history (API-003, ADR-0031, ADR-0037).

History is a projection of the stored Pydantic AI messages to AG-UI
messages, along the path of runs from the first run to the chosen one.
"""

from __future__ import annotations

import base64
import binascii
import datetime
import json
import uuid
from collections.abc import Sequence
from typing import Annotated, Any

from dbos import DBOSClient
from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic_ai.messages import ModelMessagesTypeAdapter
from pydantic_ai.ui.ag_ui import AGUIAdapter
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from mazzamurello_server import errors, schemas
from mazzamurello_server.auth import Authenticated, Engine
from mazzamurello_server.credentials import uuid7
from mazzamurello_server.database import transaction

router = APIRouter()

CONVERSATION_COLUMNS = "id, title, archived_at IS NOT NULL AS archived, active_run_id, created_at, updated_at"
ACTIVE_STATUSES = ("queued", "running")

type Limit = Annotated[int, Query(ge=1, le=100)]


def client_of(request: Request) -> DBOSClient:
    client = request.app.state.durable
    if not isinstance(client, DBOSClient):
        raise RuntimeError("the durable execution client is not started")
    return client


type Durable = Annotated[DBOSClient, Depends(client_of)]


def conversation_response(row: Any) -> schemas.Conversation:
    return schemas.Conversation(
        id=row.id,
        title=row.title,
        archived=row.archived,
        active_run_id=row.active_run_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _encode(value: object) -> str:
    return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")


def _decode(cursor: str) -> Any:
    try:
        return json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
    except (binascii.Error, ValueError):
        raise errors.invalid("cursor", "invalid") from None


async def find_conversation(connection: AsyncConnection, conversation_id: uuid.UUID, *, lock: bool = False) -> Any:
    """The conversation, if the user owns it; others' are reported as not found (TEN-006)."""
    row = (
        await connection.execute(
            text(f"SELECT {CONVERSATION_COLUMNS} FROM conversations WHERE id = :id{' FOR UPDATE' if lock else ''}"),  # noqa: S608
            {"id": conversation_id},
        )
    ).one_or_none()
    if row is None:
        raise errors.not_found()
    return row


@router.post("/conversations", status_code=status.HTTP_201_CREATED, response_model=schemas.Conversation)
async def create_conversation(
    identity: Authenticated, engine: Engine, body: schemas.CreateConversationRequest | None = None
) -> schemas.Conversation:
    async with transaction(engine, identity) as connection:
        row = (
            await connection.execute(
                text(
                    "INSERT INTO conversations (id, tenant_id, owner_id, title, created_at, updated_at)"  # noqa: S608
                    " VALUES (:id, :tenant_id, :owner_id, :title, now(), now())"
                    f" RETURNING {CONVERSATION_COLUMNS}"
                ),
                {
                    "id": uuid7(),
                    "tenant_id": identity.tenant_id,
                    "owner_id": identity.user_id,
                    # Untitled until named (ADR-0052).
                    "title": body.title if body is not None and body.title is not None else "",
                },
            )
        ).one()
    return conversation_response(row)


@router.get("/conversations", response_model=schemas.ConversationPage)
async def list_conversations(
    identity: Authenticated, engine: Engine, archived: bool = False, cursor: str | None = None, limit: Limit = 50
) -> schemas.ConversationPage:
    after: tuple[datetime.datetime, uuid.UUID] | None = None
    if cursor is not None:
        decoded = _decode(cursor)
        try:
            after = (datetime.datetime.fromisoformat(decoded[0]), uuid.UUID(decoded[1]))
        except (TypeError, ValueError, IndexError):
            raise errors.invalid("cursor", "invalid") from None
    async with transaction(engine, identity) as connection:
        rows = (
            await connection.execute(
                text(
                    f"SELECT {CONVERSATION_COLUMNS} FROM conversations"  # noqa: S608
                    " WHERE (archived_at IS NOT NULL) = :archived"
                    " AND (CAST(:after_time AS timestamptz) IS NULL"
                    " OR (updated_at, id) < (CAST(:after_time AS timestamptz), CAST(:after_id AS uuid)))"
                    " ORDER BY updated_at DESC, id DESC LIMIT :limit"
                ),
                {
                    "archived": archived,
                    "after_time": None if after is None else after[0],
                    "after_id": None if after is None else after[1],
                    "limit": limit + 1,
                },
            )
        ).all()
    items = [conversation_response(row) for row in rows[:limit]]
    next_cursor = None
    if len(rows) > limit:
        last = rows[limit - 1]
        next_cursor = _encode([last.updated_at.isoformat(), str(last.id)])
    return schemas.ConversationPage(items=items, next_cursor=next_cursor)


@router.get("/conversations/{conversation_id}", response_model=schemas.Conversation)
async def get_conversation(conversation_id: uuid.UUID, identity: Authenticated, engine: Engine) -> schemas.Conversation:
    async with transaction(engine, identity) as connection:
        return conversation_response(await find_conversation(connection, conversation_id))


@router.patch("/conversations/{conversation_id}", response_model=schemas.Conversation)
async def update_conversation(
    conversation_id: uuid.UUID, body: schemas.UpdateConversationRequest, identity: Authenticated, engine: Engine
) -> schemas.Conversation:
    present = body.model_fields_set
    if not present:
        raise errors.invalid("/", "empty")
    async with transaction(engine, identity) as connection:
        await find_conversation(connection, conversation_id, lock=True)
        if "active_run_id" in present and body.active_run_id is not None:
            # Switching versions or rewinding (ADR-0037).
            await _refuse_while_active(connection, conversation_id)
            owned = (
                await connection.execute(
                    text("SELECT 1 FROM runs WHERE id = :run AND conversation_id = :conversation"),
                    {"run": body.active_run_id, "conversation": conversation_id},
                )
            ).one_or_none()
            if owned is None:
                raise errors.invalid("/active_run_id", "not_in_conversation")
        changes = {
            "title": body.title if "title" in present else None,
            "archived": body.archived if "archived" in present else None,
            "active_run_id": body.active_run_id if "active_run_id" in present else None,
        }
        row = (
            await connection.execute(
                text(
                    "UPDATE conversations SET title = coalesce(:title, title),"  # noqa: S608
                    " archived_at = CASE WHEN CAST(:archived AS boolean) IS NULL THEN archived_at"
                    " WHEN CAST(:archived AS boolean) THEN coalesce(archived_at, now()) ELSE NULL END,"
                    " active_run_id = coalesce(CAST(:active_run_id AS uuid), active_run_id), updated_at = now()"
                    f" WHERE id = :id RETURNING {CONVERSATION_COLUMNS}"
                ),
                changes | {"id": conversation_id},
            )
        ).one()
    return conversation_response(row)


async def _refuse_while_active(connection: AsyncConnection, conversation_id: uuid.UUID) -> None:
    active = (
        await connection.execute(
            text("SELECT 1 FROM runs WHERE conversation_id = :id AND status IN ('queued', 'running') LIMIT 1"),
            {"id": conversation_id},
        )
    ).one_or_none()
    if active is not None:
        raise errors.ApiError(409, "run.in_progress", "Run in progress")


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def delete_conversation(
    conversation_id: uuid.UUID, identity: Authenticated, engine: Engine, durable: Durable
) -> Response:
    async with transaction(engine, identity) as connection:
        await find_conversation(connection, conversation_id, lock=True)
        await _refuse_while_active(connection, conversation_id)
        run_ids = [
            str(row.id)
            for row in await connection.execute(
                text("SELECT id FROM runs WHERE conversation_id = :id"), {"id": conversation_id}
            )
        ]
        # The workflows hold the runs' content without row-level security, so
        # they go first; their IDs come from the row-level-secured runs (TEN-009).
        if run_ids:
            await durable.delete_workflows_async(run_ids)
        # Messages and runs follow by cascade; ledger entries are detached (ADR-0042).
        await connection.execute(text("DELETE FROM conversations WHERE id = :id"), {"id": conversation_id})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def path_runs(connection: AsyncConnection, conversation_id: uuid.UUID, last_run_id: uuid.UUID) -> list[Any]:
    """The runs from the first run of the conversation to `last_run_id`, in path order (ADR-0037)."""
    return list(
        (
            await connection.execute(
                text(
                    "WITH RECURSIVE path AS ("
                    " SELECT id, parent_run_id, kind, 0 AS depth FROM runs"
                    " WHERE id = :last AND conversation_id = :conversation"
                    " UNION ALL"
                    " SELECT r.id, r.parent_run_id, r.kind, p.depth + 1"
                    " FROM runs r JOIN path p ON r.id = p.parent_run_id"
                    ") SELECT id, parent_run_id, kind FROM path ORDER BY depth DESC"
                ),
                {"last": last_run_id, "conversation": conversation_id},
            )
        ).all()
    )


async def stored_messages(connection: AsyncConnection, run_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, list[Any]]:
    """The stored Pydantic AI messages of each run, in order."""
    rows = (
        await connection.execute(
            text("SELECT run_id, message FROM conversation_messages WHERE run_id = ANY(:ids) ORDER BY run_id, seq"),
            {"ids": list(run_ids)},
        )
    ).all()
    by_run: dict[uuid.UUID, list[Any]] = {run_id: [] for run_id in run_ids}
    for row in rows:
        by_run[row.run_id].append(row.message)
    return by_run


def message_id(run_id: uuid.UUID, position: int) -> uuid.UUID:
    """The ID of a run's message in history, from the run and its position in it (CNV-001)."""
    return uuid.uuid5(run_id, f"message-{position}")


@router.get("/conversations/{conversation_id}/messages", response_model=schemas.MessagePage)
async def list_messages(
    conversation_id: uuid.UUID,
    identity: Authenticated,
    engine: Engine,
    run_id: uuid.UUID | None = None,
    cursor: str | None = None,
    limit: Limit = 50,
) -> schemas.MessagePage:
    start = 0 if cursor is None else _decode(cursor)
    if not isinstance(start, int) or start < 0:
        raise errors.invalid("cursor", "invalid")
    async with transaction(engine, identity) as connection:
        conversation = await find_conversation(connection, conversation_id)
        last = run_id or conversation.active_run_id
        if last is None:
            return schemas.MessagePage(items=[], runs=[], next_cursor=None)
        path = await path_runs(connection, conversation_id, last)
        if not path:
            raise errors.not_found()
        stored = await stored_messages(connection, [run.id for run in path])
        versions = {
            run.id: [
                row.id
                for row in await connection.execute(
                    text(
                        "SELECT id FROM runs WHERE conversation_id = :conversation AND kind = 'message'"
                        " AND parent_run_id IS NOT DISTINCT FROM CAST(:parent AS uuid) ORDER BY created_at, id"
                    ),
                    {"conversation": conversation_id, "parent": run.parent_run_id},
                )
            ]
            for run in path
        }
    flattened: list[tuple[Any, dict[str, Any]]] = []
    for run in path:
        model_messages = ModelMessagesTypeAdapter.validate_python(stored[run.id])
        for position, message in enumerate(AGUIAdapter.dump_messages(model_messages)):
            dumped = message.model_dump(mode="json", by_alias=True, exclude_none=True)
            # The same ID on every read, and in every version that contains the message.
            dumped["id"] = str(message_id(run.id, position))
            flattened.append((run, dumped))
    page = flattened[start : start + limit]
    runs: list[schemas.PathRun] = []
    for run, message in page:
        if not runs or runs[-1].run_id != run.id:
            runs.append(
                schemas.PathRun(
                    run_id=run.id,
                    parent_run_id=run.parent_run_id,
                    kind=run.kind,
                    message_ids=[],
                    versions=versions[run.id] if run.kind == "message" else [run.id],
                )
            )
        runs[-1].message_ids.append(str(message["id"]))
    next_cursor = _encode(start + limit) if start + limit < len(flattened) else None
    return schemas.MessagePage(items=[message for _, message in page], runs=runs, next_cursor=next_cursor)
