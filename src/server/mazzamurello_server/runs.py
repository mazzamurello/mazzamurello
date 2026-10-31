"""Runs: starting them, following their events, stopping them (API-004, AGT-009, CNV-003).

The API never executes a run: it records it, enqueues its durable workflow
for a worker, and streams the AG-UI events the workflow writes, as
Server-Sent Events whose `id` is the sequence number (ADR-0032, ADR-0034).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any, cast
from urllib.parse import urlsplit

from dbos import DBOSClient
from fastapi import APIRouter, Header, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from mazzamurello_server import errors, schemas
from mazzamurello_server.auth import Authenticated, Engine
from mazzamurello_server.conversations import Durable, find_conversation
from mazzamurello_server.database import UNIQUE_VIOLATION, Identity, sqlstate, transaction
from mazzamurello_server.durable import APPLICATION_VERSION, EVENTS_STREAM, RUN_QUEUE, RUN_WORKFLOW
from mazzamurello_server.workflow_input import RunWorkflowInput

router = APIRouter()

RUN_COLUMNS = (
    "id, conversation_id, parent_run_id, kind, status, error_code, model_provider, model_name, last_event_seq,"
    " created_at, started_at, finished_at"
)
FINAL_STATUSES = frozenset({"completed", "failed", "cancelled", "interrupted"})
TERMINAL_EVENTS = frozenset({"RUN_FINISHED", "RUN_ERROR"})
SSE_MEDIA_TYPE = "text/event-stream"


def run_response(row: Any) -> schemas.Run:
    model = None
    if row.model_provider is not None and row.model_name is not None:
        model = schemas.ModelRef(provider=row.model_provider, model=row.model_name)
    return schemas.Run(
        id=row.id,
        conversation_id=row.conversation_id,
        parent_run_id=row.parent_run_id,
        kind=row.kind,
        status=row.status,
        error_code=row.error_code,
        model=model,
        last_event_seq=row.last_event_seq or 0,
        created_at=row.created_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
    )


async def find_run(connection: AsyncConnection, run_id: uuid.UUID) -> Any:
    """The run, if the user owns it; others' are reported as not found (TEN-006)."""
    row = (
        await connection.execute(text(f"SELECT {RUN_COLUMNS} FROM runs WHERE id = :id"), {"id": run_id})  # noqa: S608
    ).one_or_none()
    if row is None:
        raise errors.not_found()
    return row


def _user_text(run_input: schemas.RunInput) -> str:
    """The text of the last message, which must come from the user (ADR-0031)."""
    last = run_input.messages[-1]
    if last.role != "user":
        raise errors.invalid(f"/messages/{len(run_input.messages) - 1}/role", "must_be_user")
    content: Any = last.content
    if isinstance(content, list):
        texts: list[str] = []
        for part in cast(list[Any], content):
            if isinstance(part, dict):
                item = cast(dict[str, Any], part)
                if item.get("type") == "text":
                    texts.append(str(item.get("text", "")))
        content = "".join(texts)
    if not isinstance(content, str) or not content:
        raise errors.invalid(f"/messages/{len(run_input.messages) - 1}/content", "must_be_text")
    return content


def _sse(seq: int, event: dict[str, Any]) -> str:
    return f"id: {seq}\nevent: {event.get('type', '')}\ndata: {json.dumps(event, separators=(',', ':'))}\n\n"


async def _workflow_exists(durable: DBOSClient, run_id: uuid.UUID) -> bool:
    return bool(await durable.list_workflows_async(workflow_ids=[str(run_id)]))


async def stream_events(
    durable: DBOSClient, engine: AsyncEngine, identity: Identity, run_id: uuid.UUID, after: int
) -> AsyncIterator[str]:
    """The run's events after sequence number `after`, following the run until it ends."""
    seq = 0
    last_type = None
    async for value in durable.read_stream_async(str(run_id), EVENTS_STREAM):
        seq += 1
        event: dict[str, Any] = value
        last_type = event.get("type")
        if seq > after:
            yield _sse(seq, event)
    if last_type in TERMINAL_EVENTS:
        return
    # A stopped workflow, or one that ended without its last event, still ends
    # its stream visibly (CNV-003, AGT-010).
    async with transaction(engine, identity) as connection:
        run = await find_run(connection, run_id)
    if run.status in FINAL_STATUSES and seq + 1 > after:
        code = "run.cancelled" if run.status == "cancelled" else (run.error_code or "run.worker_lost")
        yield _sse(seq + 1, {"type": "RUN_ERROR", "message": code, "code": code})


def _streaming(
    durable: DBOSClient, engine: AsyncEngine, identity: Identity, run_id: uuid.UUID, after: int
) -> StreamingResponse:
    return StreamingResponse(
        stream_events(durable, engine, identity, run_id, after),
        media_type=SSE_MEDIA_TYPE,
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


async def _default_model(connection: AsyncConnection) -> Any:
    """The tenant's default model, or else the instance's (ADR-0051); row-level security scopes both."""
    return (
        await connection.execute(
            text(
                "SELECT scope, id, base_url, model FROM ("
                " SELECT 'tenant' AS scope, 1 AS rank, id, base_url, model FROM tenant_models WHERE is_default"
                " UNION ALL"
                " SELECT 'instance', 2, id, base_url, model FROM instance_models WHERE is_default"
                ") defaults ORDER BY rank LIMIT 1"
            )
        )
    ).one_or_none()


@router.post("/conversations/{conversation_id}/runs")
async def start_run(
    conversation_id: uuid.UUID, body: schemas.RunInput, identity: Authenticated, engine: Engine, durable: Durable
) -> StreamingResponse:
    if body.thread_id != conversation_id:
        raise errors.invalid("/threadId", "must_match_conversation")
    if body.resume:
        # No interrupt can be pending yet: there are no tools that ask for approval.
        raise errors.ApiError(422, "approval.invalid", "No interrupt to answer")
    user_text = _user_text(body)
    try:
        async with transaction(engine, identity) as connection:
            conversation = await find_conversation(connection, conversation_id, lock=True)
            existing = (
                await connection.execute(
                    text("SELECT 1 FROM runs WHERE id = :id AND conversation_id = :conversation"),
                    {"id": body.run_id, "conversation": conversation_id},
                )
            ).one_or_none()
            if existing is not None:
                # A retried request: the same run's stream, from the beginning.
                return _streaming(durable, engine, identity, body.run_id, 0)
            active = (
                await connection.execute(
                    text("SELECT 1 FROM runs WHERE conversation_id = :id AND status IN ('queued', 'running')"),
                    {"id": conversation_id},
                )
            ).one_or_none()
            if active is not None:
                raise errors.ApiError(409, "run.in_progress", "Run in progress")
            parent = conversation.active_run_id
            if body.parent_run_id is not None:
                found = (
                    await connection.execute(
                        text("SELECT id FROM runs WHERE id = :id AND conversation_id = :conversation"),
                        {"id": body.parent_run_id, "conversation": conversation_id},
                    )
                ).one_or_none()
                if found is None:
                    raise errors.not_found()
                parent = body.parent_run_id
            model = await _default_model(connection)
            if model is None:
                raise errors.ApiError(409, "model.unavailable", "No default model")
            await connection.execute(
                text(
                    "INSERT INTO runs (id, tenant_id, owner_id, conversation_id, parent_run_id, kind, status,"
                    " model_provider, model_name, last_event_seq, created_at)"
                    " VALUES (:id, :tenant_id, :owner_id, :conversation, :parent, 'message', 'queued', :provider,"
                    " :model, 0, now())"
                ),
                {
                    "id": body.run_id,
                    "tenant_id": identity.tenant_id,
                    "owner_id": identity.user_id,
                    "conversation": conversation_id,
                    "parent": parent,
                    "provider": urlsplit(str(model.base_url)).netloc,
                    "model": model.model,
                },
            )
            await connection.execute(
                text("UPDATE conversations SET active_run_id = :run, updated_at = now() WHERE id = :id"),
                {"run": body.run_id, "id": conversation_id},
            )
    except DBAPIError as error:
        if sqlstate(error) == UNIQUE_VIOLATION:
            # The run ID is taken by a run the user cannot see, or another run started meanwhile.
            raise errors.conflict() from None
        raise
    workflow_input = RunWorkflowInput(
        tenant_id=str(identity.tenant_id),
        user_id=str(identity.user_id),
        role=identity.role,
        instance_admin=identity.instance_admin,
        conversation_id=str(conversation_id),
        run_id=str(body.run_id),
        parent_run_id=None if parent is None else str(parent),
        user_text=user_text,
        model_scope=model.scope,
        model_id=str(model.id),
    )
    await durable.enqueue_async(
        {
            "queue_name": RUN_QUEUE,
            "workflow_name": RUN_WORKFLOW,
            "workflow_id": str(body.run_id),
            # One run at a time per conversation (ADR-0034).
            "queue_partition_key": str(conversation_id),
            "app_version": APPLICATION_VERSION,
        },
        workflow_input.to_json(),
    )
    return _streaming(durable, engine, identity, body.run_id, 0)


@router.get("/runs/{run_id}", response_model=schemas.Run)
async def get_run(run_id: uuid.UUID, identity: Authenticated, engine: Engine) -> schemas.Run:
    async with transaction(engine, identity) as connection:
        return run_response(await find_run(connection, run_id))


@router.post("/runs/{run_id}/cancel", response_model=schemas.Run)
async def cancel_run(run_id: uuid.UUID, identity: Authenticated, engine: Engine, durable: Durable) -> schemas.Run:
    async with transaction(engine, identity) as connection:
        run = await find_run(connection, run_id)
    if run.status in FINAL_STATUSES:
        return run_response(run)
    # A queued run never starts; a running one starts no further model or tool calls (CNV-003).
    await durable.cancel_workflow_async(str(run_id))
    async with transaction(engine, identity) as connection:
        await connection.execute(
            text(
                "UPDATE runs SET status = 'cancelled', finished_at = now()"
                " WHERE id = :id AND status IN ('queued', 'running')"
            ),
            {"id": run_id},
        )
        return run_response(await find_run(connection, run_id))


@router.get("/runs/{run_id}/events")
async def stream_run_events(
    run_id: uuid.UUID,
    identity: Authenticated,
    engine: Engine,
    durable: Durable,
    last_event_id: Annotated[int | None, Header(ge=0)] = None,
    after: Annotated[int | None, Query(ge=0)] = None,
) -> StreamingResponse:
    async with transaction(engine, identity) as connection:
        await find_run(connection, run_id)
    # Workflows of old runs are deleted after the retention period (ADR-0052).
    if not await _workflow_exists(durable, run_id):
        raise errors.not_found()
    return _streaming(durable, engine, identity, run_id, last_event_id if last_event_id is not None else after or 0)
