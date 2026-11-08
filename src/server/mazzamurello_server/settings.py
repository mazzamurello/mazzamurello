"""A user's defaults for their conversations (CNV-013, CNV-014, ADR-0081).

New conversations copy the model, reasoning and tools; conversations without
instructions of their own use the instructions as they are at each run. There
are no defaults but the user's: without them, the tenant's default model,
reasoning on and every tool.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from mazzamurello_server import errors, schemas
from mazzamurello_server.auth import Authenticated, Engine
from mazzamurello_server.connections import default_model, offered
from mazzamurello_server.database import transaction

router = APIRouter()

DEFAULT_REASONING: schemas.Reasoning = "on"
# The built-in base instructions, which a user may replace (CNV-014, ADR-0044).
BUILT_IN_BASE_INSTRUCTIONS = (
    "You are Mazzamurello, an assistant for the people of a household. "
    "Answer helpfully, clearly and briefly, in the language the user writes in."
)
SETTINGS_COLUMNS = "connection_id, model, reasoning, disabled_tools, base_instructions, additional_instructions"


@dataclass(frozen=True)
class NewConversation:
    """What a new conversation starts with."""

    model: schemas.ModelChoiceOut | None
    reasoning: schemas.Reasoning = DEFAULT_REASONING
    disabled_tools: list[schemas.ToolName] = field(default_factory=list[schemas.ToolName])


async def _stored(connection: AsyncConnection) -> Any:
    """The user's row of defaults, if they set any; row-level security scopes it to them."""
    return (await connection.execute(text(f"SELECT {SETTINGS_COLUMNS} FROM user_settings"))).one_or_none()  # noqa: S608


def _response(row: Any) -> schemas.UserSettingsOut:
    if row is None:
        return schemas.UserSettingsOut(
            model=None,
            reasoning=None,
            disabled_tools=[],
            base_instructions=None,
            additional_instructions=None,
            built_in_base_instructions=BUILT_IN_BASE_INSTRUCTIONS,
        )
    return schemas.UserSettingsOut(
        model=None
        if row.connection_id is None or row.model is None
        else schemas.ModelChoiceOut(connection_id=row.connection_id, model=row.model),
        reasoning=row.reasoning,
        disabled_tools=list(row.disabled_tools),
        base_instructions=row.base_instructions,
        additional_instructions=row.additional_instructions,
        built_in_base_instructions=BUILT_IN_BASE_INSTRUCTIONS,
    )


async def new_conversation(connection: AsyncConnection) -> NewConversation:
    """A copy of the user's defaults, with the tenant's default model when theirs is unset or gone (MOD-012)."""
    settings = _response(await _stored(connection))
    model = settings.model
    if model is None or not await offered(connection, schemas.ModelChoice(**model.model_dump())):
        model = await default_model(connection)
    return NewConversation(model, settings.reasoning or DEFAULT_REASONING, settings.disabled_tools)


@router.get("/me/settings", response_model=schemas.UserSettingsOut)
async def get_settings(identity: Authenticated, engine: Engine) -> schemas.UserSettingsOut:
    async with transaction(engine, identity) as connection:
        return _response(await _stored(connection))


@router.put("/me/settings", response_model=schemas.UserSettingsOut)
async def set_settings(body: schemas.UserSettings, identity: Authenticated, engine: Engine) -> schemas.UserSettingsOut:
    async with transaction(engine, identity) as connection:
        if body.model is not None and not await offered(connection, body.model):
            raise errors.invalid("/model", "not_offered")
        row = (
            await connection.execute(
                text(
                    f"INSERT INTO user_settings (tenant_id, owner_id, {SETTINGS_COLUMNS}, updated_at)"  # noqa: S608
                    " VALUES (:tenant_id, :owner_id, :connection_id, :model, :reasoning, :disabled_tools,"
                    " :base_instructions, :additional_instructions, now())"
                    " ON CONFLICT (tenant_id, owner_id) DO UPDATE SET connection_id = excluded.connection_id,"
                    " model = excluded.model, reasoning = excluded.reasoning,"
                    " disabled_tools = excluded.disabled_tools, base_instructions = excluded.base_instructions,"
                    " additional_instructions = excluded.additional_instructions, updated_at = now()"
                    f" RETURNING {SETTINGS_COLUMNS}"
                ),
                {
                    "tenant_id": identity.tenant_id,
                    "owner_id": identity.user_id,
                    "connection_id": None if body.model is None else body.model.connection_id,
                    "model": None if body.model is None else body.model.model,
                    "reasoning": body.reasoning,
                    "disabled_tools": body.disabled_tools,
                    "base_instructions": body.base_instructions,
                    "additional_instructions": body.additional_instructions,
                },
            )
        ).one()
    return _response(row)
