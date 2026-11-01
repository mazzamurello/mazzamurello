"""Model configurations of the instance and of tenants (MOD-008, MOD-002, ADR-0051).

The instance admin manages `instance_models`, a tenant admin the
`tenant_models` of their tenant; row-level security enforces both, and the
role checks here only choose between `403` and trying.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import uuid
from decimal import Decimal
from typing import Annotated, Any, Literal, LiteralString
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection

from mazzamurello_server import errors, schemas
from mazzamurello_server.auth import Authenticated, Engine
from mazzamurello_server.credentials import uuid7
from mazzamurello_server.database import UNIQUE_VIOLATION, Identity, sqlstate, transaction
from mazzamurello_server.encryption import encrypt

router = APIRouter()

type Scope = Literal["instance", "tenant"]

COLUMNS = (
    "id, name, base_url, model, api_key_ciphertext IS NOT NULL AS has_api_key, paid, input_price,"
    " cached_input_price, output_price, currency, is_default, created_at, updated_at"
)
TABLES: dict[Scope, LiteralString] = {"instance": "instance_models", "tenant": "tenant_models"}


async def endpoint_refusal(base_url: str) -> str | None:
    """Why a tenant model may not use `base_url`, or None (ADR-0051).

    The endpoint must be `https` and its host must resolve only to public
    addresses, since requests leave from the control plane.
    """
    parts = urlsplit(base_url)
    if parts.scheme != "https" or not parts.hostname:
        return "endpoint_must_use_https"
    try:
        literal = ipaddress.ip_address(parts.hostname)
    except ValueError:
        literal = None
    if literal is not None:
        addresses = [literal]
    else:
        try:
            resolved = await asyncio.get_running_loop().getaddrinfo(parts.hostname, parts.port or 443)
        except (socket.gaierror, UnicodeError):
            return "endpoint_not_resolvable"
        addresses = [ipaddress.ip_address(info[4][0]) for info in resolved]
    if not addresses or not all(address.is_global for address in addresses):
        return "endpoint_not_public"
    return None


def _decimal(value: Decimal | None) -> str | None:
    return None if value is None else format(value.normalize(), "f")


def _configuration(row: Any) -> schemas.ModelConfiguration:
    prices = None
    if row.currency is not None:
        prices = schemas.ModelPricesOut(
            input=_decimal(row.input_price) or "0",
            cached_input=_decimal(row.cached_input_price),
            output=_decimal(row.output_price) or "0",
            currency=row.currency,
        )
    return schemas.ModelConfiguration(
        id=row.id,
        name=row.name,
        base_url=row.base_url,
        model=row.model,
        has_api_key=row.has_api_key,
        paid=row.paid,
        prices=prices,
        is_default=row.is_default,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _check_role(identity: Identity, scope: Scope) -> None:
    allowed = identity.instance_admin if scope == "instance" else identity.tenant_admin
    if not allowed:
        raise errors.permission_denied()


async def _check_endpoint(scope: Scope, base_url: str) -> None:
    if scope == "tenant" and (refusal := await endpoint_refusal(base_url)) is not None:
        raise errors.invalid("/base_url", refusal)


def _price_values(prices: schemas.ModelPrices | None) -> dict[str, object]:
    if prices is None:
        return {"input_price": None, "cached_input_price": None, "output_price": None, "currency": None}
    return {
        "input_price": Decimal(prices.input),
        "cached_input_price": None if prices.cached_input is None else Decimal(prices.cached_input),
        "output_price": Decimal(prices.output),
        "currency": prices.currency,
    }


async def _clear_default(connection: AsyncConnection, scope: Scope, keep: uuid.UUID) -> None:
    # One default per scope; row-level security limits a tenant's change to its own rows.
    await connection.execute(
        text(f"UPDATE {TABLES[scope]} SET is_default = false, updated_at = now() WHERE is_default AND id <> :id"),  # noqa: S608
        {"id": keep},
    )


async def _create(
    scope: Scope, body: schemas.CreateModelConfigurationRequest, identity: Identity, engine: Engine, secret: bytes
) -> schemas.ModelConfiguration:
    _check_role(identity, scope)
    base_url = str(body.base_url)
    await _check_endpoint(scope, base_url)
    configuration_id = uuid7()
    values: dict[str, object] = {
        "id": configuration_id,
        "tenant_id": identity.tenant_id,
        "name": body.name,
        "base_url": base_url,
        "model": body.model,
        "api_key_ciphertext": None if body.api_key is None else encrypt(secret, configuration_id, body.api_key),
        "paid": body.paid,
        "is_default": body.is_default,
    } | _price_values(body.prices)
    tenant_column, tenant_value = ("tenant_id, ", ":tenant_id, ") if scope == "tenant" else ("", "")
    try:
        async with transaction(engine, identity) as connection:
            if body.is_default:
                await _clear_default(connection, scope, configuration_id)
            row = (
                await connection.execute(
                    text(
                        f"INSERT INTO {TABLES[scope]} (id, {tenant_column}name, base_url, model, api_key_ciphertext,"  # noqa: S608
                        " paid, input_price, cached_input_price, output_price, currency, is_default, created_at,"
                        f" updated_at) VALUES (:id, {tenant_value}:name, :base_url, :model, :api_key_ciphertext,"
                        " :paid, :input_price, :cached_input_price, :output_price, :currency, :is_default, now(),"
                        f" now()) RETURNING {COLUMNS}"
                    ),
                    values,
                )
            ).one()
    except DBAPIError as error:
        if sqlstate(error) == UNIQUE_VIOLATION:
            raise errors.conflict() from None
        raise
    return _configuration(row)


async def _list(scope: Scope, identity: Identity, engine: Engine) -> schemas.ModelConfigurationList:
    _check_role(identity, scope)
    async with transaction(engine, identity) as connection:
        rows = (await connection.execute(text(f"SELECT {COLUMNS} FROM {TABLES[scope]} ORDER BY name, id"))).all()  # noqa: S608
    return schemas.ModelConfigurationList(items=[_configuration(row) for row in rows])


async def _update(
    scope: Scope,
    configuration_id: uuid.UUID,
    body: schemas.UpdateModelConfigurationRequest,
    identity: Identity,
    engine: Engine,
    secret: bytes,
) -> schemas.ModelConfiguration:
    _check_role(identity, scope)
    present = body.model_fields_set
    if not present:
        raise errors.invalid("/", "empty")
    changes: dict[str, object] = {}
    for name in ("name", "model", "paid", "is_default"):
        if name in present:
            if getattr(body, name) is None:
                raise errors.invalid(f"/{name}", "null")
            changes[name] = getattr(body, name)
    if "base_url" in present:
        if body.base_url is None:
            raise errors.invalid("/base_url", "null")
        base_url = str(body.base_url)
        await _check_endpoint(scope, base_url)
        changes["base_url"] = base_url
    if "api_key" in present:
        changes["api_key_ciphertext"] = (
            None if body.api_key is None else encrypt(secret, configuration_id, body.api_key)
        )
    if "prices" in present:
        changes |= _price_values(body.prices)
    assignments = ", ".join(f"{column} = :{column}" for column in changes)
    try:
        async with transaction(engine, identity) as connection:
            if changes.get("is_default") is True:
                await _clear_default(connection, scope, configuration_id)
            row = (
                await connection.execute(
                    text(
                        f"UPDATE {TABLES[scope]} SET {assignments}, updated_at = now() WHERE id = :id"  # noqa: S608
                        f" RETURNING {COLUMNS}"
                    ),
                    changes | {"id": configuration_id},
                )
            ).one_or_none()
            if row is None:
                raise errors.not_found()
    except DBAPIError as error:
        if sqlstate(error) == UNIQUE_VIOLATION:
            raise errors.conflict() from None
        raise
    return _configuration(row)


async def _delete(scope: Scope, configuration_id: uuid.UUID, identity: Identity, engine: Engine) -> Response:
    _check_role(identity, scope)
    async with transaction(engine, identity) as connection:
        result = await connection.execute(
            text(f"DELETE FROM {TABLES[scope]} WHERE id = :id"),  # noqa: S608
            {"id": configuration_id},
        )
    if result.rowcount == 0:
        raise errors.not_found()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def secret_key_of(request: Request) -> bytes:
    """The key that encrypts API keys, from the process configuration (ADR-0051)."""
    key = request.app.state.configuration.secret_key
    if not isinstance(key, bytes):
        raise RuntimeError("the secret key is not configured")
    return key


type SecretKey = Annotated[bytes, Depends(secret_key_of)]


def _routes(scope: Scope) -> None:
    @router.post(f"/{scope}/models", status_code=status.HTTP_201_CREATED, response_model=schemas.ModelConfiguration)
    async def create(  # pyright: ignore[reportUnusedFunction]
        body: schemas.CreateModelConfigurationRequest, identity: Authenticated, engine: Engine, secret: SecretKey
    ) -> schemas.ModelConfiguration:
        return await _create(scope, body, identity, engine, secret)

    @router.get(f"/{scope}/models", response_model=schemas.ModelConfigurationList)
    async def list_(identity: Authenticated, engine: Engine) -> schemas.ModelConfigurationList:  # pyright: ignore[reportUnusedFunction]
        return await _list(scope, identity, engine)

    @router.patch(f"/{scope}/models/{{model_id}}", response_model=schemas.ModelConfiguration)
    async def update(  # pyright: ignore[reportUnusedFunction]
        model_id: uuid.UUID,
        body: schemas.UpdateModelConfigurationRequest,
        identity: Authenticated,
        engine: Engine,
        secret: SecretKey,
    ) -> schemas.ModelConfiguration:
        return await _update(scope, model_id, body, identity, engine, secret)

    @router.delete(f"/{scope}/models/{{model_id}}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
    async def delete(model_id: uuid.UUID, identity: Authenticated, engine: Engine) -> Response:  # pyright: ignore[reportUnusedFunction]
        return await _delete(scope, model_id, identity, engine)


_routes("instance")
_routes("tenant")
