"""The instance's health (OPS-002, ADR-0054).

`unavailable` when the database is unreachable or the sandbox driver
refuses sandboxes, `degraded` when no instance default model is configured,
`ok` otherwise. Anonymous callers and members see only the status; instance
admins see every check.
"""

from __future__ import annotations

from typing import Any, Literal

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from mazzamurello_server import errors
from mazzamurello_server.auth import Engine, authenticate
from mazzamurello_server.database import Identity, transaction

router = APIRouter()

type Status = Literal["ok", "degraded", "unavailable"]
DRIVER_TIMEOUT_SECONDS = 5


async def _database_and_model(engine: Engine) -> tuple[Status, Status]:
    try:
        async with transaction(engine, None) as connection:
            configured = (await connection.execute(text("SELECT instance_default_model_configured()"))).scalar_one()
    except (SQLAlchemyError, OSError):
        return "unavailable", "unavailable"
    return "ok", "ok" if configured else "degraded"


async def _driver(request: Request) -> dict[str, Status]:
    configuration = request.app.state.configuration
    unreachable: dict[str, Status] = dict.fromkeys(
        ("sandbox_driver", "platform", "isolation_runtime", "egress_table"), "unavailable"
    )
    try:
        async with httpx.AsyncClient(timeout=DRIVER_TIMEOUT_SECONDS) as client:
            response = await client.get(
                f"{configuration.sandboxd_url}/health",
                headers={"Authorization": f"Bearer {configuration.sandboxd_token}"},
            )
        health: dict[str, Any] = response.json()
        checks: dict[str, dict[str, Any]] = health["checks"]
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return unreachable

    def state(*names: str) -> Status:
        return "ok" if all(checks.get(name, {}).get("ok") is True for name in names) else "unavailable"

    return {
        "sandbox_driver": "ok" if health.get("ready") is True else "unavailable",
        "platform": state("platform"),
        "isolation_runtime": state("isolation_runtime", "runtime_version", "canary"),
        "egress_table": state("egress_table"),
    }


async def _identity(request: Request, engine: Engine) -> Identity | None:
    """The caller, when signed in; health is also answered without a session."""
    if not request.headers.get("authorization"):
        return None
    try:
        return await authenticate(request, engine)
    except errors.ApiError:
        return None


@router.get("/health")
async def get_health(request: Request, engine: Engine) -> JSONResponse:
    database, model = await _database_and_model(engine)
    checks: dict[str, Status] = {"database": database, **await _driver(request), "model_gateway": model}
    if database == "unavailable" or checks["sandbox_driver"] != "ok":
        status: Status = "unavailable"
    elif model != "ok":
        status = "degraded"
    else:
        status = "ok"
    body: dict[str, Any] = {"status": status}
    identity = await _identity(request, engine)
    if identity is not None and identity.instance_admin:
        body["checks"] = checks
    return JSONResponse(body, status_code=503 if status == "unavailable" else 200)
