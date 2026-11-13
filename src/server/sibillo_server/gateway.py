"""The model gateway, as a capability of the agent (MOD-001, MOD-002, MOD-005, MOD-006, MOD-014, ADR-0036).

It turns the model reference of a run, a connection and a model, into a
model of the connection's API, OpenAI-compatible or OpenRouter (ADR-0057,
ADR-0069), decrypting the connection's API key only to make the request. It
withholds tools from a model that cannot call them, records every model
request in the cost ledger, and stores the run's messages as they are
produced (ADR-0052).
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, cast

from openai import AsyncOpenAI
from pydantic_ai import RunContext
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)
from pydantic_ai.models import Model, ModelRequestContext, ModelRequestParameters, ModelResolutionContext
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.models.openrouter import OpenRouterModel
from pydantic_ai.profiles.openai import OpenAIModelProfile
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.providers.openrouter import OpenRouterProvider
from pydantic_ai.settings import ModelSettings, ThinkingLevel
from pydantic_ai.tools import ToolDefinition
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from sibillo_server.costs import amount
from sibillo_server.database import Identity, transaction
from sibillo_server.egress import check
from sibillo_server.encryption import decrypt
from sibillo_server.endpoints import tenant_http_client
from sibillo_server.tool_policy import Allowances, Permissions

logger = logging.getLogger(__name__)

MODEL_PREFIX = "sibillo"
DEFAULT_CONTEXT_WINDOW = 8192
# Compaction starts when the history would exceed this share of the window (ADR-0073).
COMPACTION_SHARE = 0.8
# A rough count of tokens: four characters each.
CHARS_PER_TOKEN = 4
SUMMARY_PROMPT = (
    "Summarize the conversation below for yourself, so that you can continue it without it: keep facts, names,"
    " decisions, numbers and open questions. Write the summary in the language of the conversation.\n\n"
)
# The server needs no key; OpenAI clients refuse an empty one.
NO_API_KEY = "none"


class ModelUnavailableError(Exception):
    """The run's connection or model is gone or may not be used."""


@dataclass
class RunDeps:
    """What the agent of one run needs from the worker."""

    engine: AsyncEngine
    identity: Identity
    secret_key: bytes
    conversation_id: uuid.UUID
    run_id: uuid.UUID
    # Messages of the path before this run; the run's own come after them.
    history_length: int
    # The sandbox driver, for the run's workspace (ADR-0035).
    sandboxd_url: str = ""
    sandboxd_token: str = ""
    # The instance's search service, when there is one (AGT-020, ADR-0075).
    search_url: str = ""
    provider: str = ""
    model: str = ""
    # Whether the model may be given tools (MOD-014), and where it runs (MOD-010).
    tools: bool = True
    # Whether the model can reason, `None` when unknown, and how much it should (CNV-013, ADR-0081).
    reasons: bool | None = None
    reasoning: str = "on"
    # The tools the user switched off, by the names the model knows them by (CNV-013, ADR-0087).
    disabled_tools: frozenset[str] = frozenset()
    # The instructions of the run: null base instructions are the built-in ones (CNV-014).
    base_instructions: str | None = None
    additional_instructions: str | None = None
    # How the run's message came, when it was not typed (UX-005, ADR-0088).
    voice: str | None = None
    # The user's tool permissions, what they allowed, and whether the path before this run holds untrusted
    # content (AGT-002, AGT-003, AGT-006, ADR-0090).
    permissions: Permissions = field(default_factory=Permissions)
    allowances: Allowances = field(default_factory=Allowances)
    untrusted: bool = False
    # The run this one continues: for a run that answers an interrupt, the run that asked (ADR-0033).
    parent_run_id: uuid.UUID | None = None
    location: str = "remote"
    prices: dict[str, Any] = field(default_factory=dict[str, Any])
    # The model's context window, and what the run used so far (MOD-007, ADR-0073).
    context_window: int = DEFAULT_CONTEXT_WINDOW
    input_tokens: int = 0
    output_tokens: int = 0
    cost: Decimal | None = Decimal(0)
    currency: str = "USD"
    # Writes an event to the run's stream; set by the worker.
    emit: Callable[[dict[str, Any]], Awaitable[None]] | None = None
    # The summary that replaces the oldest history in this run's requests, once made (AGT-016).
    compacted: tuple[int, list[ModelMessage]] | None = None
    compactions: int = 0


def model_reference(connection_id: str, model: str) -> str:
    """The model of a run, as the agent names it: the connection, then the model's own name."""
    return f"{MODEL_PREFIX}:{connection_id}:{model}"


def _ledger_id(run_id: uuid.UUID, request_number: int) -> uuid.UUID:
    """The same entry for the same model request, however often a step is retried."""
    return uuid.uuid5(run_id, f"model-request-{request_number}")


async def connection_model(deps: RunDeps, connection_id: uuid.UUID, model: str) -> Model:
    """The model a connection offers, ready to request, with the run's facts about it in `deps`."""
    async with transaction(deps.engine, deps.identity) as connection:
        row = (
            await connection.execute(
                text(
                    "SELECT c.id, c.kind, c.base_url, c.location, c.api_key_ciphertext, c.private_network, m.tools,"
                    " m.reasoning,"
                    " coalesce(c.context_window, m.context_window) AS context_window"
                    " FROM connections c JOIN connection_models m ON m.connection_id = c.id"
                    " WHERE c.id = :id AND m.model = :model"
                ),
                {"id": connection_id, "model": model},
            )
        ).one_or_none()
    if row is None:
        raise ModelUnavailableError("the connection no longer offers the model")
    if not row.private_network and not str(row.base_url).startswith("https://"):
        raise ModelUnavailableError("the connection's address is not allowed")
    api_key = NO_API_KEY
    if row.api_key_ciphertext is not None:
        api_key = decrypt(deps.secret_key, row.id, bytes(row.api_key_ciphertext))
    # A model known not to call tools runs without them; an unknown one is given them (MOD-014).
    deps.tools = row.tools is not False
    deps.reasons = row.reasoning
    deps.location = row.location
    # Never a request the user's data egress policy refuses (MOD-003, ADR-0091).
    await check(deps.engine, deps.identity, row.location)
    deps.context_window = row.context_window or DEFAULT_CONTEXT_WINDOW
    # Addresses not set by the instance admin connect only to checked public addresses,
    # without redirects (MOD-009, ADR-0061).
    http_client = None if row.private_network else tenant_http_client()
    if row.kind == "openrouter":
        # A client of our own: the provider would add attribution headers from the environment.
        # The SDK's signature names httpx2, and it also accepts a legacy httpx client, as here.
        legacy_client = cast("Any", http_client)
        client = AsyncOpenAI(base_url=row.base_url, api_key=api_key, http_client=legacy_client)
        return OpenRouterModel(model, provider=OpenRouterProvider(openai_client=client))
    provider = OpenAIProvider(base_url=row.base_url, api_key=api_key, http_client=http_client)
    # Such servers, Ollama and vLLM among them, take OpenAI's `reasoning_effort`, `none` included (ADR-0081).
    profile: OpenAIModelProfile = {
        **(provider.model_profile(model) or {}),
        "supports_thinking": True,
        "openai_supports_reasoning": True,
        "openai_supports_reasoning_effort_none": True,
    }
    return OpenAIChatModel(model, provider=provider, profile=profile)


# Pydantic AI's unified setting for each reasoning level (CNV-013, ADR-0081).
THINKING: dict[str, ThinkingLevel] = {"off": False, "on": True, "deep": "high"}


def model_settings(ctx: RunContext[RunDeps]) -> ModelSettings:
    """The run's reasoning level, unless its model is known not to reason."""
    if ctx.deps.reasons is False:
        return ModelSettings()
    return ModelSettings(thinking=THINKING.get(ctx.deps.reasoning, True))


def readable_text(message: ModelMessage) -> str:
    """What a person reads in a message: the user's prompt or the assistant's text, never tools (CNV-009)."""
    texts: list[str] = []
    for part in message.parts:
        if isinstance(part, UserPromptPart):
            content = part.content
            if isinstance(content, str):
                texts.append(content)
            else:
                texts.extend(item for item in content if isinstance(item, str))
        elif isinstance(part, TextPart):
            texts.append(part.content)
    return "\n".join(texts)


def _estimated_tokens(messages: list[ModelMessage]) -> int:
    return (
        sum(len(json.dumps(item)) for item in ModelMessagesTypeAdapter.dump_python(messages, mode="json"))
        // CHARS_PER_TOKEN
    )


def _turn_start(messages: list[ModelMessage], limit: int) -> int:
    """The index of the last user prompt before `limit`, where a turn starts; 0 when there is none."""
    for index in range(limit - 1, 0, -1):
        message = messages[index]
        if isinstance(message, ModelRequest) and any(isinstance(part, UserPromptPart) for part in message.parts):
            return index
    return 0


@dataclass
class Gateway(AbstractCapability[RunDeps]):
    async def resolve_model_id(self, ctx: ModelResolutionContext[RunDeps], *, model_id: str) -> Model | None:
        prefix, _, rest = model_id.partition(":")
        if prefix != MODEL_PREFIX:
            return None
        connection_id, _, model = rest.partition(":")
        return await connection_model(ctx.deps, uuid.UUID(connection_id), model)

    def get_model_settings(self) -> Callable[[RunContext[RunDeps]], ModelSettings]:
        return model_settings

    async def prepare_tools(self, ctx: RunContext[RunDeps], tool_defs: list[ToolDefinition]) -> list[ToolDefinition]:
        if not ctx.deps.tools:
            return []
        return [tool for tool in tool_defs if tool.name not in ctx.deps.disabled_tools]

    async def before_model_request(
        self, ctx: RunContext[RunDeps], request_context: ModelRequestContext
    ) -> ModelRequestContext:
        # The user's message is kept even if the run stops before the answer.
        await store_messages(ctx.deps, ctx.messages[ctx.deps.history_length :])
        # Checked before every request, so that a policy changed during the run applies (MOD-003, ADR-0091).
        await check(ctx.deps.engine, ctx.deps.identity, ctx.deps.location)
        request_context.messages = await _compacted(ctx, list(request_context.messages))
        return request_context

    async def after_model_request(
        self, ctx: RunContext[RunDeps], *, request_context: ModelRequestContext, response: ModelResponse
    ) -> ModelResponse:
        deps = ctx.deps
        await store_messages(deps, [*ctx.messages[deps.history_length :], response])
        await record_usage(deps, _ledger_id(deps.run_id, ctx.run_step), response)
        await _report_usage(deps, response)
        return response


async def _compacted(ctx: RunContext[RunDeps], messages: list[ModelMessage]) -> list[ModelMessage]:
    """The history the model receives: the oldest turns summarized once it would fill the window (AGT-016).

    Only the model sees the summary; it is kept as a checkpoint of the run, and
    the stored conversation never changes (ADR-0041, ADR-0073). Replacing the
    request's messages leaves the run's own history whole, so later requests
    of the run reuse the summary.
    """
    deps = ctx.deps
    if deps.compacted is not None:
        cut, summary = deps.compacted
        return [*summary, *messages[cut:]]
    if _estimated_tokens(messages) <= deps.context_window * COMPACTION_SHARE:
        return messages
    cut = _turn_start(messages, deps.history_length)
    model = ctx.model
    if cut == 0 or not isinstance(model, Model):
        return messages
    transcript = "\n\n".join(said for message in messages[:cut] if (said := readable_text(message)))
    try:
        response = await model.request(
            [ModelRequest(parts=[UserPromptPart(SUMMARY_PROMPT + transcript)])], None, ModelRequestParameters()
        )
    except Exception:
        # Without a summary, the request goes as it is; the model may then see less than all of it.
        logger.warning("run %s could not be compacted", deps.run_id, exc_info=True)
        return messages
    deps.compactions += 1
    await record_usage(deps, uuid.uuid5(deps.run_id, f"compaction-{deps.compactions}"), response, "compaction")
    # A request and its answer: two requests in a row would be merged into one.
    summary: list[ModelMessage] = [
        ModelRequest(parts=[UserPromptPart("Summary of the conversation so far:\n" + readable_text(response))]),
        ModelResponse(parts=[TextPart("Noted. I will continue from this summary.")]),
    ]
    deps.compacted = (cut, summary)
    checkpoint = storable(
        ModelMessagesTypeAdapter.dump_python([*summary, *messages[cut : deps.history_length]], mode="json")
    )
    async with transaction(deps.engine, deps.identity) as connection:
        await connection.execute(
            text(
                "INSERT INTO compaction_checkpoints (run_id, tenant_id, owner_id, conversation_id, messages,"
                " created_at) VALUES (:run_id, :tenant_id, :owner_id, :conversation_id,"
                " CAST(:messages AS jsonb), now()) ON CONFLICT (run_id) DO NOTHING"
            ),
            {
                "run_id": deps.run_id,
                "tenant_id": deps.identity.tenant_id,
                "owner_id": deps.identity.user_id,
                "conversation_id": deps.conversation_id,
                "messages": json.dumps(checkpoint),
            },
        )
    return [*summary, *messages[cut:]]


async def _report_usage(deps: RunDeps, response: ModelResponse) -> None:
    """The context in use and the run's tokens and cost so far, as an AG-UI event (MOD-007, ADR-0073)."""
    usage = response.usage
    deps.input_tokens += usage.input_tokens or 0
    deps.output_tokens += usage.output_tokens or 0
    if deps.emit is None:
        return
    cost = None if deps.cost is None else {"amount": amount(deps.cost), "currency": deps.currency}
    await deps.emit(
        {
            "type": "CUSTOM",
            "name": "sibillo.usage",
            "value": {
                "context_window": deps.context_window,
                "context_tokens": usage.input_tokens or 0,
                "input_tokens": deps.input_tokens,
                "output_tokens": deps.output_tokens,
                "cost": cost,
            },
        }
    )


def _cost(deps: RunDeps, response: ModelResponse) -> tuple[Decimal | None, str | None, str]:
    """The cost of a response, its currency and where the price came from (ADR-0042, ADR-0069)."""
    if deps.location == "local":
        # A cost of zero still names a currency; any one will do.
        return Decimal(0), "USD", "free"
    reported = (response.provider_details or {}).get("cost")
    if isinstance(reported, int | float) and not isinstance(reported, bool):
        # OpenRouter reports the cost in credits of one US dollar each (ADR-0057).
        return Decimal(str(reported)), "USD", "provider"
    try:
        estimate = response.cost()
    except (LookupError, ValueError):
        return None, None, "unknown"
    return Decimal(str(estimate.total_price)), "USD", "catalog"


async def record_usage(deps: RunDeps, entry_id: uuid.UUID, response: ModelResponse, purpose: str = "run") -> None:
    """Record a model request in the cost ledger, once, and add its cost to the run's (MOD-006)."""
    cost, currency, price_source = _cost(deps, response)
    if cost is None:
        deps.cost = None
    elif deps.cost is not None:
        deps.cost += cost
        deps.currency = currency or deps.currency
    usage = response.usage
    async with transaction(deps.engine, deps.identity) as connection:
        await connection.execute(
            text(
                "INSERT INTO usage_ledger (id, tenant_id, owner_id, conversation_id, run_id, purpose, provider, model,"
                " input_tokens, cached_input_tokens, cache_write_tokens, output_tokens, cost, currency, price_source,"
                " created_at) VALUES (:id, :tenant_id, :owner_id, :conversation_id, :run_id, :purpose, :provider,"
                " :model, :input, :cached, :cache_write, :output, :cost, :currency, :price_source, now())"
                " ON CONFLICT (id) DO NOTHING"
            ),
            {
                "id": entry_id,
                "purpose": purpose,
                "tenant_id": deps.identity.tenant_id,
                "owner_id": deps.identity.user_id,
                "conversation_id": deps.conversation_id,
                "run_id": deps.run_id,
                "provider": deps.provider,
                "model": deps.model,
                "input": usage.input_tokens or 0,
                "cached": usage.cache_read_tokens or 0,
                "cache_write": usage.cache_write_tokens or 0,
                "output": usage.output_tokens or 0,
                "cost": cost,
                "currency": currency,
                "price_source": price_source,
            },
        )


def storable(value: Any) -> Any:
    """`value` with every NUL character as U+FFFD: Postgres stores none in text or JSONB (CNV-018)."""
    if isinstance(value, str):
        return value.replace("\x00", "\ufffd")
    if isinstance(value, list):
        return [storable(item) for item in cast(list[Any], value)]
    if isinstance(value, dict):
        return {key: storable(item) for key, item in cast(dict[str, Any], value).items()}
    return value


async def store_messages(deps: RunDeps, messages: list[ModelMessage]) -> None:
    """Store the run's messages so far; already stored ones are kept as they are (ADR-0041)."""
    if not messages:
        return
    serialized = storable(ModelMessagesTypeAdapter.dump_python(messages, mode="json"))
    async with transaction(deps.engine, deps.identity) as connection:
        for seq, message in enumerate(serialized, start=1):
            await connection.execute(
                text(
                    "INSERT INTO conversation_messages (run_id, seq, tenant_id, owner_id, conversation_id, message,"
                    " text, created_at) VALUES (:run_id, :seq, :tenant_id, :owner_id, :conversation_id,"
                    " CAST(:message AS jsonb), :text, now()) ON CONFLICT (run_id, seq) DO NOTHING"
                ),
                {
                    "run_id": deps.run_id,
                    "seq": seq,
                    "tenant_id": deps.identity.tenant_id,
                    "owner_id": deps.identity.user_id,
                    "conversation_id": deps.conversation_id,
                    "message": json.dumps(message),
                    "text": storable(readable_text(messages[seq - 1])),
                },
            )
        # The list orders conversations by their latest message (CNV-008).
        await connection.execute(
            text("UPDATE conversations SET last_message_at = now() WHERE id = :id"), {"id": deps.conversation_id}
        )
