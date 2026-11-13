"""Tool permissions, approvals and audit events in a run (AGT-002, AGT-004, AGT-006, AGT-008, ADR-0033, ADR-0090).

The capability takes away the tools a user's permissions deny, ends the run
with an approval request for each call that needs one, and records an audit
event for every call. A call needing approval raises `ApprovalRequired`
before the tool runs: the run ends with `DeferredToolRequests`, whose
metadata says why and with which scopes, and the answer starts a new run in
which the call is approved, its scope and reason in its metadata.

Tool calls are not durable steps: a run replayed after a crash calls its
tools again, and records the attempt again (ADR-0034).
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, cast

from pydantic_ai import RunContext
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.exceptions import ApprovalRequired
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models import ModelRequestContext
from pydantic_ai.tools import ToolDefinition
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from sibillo_server.credentials import uuid7
from sibillo_server.database import Identity, transaction
from sibillo_server.gateway import RunDeps
from sibillo_server.tool_policy import (
    decide,
    denied,
    has_external_effects,
    has_untrusted_content,
)

logger = logging.getLogger(__name__)


async def record(
    connection: AsyncConnection,
    identity: Identity,
    *,
    conversation_id: uuid.UUID,
    run_id: uuid.UUID,
    tool_call_id: str,
    tool: str,
    outcome: str,
    scope: str | None = None,
    reason: str | None = None,
    attempt: bool = False,
) -> None:
    """Write the audit event of a call, or complete it: a call is recorded once, its attempts counted (AGT-008)."""
    await connection.execute(
        text(
            "INSERT INTO audit_events (id, tenant_id, owner_id, conversation_id, run_id, tool_call_id, tool, outcome,"
            " scope, reason, attempts, created_at) VALUES (:id, :tenant, :owner, :conversation, :run, :call, :tool,"
            " :outcome, :scope, :reason, :attempts, now())"
            " ON CONFLICT (run_id, tool_call_id) DO UPDATE SET outcome = EXCLUDED.outcome,"
            " scope = EXCLUDED.scope, reason = EXCLUDED.reason,"
            " attempts = audit_events.attempts + EXCLUDED.attempts"
        ),
        {
            "id": uuid7(),
            "tenant": identity.tenant_id,
            "owner": identity.user_id,
            "conversation": conversation_id,
            "run": run_id,
            "call": tool_call_id,
            "tool": tool,
            "outcome": outcome,
            "scope": scope,
            "reason": reason,
            "attempts": 1 if attempt else 0,
        },
    )


class Approvals(AbstractCapability[RunDeps]):
    """Takes denied tools away, asks before the calls that need approval, and audits every call."""

    async def prepare_tools(self, ctx: RunContext[RunDeps], tool_defs: list[ToolDefinition]) -> list[ToolDefinition]:
        away = denied(ctx.deps.permissions)
        return [tool for tool in tool_defs if tool.name not in away]

    async def after_model_request(
        self, ctx: RunContext[RunDeps], *, request_context: ModelRequestContext, response: ModelResponse
    ) -> ModelResponse:
        # A call to a tool the user's permissions deny is refused, and recorded as such.
        away = denied(ctx.deps.permissions)
        refused = [part for part in response.parts if isinstance(part, ToolCallPart) and part.tool_name in away]
        if refused:
            deps = ctx.deps
            async with transaction(deps.engine, deps.identity) as connection:
                for part in refused:
                    await record(
                        connection,
                        deps.identity,
                        conversation_id=deps.conversation_id,
                        run_id=deps.run_id,
                        tool_call_id=part.tool_call_id,
                        tool=part.tool_name,
                        outcome="refused",
                        reason="permission",
                    )
        return response

    async def wrap_tool_execute(
        self,
        ctx: RunContext[RunDeps],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: dict[str, Any],
        handler: Any,
    ) -> Any:
        deps = ctx.deps
        run_id = deps.run_id
        if ctx.tool_call_approved:
            # Approved by the user: the call was made by the run the answer continues.
            metadata = cast(dict[str, Any], ctx.tool_call_metadata or {})
            outcome, scope, reason = "approved", metadata.get("scope"), metadata.get("reason")
            run_id = deps.parent_run_id or run_id
        else:
            untrusted = deps.untrusted or has_untrusted_content(ctx.messages)
            decision = decide(call.tool_name, deps.permissions, untrusted, deps.allowances)
            if decision.request is not None:
                raise ApprovalRequired(
                    metadata={"reason": decision.request.reason, "scopes": list(decision.request.scopes)}
                )
            outcome = "not_needed" if decision.allowed is None else "allowed"
            scope, reason = decision.allowed, None
        async with transaction(deps.engine, deps.identity) as connection:
            await record(
                connection,
                deps.identity,
                conversation_id=deps.conversation_id,
                run_id=run_id,
                tool_call_id=call.tool_call_id,
                tool=call.tool_name,
                outcome=outcome,
                scope=scope,
                reason=reason,
                attempt=has_external_effects(call.tool_name),
            )
        return await handler(args)
