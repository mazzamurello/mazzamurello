"""Connections of a household, their models and their tests (MOD-008, MOD-009, MOD-011 to MOD-013, ADR-0069).

A tenant admin manages the connections of their tenant; row-level security
enforces it, and the role checks here only choose between `403` and trying.
Every user of the tenant reads the models the connections offer, which the
server lists from each provider and keeps in `connection_models`.
"""

from __future__ import annotations

import asyncio
import collections
import logging
import ssl
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, cast
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from mazzamurello_server import errors, schemas
from mazzamurello_server.auth import Authenticated, Engine
from mazzamurello_server.credentials import uuid7
from mazzamurello_server.database import UNIQUE_VIOLATION, Identity, sqlstate, transaction
from mazzamurello_server.encryption import decrypt, encrypt
from mazzamurello_server.endpoints import Address, is_public, resolve, tenant_http_client

logger = logging.getLogger(__name__)
router = APIRouter()

OPENROUTER_URL = "https://openrouter.ai/api/v1"
COLUMNS = (
    "c.id, c.name, c.kind, c.base_url, c.location, c.api_key_ciphertext IS NOT NULL AS has_api_key,"
    " c.private_network, c.models_refreshed_at, c.created_at, c.updated_at,"
    " (SELECT count(*) FROM connection_models m WHERE m.connection_id = c.id) AS model_count"
)
CONNECT_SECONDS = 10
READ_SECONDS = 20
RESOLVE_SECONDS = 5
# The most of a response a test quotes, and the longest technical detail.
EXCERPT_CHARS = 500
DETAIL_CHARS = 2000
# Lists older than this are listed again when someone reads them (ADR-0069).
REFRESH_SECONDS = 24 * 3600
TESTS_PER_MINUTE = 20
TOKENS_PER_PRICE = Decimal(1_000_000)


def secret_key_of(request: Request) -> bytes:
    """The key that encrypts API keys, from the process configuration (ADR-0051)."""
    key = request.app.state.configuration.secret_key
    if not isinstance(key, bytes):
        raise RuntimeError("the secret key is not configured")
    return key


type SecretKey = Annotated[bytes, Depends(secret_key_of)]


@dataclass(frozen=True)
class Target:
    """What a test or a model request reaches: a connection's address, credentials and rules."""

    kind: str
    base_url: str
    api_key: str | None
    # Set by the instance admin: any address is allowed (MOD-009).
    private_network: bool


@dataclass(frozen=True)
class ListedModel:
    model: str
    name: str
    context_window: int | None = None
    tools: bool | None = None
    input_price: Decimal | None = None
    cached_input_price: Decimal | None = None
    output_price: Decimal | None = None
    currency: str | None = None


@dataclass
class Probe:
    """A connection test under way: its steps so far and what it found."""

    steps: list[schemas.ConnectionTestStep] = field(default_factory=list[schemas.ConnectionTestStep])
    models: list[ListedModel] = field(default_factory=list[ListedModel])


class _StepError(Exception):
    def __init__(self, reason: str, detail: str, technical: str, http_status: int | None = None) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail
        self.technical = technical
        self.http_status = http_status


def _scrub(value: str, api_key: str | None) -> str:
    """Never repeat the key (MOD-013)."""
    if api_key:
        value = value.replace(api_key, "…")
    return value[:DETAIL_CHARS]


async def _step(probe: Probe, name: str, action: Callable[[], Awaitable[str]]) -> None:
    started = time.monotonic()
    try:
        detail = await action()
    except _StepError as failure:
        probe.steps.append(_record(name, "failed", started, failure.detail))
        raise
    probe.steps.append(_record(name, "passed", started, detail))


def _record(name: str, outcome: str, started: float, detail: str) -> schemas.ConnectionTestStep:
    return schemas.ConnectionTestStep.model_validate(
        {"step": name, "outcome": outcome, "duration_ms": int((time.monotonic() - started) * 1000), "detail": detail}
    )


def _http_client(target: Target) -> httpx.AsyncClient:
    if target.private_network:
        return httpx.AsyncClient(follow_redirects=False, timeout=httpx.Timeout(READ_SECONDS, connect=CONNECT_SECONDS))
    # Checked addresses only, and no redirects (ADR-0061).
    return tenant_http_client()


async def _get(target: Target, path: str, params: dict[str, str] | None = None) -> httpx.Response:
    headers = {} if target.api_key is None else {"Authorization": f"Bearer {target.api_key}"}
    url = target.base_url.rstrip("/") + path
    try:
        async with _http_client(target) as client:
            return await client.get(url, params=params, headers=headers)
    except httpx.TimeoutException as error:
        raise _StepError("timeout", f"no answer from {url}", _scrub(repr(error), target.api_key)) from None
    except httpx.HTTPError as error:
        raise _StepError("connection_refused", f"GET {path} failed", _scrub(str(error), target.api_key)) from None


def _excerpt(response: httpx.Response) -> str:
    return f"HTTP {response.status_code} {response.reason_phrase}\n{response.text[:EXCERPT_CHARS]}"


def _decimal(value: object) -> Decimal | None:
    """A price, or None when it is missing or not a price.

    OpenRouter lists `-1` for a router whose price depends on the model it
    picks: that price is not known.
    """
    try:
        price = None if value is None else Decimal(str(value))
    except InvalidOperation:
        return None
    return price if price is not None and price.is_finite() and price >= 0 else None


def _openrouter_models(payload: list[Any]) -> list[ListedModel]:
    models: list[ListedModel] = []
    for item in payload:
        entry = cast(dict[str, Any], item) if isinstance(item, dict) else {}
        outputs = cast(dict[str, Any], entry.get("architecture") or {}).get("output_modalities") or ["text"]
        if not isinstance(entry.get("id"), str) or "text" not in outputs:
            continue
        pricing = cast(dict[str, Any], entry.get("pricing") or {})
        prompt, completion = _decimal(pricing.get("prompt")), _decimal(pricing.get("completion"))
        cached = _decimal(pricing.get("input_cache_read"))
        priced = prompt is not None and completion is not None
        models.append(
            ListedModel(
                model=entry["id"],
                name=str(entry.get("name") or entry["id"]),
                context_window=entry.get("context_length") if isinstance(entry.get("context_length"), int) else None,
                tools="tools" in (entry.get("supported_parameters") or []),
                # OpenRouter prices one token; the contract prices a million.
                input_price=prompt * TOKENS_PER_PRICE if priced and prompt is not None else None,
                cached_input_price=cached * TOKENS_PER_PRICE if priced and cached is not None else None,
                output_price=completion * TOKENS_PER_PRICE if priced and completion is not None else None,
                currency="USD" if priced else None,
            )
        )
    return models


async def probe(target: Target) -> tuple[schemas.ConnectionTest, list[ListedModel]]:
    """Test a connection step by step, as a request would reach it, and list its models (MOD-013)."""
    result = Probe()
    parts = urlsplit(target.base_url)
    host = parts.hostname or ""
    https = parts.scheme == "https"
    port = parts.port or (443 if https else 80)
    addresses: list[Address] = []

    async def find() -> str:
        try:
            found = await asyncio.wait_for(resolve(host, port), RESOLVE_SECONDS)
        except TimeoutError:
            raise _StepError(
                "timeout", f"{host} could not be looked up in time", f"lookup of {host} timed out"
            ) from None
        if not found:
            raise _StepError("name_not_found", f"{host} was not found", f"getaddrinfo found no address for {host}")
        addresses.extend(found)
        listed = ", ".join(str(address) for address in found[:3])
        # Requests leave from the control plane: only the instance admin's addresses may be private (MOD-009).
        if not target.private_network:
            if not https:
                raise _StepError(
                    "address_not_allowed", "only https addresses are allowed", "plain http needs the instance admin"
                )
            if not all(is_public(address) for address in found):
                raise _StepError(
                    "address_not_allowed",
                    f"{host} is on a private network",
                    f"{host} resolves to {listed}, which is not a public address",
                )
        return listed

    async def connect() -> str:
        try:
            _, writer = await asyncio.wait_for(asyncio.open_connection(str(addresses[0]), port), CONNECT_SECONDS)
        except TimeoutError:
            raise _StepError(
                "timeout", f"no answer from {host}:{port}", f"connect to {addresses[0]}:{port} timed out"
            ) from None
        except OSError as error:
            raise _StepError("connection_refused", f"{host}:{port} refused the connection", str(error)) from None
        writer.close()
        return f"port {port}"

    async def secure() -> str:
        context = ssl.create_default_context()
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(str(addresses[0]), port, ssl=context, server_hostname=host), CONNECT_SECONDS
            )
        except ssl.SSLCertVerificationError as error:
            raise _StepError("tls_untrusted", "the certificate is not trusted", str(error)) from None
        except TimeoutError:
            raise _StepError("timeout", "the secure connection timed out", f"TLS to {host}:{port} timed out") from None
        except OSError as error:
            raise _StepError("tls_untrusted", "the secure connection failed", str(error)) from None
        writer.close()
        return "certificate valid"

    async def authenticate() -> str:
        response = await _get(target, "/key")
        if response.status_code in (401, 403):
            raise _StepError(
                "unauthorized",
                f"GET /key → {response.status_code} {response.reason_phrase}",
                _scrub(_excerpt(response), target.api_key),
                response.status_code,
            )
        if not response.is_success:
            raise _StepError(
                "http_error",
                f"GET /key → {response.status_code} {response.reason_phrase}",
                _scrub(_excerpt(response), target.api_key),
                response.status_code,
            )
        return f"GET /key → {response.status_code} {response.reason_phrase}"

    async def list_models() -> str:
        params = {"sort": "top-weekly"} if target.kind == "openrouter" else None
        response = await _get(target, "/models", params)
        line = f"GET {parts.path.rstrip('/')}/models → {response.status_code} {response.reason_phrase}"
        if response.status_code in (401, 403):
            raise _StepError("unauthorized", line, _scrub(_excerpt(response), target.api_key), response.status_code)
        if not response.is_success:
            raise _StepError("http_error", line, _scrub(_excerpt(response), target.api_key), response.status_code)
        try:
            data = response.json().get("data")
        except (ValueError, AttributeError):
            data = None
        if not isinstance(data, list):
            raise _StepError(
                "not_a_model_server", f"{line}, not a model list", _scrub(_excerpt(response), target.api_key)
            )
        entries = cast(list[Any], data)
        if target.kind == "openrouter":
            result.models = _openrouter_models(entries)
        else:
            listed = [cast(dict[str, Any], item) for item in entries if isinstance(item, dict)]
            names = [str(item["id"]) for item in listed if item.get("id")]
            result.models = [ListedModel(model=name, name=name) for name in names]
        return f"{line}, {len(result.models)} models"

    actions: list[tuple[str, Callable[[], Awaitable[str]]]] = [("resolve", find), ("connect", connect)]
    if https:
        actions.append(("tls", secure))
    if target.kind == "openrouter":
        actions.append(("authenticate", authenticate))
    actions.append(("list_models", list_models))
    for index, (name, action) in enumerate(actions):
        try:
            await _step(result, name, action)
        except _StepError as failure:
            for skipped, _ in actions[index + 1 :]:
                result.steps.append(
                    schemas.ConnectionTestStep.model_validate(
                        {"step": skipped, "outcome": "skipped", "duration_ms": None, "detail": "Not tried"}
                    )
                )
            test = schemas.ConnectionTest.model_validate(
                {
                    "passed": False,
                    "steps": result.steps,
                    "reason": failure.reason,
                    "http_status": failure.http_status,
                    "technical_detail": _scrub(failure.technical or failure.detail, target.api_key),
                    "model_count": None,
                }
            )
            return test, []
    test = schemas.ConnectionTest(
        passed=True,
        steps=result.steps,
        reason=None,
        http_status=None,
        technical_detail=None,
        model_count=len(result.models),
    )
    return test, result.models


class _TestLimit:
    """At most `TESTS_PER_MINUTE` tests per tenant and minute, per API process (T-31)."""

    def __init__(self) -> None:
        self._times: dict[uuid.UUID, collections.deque[float]] = collections.defaultdict(collections.deque)

    def take(self, tenant_id: uuid.UUID) -> None:
        now = time.monotonic()
        times = self._times[tenant_id]
        while times and times[0] <= now - 60:
            times.popleft()
        if len(times) >= TESTS_PER_MINUTE:
            raise errors.rate_limited(max(1, int(times[0] + 60 - now) + 1))
        times.append(now)


_LIMIT = _TestLimit()


def _connection(row: Any) -> schemas.Connection:
    return schemas.Connection(
        id=row.id,
        name=row.name,
        kind=row.kind,
        base_url=row.base_url,
        location=row.location,
        has_api_key=row.has_api_key,
        private_network=row.private_network,
        model_count=row.model_count,
        models_refreshed_at=row.models_refreshed_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _check_admin(identity: Identity) -> None:
    if not identity.tenant_admin:
        raise errors.permission_denied()


def _refused(test: schemas.ConnectionTest) -> errors.ApiError:
    return errors.ApiError(
        422, "connection.test_failed", "The connection failed its test", test=test.model_dump(mode="json")
    )


def _new_target(body: schemas.CreateConnectionRequest, identity: Identity) -> tuple[Target, str]:
    """The target of a new connection, and where its inference runs."""
    if body.kind == "openrouter":
        if body.location == "local":
            raise errors.invalid("/location", "openrouter_is_remote")
        if body.api_key is None:
            raise errors.invalid("/api_key", "required")
        base_url, location = str(body.base_url or OPENROUTER_URL), "remote"
    else:
        if body.base_url is None:
            raise errors.invalid("/base_url", "required")
        if body.location is None:
            raise errors.invalid("/location", "required")
        base_url, location = str(body.base_url), body.location
    return Target(body.kind, base_url.rstrip("/"), body.api_key, identity.instance_admin), location


async def store_models(
    connection: AsyncConnection, tenant_id: uuid.UUID, connection_id: uuid.UUID, models: list[ListedModel]
) -> None:
    """Replace the models of a connection with those just listed."""
    await connection.execute(text("DELETE FROM connection_models WHERE connection_id = :id"), {"id": connection_id})
    for position, listed in enumerate(models, start=1):
        await connection.execute(
            text(
                "INSERT INTO connection_models (tenant_id, connection_id, model, name, position, context_window, tools,"
                " input_price, cached_input_price, output_price, currency) VALUES (:tenant_id, :connection_id, :model,"
                " :name, :position, :context_window, :tools, :input_price, :cached_input_price, :output_price,"
                " :currency) ON CONFLICT (connection_id, model) DO NOTHING"
            ),
            {
                "tenant_id": tenant_id,
                "connection_id": connection_id,
                "model": listed.model,
                "name": listed.name,
                "position": position,
                "context_window": listed.context_window,
                "tools": listed.tools,
                "input_price": listed.input_price,
                "cached_input_price": listed.cached_input_price,
                "output_price": listed.output_price,
                "currency": listed.currency,
            },
        )
    await connection.execute(
        text("UPDATE connections SET models_refreshed_at = clock_timestamp() WHERE id = :id"), {"id": connection_id}
    )


async def _default_if_none(
    connection: AsyncConnection, connection_id: uuid.UUID, kind: str, models: list[ListedModel]
) -> None:
    """Give a household without a default model one of the connection's models (MOD-012, ADR-0069).

    For OpenRouter, its most used free model that can call tools, which costs
    nothing until an admin chooses; for another server, the first model it lists.
    """
    if not models or await default_model(connection) is not None:
        return
    pick = models[0]
    if kind == "openrouter":
        free = [listed for listed in models if listed.input_price == 0 and listed.output_price == 0]
        pick = next((listed for listed in free if listed.tools), free[0] if free else models[0])
    await connection.execute(
        text("UPDATE connections SET default_model = :model WHERE id = :id"), {"model": pick.model, "id": connection_id}
    )


async def _read(connection: AsyncConnection, connection_id: uuid.UUID) -> schemas.Connection:
    row = (
        await connection.execute(text(f"SELECT {COLUMNS} FROM connections c WHERE c.id = :id"), {"id": connection_id})  # noqa: S608
    ).one_or_none()
    if row is None:
        raise errors.not_found()
    return _connection(row)


def _unique(error: DBAPIError) -> errors.ApiError | None:
    return errors.conflict() if sqlstate(error) == UNIQUE_VIOLATION else None


@router.post("/tenant/connections", status_code=status.HTTP_201_CREATED, response_model=schemas.Connection)
async def create_connection(
    body: schemas.CreateConnectionRequest, identity: Authenticated, engine: Engine, secret: SecretKey
) -> schemas.Connection:
    _check_admin(identity)
    target, location = _new_target(body, identity)
    test, models = await probe(target)
    if not test.passed:
        raise _refused(test)
    connection_id = uuid7()
    try:
        async with transaction(engine, identity) as connection:
            await connection.execute(
                text(
                    "INSERT INTO connections (id, tenant_id, name, kind, base_url, location, api_key_ciphertext,"
                    " private_network, created_at, updated_at) VALUES (:id, :tenant_id, :name, :kind, :base_url,"
                    " :location, :key, :private_network, now(), now())"
                ),
                {
                    "id": connection_id,
                    "tenant_id": identity.tenant_id,
                    "name": body.name,
                    "kind": body.kind,
                    "base_url": target.base_url,
                    "location": location,
                    "key": None if body.api_key is None else encrypt(secret, connection_id, body.api_key),
                    "private_network": target.private_network,
                },
            )
            await store_models(connection, identity.tenant_id, connection_id, models)
            await _default_if_none(connection, connection_id, body.kind, models)
            return await _read(connection, connection_id)
    except DBAPIError as error:
        if (refusal := _unique(error)) is not None:
            raise refusal from None
        raise


@router.get("/tenant/connections", response_model=schemas.ConnectionList)
async def list_connections(identity: Authenticated, engine: Engine) -> schemas.ConnectionList:
    _check_admin(identity)
    async with transaction(engine, identity) as connection:
        rows = (await connection.execute(text(f"SELECT {COLUMNS} FROM connections c ORDER BY c.name, c.id"))).all()  # noqa: S608
    return schemas.ConnectionList(items=[_connection(row) for row in rows])


async def _stored_target(connection: AsyncConnection, connection_id: uuid.UUID, secret: bytes) -> tuple[Any, Target]:
    row = (
        await connection.execute(
            text(
                "SELECT id, kind, base_url, location, api_key_ciphertext, private_network FROM connections"
                " WHERE id = :id FOR UPDATE"
            ),
            {"id": connection_id},
        )
    ).one_or_none()
    if row is None:
        raise errors.not_found()
    key = None if row.api_key_ciphertext is None else decrypt(secret, row.id, bytes(row.api_key_ciphertext))
    return row, Target(row.kind, row.base_url, key, row.private_network)


@router.patch("/tenant/connections/{connection_id}", response_model=schemas.Connection)
async def update_connection(
    connection_id: uuid.UUID,
    body: schemas.UpdateConnectionRequest,
    identity: Authenticated,
    engine: Engine,
    secret: SecretKey,
) -> schemas.Connection:
    _check_admin(identity)
    present = body.model_fields_set
    if not present:
        raise errors.invalid("/", "empty")
    for name in ("name", "base_url", "location"):
        if name in present and getattr(body, name) is None:
            raise errors.invalid(f"/{name}", "null")
    async with transaction(engine, identity) as connection:
        row, target = await _stored_target(connection, connection_id, secret)
    if row.kind == "openrouter" and body.location == "local":
        raise errors.invalid("/location", "openrouter_is_remote")
    if "base_url" in present:
        # A new address is private only when the instance admin sets it (MOD-009).
        target = Target(target.kind, str(body.base_url).rstrip("/"), target.api_key, identity.instance_admin)
    if "api_key" in present:
        target = Target(target.kind, target.base_url, body.api_key, target.private_network)
    models: list[ListedModel] | None = None
    if "base_url" in present or "api_key" in present:
        test, models = await probe(target)
        if not test.passed:
            raise _refused(test)
    changes: dict[str, object] = {}
    if "name" in present:
        changes["name"] = body.name
    if "location" in present:
        changes["location"] = body.location
    if "base_url" in present:
        changes["base_url"] = target.base_url
        changes["private_network"] = target.private_network
    if "api_key" in present:
        changes["api_key_ciphertext"] = None if body.api_key is None else encrypt(secret, connection_id, body.api_key)
    assignments = ", ".join(f"{column} = :{column}" for column in changes)
    try:
        async with transaction(engine, identity) as connection:
            if changes:
                result = await connection.execute(
                    text(f"UPDATE connections SET {assignments}, updated_at = now() WHERE id = :id"),  # noqa: S608
                    changes | {"id": connection_id},
                )
                if result.rowcount == 0:
                    raise errors.not_found()
            if models is not None:
                await store_models(connection, identity.tenant_id, connection_id, models)
                await _default_if_none(connection, connection_id, row.kind, models)
            return await _read(connection, connection_id)
    except DBAPIError as error:
        if (refusal := _unique(error)) is not None:
            raise refusal from None
        raise


@router.delete("/tenant/connections/{connection_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def delete_connection(connection_id: uuid.UUID, identity: Authenticated, engine: Engine) -> Response:
    _check_admin(identity)
    async with transaction(engine, identity) as connection:
        result = await connection.execute(text("DELETE FROM connections WHERE id = :id"), {"id": connection_id})
    if result.rowcount == 0:
        raise errors.not_found()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/tenant/connections/{connection_id}/test", response_model=schemas.ConnectionTest)
async def test_connection(
    connection_id: uuid.UUID, identity: Authenticated, engine: Engine, secret: SecretKey
) -> schemas.ConnectionTest:
    _check_admin(identity)
    async with transaction(engine, identity) as connection:
        _, target = await _stored_target(connection, connection_id, secret)
    _LIMIT.take(identity.tenant_id)
    test, models = await probe(target)
    if test.passed:
        async with transaction(engine, identity) as connection:
            await store_models(connection, identity.tenant_id, connection_id, models)
            await _default_if_none(connection, connection_id, target.kind, models)
    return test


@router.post("/tenant/connection-tests", response_model=schemas.ConnectionTest)
async def test_new_connection(body: schemas.CreateConnectionRequest, identity: Authenticated) -> schemas.ConnectionTest:
    _check_admin(identity)
    target, _ = _new_target(body, identity)
    _LIMIT.take(identity.tenant_id)
    test, _ = await probe(target)
    return test


async def offered(connection: AsyncConnection, choice: schemas.ModelChoice) -> bool:
    """Whether a connection of the tenant offers the model; row-level security scopes the lookup."""
    row = (
        await connection.execute(
            text("SELECT 1 FROM connection_models WHERE connection_id = :connection AND model = :model"),
            {"connection": choice.connection_id, "model": choice.model},
        )
    ).one_or_none()
    return row is not None


async def default_model(connection: AsyncConnection) -> schemas.ModelChoiceOut | None:
    row = (
        await connection.execute(text("SELECT id, default_model FROM connections WHERE default_model IS NOT NULL"))
    ).one_or_none()
    return None if row is None else schemas.ModelChoiceOut(connection_id=row.id, model=row.default_model)


@router.put("/tenant/default-model", response_model=schemas.ModelChoiceOut)
async def set_default_model(
    body: schemas.ModelChoice, identity: Authenticated, engine: Engine
) -> schemas.ModelChoiceOut:
    _check_admin(identity)
    async with transaction(engine, identity) as connection:
        if not await offered(connection, body):
            raise errors.invalid("/model", "not_offered")
        await connection.execute(
            text("UPDATE connections SET default_model = NULL WHERE default_model IS NOT NULL AND id <> :id"),
            {"id": body.connection_id},
        )
        await connection.execute(
            text("UPDATE connections SET default_model = :model, updated_at = now() WHERE id = :id"),
            {"id": body.connection_id, "model": body.model},
        )
    return schemas.ModelChoiceOut(connection_id=body.connection_id, model=body.model)


def _prices(row: Any) -> schemas.ModelPricesOut | None:
    if row.currency is None or row.input_price is None or row.output_price is None:
        return None

    def decimal(value: Decimal | None) -> str | None:
        return None if value is None else format(value.normalize(), "f")

    return schemas.ModelPricesOut(
        input=decimal(row.input_price) or "0",
        cached_input=decimal(row.cached_input_price),
        output=decimal(row.output_price) or "0",
        currency=row.currency,
    )


async def _refresh_stale(engine: AsyncEngine, identity: Identity, secret: bytes) -> None:
    """List again the models of connections whose list is older than a day (ADR-0069).

    The refresh changes the tenant's own rows on behalf of whoever read the
    list, so it acts as a tenant admin of the same tenant; row-level security
    still scopes it to that tenant.
    """
    acting = Identity(
        session_id=identity.session_id,
        user_id=identity.user_id,
        tenant_id=identity.tenant_id,
        role="tenant_admin",
        instance_admin=False,
    )
    async with transaction(engine, acting) as connection:
        stale = (
            await connection.execute(
                text(
                    "SELECT id, kind, base_url, api_key_ciphertext, private_network FROM connections"
                    " WHERE models_refreshed_at IS NULL OR models_refreshed_at < now() - make_interval(secs => :age)"
                ),
                {"age": REFRESH_SECONDS},
            )
        ).all()
    for row in stale:
        key = None if row.api_key_ciphertext is None else decrypt(secret, row.id, bytes(row.api_key_ciphertext))
        test, models = await probe(Target(row.kind, row.base_url, key, row.private_network))
        if not test.passed:
            logger.info("the models of connection %s could not be listed: %s", row.id, test.reason)
            continue
        async with transaction(engine, acting) as connection:
            await store_models(connection, identity.tenant_id, row.id, models)


_REFRESHING: set[asyncio.Task[None]] = set()


@router.get("/models", response_model=schemas.ModelList)
async def list_models(identity: Authenticated, engine: Engine, secret: SecretKey) -> schemas.ModelList:
    async with transaction(engine, identity) as connection:
        rows = (
            await connection.execute(
                text(
                    "SELECT m.connection_id, c.name AS connection_name, c.location, m.model, m.name, m.context_window,"
                    " m.tools, m.input_price, m.cached_input_price, m.output_price, m.currency,"
                    " c.models_refreshed_at < now() - make_interval(secs => :age) AS stale"
                    " FROM connection_models m JOIN connections c ON c.id = m.connection_id"
                    " ORDER BY c.name, c.id, m.position"
                ),
                {"age": REFRESH_SECONDS},
            )
        ).all()
        default = await default_model(connection)
    if any(row.stale for row in rows):
        task = asyncio.create_task(_refresh_stale(engine, identity, secret))
        _REFRESHING.add(task)
        task.add_done_callback(_REFRESHING.discard)
    items = [
        schemas.ModelOption(
            connection_id=row.connection_id,
            connection_name=row.connection_name,
            model=row.model,
            name=row.name,
            location=row.location,
            # A local server costs nothing (ADR-0069).
            prices=None if row.location == "local" else _prices(row),
            context_window=row.context_window,
            tools=row.tools,
        )
        for row in rows
    ]
    return schemas.ModelList(items=items, default=default)
