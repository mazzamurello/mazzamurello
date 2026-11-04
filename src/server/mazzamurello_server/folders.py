"""Folders, the conversation list and search (CNV-007, CNV-008, CNV-009, ADR-0073).

Everything here is the user's own: row-level security scopes every query to
their rows (TEN-003), so no query filters by user.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Query, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from mazzamurello_server import errors, schemas
from mazzamurello_server.auth import Authenticated, Engine
from mazzamurello_server.conversations import CONVERSATION_COLUMNS, conversation_response, decode_cursor, encode_cursor
from mazzamurello_server.credentials import uuid7
from mazzamurello_server.database import transaction

router = APIRouter()

# A folder's time is that of its newest conversation, or its creation while empty (CNV-008).
FOLDER_COLUMNS = (
    "f.id, f.name, f.pinned_at IS NOT NULL AS pinned, f.collapsed, f.created_at,"
    " (SELECT max(c.last_message_at) FROM conversations c WHERE c.folder_id = f.id AND c.archived_at IS NULL)"
    " AS last_message_at"
)
SNIPPET_CHARS = 200

type Limit = Annotated[int, Query(ge=1, le=100)]


def _folder(row: Any) -> schemas.Folder:
    return schemas.Folder(
        id=row.id,
        name=row.name,
        pinned=row.pinned,
        collapsed=row.collapsed,
        last_message_at=row.last_message_at,
        created_at=row.created_at,
    )


async def _read_folder(connection: AsyncConnection, folder_id: uuid.UUID) -> schemas.Folder:
    row = (
        await connection.execute(text(f"SELECT {FOLDER_COLUMNS} FROM folders f WHERE f.id = :id"), {"id": folder_id})  # noqa: S608
    ).one_or_none()
    if row is None:
        raise errors.not_found()
    return _folder(row)


@router.post("/folders", status_code=status.HTTP_201_CREATED, response_model=schemas.Folder)
async def create_folder(body: schemas.CreateFolderRequest, identity: Authenticated, engine: Engine) -> schemas.Folder:
    folder_id = uuid7()
    async with transaction(engine, identity) as connection:
        await connection.execute(
            text(
                "INSERT INTO folders (id, tenant_id, owner_id, name, created_at, updated_at)"
                " VALUES (:id, :tenant_id, :owner_id, :name, now(), now())"
            ),
            {"id": folder_id, "tenant_id": identity.tenant_id, "owner_id": identity.user_id, "name": body.name},
        )
        return await _read_folder(connection, folder_id)


@router.patch("/folders/{folder_id}", response_model=schemas.Folder)
async def update_folder(
    folder_id: uuid.UUID, body: schemas.UpdateFolderRequest, identity: Authenticated, engine: Engine
) -> schemas.Folder:
    present = body.model_fields_set
    if not present:
        raise errors.invalid("/", "empty")
    for name in present:
        if getattr(body, name) is None:
            raise errors.invalid(f"/{name}", "null")
    async with transaction(engine, identity) as connection:
        result = await connection.execute(
            text(
                "UPDATE folders SET name = coalesce(:name, name), collapsed = coalesce(:collapsed, collapsed),"
                " pinned_at = CASE WHEN CAST(:pinned AS boolean) IS NULL THEN pinned_at"
                " WHEN CAST(:pinned AS boolean) THEN coalesce(pinned_at, now()) ELSE NULL END, updated_at = now()"
                " WHERE id = :id"
            ),
            {"id": folder_id, "name": body.name, "collapsed": body.collapsed, "pinned": body.pinned},
        )
        if result.rowcount == 0:
            raise errors.not_found()
        return await _read_folder(connection, folder_id)


@router.delete("/folders/{folder_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def delete_folder(folder_id: uuid.UUID, identity: Authenticated, engine: Engine) -> Response:
    """Its conversations move out of it, by the foreign key (CNV-007)."""
    async with transaction(engine, identity) as connection:
        result = await connection.execute(text("DELETE FROM folders WHERE id = :id"), {"id": folder_id})
    if result.rowcount == 0:
        raise errors.not_found()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/conversation-list", response_model=schemas.ConversationListPage)
async def conversation_list(
    identity: Authenticated, engine: Engine, cursor: str | None = None, limit: Limit = 50
) -> schemas.ConversationListPage:
    """Pinned entries first, then newest first; a folder carries its conversations (CNV-008)."""
    after: tuple[bool, datetime.datetime, uuid.UUID] | None = None
    if cursor is not None:
        decoded = decode_cursor(cursor)
        try:
            after = (bool(decoded[0]), datetime.datetime.fromisoformat(decoded[1]), uuid.UUID(decoded[2]))
        except (TypeError, ValueError, IndexError):
            raise errors.invalid("cursor", "invalid") from None
    async with transaction(engine, identity) as connection:
        entries = (
            await connection.execute(
                text(
                    "SELECT kind, id, pinned, at FROM ("
                    " SELECT 'folder' AS kind, f.id, f.pinned_at IS NOT NULL AS pinned,"
                    " coalesce((SELECT max(c.last_message_at) FROM conversations c"
                    " WHERE c.folder_id = f.id AND c.archived_at IS NULL), f.created_at) AS at FROM folders f"
                    " UNION ALL"
                    " SELECT 'conversation', c.id, c.pinned_at IS NOT NULL, c.last_message_at FROM conversations c"
                    " WHERE c.folder_id IS NULL AND c.archived_at IS NULL"
                    ") entries"
                    " WHERE CAST(:after_at AS timestamptz) IS NULL"
                    " OR (pinned, at, id) < (CAST(:after_pinned AS boolean), CAST(:after_at AS timestamptz),"
                    " CAST(:after_id AS uuid))"
                    " ORDER BY pinned DESC, at DESC, id DESC LIMIT :limit"
                ),
                {
                    "after_pinned": None if after is None else after[0],
                    "after_at": None if after is None else after[1],
                    "after_id": None if after is None else after[2],
                    "limit": limit + 1,
                },
            )
        ).all()
        page = entries[:limit]
        folder_ids = [entry.id for entry in page if entry.kind == "folder"]
        conversation_ids = [entry.id for entry in page if entry.kind == "conversation"]
        folders = {
            row.id: _folder(row)
            for row in await connection.execute(
                text(f"SELECT {FOLDER_COLUMNS} FROM folders f WHERE f.id = ANY(:ids)"),  # noqa: S608
                {"ids": folder_ids},
            )
        }
        rows = (
            await connection.execute(
                text(
                    f"SELECT {CONVERSATION_COLUMNS} FROM conversations"  # noqa: S608
                    " WHERE archived_at IS NULL AND (id = ANY(:ids) OR folder_id = ANY(:folders))"
                    " ORDER BY pinned_at IS NOT NULL DESC, last_message_at DESC, id DESC"
                ),
                {"ids": conversation_ids, "folders": folder_ids},
            )
        ).all()
    conversations = {row.id: conversation_response(row) for row in rows}
    inside: dict[uuid.UUID, list[schemas.Conversation]] = {folder_id: [] for folder_id in folder_ids}
    for row in rows:
        if row.folder_id in inside:
            inside[row.folder_id].append(conversations[row.id])
    items: list[schemas.FolderEntry | schemas.ConversationEntry] = [
        schemas.FolderEntry(folder=folders[entry.id], conversations=inside[entry.id])
        if entry.kind == "folder"
        else schemas.ConversationEntry(conversation=conversations[entry.id])
        for entry in page
    ]
    next_cursor = None
    if len(entries) > limit:
        last = page[-1]
        next_cursor = encode_cursor([last.pinned, last.at.isoformat(), str(last.id)])
    return schemas.ConversationListPage(items=items, next_cursor=next_cursor)


def _snippet(content: str, words: list[str]) -> str:
    """Plain text around the first word found, at most `SNIPPET_CHARS` long."""
    lower = content.lower()
    found = [index for word in words if (index := lower.find(word.lower())) >= 0]
    start = max(0, min(found, default=0) - SNIPPET_CHARS // 3)
    piece = " ".join(content[start : start + SNIPPET_CHARS].split())
    return ("…" if start > 0 else "") + piece


@router.get("/search", response_model=schemas.SearchResults)
async def search(
    identity: Authenticated,
    engine: Engine,
    q: Annotated[str, Query(min_length=1, max_length=200)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> schemas.SearchResults:
    """Titles and message text, in any language, ranked, then newest first (CNV-009, ADR-0073)."""
    words = [word for word in q.split() if word]
    if not words:
        raise errors.invalid("q", "empty")
    async with transaction(engine, identity) as connection:
        rows = (
            await connection.execute(
                text(
                    "WITH query AS (SELECT plainto_tsquery('simple', :q) AS q),"
                    " matches AS ("
                    " SELECT m.conversation_id, ts_rank(m.search, query.q) AS rank, m.text AS content"
                    " FROM conversation_messages m, query WHERE m.search @@ query.q"
                    " UNION ALL"
                    " SELECT c.id, ts_rank(to_tsvector('simple', c.title), query.q), c.title"
                    " FROM conversations c, query WHERE to_tsvector('simple', c.title) @@ query.q"
                    "), best AS ("
                    " SELECT DISTINCT ON (conversation_id) conversation_id, rank, content FROM matches"
                    " ORDER BY conversation_id, rank DESC"
                    ") SELECT c.id, c.title, c.last_message_at, best.rank, best.content"
                    " FROM best JOIN conversations c ON c.id = best.conversation_id"
                    " ORDER BY best.rank DESC, c.last_message_at DESC LIMIT :limit"
                ),
                {"q": q, "limit": limit},
            )
        ).all()
    return schemas.SearchResults(
        items=[
            schemas.SearchResult(
                conversation_id=row.id,
                title=row.title,
                snippet=_snippet(row.content, words),
                last_message_at=row.last_message_at,
            )
            for row in rows
        ]
    )
