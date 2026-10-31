"""The model gateway, as a capability of the agent (MOD-001, MOD-002, MOD-005, MOD-006, ADR-0036).

It turns the model reference of a run into an OpenAI-compatible model,
decrypting the configuration's API key only to make the request, records
every model request in the cost ledger, and stores the run's messages as
they are produced (ADR-0052).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter, ModelResponse
from pydantic_ai.models import Model, ModelRequestContext, ModelResolutionContext
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from mazzamurello_server.database import Identity, transaction
from mazzamurello_server.encryption import decrypt
from mazzamurello_server.model_configurations import TABLES, endpoint_refusal

MODEL_PREFIX = "mzm"
TOKENS_PER_PRICE = Decimal(1_000_000)
# The endpoint needs no key; OpenAI clients refuse an empty one.
NO_API_KEY = "none"


class ModelUnavailableError(Exception):
    """The run's model configuration is gone or may not be used."""


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
    provider: str = ""
    model: str = ""
    prices: dict[str, Any] = field(default_factory=dict[str, Any])


def model_reference(scope: str, configuration_id: str) -> str:
    return f"{MODEL_PREFIX}:{scope}:{configuration_id}"


def _ledger_id(run_id: uuid.UUID, request_number: int) -> uuid.UUID:
    """The same entry for the same model request, however often a step is retried."""
    return uuid.uuid5(run_id, f"model-request-{request_number}")


@dataclass
class Gateway(AbstractCapability[RunDeps]):
    async def resolve_model_id(self, ctx: ModelResolutionContext[RunDeps], *, model_id: str) -> Model | None:
        prefix, _, rest = model_id.partition(":")
        if prefix != MODEL_PREFIX:
            return None
        scope, _, configuration_id = rest.partition(":")
        deps = ctx.deps
        async with transaction(deps.engine, deps.identity) as connection:
            row = (
                await connection.execute(
                    text(
                        f"SELECT id, base_url, model, api_key_ciphertext, paid, input_price, cached_input_price,"  # noqa: S608
                        f" output_price, currency FROM {TABLES['tenant' if scope == 'tenant' else 'instance']}"
                        " WHERE id = :id"
                    ),
                    {"id": uuid.UUID(configuration_id)},
                )
            ).one_or_none()
        if row is None:
            raise ModelUnavailableError("the model configuration no longer exists")
        # Endpoints of tenant models are checked again on every request (ADR-0051).
        if scope == "tenant" and await endpoint_refusal(row.base_url) is not None:
            raise ModelUnavailableError("the endpoint of the tenant model is not allowed")
        api_key = NO_API_KEY
        if row.api_key_ciphertext is not None:
            api_key = decrypt(deps.secret_key, row.id, bytes(row.api_key_ciphertext))
        deps.prices = {
            "paid": row.paid,
            "input": row.input_price,
            "cached_input": row.cached_input_price,
            "output": row.output_price,
            "currency": row.currency,
        }
        return OpenAIChatModel(row.model, provider=OpenAIProvider(base_url=row.base_url, api_key=api_key))

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
    """The cost of a response, its currency and where the price came from (ADR-0042)."""
    prices = deps.prices
    configured_currency: str | None = prices.get("currency")
    if not prices.get("paid", False):
        # A cost of zero still names a currency; any one will do.
        return Decimal(0), configured_currency or "USD", "free"
    usage = response.usage
    if configured_currency is not None:
        cached = usage.cache_read_tokens or 0
        uncached = max(0, (usage.input_tokens or 0) - cached)
        cached_price = prices["cached_input"] if prices["cached_input"] is not None else prices["input"]
        cost = (
            uncached * prices["input"] + cached * cached_price + (usage.output_tokens or 0) * prices["output"]
        ) / TOKENS_PER_PRICE
        return cost, configured_currency, "admin"
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
