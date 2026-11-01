"""The sandbox driver's API (specs/contracts/sandbox-driver.yaml, ADR-0022).

Every request presents the secret shared with the control plane. Sandboxes
are addressed by tenant and user identifiers; nothing in a request can change
the sandbox policy.
"""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import json
import uuid
from collections.abc import AsyncGenerator, AsyncIterator
from typing import Annotated, Any

import aiodocker
from fastapi import Depends, FastAPI, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from starlette.exceptions import HTTPException as StarletteHTTPException

from mazzamurello_sandboxd.config import DriverConfiguration
from mazzamurello_sandboxd.isolation import Isolation
from mazzamurello_sandboxd.sandboxes import Exit, Output, Sandboxes

API_PREFIX = "/v1"


class DriverError(Exception):
    def __init__(self, status: int, code: str, title: str) -> None:
        super().__init__(code)
        self.status, self.code, self.title = status, code, title


def _problem(status: int, code: str, title: str) -> JSONResponse:
    return JSONResponse(
        {"type": "about:blank", "title": title, "status": status, "code": code},
        status_code=status,
        media_type="application/problem+json",
    )


class ExecRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    argv: Annotated[list[str], Field(min_length=1)] | None = None
    shell_command: Annotated[str, Field(min_length=1)] | None = None
    env: dict[str, str] = Field(default_factory=dict[str, str])
    workdir: str | None = None
    timeout_seconds: Annotated[int, Field(ge=1)] | None = None
    max_output_bytes: Annotated[int, Field(ge=1)] | None = None

    @model_validator(mode="after")
    def _one_command(self) -> ExecRequest:
        if (self.argv is None) == (self.shell_command is None):
            raise ValueError("exactly one of argv and shell_command is required")
        return self


def authenticate(request: Request) -> None:
    configuration: DriverConfiguration = request.app.state.configuration
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(token.strip().encode(), configuration.token.encode()):
        raise DriverError(401, "driver.unauthenticated", "Unauthenticated")


def isolation_of(request: Request) -> Isolation:
    return request.app.state.isolation


def ready(request: Request) -> Sandboxes:
    """Sandboxes, once isolation is verified; refused otherwise (fail closed, SBX-003)."""
    isolation: Isolation = request.app.state.isolation
    if not isolation.state.ready:
        raise DriverError(503, isolation.state.refusal_code(), "Isolation is not verified")
    return request.app.state.sandboxes


def _exit_object(event: Exit) -> dict[str, Any]:
    return {
        "kind": "exit",
        "exit_code": event.exit_code,
        "timed_out": event.timed_out,
        "truncated": event.truncated,
        "duration_ms": event.duration_ms,
    }


def create_app(configuration: DriverConfiguration) -> FastAPI:
    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        docker = aiodocker.Docker()
        sandboxes = Sandboxes(docker, configuration)
        isolation = Isolation(docker, configuration, sandboxes)
        app.state.sandboxes, app.state.isolation = sandboxes, isolation
        await isolation.startup()
        monitor = asyncio.create_task(isolation.monitor())
        try:
            yield
        finally:
            monitor.cancel()
            await docker.close()

    app = FastAPI(
        title="Mazzamurello sandbox driver API", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None
    )
    app.state.configuration = configuration

    authenticated = [Depends(authenticate)]

    @app.exception_handler(DriverError)
    async def driver_error(request: Request, error: DriverError) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return _problem(error.status, error.code, error.title)

    @app.exception_handler(RequestValidationError)
    async def invalid(request: Request, error: RequestValidationError) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return _problem(422, "driver.validation_failed", "Validation failed")

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, error: StarletteHTTPException) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        if error.status_code == 404:
            return _problem(404, "driver.not_found", "Not found")
        return _problem(error.status_code, "driver.validation_failed", "Request not accepted")

    @app.get(f"{API_PREFIX}/health", dependencies=authenticated)
    async def health(isolation: Annotated[Isolation, Depends(isolation_of)]) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return JSONResponse(isolation.state.health(), status_code=200 if isolation.state.ready else 503)

    @app.post(f"{API_PREFIX}/sandboxes/{{tenant_id}}/{{user_id}}/ensure", dependencies=authenticated)
    async def ensure(  # pyright: ignore[reportUnusedFunction]
        tenant_id: uuid.UUID, user_id: uuid.UUID, sandboxes: Annotated[Sandboxes, Depends(ready)]
    ) -> dict[str, Any]:
        return await sandboxes.ensure(tenant_id, user_id)

    @app.post(f"{API_PREFIX}/sandboxes/{{tenant_id}}/{{user_id}}/exec", dependencies=authenticated)
    async def execute(  # pyright: ignore[reportUnusedFunction]
        tenant_id: uuid.UUID, user_id: uuid.UUID, body: ExecRequest, sandboxes: Annotated[Sandboxes, Depends(ready)]
    ) -> StreamingResponse:
        argv = body.argv if body.argv is not None else ["sh", "-c", body.shell_command or ""]
        events = sandboxes.execute(
            tenant_id,
            user_id,
            argv,
            env=body.env,
            workdir=body.workdir,
            timeout_seconds=body.timeout_seconds,
            max_output_bytes=body.max_output_bytes,
        )

        async def lines() -> AsyncIterator[bytes]:
            async for event in events:
                if isinstance(event, Output):
                    item: dict[str, Any] = {"kind": "output", "stream": event.stream, "data": event.data}
                else:
                    item = _exit_object(event)
                yield (json.dumps(item) + "\n").encode()

        return StreamingResponse(lines(), media_type="application/x-ndjson")

    @app.post(f"{API_PREFIX}/sandboxes/{{tenant_id}}/{{user_id}}/stop", dependencies=authenticated)
    async def stop(tenant_id: uuid.UUID, user_id: uuid.UUID, request: Request) -> Response:  # pyright: ignore[reportUnusedFunction]
        await request.app.state.sandboxes.stop(tenant_id, user_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return app
