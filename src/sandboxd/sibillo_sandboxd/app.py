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
import shutil
import tarfile
import tempfile
import uuid
from collections.abc import AsyncGenerator, AsyncIterator
from pathlib import Path
from typing import Annotated, Any

import aiodocker
from fastapi import Depends, FastAPI, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from starlette.background import BackgroundTask
from starlette.exceptions import HTTPException as StarletteHTTPException

from sibillo_sandboxd.config import DriverConfiguration
from sibillo_sandboxd.files import FileOperationError, PathRefusedError
from sibillo_sandboxd.isolation import Isolation
from sibillo_sandboxd.policy import SandboxId
from sibillo_sandboxd.sandboxes import Exit, Output, Sandboxes
from sibillo_sandboxd.workspaces import UnsafeArchiveError

API_PREFIX = "/v1"
# A conversation's sandbox (SBX-001, ADR-0078).
SANDBOX = f"{API_PREFIX}/sandboxes/{{tenant_id}}/{{user_id}}/{{conversation_id}}"


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


class PathRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1)


class MoveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    from_: str = Field(alias="from", min_length=1)
    to: str = Field(min_length=1)


class CopyRequest(BaseModel):
    """The conversation, of the same tenant and user, whose workspace a fork copies (SBX-010)."""

    model_config = ConfigDict(extra="forbid")
    from_conversation_id: uuid.UUID


def authenticate(request: Request) -> None:
    configuration: DriverConfiguration = request.app.state.configuration
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(token.strip().encode(), configuration.token.encode()):
        raise DriverError(401, "driver.unauthenticated", "Unauthenticated")


def isolation_of(request: Request) -> Isolation:
    return request.app.state.isolation


def sandbox_of(tenant_id: uuid.UUID, user_id: uuid.UUID, conversation_id: uuid.UUID) -> SandboxId:
    """The sandbox a request names, by its tenant, user and conversation."""
    return SandboxId(tenant_id, user_id, conversation_id)


type Addressed = Annotated[SandboxId, Depends(sandbox_of)]


def ready(request: Request) -> Sandboxes:
    """Sandboxes, once isolation is verified; refused otherwise (fail closed, SBX-003)."""
    isolation: Isolation = request.app.state.isolation
    if not isolation.state.ready:
        raise DriverError(503, isolation.state.refusal_code(), "Isolation is not verified")
    return request.app.state.sandboxes


def _temporary_folder(prefix: str, parent: Path | None) -> Path:
    return Path(tempfile.mkdtemp(prefix=prefix, dir=parent))


def _exit_object(event: Exit) -> dict[str, Any]:
    return {
        "kind": "exit",
        "exit_code": event.exit_code,
        "timed_out": event.timed_out,
        "truncated": event.truncated,
        "duration_ms": event.duration_ms,
        "workspace_bytes": event.workspace_bytes,
        "workspace_quota_bytes": event.workspace_quota_bytes,
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
        title="Sibillo sandbox driver API", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None
    )
    app.state.configuration = configuration

    authenticated = [Depends(authenticate)]

    @app.exception_handler(DriverError)
    async def driver_error(request: Request, error: DriverError) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return _problem(error.status, error.code, error.title)

    @app.exception_handler(FileOperationError)
    async def file_error(request: Request, error: FileOperationError) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        codes = {404: "driver.not_found", 409: "driver.conflict", 413: "driver.too_large"}
        return _problem(error.status, codes.get(error.status, "driver.validation_failed"), str(error))

    @app.exception_handler(PathRefusedError)
    async def path_refused(request: Request, error: PathRefusedError) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return _problem(422, "driver.validation_failed", f"The path is refused: {error}")

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

    @app.post(f"{SANDBOX}/ensure", dependencies=authenticated)
    async def ensure(  # pyright: ignore[reportUnusedFunction]
        sandbox: Addressed,
        sandboxes: Annotated[Sandboxes, Depends(ready)],
    ) -> dict[str, Any]:
        return await sandboxes.ensure(sandbox)

    @app.post(f"{SANDBOX}/exec", dependencies=authenticated)
    async def execute(  # pyright: ignore[reportUnusedFunction]
        sandbox: Addressed,
        body: ExecRequest,
        sandboxes: Annotated[Sandboxes, Depends(ready)],
    ) -> StreamingResponse:
        argv = body.argv if body.argv is not None else ["sh", "-c", body.shell_command or ""]
        events = sandboxes.execute(
            sandbox,
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

    @app.post(f"{SANDBOX}/stop", dependencies=authenticated)
    async def stop(sandbox: Addressed, request: Request) -> Response:  # pyright: ignore[reportUnusedFunction]
        await request.app.state.sandboxes.stop(sandbox)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.get(f"{SANDBOX}/workspace", dependencies=authenticated)
    async def export_workspace(  # pyright: ignore[reportUnusedFunction]
        sandbox: Addressed,
        sandboxes: Annotated[Sandboxes, Depends(ready)],
    ) -> FileResponse:
        folder = await asyncio.to_thread(_temporary_folder, "sibillo-export-", None)
        archive = folder / "workspace.tar"
        try:
            await sandboxes.export_workspace(sandbox, archive)
        except BaseException:
            await asyncio.to_thread(shutil.rmtree, folder, True)
            raise
        return FileResponse(
            archive,
            media_type="application/x-tar",
            background=BackgroundTask(asyncio.to_thread, shutil.rmtree, folder, True),
        )

    @app.put(f"{SANDBOX}/workspace", dependencies=authenticated)
    async def import_workspace(  # pyright: ignore[reportUnusedFunction]
        sandbox: Addressed,
        request: Request,
        sandboxes: Annotated[Sandboxes, Depends(ready)],
    ) -> Response:
        folder = await asyncio.to_thread(_temporary_folder, "sibillo-import-", None)
        archive = folder / "workspace.tar"
        try:
            with archive.open("wb") as file:
                async for chunk in request.stream():
                    await asyncio.to_thread(file.write, chunk)
            await sandboxes.import_workspace(sandbox, archive)
        except UnsafeArchiveError as error:
            raise DriverError(422, "driver.validation_failed", f"The archive is refused: {error}") from error
        except tarfile.TarError as error:
            raise DriverError(422, "driver.validation_failed", "The archive is not a tar archive") from error
        finally:
            await asyncio.to_thread(shutil.rmtree, folder, True)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.delete(f"{SANDBOX}/workspace", dependencies=authenticated)
    async def delete_workspace(  # pyright: ignore[reportUnusedFunction]
        sandbox: Addressed,
        sandboxes: Annotated[Sandboxes, Depends(ready)],
    ) -> Response:
        await sandboxes.delete_workspace(sandbox)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.post(
        f"{SANDBOX}/workspace/copy",
        dependencies=authenticated,
    )
    async def copy_workspace(  # pyright: ignore[reportUnusedFunction]
        sandbox: Addressed,
        body: CopyRequest,
        sandboxes: Annotated[Sandboxes, Depends(ready)],
    ) -> Response:
        folder = await asyncio.to_thread(_temporary_folder, "sibillo-copy-", None)
        try:
            await sandboxes.copy_workspace(
                sandbox,
                SandboxId(sandbox.tenant_id, sandbox.user_id, body.from_conversation_id),
                folder,
            )
        finally:
            await asyncio.to_thread(shutil.rmtree, folder, True)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    # Files of the workspace (SBX-014, ADR-0079).

    @app.get(f"{SANDBOX}/size", dependencies=authenticated)
    async def workspace_size(  # pyright: ignore[reportUnusedFunction]
        sandbox: Addressed, sandboxes: Annotated[Sandboxes, Depends(ready)]
    ) -> dict[str, int]:
        return await sandboxes.workspace_size(sandbox)

    @app.get(f"{SANDBOX}/entries", dependencies=authenticated)
    async def list_folder(  # pyright: ignore[reportUnusedFunction]
        sandbox: Addressed, path: str, sandboxes: Annotated[Sandboxes, Depends(ready)]
    ) -> dict[str, Any]:
        return await sandboxes.list_folder(sandbox, path)

    @app.delete(f"{SANDBOX}/entries", dependencies=authenticated)
    async def delete_entry(  # pyright: ignore[reportUnusedFunction]
        sandbox: Addressed, path: str, sandboxes: Annotated[Sandboxes, Depends(ready)]
    ) -> Response:
        await sandboxes.delete_entry(sandbox, path)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.get(f"{SANDBOX}/files", dependencies=authenticated)
    async def read_file(  # pyright: ignore[reportUnusedFunction]
        sandbox: Addressed, path: str, sandboxes: Annotated[Sandboxes, Depends(ready)]
    ) -> StreamingResponse:
        item, content = await sandboxes.read_file(sandbox, path)
        return StreamingResponse(
            content, media_type="application/octet-stream", headers={"Content-Length": str(item["size"])}
        )

    @app.put(f"{SANDBOX}/files", dependencies=authenticated, status_code=status.HTTP_201_CREATED)
    async def write_file(  # pyright: ignore[reportUnusedFunction]
        sandbox: Addressed, path: str, request: Request, sandboxes: Annotated[Sandboxes, Depends(ready)]
    ) -> dict[str, Any]:
        length = request.headers.get("content-length", "")
        if not length.isdigit():
            raise DriverError(422, "driver.validation_failed", "Content-Length is required")
        return await sandboxes.write_file(sandbox, path, int(length), request.stream())

    @app.get(f"{SANDBOX}/archive", dependencies=authenticated)
    async def zip_folder(  # pyright: ignore[reportUnusedFunction]
        sandbox: Addressed, path: str, sandboxes: Annotated[Sandboxes, Depends(ready)]
    ) -> FileResponse:
        folder = await asyncio.to_thread(_temporary_folder, "sibillo-zip-", None)
        archive = folder / "folder.zip"
        try:
            await sandboxes.zip_folder(sandbox, path, archive)
        except BaseException:
            await asyncio.to_thread(shutil.rmtree, folder, True)
            raise
        return FileResponse(
            archive,
            media_type="application/zip",
            background=BackgroundTask(asyncio.to_thread, shutil.rmtree, folder, True),
        )

    @app.post(f"{SANDBOX}/folders", dependencies=authenticated, status_code=status.HTTP_201_CREATED)
    async def create_folder(  # pyright: ignore[reportUnusedFunction]
        sandbox: Addressed, body: PathRequest, sandboxes: Annotated[Sandboxes, Depends(ready)]
    ) -> dict[str, Any]:
        return await sandboxes.create_folder(sandbox, body.path)

    @app.post(f"{SANDBOX}/move", dependencies=authenticated)
    async def move_entry(  # pyright: ignore[reportUnusedFunction]
        sandbox: Addressed, body: MoveRequest, sandboxes: Annotated[Sandboxes, Depends(ready)]
    ) -> dict[str, Any]:
        return await sandboxes.move_entry(sandbox, body.from_, body.to)

    return app
