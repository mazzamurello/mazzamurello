"""The data egress policy: local models only, for the household, a member or oneself (MOD-003, ADR-0091).

A row of `egress_policies` holds a policy stricter than `any`: the
household's, the one a tenant admin set for a user, or a user's own choice.
The strictest applies. Row-level security shows a user the household's and
their own, and an admin what admins set, never a user's own choice.

The model gateway checks the policy just before each model request it makes
for a user, so a change applies from the next request, also during a run; a
policy that cannot be read refuses the request.
"""

from __future__ import annotations

import logging
import uuid
from typing import Literal

from fastapi import APIRouter
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from sibillo_server import errors, schemas
from sibillo_server.auth import Authenticated, Engine
from sibillo_server.database import Identity, transaction

logger = logging.getLogger(__name__)

router = APIRouter()

type SetBy = Literal["admin", "user"]


class EgressRefusedError(Exception):
    """A model request the user's data egress policy refuses; it is never sent."""


def refused() -> errors.ApiError:
    return errors.ApiError(409, "model.egress_refused", "Only local models are allowed")


async def policies(connection: AsyncConnection) -> schemas.EgressPolicies:
    """The policies that apply to the user of the request context, and the strictest of them."""
    rows = (
        await connection.execute(
            text("SELECT user_id, set_by, policy FROM egress_policies WHERE user_id IS NULL OR user_id = app_user_id()")
        )
    ).all()
    household: schemas.EgressPolicy = "any"
    admin: schemas.EgressPolicy = "any"
    own: schemas.EgressPolicy = "any"
    for row in rows:
        if row.user_id is None:
            household = row.policy
        elif row.set_by == "admin":
            admin = row.policy
        else:
            own = row.policy
    effective: schemas.EgressPolicy = "local_only" if "local_only" in (household, admin, own) else "any"
    return schemas.EgressPolicies(household=household, admin=admin, own=own, effective=effective)


async def allows(connection: AsyncConnection, location: str) -> bool:
    """Whether the user's policy allows a model whose inference runs at `location` (MOD-010)."""
    return location == "local" or (await policies(connection)).effective == "any"


async def check(engine: AsyncEngine, identity: Identity, location: str) -> None:
    """Refuse a model request the user's policy does not allow, or whose policy cannot be read."""
    if location == "local":
        return
    try:
        async with transaction(engine, identity) as connection:
            allowed = await allows(connection, location)
    except Exception as error:
        logger.warning("the data egress policy could not be read", exc_info=True)
        raise EgressRefusedError("the data egress policy could not be read") from error
    if not allowed:
        raise EgressRefusedError("only local models are allowed")


async def _set(
    connection: AsyncConnection,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID | None,
    set_by: SetBy,
    policy: schemas.EgressPolicy,
) -> None:
    await connection.execute(
        text("DELETE FROM egress_policies WHERE user_id IS NOT DISTINCT FROM :user AND set_by = :set_by"),
        {"user": user_id, "set_by": set_by},
    )
    if policy != "any":
        await connection.execute(
            text(
                "INSERT INTO egress_policies (tenant_id, user_id, set_by, policy, updated_at)"
                " VALUES (:tenant, :user, :set_by, :policy, now())"
            ),
            {"tenant": tenant_id, "user": user_id, "set_by": set_by, "policy": policy},
        )


async def _set_by_admin(connection: AsyncConnection, user_id: uuid.UUID) -> schemas.EgressPolicy:
    row = (
        await connection.execute(
            text("SELECT policy FROM egress_policies WHERE user_id = :user AND set_by = 'admin'"), {"user": user_id}
        )
    ).one_or_none()
    return "any" if row is None else row.policy


async def _tenant_user(connection: AsyncConnection, user_id: uuid.UUID) -> None:
    """The user, if they belong to the tenant; others' are reported as not found (TEN-006)."""
    row = (await connection.execute(text("SELECT 1 FROM users WHERE id = :id"), {"id": user_id})).one_or_none()
    if row is None:
        raise errors.not_found()


@router.get("/me/egress-policy", response_model=schemas.EgressPolicies)
async def get_my_policies(identity: Authenticated, engine: Engine) -> schemas.EgressPolicies:
    async with transaction(engine, identity) as connection:
        return await policies(connection)


@router.put("/me/egress-policy", response_model=schemas.EgressPolicies)
async def set_my_policy(
    body: schemas.EgressPolicySetting, identity: Authenticated, engine: Engine
) -> schemas.EgressPolicies:
    async with transaction(engine, identity) as connection:
        await _set(connection, identity.tenant_id, identity.user_id, "user", body.policy)
        return await policies(connection)


@router.put("/tenant/egress-policy", response_model=schemas.EgressPolicySetting)
async def set_household_policy(
    body: schemas.EgressPolicySetting, identity: Authenticated, engine: Engine
) -> schemas.EgressPolicySetting:
    if not identity.tenant_admin:
        raise errors.permission_denied()
    async with transaction(engine, identity) as connection:
        await _set(connection, identity.tenant_id, None, "admin", body.policy)
    return schemas.EgressPolicySetting(policy=body.policy)


@router.get("/tenant/users/{user_id}/egress-policy", response_model=schemas.EgressPolicySetting)
async def get_user_policy(user_id: uuid.UUID, identity: Authenticated, engine: Engine) -> schemas.EgressPolicySetting:
    if not identity.tenant_admin:
        raise errors.permission_denied()
    async with transaction(engine, identity) as connection:
        await _tenant_user(connection, user_id)
        return schemas.EgressPolicySetting(policy=await _set_by_admin(connection, user_id))


@router.put("/tenant/users/{user_id}/egress-policy", response_model=schemas.EgressPolicySetting)
async def set_user_policy(
    user_id: uuid.UUID, body: schemas.EgressPolicySetting, identity: Authenticated, engine: Engine
) -> schemas.EgressPolicySetting:
    if not identity.tenant_admin:
        raise errors.permission_denied()
    async with transaction(engine, identity) as connection:
        await _tenant_user(connection, user_id)
        await _set(connection, identity.tenant_id, user_id, "admin", body.policy)
        return schemas.EgressPolicySetting(policy=await _set_by_admin(connection, user_id))
