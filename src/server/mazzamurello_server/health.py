"""The instance's health (OPS-002, ADR-0054).

`unavailable` when the database is unreachable or the sandbox driver
refuses sandboxes, `degraded` when no household has a default model (ADR-0069)
or when backups fail (OPS-011), `ok` otherwise. Anonymous callers and members see only the status; instance
admins see every check.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, cast

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from mazzamurello_server import errors
from mazzamurello_server.auth import SESSION_COOKIE, Engine, authenticate
from mazzamurello_server.database import Identity, transaction

router = APIRouter()

type Status = Literal["ok", "degraded", "unavailable"]
DRIVER_TIMEOUT_SECONDS = 5
# How old the last successful backup, or the schedule's start, may be (OPS-011).
BACKUP_MAX_AGE = timedelta(days=2)


async def _database_and_model(engine: Engine) -> tuple[Status, Status]:
    try:
        async with transaction(engine, None) as connection:
            configured = (await connection.execute(text("SELECT default_model_configured()"))).scalar_one()
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


def _backups(status_file: Path) -> Status:
    """`degraded` when the backup service's status is missing, its newest attempt failed, or it is stale (OPS-011)."""
    try:
        loaded: object = json.loads(status_file.read_text())
    except (OSError, ValueError):
        return "degraded"
    if not isinstance(loaded, dict):
        return "degraded"
    status = cast(dict[str, Any], loaded)
    if status.get("outcome") == "failed":
        return "degraded"
    recent = datetime.now(UTC) - BACKUP_MAX_AGE
    for key in ("last_success", "started"):
        try:
            if status.get(key) and datetime.fromisoformat(str(status[key])) >= recent:
                return "ok"
        except ValueError:
            return "degraded"
    return "degraded"


async def _identity(request: Request, engine: Engine) -> Identity | None:
    """The caller, when signed in; health is also answered without a session."""
    if not request.headers.get("authorization") and not request.cookies.get(SESSION_COOKIE):
        return None
    try:
        return await authenticate(request, engine)
    except errors.ApiError:
        return None


@router.get("/health")
async def get_health(request: Request, engine: Engine) -> JSONResponse:
    database, model = await _database_and_model(engine)
    checks: dict[str, Status] = {"database": database, **await _driver(request), "model_gateway": model}
    status_file: Path | None = request.app.state.configuration.backup_status
    if status_file is not None:
        checks["backups"] = _backups(status_file)
    if database == "unavailable" or checks["sandbox_driver"] != "ok":
        status: Status = "unavailable"
    elif model != "ok" or checks.get("backups", "ok") != "ok":
        status = "degraded"
    else:
        status = "ok"
    body: dict[str, Any] = {"status": status}
    identity = await _identity(request, engine)
    if identity is not None and identity.instance_admin:
        body["checks"] = checks
    return JSONResponse(body, status_code=503 if status == "unavailable" else 200)
