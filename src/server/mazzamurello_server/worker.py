"""The worker: executes runs as durable workflows (AGT-009, AGT-010, ADR-0034, ADR-0052).

Each run is a DBOS workflow named after the run. It sets the request context
from the tenant and user of its input, runs the agent on the path of the
conversation, and writes the run's AG-UI events to the workflow's stream as
they are produced.
"""

from __future__ import annotations

import asyncio
import json
import logging
import signal
import uuid
from collections.abc import AsyncIterable
from dataclasses import replace
from typing import Any, cast

from dbos import DBOS, DBOSConfig
from pydantic_ai import Agent, DeferredToolRequests, DeferredToolResults, RunContext
from pydantic_ai.durable_exec.dbos import DBOSDurability
from pydantic_ai.exceptions import ContentFilterError, ModelAPIError, ModelHTTPError
from pydantic_ai.messages import (
    AgentStreamEvent,
    FunctionToolResultEvent,
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    ModelSettingsDeltaEvent,
    TextContent,
    UserContent,
    UserPromptPart,
    repair_messages,
)
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.toolsets import FunctionToolset
from pydantic_ai.ui.ag_ui import AGUIEventStream
from pydantic_ai_harness.ask_user import AskUser
from pydantic_ai_harness.filesystem import FileSystem
from pydantic_ai_harness.planning import Planning
from pydantic_ai_harness.shell import Shell
from pydantic_ai_harness.tool_output_limits import ToolOutputLimits
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from mazzamurello_server.config import WorkerConfiguration
from mazzamurello_server.conversations import delete_everything, path_runs, stored_messages
from mazzamurello_server.database import Identity, create_engine, transaction
from mazzamurello_server.durable import (
    APPLICATION_NAME,
    APPLICATION_VERSION,
    EVENTS_STREAM,
    RUN_QUEUE,
    RUN_WORKFLOW,
)
from mazzamurello_server.gateway import (
    Gateway,
    ModelUnavailableError,
    RunDeps,
    connection_model,
    model_reference,
    readable_text,
    record_usage,
    store_messages,
)
from mazzamurello_server.offers import TOOLS as OFFER_TOOLS
from mazzamurello_server.plans import ConversationPlanStore, plan_steps
from mazzamurello_server.questions import REQUESTS, asks_user, interrupts
from mazzamurello_server.sandbox import CommandPurposes, SandboxDriver, SandboxWorkspace, sandbox_ref, stop_sandbox
from mazzamurello_server.settings import BUILT_IN_BASE_INSTRUCTIONS
from mazzamurello_server.web_tools import TOOLS as WEB_TOOLS
from mazzamurello_server.workflow_input import RunWorkflowInput

logger = logging.getLogger(__name__)

RETENTION_INTERVAL_SECONDS = 3600
# The driver caps output already; the shell tool must not cut it before the
# output limits keep the rest in the workspace (AGT-014).
SHELL_OUTPUT_CHARS = 64 * 1024 * 1024
QUEUE_POLLING_SECONDS = 0.2
# The most of a provider's refusal a run's error repeats.
REASON_CHARS = 500
# The sandbox, not a list of command names, decides what a command can do (ADR-0062).
SHELL = Shell(max_output_chars=SHELL_OUTPUT_CHARS, denied_commands=())
FILE_SYSTEM = FileSystem()


def _tool_names(capability: Shell[Any] | FileSystem[Any]) -> frozenset[str]:
    toolset = capability.get_toolset()
    if not isinstance(toolset, FunctionToolset):
        raise TypeError(f"{type(capability).__name__} has no tools of its own")
    return frozenset(cast("FunctionToolset[Any]", toolset).tools)


# The tools a user can switch off, and the names the model knows them by (CNV-013, ADR-0081).
TOOL_NAMES: dict[str, frozenset[str]] = {
    "web_search": frozenset({"web_search"}),
    "read_page": frozenset({"read_page"}),
    "shell": _tool_names(SHELL),
    "file_system": _tool_names(FILE_SYSTEM),
    "offer_download": frozenset({"offer_download"}),
}
# The working instructions, each about tools that must be on (CNV-014, ADR-0081).
# What the workspace keeps (AGT-022, ADR-0076).
WORKSPACE_INSTRUCTIONS = (
    "Your commands run in the user's sandbox, starting in /scratch. Everything outside /workspace,"
    " /scratch included, and anything you install in the system, is discarded when the sandbox stops."
    " Work in /scratch. Put in /workspace only what the user will want again: scripts, results and notes,"
    " each piece of work in a folder of its own with a README.md that says what it is and how to make it"
    " again. Do not keep data there that can be fetched again: write down where it comes from instead."
    " Look in /workspace for earlier work before starting again. Files the user attaches are in"
    " /workspace/uploads/."
)
DOWNLOAD_INSTRUCTIONS = "To give the user a file of /workspace, offer it with offer_download."
# The sandbox toolbox (SBX-021, ADR-0080).
TOOLBOX_INSTRUCTIONS = (
    "The sandbox has these tools, ready without installing anything: for PDFs, pdftotext, pdftoppm,"
    " pdfinfo and qpdf; markitdown, which turns PDF, Word, Excel, PowerPoint and HTML files into Markdown"
    " for you to read; pandoc for documents, with the DejaVu, Liberation and Noto fonts; ImageMagick"
    " (magick) for images, ffmpeg and ffprobe for audio and video; jq, sqlite3, file, zip and unzip; Node.js (node)"
    " with npm. python3 has pandas, numpy, matplotlib, Pillow, pypdf, python-docx, openpyxl and python-pptx."
    " There is no office suite and no text recognition. Use these tools before installing anything, and"
    " install only what is missing: it lasts for this answer only."
)


def instructions(ctx: RunContext[RunDeps]) -> str:
    """The base instructions, the working instructions for the tools that are on, then the user's additions."""
    deps = ctx.deps
    off = deps.disabled_tools if deps.tools else frozenset(TOOL_NAMES)
    working = [
        WORKSPACE_INSTRUCTIONS if not {"shell", "file_system"} <= off else "",
        DOWNLOAD_INSTRUCTIONS if "offer_download" not in off else "",
        TOOLBOX_INSTRUCTIONS if "shell" not in off else "",
    ]
    base = BUILT_IN_BASE_INSTRUCTIONS if deps.base_instructions is None else deps.base_instructions
    parts = [base, " ".join(part for part in working[:2] if part), working[2], deps.additional_instructions or ""]
    return "\n\n".join(part for part in parts if part.strip())


class _Worker:
    """What the workflows of this process share: set once, before DBOS launches."""

    engine: AsyncEngine | None = None
    secret_key: bytes = b""
    sandboxd_url: str = ""
    sandboxd_token: str = ""
    search_url: str = ""


_WORKER = _Worker()
# The AG-UI encoder of each run executing in this process; it keeps the
# message identities of the run between model requests.
_ENCODERS: dict[str, AGUIEventStream[Any, Any]] = {}
# Events written to each run's stream by this process.
_WRITTEN: dict[str, int] = {}
# The title request of each first run executing in this process, until announced (CNV-006).
_TITLES: dict[str, asyncio.Task[str | None]] = {}


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
        # A change of reasoning level is the history's business, not the client's (ADR-0081).
        if isinstance(event, ModelSettingsDeltaEvent):
            continue
        async for encoded in encoder.handle_event(event):
            # The provider's own form of the reasoning stays with the stored messages: clients never send
            # history back (ADR-0031).
            if encoded.type == "REASONING_ENCRYPTED_VALUE":
                continue
            await _write(run_id, _encoded(encoded))
        # The task list, as it changes (UX-009, ADR-0083).
        if isinstance(event, FunctionToolResultEvent) and event.part.tool_name in PLANNING_TOOLS:
            steps = plan_steps([item.model_dump(mode="json") for item in await _plan_store(ctx).get_items()])
            await _write(run_id, {"type": "CUSTOM", "name": "mzm.plan", "value": {"steps": steps}})
        title = _TITLES.get(run_id)
        if title is not None and title.done():
            await _announce_title(run_id)


async def _announce_title(run_id: str) -> None:
    """Wait for the run's title request, and name the conversation on the run's stream (CNV-006, ADR-0073)."""
    title = await _TITLES.pop(run_id)
    if title is not None:
        await _write(run_id, {"type": "CUSTOM", "name": "mzm.title", "value": {"title": title}})


def _plan_store(ctx: RunContext[RunDeps]) -> ConversationPlanStore:
    """The conversation's task list, which lasts from run to run (UX-009, ADR-0083)."""
    return ConversationPlanStore(ctx.deps.engine, ctx.deps.identity, ctx.deps.conversation_id)


# The tools of `Planning` that change or read the task list.
PLANNING_TOOLS = frozenset(
    {"write_plan", "read_plan", "add_task", "update_task_status", "update_task_statuses", "remove_task"}
)

# A run ends with the answer, or with the questions it asks the user (ADR-0083).
agent = Agent[RunDeps, str | DeferredToolRequests](
    model_reference(str(uuid.UUID(int=0)), "unset"),
    name="mazzamurello",
    deps_type=RunDeps,
    # A run may end to ask the user (AGT-015, ADR-0083).
    output_type=[str, DeferredToolRequests],
    instructions=instructions,
    # Web search through the instance's search service, page reading in the sandbox (ADR-0075).
    # And offering a file of the workspace to download (AGT-023, ADR-0079).
    tools=(*WEB_TOOLS, *OFFER_TOOLS),
    capabilities=[
        Gateway(),
        # The user's sandbox, and the harness's tools that work in it (AGT-011, ADR-0035).
        SandboxWorkspace(),
        # Each sandbox command says what it is for (UX-003, ADR-0085).
        CommandPurposes(),
        SHELL,
        FILE_SYSTEM,
        # Large results reach the model bounded; the rest stays in the workspace (AGT-014).
        ToolOutputLimits(),
        # Questions to the user end the run, and the answer starts the next one; the task list lasts
        # from run to run (AGT-015, UX-009, ADR-0083).
        AskUser(answerer=None),
        Planning(store_resolver=_plan_store),
        DBOSDurability(event_stream_handler=_handle_events),
    ],
)


def _engine() -> AsyncEngine:
    if _WORKER.engine is None:
        raise RuntimeError("the worker is not started")
    return _WORKER.engine


async def _set_status(identity: Identity, run_id: uuid.UUID, status: str, error_code: str | None = None) -> None:
    """Move a run that is still queued or running; a cancelled run stays cancelled."""
    started = "started_at = coalesce(started_at, now())," if status == "running" else ""
    finished = "finished_at = now()," if status in ("completed", "failed", "interrupted") else ""
    async with transaction(_engine(), identity) as connection:
        await connection.execute(
            text(
                f"UPDATE runs SET {started} {finished} status = :status, error_code = :error_code"  # noqa: S608
                " WHERE id = :id AND status IN ('queued', 'running')"
            ),
            {"id": run_id, "status": status, "error_code": error_code},
        )


async def _history(
    identity: Identity, conversation_id: uuid.UUID, parent: uuid.UUID | None, *, answering: bool = False
) -> list[ModelMessage]:
    """The messages of the path that the run continues, and nothing else (CNV-002)."""
    if parent is None:
        return []
    async with transaction(_engine(), identity) as connection:
        path = await path_runs(connection, conversation_id, parent)
        # The latest compaction on the path replaces the history before its run (ADR-0041).
        checkpoint = (
            await connection.execute(
                text("SELECT run_id, messages FROM compaction_checkpoints WHERE run_id = ANY(:ids)"),
                {"ids": [run.id for run in path]},
            )
        ).all()
        checkpoints = {row.run_id: row.messages for row in checkpoint}
        start = max((index for index, run in enumerate(path) if run.id in checkpoints), default=None)
        stored = await stored_messages(connection, [run.id for run in path])
    history: list[ModelMessage] = []
    if start is not None:
        history = list(ModelMessagesTypeAdapter.validate_python(checkpoints[path[start].id]))
        path = path[start:]
    history += [message for run in path for message in ModelMessagesTypeAdapter.validate_python(stored[run.id])]
    # A run that failed or was stopped while a tool worked left its call without a result: the
    # model reads it as interrupted, and the conversation goes on (CNV-018). The questions a run
    # that answers them continues are left to their answers (ADR-0083).
    return repair_messages(history, repair_last_response=not answering)


def _error_code(error: BaseException) -> str:
    if isinstance(error, ModelUnavailableError):
        return "model.unavailable"
    if isinstance(error, ContentFilterError):
        return "model.refused"
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
        identity,
        conversation_id,
        None if run.parent_run_id is None else uuid.UUID(run.parent_run_id),
        answering=run.answers is not None,
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
        sandboxd_url=_WORKER.sandboxd_url,
        sandboxd_token=_WORKER.sandboxd_token,
        search_url=_WORKER.search_url,
        emit=lambda event: _write(run.run_id, event),
        reasoning=run.reasoning,
        disabled_tools=frozenset(run.disabled_tools),
        withheld_tools=frozenset(name for group in run.disabled_tools for name in TOOL_NAMES.get(group, ())),
        base_instructions=run.base_instructions,
        additional_instructions=run.additional_instructions,
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
        # Cancelled: the API has recorded it and stops the sandbox, and the stream ends with the workflow (CNV-003).
        _ENCODERS.pop(run.run_id, None)
        _WRITTEN.pop(run.run_id, None)
        raise
    # The sandbox ends with the answer, and whatever it started with it (SBX-018, ADR-0078).
    await _end_sandbox(deps)
    _ENCODERS.pop(run.run_id, None)
    async with transaction(_engine(), identity) as connection:
        await connection.execute(
            text("UPDATE runs SET last_event_seq = :count WHERE id = :id"),
            {"id": run_id, "count": _WRITTEN.pop(run.run_id, 0)},
        )
    await DBOS.close_stream_async(EVENTS_STREAM)


# Labels the part of a user's message that lists its attachments, apart from what they wrote (CNV-017).
ATTACHMENTS_ORIGIN = "mazzamurello.attachments"


def _user_prompt(run: RunWorkflowInput) -> str | list[UserContent] | None:
    """The user's message, with the files attached to it, which the model reads with their paths and sizes."""
    if run.answers is not None:
        # The answers to the questions are the user's input (ADR-0083).
        return None
    if not run.attachments:
        return run.user_text
    lines = "\n".join(f"- /workspace/{item['path']} ({item['size']} bytes)" for item in run.attachments)
    listing = TextContent(
        f"Files the user attached to this message, in the conversation's workspace:\n{lines}",
        metadata={"origin": ATTACHMENTS_ORIGIN, "attachments": run.attachments},
    )
    return [run.user_text, listing]


async def _end_sandbox(deps: RunDeps) -> None:
    try:
        await stop_sandbox(deps)
    except Exception:
        # The driver's idle limit removes it later (SBX-018).
        logger.warning("run %s: its sandbox could not be stopped", deps.run_id)


async def _execute(
    run: RunWorkflowInput,
    identity: Identity,
    deps: RunDeps,
    history: list[ModelMessage],
    encoder: AGUIEventStream[Any, Any],
) -> None:
    async for event in encoder.before_stream():
        await _write(run.run_id, _encoded(event))
    if run.parent_run_id is None and not run.temporary:
        # The title is asked for alongside the answer, from the first message (CNV-006, ADR-0073);
        # the step's place in the workflow is taken here, before the agent's.
        _TITLES[run.run_id] = asyncio.create_task(_title(run, replace(deps, emit=None)))
    try:
        result = await agent.run(
            _user_prompt(run),
            message_history=history,
            model=model_reference(run.connection_id, run.model),
            deps=deps,
            run_id=run.run_id,
            conversation_id=run.conversation_id,
            # The conversation's own sandbox, whatever an earlier reference in its history names (ADR-0078).
            workspace=sandbox_ref(str(identity.tenant_id), str(identity.user_id), run.conversation_id),
            deferred_tool_results=None if run.answers is None else DeferredToolResults(calls=run.answers),
        )
    except (ModelUnavailableError, ModelAPIError, ContentFilterError) as error:
        code = _error_code(error)
        logger.warning("run %s failed: %s", run.run_id, code)
        if run.run_id in _TITLES:
            await _announce_title(run.run_id)
        await _write_error(run.run_id, code, _reason(error))
        await _set_status(identity, deps.run_id, "failed", code)
        return
    except BaseException:
        if (title := _TITLES.pop(run.run_id, None)) is not None:
            title.cancel()
        raise
    await store_messages(deps, result.new_messages())
    if run.run_id in _TITLES:
        await _announce_title(run.run_id)
    output = result.output
    pending = REQUESTS.dump_python(output, mode="json") if isinstance(output, DeferredToolRequests) else None
    if isinstance(output, DeferredToolRequests) and not asks_user(output):
        raise RuntimeError("the run left calls that are not questions to the user")
    if pending is not None:
        # The run waits for the user's answer, which the next run brings (ADR-0033, ADR-0083).
        async with transaction(_engine(), identity) as connection:
            await connection.execute(
                text("UPDATE conversations SET pending_interrupts = CAST(:pending AS jsonb) WHERE id = :id"),
                {"pending": json.dumps(pending), "id": deps.conversation_id},
            )
    async for event in encoder.after_stream():
        encoded = _encoded(event)
        if pending is not None and encoded["type"] == "RUN_FINISHED":
            encoded["outcome"] = {"type": "interrupt", "interrupts": interrupts(pending)}
        await _write(run.run_id, encoded)
    await _set_status(identity, deps.run_id, "completed" if pending is None else "interrupted")


TITLE_PROMPT = (
    "Write a title of at most six words for a conversation that starts with this message, in its language."
    " Answer with the title only, without quotes.\n\n"
)
TITLE_CHARS = 80
TITLE_INPUT_CHARS = 2000


@DBOS.step()
async def _title(run: RunWorkflowInput, deps: RunDeps) -> str | None:
    """Name an untitled conversation after its first message, by its own model; the title, if stored."""
    try:
        return await _name_conversation(run, deps)
    except Exception as error:
        # A title is a courtesy: whatever goes wrong, the run it goes with is unaffected.
        logger.warning("run %s got no title: %s", run.run_id, _error_code(error))
        return None


async def _name_conversation(run: RunWorkflowInput, deps: RunDeps) -> str | None:
    async with transaction(_engine(), deps.identity) as connection:
        title = (
            await connection.execute(
                text("SELECT title FROM conversations WHERE id = :id"), {"id": deps.conversation_id}
            )
        ).scalar_one_or_none()
    if title != "":
        return None
    model = await connection_model(deps, uuid.UUID(run.connection_id), run.model)
    response = await model.request(
        [ModelRequest(parts=[UserPromptPart(TITLE_PROMPT + run.user_text[:TITLE_INPUT_CHARS])])],
        None,
        ModelRequestParameters(),
    )
    await record_usage(deps, uuid.uuid5(deps.run_id, "title"), response, "title")
    lines = [line.strip(" \t\"'*#") for line in readable_text(response).splitlines() if line.strip()]
    if not lines:
        return None
    title = lines[0][:TITLE_CHARS]
    async with transaction(_engine(), deps.identity) as connection:
        # Unless the user named it meanwhile.
        result = await connection.execute(
            text("UPDATE conversations SET title = :title WHERE id = :id AND title = ''"),
            {"title": title, "id": deps.conversation_id},
        )
    return title if result.rowcount == 1 else None


def _reason(error: BaseException) -> str | None:
    """What the provider said, for a refused request: such as a model that cannot call tools (MOD-014)."""
    if isinstance(error, ContentFilterError):
        return _refusal(error)
    if not isinstance(error, ModelHTTPError):
        return None
    raw: object = error.body
    if isinstance(raw, dict):
        body = cast(dict[str, Any], raw)
        nested = body.get("error")
        message = cast(dict[str, Any], nested).get("message") if isinstance(nested, dict) else body.get("message")
        if isinstance(message, str):
            return message[:REASON_CHARS]
    return str(error)[:REASON_CHARS]


def _refusal(error: ContentFilterError) -> str | None:
    """The reason a model or its provider gave for refusing to answer (MOD-015)."""
    try:
        responses = ModelMessagesTypeAdapter.validate_json(error.body or "[]")
    except ValueError:
        return None
    for response in responses:
        details = (response.provider_details if isinstance(response, ModelResponse) else None) or {}
        reason = details.get("refusal") or details.get("block_reason")
        if isinstance(reason, str) and reason:
            return reason[:REASON_CHARS]
    return None


async def _write_error(run_id: str, code: str, reason: str | None = None) -> None:
    message = code if reason is None else f"{code}: {reason}"
    await _write(run_id, {"type": "RUN_ERROR", "message": message, "code": code})


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


# A temporary conversation is deleted a day after its last activity (CNV-011, ADR-0082).
TEMPORARY_HOURS = 24


async def _delete_expired_temporary_conversations() -> None:
    """Delete each temporary conversation left a day ago, under its owner's request context (ADR-0082)."""
    async with transaction(_engine(), None) as connection:
        expired = (
            await connection.execute(
                text("SELECT * FROM expired_temporary_conversations(:hours)"), {"hours": TEMPORARY_HOURS}
            )
        ).all()
    driver = SandboxDriver(_WORKER.sandboxd_url, _WORKER.sandboxd_token)
    for row in expired:
        owner = Identity(
            session_id=uuid.UUID(int=0),
            user_id=row.owner_id,
            tenant_id=row.tenant_id,
            role="member",
            instance_admin=False,
        )
        try:
            async with transaction(_engine(), owner) as connection:
                # Still there, and still left: it may have been deleted or used since.
                still = (
                    await connection.execute(
                        text(
                            "SELECT 1 FROM conversations WHERE id = :id AND temporary"
                            " AND updated_at < now() - make_interval(hours => :hours) FOR UPDATE"
                        ),
                        {"id": row.conversation_id, "hours": TEMPORARY_HOURS},
                    )
                ).one_or_none()
                if still is not None:
                    await delete_everything(connection, DBOS.delete_workflows_async, driver, owner, row.conversation_id)
        except Exception:
            # The next sweep tries again.
            logger.exception("a temporary conversation could not be deleted")


async def _temporary_loop(seconds: int) -> None:
    while True:
        try:
            await _delete_expired_temporary_conversations()
        except Exception:
            logger.exception("the sweep for temporary conversations failed")
        await asyncio.sleep(seconds)


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
    temporary = asyncio.create_task(_temporary_loop(configuration.temporary_sweep_seconds))
    await stop.wait()
    retention.cancel()
    temporary.cancel()


def run_worker(configuration: WorkerConfiguration) -> None:
    logging.basicConfig(level=logging.INFO)
    # Its requests name search queries and sandbox paths: never logged (OBS-001).
    logging.getLogger("httpx").setLevel(logging.WARNING)
    _WORKER.engine = create_engine(configuration.database_url)
    _WORKER.secret_key = configuration.secret_key
    _WORKER.sandboxd_url = configuration.sandboxd_url
    _WORKER.sandboxd_token = configuration.sandboxd_token
    _WORKER.search_url = configuration.search_url
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
