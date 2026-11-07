"""File operations on a conversation's workspace (SBX-014, ADR-0079, T-34).

Every check and change of the file tree runs `HELPER`, a fixed script of the
driver's own, inside the conversation's sandbox: whatever it meets there, it
can reach nothing but that sandbox and its workspace. It walks a path one
component at a time with `lstat`, so that no link is ever followed, and
refuses paths that leave `/workspace`. Bytes travel through Docker's archive
API, as tar streams, never held in memory whole.
"""

from __future__ import annotations

import posixpath
import tarfile
from collections.abc import AsyncIterator

TAR_BLOCK = 512


class PathRefusedError(ValueError):
    """A path outside the workspace, or through a link."""


class FileOperationError(Exception):
    """What the helper refused, with the HTTP status the API answers."""

    def __init__(self, status: int, reason: str) -> None:
        super().__init__(reason)
        self.status = status


def relative(path: str) -> str:
    """`path` inside the workspace, normalized; empty for its root. Refuses paths that leave it."""
    if path.startswith("/"):
        raise PathRefusedError("absolute path")
    parts = [part for part in path.split("/") if part not in ("", ".")]
    if ".." in parts:
        raise PathRefusedError("parent folder")
    return "/".join(parts)


def file_header(name: str, size: int) -> bytes:
    """The tar header of one regular file, for streaming its content into the sandbox."""
    info = tarfile.TarInfo(name)
    info.size = size
    info.mode = 0o644
    return info.tobuf(format=tarfile.USTAR_FORMAT)


def padding(size: int) -> bytes:
    """What follows a file's content in a tar stream: the block padding, then the end of the archive."""
    return b"\0" * ((-size) % TAR_BLOCK) + b"\0" * (2 * TAR_BLOCK)


async def tar_member_content(chunks: AsyncIterator[bytes]) -> AsyncIterator[bytes]:
    """The content of the first member of a tar stream, a regular file, streamed."""
    buffer = b""
    async for chunk in chunks:
        buffer += chunk
        if len(buffer) >= TAR_BLOCK:
            break
    header = tarfile.TarInfo.frombuf(buffer[:TAR_BLOCK], tarfile.ENCODING, "surrogateescape")
    if not header.isreg():
        raise FileOperationError(422, "not a regular file")
    remaining = header.size
    rest = buffer[TAR_BLOCK:]
    if rest:
        piece = rest[:remaining]
        remaining -= len(piece)
        yield piece
    async for chunk in chunks:
        if remaining <= 0:
            break
        piece = chunk[:remaining]
        remaining -= len(piece)
        yield piece


def parent(path: str) -> str:
    return posixpath.dirname(path)


# Runs inside the sandbox as `python3 -I -c HELPER OPERATION ARGUMENTS...`; prints one JSON object.
HELPER = r'''
import json, os, stat, sys, datetime
ROOT = "/workspace"

def fail(status, reason):
    print(json.dumps({"error": reason, "status": status})); sys.exit(0)

def walk(rel, *, follow_last=False, missing_ok=False):
    """The absolute path of `rel`, checking that no component on the way is a link."""
    path = ROOT
    parts = [p for p in rel.split("/") if p]
    for index, part in enumerate(parts):
        path = os.path.join(path, part)
        last = index == len(parts) - 1
        try:
            mode = os.lstat(path).st_mode
        except FileNotFoundError:
            if missing_ok and last:
                return path
            fail(404, "not found")
        if stat.S_ISLNK(mode) and not (last and follow_last):
            fail(422, "through a link")
        if not last and not stat.S_ISDIR(mode):
            fail(422, "not a folder")
    return path

def entry(path):
    info = os.lstat(path)
    kind = "link" if stat.S_ISLNK(info.st_mode) else "folder" if stat.S_ISDIR(info.st_mode) else "file"
    return {
        "name": os.path.basename(path),
        "path": os.path.relpath(path, ROOT),
        "type": kind,
        "size": info.st_size if kind == "file" else 0,
        "modified": datetime.datetime.fromtimestamp(info.st_mtime, datetime.timezone.utc).isoformat(),
    }

def make_folders(rel):
    """Create the folders of `rel` that are missing; refuse links and files on the way."""
    current = ROOT
    for part in [p for p in rel.split("/") if p]:
        current = os.path.join(current, part)
        if not os.path.lexists(current):
            os.mkdir(current)
        elif not stat.S_ISDIR(os.lstat(current).st_mode) or os.path.islink(current):
            fail(422, "through a link or a file")
    return current

def size():
    total = 0
    for folder, folders, files in os.walk(ROOT):
        for name in folders + files:
            try:
                total += os.lstat(os.path.join(folder, name)).st_size if name in files else 0
            except FileNotFoundError:
                pass
    return total

operation, args = sys.argv[1], sys.argv[2:]
if operation == "list":
    path = walk(args[0])
    if path != ROOT and not stat.S_ISDIR(os.lstat(path).st_mode):
        fail(422, "not a folder")
    entries = [entry(os.path.join(path, name)) for name in os.listdir(path)]
    entries.sort(key=lambda e: (e["type"] != "folder", e["name"].lower()))
    print(json.dumps({"entries": entries}))
elif operation == "stat":
    # A link is listed and deleted, never read: `regular` asks for a regular file.
    path = walk(args[0], follow_last=True)
    item = entry(path)
    if args[1] == "regular" and item["type"] != "file":
        fail(422, "not a regular file")
    print(json.dumps(item))
elif operation == "prepare":
    # Before a write: the destination must not exist, its folders are created, the quota checked.
    target, length, quota = args[0], int(args[1]), int(args[2])
    if size() + length > quota:
        fail(413, "workspace.quota_exceeded")
    make_folders(os.path.dirname(target))
    path = walk(target, missing_ok=True)
    if os.path.lexists(path):
        fail(409, "exists")
    print(json.dumps({"ok": True}))
elif operation == "commit":
    # The temporary file becomes the destination only if that does not exist: a link fails then.
    temporary, target = os.path.join(ROOT, args[0]), walk(args[1], missing_ok=True)
    try:
        os.link(temporary, target)
    except FileExistsError:
        os.unlink(temporary); fail(409, "exists")
    os.unlink(temporary)
    print(json.dumps(entry(target)))
elif operation == "discard":
    try:
        os.unlink(os.path.join(ROOT, args[0]))
    except FileNotFoundError:
        pass
    print(json.dumps({"ok": True}))
elif operation == "mkdir":
    if os.path.lexists(os.path.join(ROOT, *[p for p in args[0].split("/") if p])):
        fail(409, "exists")
    print(json.dumps(entry(make_folders(args[0]))))
elif operation == "move":
    source = walk(args[0], follow_last=True)
    if source == ROOT:
        fail(422, "the workspace itself")
    if os.path.lexists(os.path.join(ROOT, *[p for p in args[1].split("/") if p])):
        fail(409, "exists")
    make_folders(os.path.dirname(args[1]))
    target = walk(args[1], missing_ok=True)
    os.rename(source, target)
    print(json.dumps(entry(target)))
elif operation == "delete":
    path = walk(args[0], follow_last=True)
    if path == ROOT:
        fail(422, "the workspace itself")
    if stat.S_ISDIR(os.lstat(path).st_mode):
        for folder, folders, files in os.walk(path, topdown=False):
            for name in files + [f for f in folders if os.path.islink(os.path.join(folder, f))]:
                os.unlink(os.path.join(folder, name))
            for name in folders:
                if not os.path.islink(os.path.join(folder, name)):
                    os.rmdir(os.path.join(folder, name))
        os.rmdir(path)
    else:
        os.unlink(path)
    print(json.dumps({"ok": True}))
elif operation == "folder":
    path = walk(args[0])
    if path != ROOT and not stat.S_ISDIR(os.lstat(path).st_mode):
        fail(422, "not a folder")
    print(json.dumps({"ok": True}))
else:
    fail(422, "unknown operation")
'''
