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
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, cast

from openai import AsyncOpenAI
from pydantic_ai import RunContext
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter, ModelResponse
from pydantic_ai.models import Model, ModelRequestContext, ModelResolutionContext
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.models.openrouter import OpenRouterModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.providers.openrouter import OpenRouterProvider
from pydantic_ai.tools import ToolDefinition
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from mazzamurello_server.database import Identity, transaction
from mazzamurello_server.encryption import decrypt
from mazzamurello_server.endpoints import tenant_http_client

MODEL_PREFIX = "mzm"
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
    provider: str = ""
    model: str = ""
    # Whether the model may be given tools (MOD-014), and where it runs (MOD-010).
    tools: bool = True
    location: str = "remote"
    prices: dict[str, Any] = field(default_factory=dict[str, Any])


def model_reference(connection_id: str, model: str) -> str:
    """The model of a run, as the agent names it: the connection, then the model's own name."""
    return f"{MODEL_PREFIX}:{connection_id}:{model}"


def _ledger_id(run_id: uuid.UUID, request_number: int) -> uuid.UUID:
    """The same entry for the same model request, however often a step is retried."""
    return uuid.uuid5(run_id, f"model-request-{request_number}")


@dataclass
class Gateway(AbstractCapability[RunDeps]):
    async def resolve_model_id(self, ctx: ModelResolutionContext[RunDeps], *, model_id: str) -> Model | None:
        prefix, _, rest = model_id.partition(":")
        if prefix != MODEL_PREFIX:
            return None
        connection_id, _, model = rest.partition(":")
        deps = ctx.deps
        async with transaction(deps.engine, deps.identity) as connection:
            row = (
                await connection.execute(
                    text(
                        "SELECT c.id, c.kind, c.base_url, c.location, c.api_key_ciphertext, c.private_network, m.tools"
                        " FROM connections c JOIN connection_models m ON m.connection_id = c.id"
                        " WHERE c.id = :id AND m.model = :model"
                    ),
                    {"id": uuid.UUID(connection_id), "model": model},
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
        deps.location = row.location
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
        return OpenAIChatModel(model, provider=provider)

    async def prepare_tools(self, ctx: RunContext[RunDeps], tool_defs: list[ToolDefinition]) -> list[ToolDefinition]:
        return tool_defs if ctx.deps.tools else []

    async def before_model_request(
        self, ctx: RunContext[RunDeps], request_context: ModelRequestContext
    ) -> ModelRequestContext:
        # The user's message is kept even if the run stops before the answer.
        await store_messages(ctx.deps, ctx.messages[ctx.deps.history_length :])
        return request_context

    async def after_model_request(
        self, ctx: RunContext[RunDeps], *, request_context: ModelRequestContext, response: ModelResponse
    ) -> ModelResponse:
        deps = ctx.deps
        await store_messages(deps, [*ctx.messages[deps.history_length :], response])
        await _record_usage(deps, ctx.run_step, response)
        return response


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


async def _record_usage(deps: RunDeps, request_number: int, response: ModelResponse) -> None:
    cost, currency, price_source = _cost(deps, response)
    usage = response.usage
    async with transaction(deps.engine, deps.identity) as connection:
        await connection.execute(
            text(
                "INSERT INTO usage_ledger (id, tenant_id, owner_id, conversation_id, run_id, purpose, provider, model,"
                " input_tokens, cached_input_tokens, cache_write_tokens, output_tokens, cost, currency, price_source,"
                " created_at) VALUES (:id, :tenant_id, :owner_id, :conversation_id, :run_id, 'run', :provider,"
                " :model, :input, :cached, :cache_write, :output, :cost, :currency, :price_source, now())"
                " ON CONFLICT (id) DO NOTHING"
            ),
            {
                "id": _ledger_id(deps.run_id, request_number),
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


async def store_messages(deps: RunDeps, messages: list[ModelMessage]) -> None:
    """Store the run's messages so far; already stored ones are kept as they are (ADR-0041)."""
    if not messages:
        return
    serialized = ModelMessagesTypeAdapter.dump_python(messages, mode="json")
    async with transaction(deps.engine, deps.identity) as connection:
        for seq, message in enumerate(serialized, start=1):
            await connection.execute(
                text(
                    "INSERT INTO conversation_messages (run_id, seq, tenant_id, owner_id, conversation_id, message,"
                    " created_at) VALUES (:run_id, :seq, :tenant_id, :owner_id, :conversation_id,"
                    " CAST(:message AS jsonb), now()) ON CONFLICT (run_id, seq) DO NOTHING"
                ),
                {
                    "run_id": deps.run_id,
                    "seq": seq,
                    "tenant_id": deps.identity.tenant_id,
                    "owner_id": deps.identity.user_id,
                    "conversation_id": deps.conversation_id,
                    "message": json.dumps(message),
                },
            )
