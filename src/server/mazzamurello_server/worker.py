"""The worker: executes runs as durable workflows (AGT-009, AGT-010, ADR-0034, ADR-0052).

Each run is a DBOS workflow named after the run. It sets the request context
from the tenant and user of its input, runs the agent on the path of the
conversation, and writes the run's AG-UI events to the workflow's stream as
they are produced.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import uuid
from collections.abc import AsyncIterable
from typing import Any

from dbos import DBOS, DBOSConfig
from pydantic_ai import Agent, RunContext
from pydantic_ai.durable_exec.dbos import DBOSDurability
from pydantic_ai.exceptions import ModelAPIError, ModelHTTPError
from pydantic_ai.messages import AgentStreamEvent, ModelMessage, ModelMessagesTypeAdapter
from pydantic_ai.ui.ag_ui import AGUIEventStream
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from mazzamurello_server.config import WorkerConfiguration
from mazzamurello_server.conversations import path_runs, stored_messages
from mazzamurello_server.database import Identity, create_engine, transaction
from mazzamurello_server.durable import (
    APPLICATION_NAME,
    APPLICATION_VERSION,
    EVENTS_STREAM,
    RUN_QUEUE,
    RUN_WORKFLOW,
)
from mazzamurello_server.gateway import Gateway, ModelUnavailableError, RunDeps, model_reference, store_messages
from mazzamurello_server.workflow_input import RunWorkflowInput

logger = logging.getLogger(__name__)

RETENTION_INTERVAL_SECONDS = 3600
QUEUE_POLLING_SECONDS = 0.2
# Until instructions and skills arrive (ADR-0044, ADR-0052).
INSTRUCTIONS = (
    "You are Mazzamurello, an assistant for the people of a household. "
    "Answer helpfully, clearly and briefly, in the language the user writes in."
)


class _Worker:
    """What the workflows of this process share: set once, before DBOS launches."""

    engine: AsyncEngine | None = None
    secret_key: bytes = b""


_WORKER = _Worker()
# The AG-UI encoder of each run executing in this process; it keeps the
# message identities of the run between model requests.
_ENCODERS: dict[str, AGUIEventStream[Any, Any]] = {}
# Events written to each run's stream by this process.
_WRITTEN: dict[str, int] = {}


async def _write(run_id: str, event: dict[str, Any]) -> None:
    await DBOS.write_stream_async(EVENTS_STREAM, event)
    _WRITTEN[run_id] = _WRITTEN.get(run_id, 0) + 1


def _encoded(event: Any) -> dict[str, Any]:
    dumped: dict[str, Any] = event.model_dump(mode="json", by_alias=True, exclude_none=True)
    return dumped


async def _handle_events(ctx: RunContext[RunDeps], events: AsyncIterable[AgentStreamEvent]) -> None:
    """Encode the agent's events as AG-UI events and append them to the run's stream, live."""
    run_id = str(ctx.deps.run_id)
    encoder = _ENCODERS[run_id]
    async for event in events:
        async for encoded in encoder.handle_event(event):
            await _write(run_id, _encoded(encoded))


agent = Agent(
    model_reference("instance", "unset"),
    name="mazzamurello",
    deps_type=RunDeps,
    instructions=INSTRUCTIONS,
    capabilities=[Gateway(), DBOSDurability(event_stream_handler=_handle_events)],
)


def _engine() -> AsyncEngine:
    if _WORKER.engine is None:
        raise RuntimeError("the worker is not started")
    return _WORKER.engine


async def _set_status(identity: Identity, run_id: uuid.UUID, status: str, error_code: str | None = None) -> None:
    """Move a run that is still queued or running; a cancelled run stays cancelled."""
    started = "started_at = coalesce(started_at, now())," if status == "running" else ""
    finished = "finished_at = now()," if status in ("completed", "failed") else ""
    async with transaction(_engine(), identity) as connection:
        await connection.execute(
            text(
                f"UPDATE runs SET {started} {finished} status = :status, error_code = :error_code"  # noqa: S608
                " WHERE id = :id AND status IN ('queued', 'running')"
            ),
            {"id": run_id, "status": status, "error_code": error_code},
        )


async def _history(identity: Identity, conversation_id: uuid.UUID, parent: uuid.UUID | None) -> list[ModelMessage]:
    """The messages of the path that the run continues, and nothing else (CNV-002)."""
    if parent is None:
        return []
    async with transaction(_engine(), identity) as connection:
        path = await path_runs(connection, conversation_id, parent)
        stored = await stored_messages(connection, [run.id for run in path])
    return [message for run in path for message in ModelMessagesTypeAdapter.validate_python(stored[run.id])]


def _error_code(error: BaseException) -> str:
    if isinstance(error, ModelUnavailableError):
        return "model.unavailable"
    if isinstance(error, ModelHTTPError):
        return "model.request_failed"
    if isinstance(error, ModelAPIError):
        return "model.unavailable"
    return "internal.error"


@DBOS.workflow(name=RUN_WORKFLOW)
async def run_workflow(serialized_input: str) -> None:
    run = RunWorkflowInput.from_json(serialized_input)
    identity = Identity(
        session_id=uuid.UUID(int=0),
        user_id=uuid.UUID(run.user_id),
        tenant_id=uuid.UUID(run.tenant_id),
        role=run.role,
        instance_admin=run.instance_admin,
    )
    run_id, conversation_id = uuid.UUID(run.run_id), uuid.UUID(run.conversation_id)
    await _set_status(identity, run_id, "running")
    history = await _history(
        identity, conversation_id, None if run.parent_run_id is None else uuid.UUID(run.parent_run_id)
    )
    async with transaction(_engine(), identity) as connection:
        attribution = (
            await connection.execute(text("SELECT model_provider, model_name FROM runs WHERE id = :id"), {"id": run_id})
        ).one()
    deps = RunDeps(
        engine=_engine(),
        identity=identity,
        secret_key=_WORKER.secret_key,
        conversation_id=conversation_id,
        run_id=run_id,
        history_length=len(history),
        provider=attribution.model_provider or "",
        model=attribution.model_name or "",
    )
    encoder: AGUIEventStream[Any, Any] = AGUIEventStream(thread_id=run.conversation_id, run_id=run.run_id)
    _ENCODERS[run.run_id] = encoder
    try:
        await _execute(run, identity, deps, history, encoder)
    except Exception as error:
        code = _error_code(error)
        logger.exception("run %s failed: %s", run.run_id, code)
        await _write_error(run.run_id, code)
        await _set_status(identity, run_id, "failed", code)
    except BaseException:
        # Cancelled: the API has recorded it, and the stream ends with the workflow (CNV-003).
        _ENCODERS.pop(run.run_id, None)
        _WRITTEN.pop(run.run_id, None)
        raise
    _ENCODERS.pop(run.run_id, None)
    async with transaction(_engine(), identity) as connection:
        await connection.execute(
            text("UPDATE runs SET last_event_seq = :count WHERE id = :id"),
            {"id": run_id, "count": _WRITTEN.pop(run.run_id, 0)},
        )
    await DBOS.close_stream_async(EVENTS_STREAM)


async def _execute(
    run: RunWorkflowInput,
    identity: Identity,
    deps: RunDeps,
    history: list[ModelMessage],
    encoder: AGUIEventStream[Any, Any],
) -> None:
    async for event in encoder.before_stream():
        await _write(run.run_id, _encoded(event))
    try:
        result = await agent.run(
            run.user_text,
            message_history=history,
            model=model_reference(run.model_scope, run.model_id),
            deps=deps,
            run_id=run.run_id,
            conversation_id=run.conversation_id,
        )
    except (ModelUnavailableError, ModelAPIError) as error:
        code = _error_code(error)
        logger.warning("run %s failed: %s", run.run_id, code)
        await _write_error(run.run_id, code)
        await _set_status(identity, deps.run_id, "failed", code)
        return
    await store_messages(deps, result.new_messages())
    async for event in encoder.after_stream():
        await _write(run.run_id, _encoded(event))
    await _set_status(identity, deps.run_id, "completed")


async def _write_error(run_id: str, code: str) -> None:
    await _write(run_id, {"type": "RUN_ERROR", "message": code, "code": code})


async def _apply_retention(days: int) -> None:
    """Delete the durable workflows of runs that finished more than `days` days ago (TEN-009)."""
    async with transaction(_engine(), None) as connection:
        expired = [
            str(row[0])
            for row in await connection.execute(text("SELECT retention_expired_runs(:days)"), {"days": days})
        ]
    if not expired:
        return
    existing = [status.workflow_id for status in await DBOS.list_workflows_async(workflow_ids=expired)]
    if existing:
        await DBOS.delete_workflows_async(existing)
        logger.info("deleted %d expired workflows", len(existing))


async def _retention_loop(days: int) -> None:
    while True:
        try:
            await _apply_retention(days)
        except Exception:
            logger.exception("retention failed")
        await asyncio.sleep(RETENTION_INTERVAL_SECONDS)


async def _serve(configuration: WorkerConfiguration) -> None:
    DBOS.launch()
    await DBOS.register_queue_async(RUN_QUEUE, partition_concurrency=1, polling_interval_sec=QUEUE_POLLING_SECONDS)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, stop.set)
    retention = asyncio.create_task(_retention_loop(configuration.run_retention_days))
    await stop.wait()
    retention.cancel()


def run_worker(configuration: WorkerConfiguration) -> None:
    logging.basicConfig(level=logging.INFO)
    _WORKER.engine = create_engine(configuration.database_url)
    _WORKER.secret_key = configuration.secret_key
    DBOS(
        config=DBOSConfig(
            name=APPLICATION_NAME,
            system_database_url=configuration.database_url,
            application_version=APPLICATION_VERSION,
            # mzm_app never creates or alters tables (ADR-0052).
            run_migrations=False,
            notification_listener_polling_interval_sec=0.2,
        )
    )
    try:
        asyncio.run(_serve(configuration))
    finally:
        DBOS.destroy()
