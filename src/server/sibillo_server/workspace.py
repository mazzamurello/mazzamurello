"""A conversation's workspace through the API (UX-019, UX-020, CNV-017, SBX-014, ADR-0079).

Only the conversation's owner reaches it: every operation first finds the
conversation under row-level security (TEN-006), then asks the sandbox
driver, streaming bodies both ways. A file is served for download as an
attachment, and for preview only with a type of `PREVIEW_TYPES`, never as a
page of the app (UX-020).
"""

from __future__ import annotations

import logging
import posixpath
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from starlette.background import BackgroundTask

from sibillo_server import errors, schemas
from sibillo_server.auth import Authenticated, Engine
from sibillo_server.conversations import find_conversation
from sibillo_server.database import Identity, transaction

router = APIRouter()
logger = logging.getLogger(__name__)

DRIVER_TIMEOUT_SECONDS = 600
CHUNK_BYTES = 1024 * 1024
UPLOADS = "uploads"
# The most of a text a preview shows (UX-020).
TEXT_PREVIEW_BYTES = 1024 * 1024
TEXT = "text/plain; charset=utf-8"
# The types a preview may have, by extension; anything else is downloaded (ADR-0079).
PREVIEW_TYPES: dict[str, str] = {
    **dict.fromkeys(
        (
            ".txt",
            ".log",
            ".json",
            ".yaml",
            ".yml",
            ".toml",
            ".ini",
            ".cfg",
            ".py",
            ".js",
            ".ts",
            ".tsx",
            ".jsx",
            ".css",
            ".sh",
            ".sql",
            ".xml",
            ".html",
            ".htm",
            ".c",
            ".h",
            ".rs",
            ".go",
            ".java",
            ".rb",
            # Diagrams the viewer draws (ART-002, ADR-0086).
            ".mmd",
            ".mermaid",
        ),
        TEXT,
    ),
    ".md": "text/markdown; charset=utf-8",
    ".csv": "text/csv; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".pdf": "application/pdf",
    ".mp3": "audio/mpeg",
    ".ogg": "audio/ogg",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
}
# A file opened by itself, as from a link in an answer, runs nothing in the app's origin (UX-020, T-22).
FILE_POLICY = "default-src 'none'; img-src 'self' data:; media-src 'self'; style-src 'unsafe-inline'; sandbox"
# A web page runs as a stranger to the app, an opaque origin, with nothing from the network (ART-003, ADR-0086).
PAGE_POLICY = (
    "default-src 'none'; script-src 'unsafe-inline' 'unsafe-eval'; style-src 'unsafe-inline';"
    " img-src data: blob:; font-src data:; media-src data: blob:; sandbox allow-scripts"
)
PAGE_EXTENSIONS = frozenset({".html", ".htm"})
# The browser's PDF viewer does not open in a sandboxed document; a PDF runs nothing of the app either.
PDF_POLICY = "default-src 'none'; object-src 'self'; plugin-types application/pdf"
SAFE_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "private, no-store",
    "Content-Security-Policy": FILE_POLICY,
}

type WorkspacePath = Annotated[str, Query(alias="path", max_length=4096)]


class _Driver:
    """The sandbox driver, for one conversation's workspace."""

    def __init__(self, request: Request, identity: Identity, conversation_id: uuid.UUID) -> None:
        configuration = request.app.state.configuration
        self.base = f"{configuration.sandboxd_url}/sandboxes/{identity.tenant_id}/{identity.user_id}/{conversation_id}"
        self.headers = {"Authorization": f"Bearer {configuration.sandboxd_token}"}

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(headers=self.headers, timeout=DRIVER_TIMEOUT_SECONDS)

    async def call(self, method: str, path: str, **options: Any) -> httpx.Response:
        try:
            async with self.client() as client:
                response = await client.request(method, f"{self.base}{path}", **options)
        except httpx.HTTPError as error:
            logger.warning("the sandbox driver could not be reached: %s", type(error).__name__)
            raise _unavailable() from error
        _raise_for(response)
        return response


def _unavailable() -> errors.ApiError:
    return errors.ApiError(503, "sandbox.unavailable", "The sandbox is unavailable")


def _raise_for(response: httpx.Response) -> None:
    """The driver's refusal as the API's (SBX-014)."""
    if response.status_code < 400:
        return
    if response.status_code == 404:
        raise errors.not_found()
    if response.status_code == 409:
        raise errors.ApiError(409, "resource.conflict", "The path exists already")
    if response.status_code == 413:
        raise errors.ApiError(413, "workspace.quota_exceeded", "The upload would exceed the workspace's quota")
    if response.status_code == 422:
        raise errors.invalid("/path", "refused")
    logger.warning("the sandbox driver answered %d: %s", response.status_code, response.text[:300])
    raise _unavailable()


async def _driver(request: Request, identity: Identity, engine: Any, conversation_id: uuid.UUID) -> _Driver:
    async with transaction(engine, identity) as connection:
        await find_conversation(connection, conversation_id)
    return _Driver(request, identity, conversation_id)


def _entry(item: dict[str, Any]) -> schemas.WorkspaceEntry:
    return schemas.WorkspaceEntry.model_validate(item)


def _disposition(kind: str, name: str) -> str:
    """A `Content-Disposition` naming the file, for any name (RFC 6266)."""
    ascii_name = name.encode("ascii", "replace").decode().replace('"', "'").replace("\\", "_")
    return f"{kind}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"


@router.get("/conversations/{conversation_id}/workspace", response_model=schemas.WorkspaceSummary)
async def get_workspace(
    conversation_id: uuid.UUID, identity: Authenticated, engine: Engine, request: Request
) -> schemas.WorkspaceSummary:
    driver = await _driver(request, identity, engine, conversation_id)
    size = (await driver.call("GET", "/size")).json()
    return schemas.WorkspaceSummary(size=size["bytes"], quota=size["quota_bytes"])


@router.delete(
    "/conversations/{conversation_id}/workspace", status_code=status.HTTP_204_NO_CONTENT, response_class=Response
)
async def reset_workspace(
    conversation_id: uuid.UUID, identity: Authenticated, engine: Engine, request: Request
) -> Response:
    async with transaction(engine, identity) as connection:
        await find_conversation(connection, conversation_id)
        active = (
            await connection.execute(
                text("SELECT 1 FROM runs WHERE conversation_id = :id AND status IN ('queued', 'running') LIMIT 1"),
                {"id": conversation_id},
            )
        ).one_or_none()
    if active is not None:
        raise errors.ApiError(409, "run.in_progress", "Run in progress")
    await _Driver(request, identity, conversation_id).call("DELETE", "/workspace")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/conversations/{conversation_id}/workspace/entries", response_model=schemas.WorkspaceFolder)
async def list_workspace_folder(
    conversation_id: uuid.UUID, path: WorkspacePath, identity: Authenticated, engine: Engine, request: Request
) -> schemas.WorkspaceFolder:
    driver = await _driver(request, identity, engine, conversation_id)
    entries = (await driver.call("GET", "/entries", params={"path": path})).json()["entries"]
    return schemas.WorkspaceFolder(path=path, entries=[_entry(item) for item in entries])


@router.delete(
    "/conversations/{conversation_id}/workspace/entries",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_workspace_entry(
    conversation_id: uuid.UUID, path: WorkspacePath, identity: Authenticated, engine: Engine, request: Request
) -> Response:
    driver = await _driver(request, identity, engine, conversation_id)
    await driver.call("DELETE", "/entries", params={"path": path})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _stream(driver: _Driver, path: str, params: dict[str, str]) -> tuple[httpx.Response, httpx.AsyncClient]:
    """An open streamed answer of the driver; the caller closes both."""
    client = driver.client()
    try:
        response = await client.send(client.build_request("GET", f"{driver.base}{path}", params=params), stream=True)
    except httpx.HTTPError as error:
        await client.aclose()
        logger.warning("the sandbox driver could not be reached: %s", type(error).__name__)
        raise _unavailable() from error
    if response.status_code >= 400:
        await response.aread()
        await response.aclose()
        await client.aclose()
        _raise_for(response)
    return response, client


async def _limited(chunks: AsyncIterator[bytes], limit: int | None) -> AsyncIterator[bytes]:
    sent = 0
    async for chunk in chunks:
        if limit is not None and sent + len(chunk) >= limit:
            yield chunk[: limit - sent]
            return
        sent += len(chunk)
        yield chunk


@router.get("/conversations/{conversation_id}/workspace/file")
async def read_workspace_file(
    conversation_id: uuid.UUID,
    path: WorkspacePath,
    identity: Authenticated,
    engine: Engine,
    request: Request,
    preview: bool = False,
    page: bool = False,
) -> StreamingResponse:
    name = posixpath.basename(path.rstrip("/")) or "file"
    if page and posixpath.splitext(name)[1].lower() not in PAGE_EXTENSIONS:
        raise errors.ApiError(415, "file.not_previewable", "Only a web page runs; download this file instead")
    preview_type = PREVIEW_TYPES.get(posixpath.splitext(name)[1].lower()) if preview else None
    if preview and preview_type is None:
        raise errors.ApiError(415, "file.not_previewable", "This file has no preview; download it instead")
    driver = await _driver(request, identity, engine, conversation_id)
    response, client = await _stream(driver, "/files", {"path": path})

    async def close() -> None:
        await response.aclose()
        await client.aclose()

    if page:
        return StreamingResponse(
            _limited(response.aiter_bytes(CHUNK_BYTES), TEXT_PREVIEW_BYTES),
            media_type="text/html",
            headers={
                **SAFE_HEADERS,
                "Content-Security-Policy": PAGE_POLICY,
                "Content-Disposition": _disposition("inline", name),
            },
            background=BackgroundTask(close),
        )
    if preview_type is not None:
        limit = TEXT_PREVIEW_BYTES if preview_type.startswith("text/") else None
        policy = PDF_POLICY if preview_type == "application/pdf" else FILE_POLICY
        return StreamingResponse(
            _limited(response.aiter_bytes(CHUNK_BYTES), limit),
            media_type=preview_type,
            headers={
                **SAFE_HEADERS,
                "Content-Security-Policy": policy,
                "Content-Disposition": _disposition("inline", name),
            },
            background=BackgroundTask(close),
        )
    return StreamingResponse(
        response.aiter_bytes(CHUNK_BYTES),
        media_type="application/octet-stream",
        headers={
            **SAFE_HEADERS,
            "Content-Disposition": _disposition("attachment", name),
            "Content-Length": response.headers.get("content-length", ""),
        },
        background=BackgroundTask(close),
    )


async def _write(request: Request, driver: _Driver, path: str) -> schemas.WorkspaceEntry:
    """Stream the request's body into the workspace at `path` (SBX-014, SBX-019)."""
    length = request.headers.get("content-length", "")
    if not length.isdigit():
        raise errors.ApiError(411, "request.validation_failed", "Content-Length is required")
    limit = request.app.state.configuration.upload_max_mb * 1024 * 1024
    if int(length) > limit:
        raise errors.ApiError(413, "file.too_large", "The file is larger than uploads may be")
    response = await driver.call(
        "PUT",
        "/files",
        params={"path": path},
        content=request.stream(),
        headers={"Content-Length": length, "Content-Type": "application/octet-stream"},
    )
    return _entry(response.json())


@router.put(
    "/conversations/{conversation_id}/workspace/file",
    status_code=status.HTTP_201_CREATED,
    response_model=schemas.WorkspaceEntry,
)
async def write_workspace_file(
    conversation_id: uuid.UUID, path: WorkspacePath, identity: Authenticated, engine: Engine, request: Request
) -> schemas.WorkspaceEntry:
    driver = await _driver(request, identity, engine, conversation_id)
    return await _write(request, driver, path)


def _numbered(name: str, number: int) -> str:
    """`budget.csv`, then `budget (2).csv`, `budget (3).csv`, … (CNV-017)."""
    if number == 1:
        return name
    stem, extension = posixpath.splitext(name)
    return f"{stem} ({number}){extension}"


def _attachment_name(name: str) -> str:
    """The name of a file on the user's device, as a name and never a path."""
    cleaned = posixpath.basename(name.replace("\\", "/")).strip()
    if cleaned in ("", ".", "..") or "\0" in cleaned:
        raise errors.invalid("/name", "invalid")
    return cleaned


@router.post(
    "/conversations/{conversation_id}/workspace/uploads",
    status_code=status.HTTP_201_CREATED,
    response_model=schemas.WorkspaceEntry,
)
async def upload_attachment(
    conversation_id: uuid.UUID,
    identity: Authenticated,
    engine: Engine,
    request: Request,
    name: Annotated[str, Query(min_length=1, max_length=255)],
) -> schemas.WorkspaceEntry:
    driver = await _driver(request, identity, engine, conversation_id)
    wanted = _attachment_name(name)
    taken: set[str] = set()
    try:
        response = await driver.call("GET", "/entries", params={"path": UPLOADS})
        listed: list[dict[str, Any]] = response.json()["entries"]
        taken = {str(item["name"]) for item in listed}
    except errors.ApiError as error:
        if error.status != 404:
            raise
    number = 1
    while _numbered(wanted, number) in taken:
        number += 1
    return await _write(request, driver, f"{UPLOADS}/{_numbered(wanted, number)}")


@router.get("/conversations/{conversation_id}/workspace/archive")
async def download_workspace_folder(
    conversation_id: uuid.UUID, path: WorkspacePath, identity: Authenticated, engine: Engine, request: Request
) -> StreamingResponse:
    driver = await _driver(request, identity, engine, conversation_id)
    response, client = await _stream(driver, "/archive", {"path": path})

    async def close() -> None:
        await response.aclose()
        await client.aclose()

    name = f"{posixpath.basename(path.rstrip('/')) or 'workspace'}.zip"
    return StreamingResponse(
        response.aiter_bytes(CHUNK_BYTES),
        media_type="application/zip",
        headers={**SAFE_HEADERS, "Content-Disposition": _disposition("attachment", name)},
        background=BackgroundTask(close),
    )


@router.post(
    "/conversations/{conversation_id}/workspace/folders",
    status_code=status.HTTP_201_CREATED,
    response_model=schemas.WorkspaceEntry,
)
async def create_workspace_folder(
    conversation_id: uuid.UUID,
    body: schemas.WorkspacePathRequest,
    identity: Authenticated,
    engine: Engine,
    request: Request,
) -> schemas.WorkspaceEntry:
    driver = await _driver(request, identity, engine, conversation_id)
    return _entry((await driver.call("POST", "/folders", json={"path": body.path})).json())


@router.post("/conversations/{conversation_id}/workspace/move", response_model=schemas.WorkspaceEntry)
async def move_workspace_entry(
    conversation_id: uuid.UUID,
    body: schemas.WorkspaceMoveRequest,
    identity: Authenticated,
    engine: Engine,
    request: Request,
) -> schemas.WorkspaceEntry:
    driver = await _driver(request, identity, engine, conversation_id)
    return _entry((await driver.call("POST", "/move", json={"from": body.from_, "to": body.to})).json())


async def attachment_entries(
    request: Request, identity: Identity, conversation_id: uuid.UUID, paths: list[str]
) -> list[dict[str, Any]]:
    """The attached files, as `{path, size}`: each must be a file of `uploads/` (CNV-017)."""
    if not paths:
        return []
    driver = _Driver(request, identity, conversation_id)
    try:
        listed = (await driver.call("GET", "/entries", params={"path": UPLOADS})).json()["entries"]
    except errors.ApiError as error:
        if error.status in (404, 422):
            raise errors.invalid("/attachments", "not_uploaded") from error
        raise
    files = {item["path"]: item for item in listed if item["type"] == "file"}
    found: list[dict[str, Any]] = []
    for path in paths:
        item = files.get(posixpath.normpath(path)) if not path.startswith("/") else None
        if item is None or posixpath.normpath(path) != path:
            raise errors.invalid("/attachments", "not_uploaded")
        found.append({"path": item["path"], "size": item["size"]})
    return found
