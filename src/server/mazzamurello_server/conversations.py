"""Conversations, their model and their history (API-003, CNV-004, MOD-012, ADR-0031, ADR-0037, ADR-0068).

History is a projection of the stored Pydantic AI messages to AG-UI
messages, along the chain of runs from the first run to the active one.
Rewinding deletes the runs after the turn it rewinds to.
"""

from __future__ import annotations

import base64
import binascii
import datetime
import json
import uuid
from collections.abc import Sequence
from typing import Annotated, Any, cast

from dbos import DBOSClient
from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic_ai.messages import ModelMessagesTypeAdapter
from pydantic_ai.ui.ag_ui import AGUIAdapter
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from mazzamurello_server import errors, schemas
from mazzamurello_server.auth import Authenticated, Engine
from mazzamurello_server.connections import default_model, offered
from mazzamurello_server.costs import CONVERSATION_COST, money, run_costs
from mazzamurello_server.credentials import uuid7
from mazzamurello_server.database import transaction

router = APIRouter()

CONVERSATION_COLUMNS = (
    "id, title, archived_at IS NOT NULL AS archived, active_run_id, connection_id, model, folder_id,"
    " pinned_at IS NOT NULL AS pinned, forked_from_conversation_id, forked_from_run_id, last_message_at,"
    f" created_at, updated_at, {CONVERSATION_COST}"
)
ACTIVE_STATUSES = ("queued", "running")
# The most of a model's stated reason a failed run's error repeats (MOD-015).
REASON_CHARS = 500

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
        # A model whose connection was removed is no model the client can show or choose.
        model=None
        if row.connection_id is None or row.model is None
        else schemas.ModelChoiceOut(connection_id=row.connection_id, model=row.model),
        folder_id=row.folder_id,
        pinned=row.pinned,
        forked_from=None
        if row.forked_from_conversation_id is None and row.forked_from_run_id is None
        else schemas.ForkedFrom(conversation_id=row.forked_from_conversation_id, run_id=row.forked_from_run_id),
        cost=money(row.cost),
        last_message_at=row.last_message_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def encode_cursor(value: object) -> str:
    return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> Any:
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
        # The chosen model, or else the household's default (MOD-012).
        choice = body.model if body is not None else None
        if choice is not None and not await offered(connection, choice):
            raise errors.invalid("/model", "not_offered")
        model = choice or await default_model(connection)
        row = (
            await connection.execute(
                text(
                    "INSERT INTO conversations (id, tenant_id, owner_id, title, connection_id, model, last_message_at,"  # noqa: S608
                    " created_at, updated_at) VALUES (:id, :tenant_id, :owner_id, :title, :connection_id, :model,"
                    " now(), now(), now())"
                    f" RETURNING {CONVERSATION_COLUMNS}"
                ),
                {
                    "id": uuid7(),
                    "tenant_id": identity.tenant_id,
                    "owner_id": identity.user_id,
                    # Untitled until named (ADR-0052).
                    "title": body.title if body is not None and body.title is not None else "",
                    "connection_id": None if model is None else model.connection_id,
                    "model": None if model is None else model.model,
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
        decoded = decode_cursor(cursor)
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
        next_cursor = encode_cursor([last.updated_at.isoformat(), str(last.id)])
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
    if "model" in present and body.model is None:
        raise errors.invalid("/model", "null")
    async with transaction(engine, identity) as connection:
        await find_conversation(connection, conversation_id, lock=True)
        if body.model is not None and not await offered(connection, body.model):
            raise errors.invalid("/model", "not_offered")
        if body.folder_id is not None and not await _owns_folder(connection, body.folder_id):
            raise errors.invalid("/folder_id", "not_a_folder")
        if "pinned" in present and body.pinned is None:
            raise errors.invalid("/pinned", "null")
        changes = {
            "title": body.title if "title" in present else None,
            "archived": body.archived if "archived" in present else None,
            "connection_id": None if body.model is None else body.model.connection_id,
            "model": None if body.model is None else body.model.model,
            "set_folder": "folder_id" in present,
            "folder_id": body.folder_id,
            "pinned": body.pinned,
        }
        row = (
            await connection.execute(
                text(
                    "UPDATE conversations SET title = coalesce(:title, title),"  # noqa: S608
                    " archived_at = CASE WHEN CAST(:archived AS boolean) IS NULL THEN archived_at"
                    " WHEN CAST(:archived AS boolean) THEN coalesce(archived_at, now()) ELSE NULL END,"
                    " connection_id = coalesce(CAST(:connection_id AS uuid), connection_id),"
                    " model = coalesce(CAST(:model AS text), model),"
                    " folder_id = CASE WHEN CAST(:set_folder AS boolean) THEN CAST(:folder_id AS uuid)"
                    " ELSE folder_id END,"
                    " pinned_at = CASE WHEN CAST(:pinned AS boolean) IS NULL THEN pinned_at"
                    " WHEN CAST(:pinned AS boolean) THEN coalesce(pinned_at, now()) ELSE NULL END, updated_at = now()"
                    f" WHERE id = :id RETURNING {CONVERSATION_COLUMNS}"
                ),
                changes | {"id": conversation_id},
            )
        ).one()
    return conversation_response(row)


@router.post("/conversations/{conversation_id}/rewind", response_model=schemas.Conversation)
async def rewind_conversation(
    conversation_id: uuid.UUID, body: schemas.RewindRequest, identity: Authenticated, engine: Engine, durable: Durable
) -> schemas.Conversation:
    """Make a run the last of the conversation, deleting the runs after it (CNV-004, ADR-0068)."""
    async with transaction(engine, identity) as connection:
        await find_conversation(connection, conversation_id, lock=True)
        await _refuse_while_active(connection, conversation_id)
        pending = (
            await connection.execute(
                text("SELECT pending_approvals IS NOT NULL FROM conversations WHERE id = :id"), {"id": conversation_id}
            )
        ).scalar_one()
        if pending:
            raise errors.ApiError(409, "run.interrupt_pending", "An approval is pending")
        if body.run_id is not None:
            owned = (
                await connection.execute(
                    text("SELECT 1 FROM runs WHERE id = :run AND conversation_id = :conversation"),
                    {"run": body.run_id, "conversation": conversation_id},
                )
            ).one_or_none()
            if owned is None:
                raise errors.invalid("/run_id", "not_in_conversation")
        # The first run after the kept one; its descendants follow by cascade.
        following = (
            await connection.execute(
                text(
                    "SELECT id FROM runs WHERE conversation_id = :conversation"
                    " AND parent_run_id IS NOT DISTINCT FROM CAST(:run AS uuid)"
                ),
                {"conversation": conversation_id, "run": body.run_id},
            )
        ).one_or_none()
        if following is not None:
            deleted = [
                str(row.id)
                for row in await connection.execute(
                    text(
                        "WITH RECURSIVE chain AS (SELECT id FROM runs WHERE id = :first"
                        " UNION ALL SELECT r.id FROM runs r JOIN chain c ON r.parent_run_id = c.id)"
                        " SELECT id FROM chain"
                    ),
                    {"first": following.id},
                )
            ]
            # The workflows hold the runs' content without row-level security, so
            # they go first; their IDs come from the row-level-secured runs (TEN-009).
            await durable.delete_workflows_async(deleted)
            # Messages follow by cascade; ledger entries are detached (ADR-0042).
            await connection.execute(text("DELETE FROM runs WHERE id = :id"), {"id": following.id})
        row = (
            await connection.execute(
                text(
                    "UPDATE conversations SET active_run_id = CAST(:run AS uuid), updated_at = now()"  # noqa: S608
                    f" WHERE id = :id RETURNING {CONVERSATION_COLUMNS}"
                ),
                {"run": body.run_id, "id": conversation_id},
            )
        ).one()
    return conversation_response(row)


async def _owns_folder(connection: AsyncConnection, folder_id: uuid.UUID) -> bool:
    """Whether the folder is the user's; row-level security hides the others' (TEN-006)."""
    row = (await connection.execute(text("SELECT 1 FROM folders WHERE id = :id"), {"id": folder_id})).one_or_none()
    return row is not None


@router.post(
    "/conversations/{conversation_id}/fork", status_code=status.HTTP_201_CREATED, response_model=schemas.Conversation
)
async def fork_conversation(
    conversation_id: uuid.UUID, body: schemas.ForkRequest, identity: Authenticated, engine: Engine
) -> schemas.Conversation:
    """A new conversation with copies of the runs up to `run_id`, in the same folder (CNV-005, ADR-0073)."""
    async with transaction(engine, identity) as connection:
        await find_conversation(connection, conversation_id, lock=True)
        await _refuse_while_active(connection, conversation_id)
        path = await path_runs(connection, conversation_id, body.run_id)
        if not path:
            raise errors.invalid("/run_id", "not_in_conversation")
        fork_id = uuid7()
        new_ids = {run.id: uuid7() for run in path}
        await connection.execute(
            text(
                "INSERT INTO conversations (id, tenant_id, owner_id, title, connection_id, model, folder_id,"
                " forked_from_conversation_id, forked_from_run_id, active_run_id, last_message_at, created_at,"
                " updated_at) SELECT :fork, tenant_id, owner_id, title, connection_id, model, folder_id, id, :run,"
                " NULL, now(), now(), now() FROM conversations WHERE id = :id"
            ),
            {"fork": fork_id, "run": body.run_id, "id": conversation_id},
        )
        # In path order, so that each copy's parent exists (ADR-0068).
        for run in path:
            await connection.execute(
                text(
                    "INSERT INTO runs (id, tenant_id, owner_id, conversation_id, parent_run_id, kind, status,"
                    " error_code, connection_id, model_provider, model_name, last_event_seq, created_at, started_at,"
                    " finished_at) SELECT :new, tenant_id, owner_id, :fork, CAST(:parent AS uuid), kind, status,"
                    " error_code, connection_id, model_provider, model_name, last_event_seq, created_at, started_at,"
                    " finished_at FROM runs WHERE id = :old"
                ),
                {
                    "new": new_ids[run.id],
                    "fork": fork_id,
                    "parent": None if run.parent_run_id is None else new_ids[run.parent_run_id],
                    "old": run.id,
                },
            )
            for table, columns in (
                ("conversation_messages", "seq, tenant_id, owner_id, message, text, created_at"),
                ("compaction_checkpoints", "tenant_id, owner_id, messages, created_at"),
            ):
                await connection.execute(
                    text(
                        f"INSERT INTO {table} (run_id, conversation_id, {columns})"  # noqa: S608
                        f" SELECT :new, :fork, {columns} FROM {table} WHERE run_id = :old"
                    ),
                    {"new": new_ids[run.id], "fork": fork_id, "old": run.id},
                )
        row = (
            await connection.execute(
                text(
                    f"UPDATE conversations SET active_run_id = :last WHERE id = :fork RETURNING {CONVERSATION_COLUMNS}"  # noqa: S608
                ),
                {"last": new_ids[path[-1].id], "fork": fork_id},
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
                    " SELECT id, parent_run_id, kind, status, error_code, 0 AS depth FROM runs"
                    " WHERE id = :last AND conversation_id = :conversation"
                    " UNION ALL"
                    " SELECT r.id, r.parent_run_id, r.kind, r.status, r.error_code, p.depth + 1"
                    " FROM runs r JOIN path p ON r.id = p.parent_run_id"
                    ") SELECT id, parent_run_id, kind, status, error_code FROM path ORDER BY depth DESC"
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


def run_error(run: Any, messages: Sequence[Any]) -> schemas.RunError | None:
    """Why a run failed, with the reason its stored answer keeps, such as a refusal's (UX-014, MOD-015)."""
    if run.status != "failed":
        return None
    reason: str | None = None
    for raw in reversed(messages):
        message = cast(dict[str, Any], raw) if isinstance(raw, dict) else {}
        details = message.get("provider_details")
        if message.get("kind") == "response" and isinstance(details, dict):
            found = cast(dict[str, Any], details).get("refusal") or cast(dict[str, Any], details).get("block_reason")
            if isinstance(found, str) and found:
                reason = found[:REASON_CHARS]
                break
    return schemas.RunError(code=run.error_code or "internal.error", reason=reason)


def message_id(run_id: uuid.UUID, position: int) -> uuid.UUID:
    """The ID of a run's message in history, from the run and its position in it (API-003)."""
    return uuid.uuid5(run_id, f"message-{position}")


@router.get("/conversations/{conversation_id}/messages", response_model=schemas.MessagePage)
async def list_messages(
    conversation_id: uuid.UUID,
    identity: Authenticated,
    engine: Engine,
    cursor: str | None = None,
    limit: Limit = 50,
) -> schemas.MessagePage:
    start = 0 if cursor is None else decode_cursor(cursor)
    if not isinstance(start, int) or start < 0:
        raise errors.invalid("cursor", "invalid")
    async with transaction(engine, identity) as connection:
        conversation = await find_conversation(connection, conversation_id)
        last = conversation.active_run_id
        if last is None:
            return schemas.MessagePage(items=[], runs=[], next_cursor=None)
        path = await path_runs(connection, conversation_id, last)
        if not path:
            raise errors.not_found()
        stored = await stored_messages(connection, [run.id for run in path])
        costs = await run_costs(connection, [run.id for run in path])
    flattened: list[tuple[Any, dict[str, Any]]] = []
    for run in path:
        model_messages = ModelMessagesTypeAdapter.validate_python(stored[run.id])
        for position, message in enumerate(AGUIAdapter.dump_messages(model_messages)):
            dumped = message.model_dump(mode="json", by_alias=True, exclude_none=True)
            # The same ID on every read.
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
                    cost=costs[run.id],
                    error=run_error(run, stored[run.id]),
                )
            )
        runs[-1].message_ids.append(str(message["id"]))
    next_cursor = encode_cursor(start + limit) if start + limit < len(flattened) else None
    return schemas.MessagePage(items=[message for _, message in page], runs=runs, next_cursor=next_cursor)
