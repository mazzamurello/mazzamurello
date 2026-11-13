"""Workspaces as tar archives, for backups and restores (SBX-020, ADR-0077).

An archive holds regular files, directories and symbolic links, named
relative to the workspace root. One that names anything else, or anything
outside the workspace, is refused as a whole before a byte of it is written.
"""

from __future__ import annotations

import posixpath
import tarfile
from pathlib import Path

ALLOWED_TYPES = frozenset({tarfile.REGTYPE, tarfile.AREGTYPE, tarfile.DIRTYPE, tarfile.SYMTYPE})


class UnsafeArchiveError(ValueError):
    """An archive entry that would be written outside the workspace, or is not a plain file, folder or link."""


def _relative(name: str) -> str:
    """The entry's path inside the workspace, or an error when it leaves it."""
    if name.startswith("/"):
        raise UnsafeArchiveError(f"absolute path: {name}")
    normalized = posixpath.normpath(name)
    if normalized == ".." or normalized.startswith("../"):
        raise UnsafeArchiveError(f"path outside the workspace: {name}")
    return normalized


def check_archive(path: Path) -> None:
    """Refuse an archive with any entry the workspace must not receive."""
    with tarfile.open(path, "r:") as archive:
        for member in archive:
            name = _relative(member.name)
            if member.type not in ALLOWED_TYPES:
                raise UnsafeArchiveError(f"not a file, a folder or a link: {member.name}")
            if member.type == tarfile.SYMTYPE:
                if member.linkname.startswith("/"):
                    raise UnsafeArchiveError(f"link outside the workspace: {member.name}")
                _relative(posixpath.join(posixpath.dirname(name), member.linkname))


def workspace_entries(source: Path, destination: Path, root: str) -> None:
    """Rewrite Docker's archive of the folder `root` as one named relative to that folder.

    Entries of other types than files, folders and links are left out, so that
    an export can always be imported again.
    """
    prefix = posixpath.basename(root.rstrip("/"))
    with tarfile.open(source, "r:") as archive, tarfile.open(destination, "w:") as result:
        for member in archive:
            if member.type not in ALLOWED_TYPES:
                continue
            name = posixpath.normpath(member.name)
            if name == prefix:
                continue
            if not name.startswith(f"{prefix}/"):
                raise UnsafeArchiveError(f"unexpected entry in the export: {member.name}")
            member.name = name.removeprefix(f"{prefix}/")
            result.addfile(member, archive.extractfile(member) if member.isreg() else None)
