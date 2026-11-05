"""Backups of an instance, and their restore (OPS-006, OPS-010, ADR-0077).

An archive is a tar file encrypted with age to the backup key's recipient:
a manifest, the database as `pg_dump` writes it, the secret key, and every
user's workspace as the sandbox driver exports it (SBX-020). The external
programs, `pg_dump`, `pg_restore` and `age`, run on files of the backup's
own, never on anything a user chose.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import shutil
import subprocess
import tarfile
import tempfile
from collections.abc import Sequence
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import Any, cast

import httpx
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from mazzamurello_server.config import BackupConfiguration
from mazzamurello_server.database import create_engine
from mazzamurello_server.durable import APPLICATION_VERSION

logger = logging.getLogger(__name__)

ARCHIVE_PREFIX = "mazzamurello-"
ARCHIVE_SUFFIX = ".tar.age"
STATUS_FILE = "status.json"
MANIFEST = "manifest.json"
DATABASE = "database.dump"
SECRET_KEY = "secret-key"  # noqa: S105 - the name of an archive entry
# How long a backup waits for runs to end, and how often it looks (ADR-0077).
QUIET_TIMEOUT_SECONDS = 600
QUIET_POLL_SECONDS = 5
DRIVER_TIMEOUT_SECONDS = 600
CHUNK_BYTES = 1024 * 1024
BECH32 = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


class BackupError(Exception):
    """A backup or a restore that cannot go on, with the reason the operator reads."""


# --- the backup key: an age X25519 identity, in Bech32 (age's format) ---


def _polymod(values: Sequence[int]) -> int:
    generator = (0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3)
    checksum = 1
    for value in values:
        top = checksum >> 25
        checksum = (checksum & 0x1FFFFFF) << 5 ^ value
        for index, constant in enumerate(generator):
            checksum ^= constant if (top >> index) & 1 else 0
    return checksum


def _bech32(hrp: str, data: bytes) -> str:
    groups: list[int] = []
    accumulator, bits = 0, 0
    for byte in data:
        accumulator, bits = (accumulator << 8) | byte, bits + 8
        while bits >= 5:
            bits -= 5
            groups.append((accumulator >> bits) & 31)
    if bits:
        groups.append((accumulator << (5 - bits)) & 31)
    expanded = [ord(char) >> 5 for char in hrp] + [0] + [ord(char) & 31 for char in hrp]
    polymod = _polymod([*expanded, *groups, 0, 0, 0, 0, 0, 0]) ^ 1
    checksum = [(polymod >> 5 * (5 - index)) & 31 for index in range(6)]
    return hrp + "1" + "".join(BECH32[value] for value in [*groups, *checksum])


def _unbech32(value: str, hrp: str) -> bytes:
    lowered = value.strip().lower()
    if not lowered.startswith(f"{hrp}1"):
        raise BackupError("MZM_BACKUP_KEY is not an age identity")
    groups = [BECH32.index(char) for char in lowered[len(hrp) + 1 :] if char in BECH32]
    accumulator, bits, data = 0, 0, bytearray()
    for group in groups[:-6]:
        accumulator, bits = (accumulator << 5) | group, bits + 5
        if bits >= 8:
            bits -= 8
            data.append((accumulator >> bits) & 255)
    if _bech32(hrp, bytes(data)) != lowered:
        raise BackupError("MZM_BACKUP_KEY is not a valid age identity")
    return bytes(data)


def new_backup_key() -> str:
    """A new age identity, `AGE-SECRET-KEY-1…`."""
    private = X25519PrivateKey.generate().private_bytes_raw()
    return _bech32("age-secret-key-", private).upper()


def recipient(key: str) -> str:
    """The age recipient, `age1…`, that encrypts archives for the backup key."""
    private = X25519PrivateKey.from_private_bytes(_unbech32(key, "age-secret-key-"))
    return _bech32("age", private.public_key().public_bytes_raw())


# --- the schedule ---


def next_backup(now: datetime, at: str) -> datetime:
    """When the daily backup at `at`, `HH:MM` in UTC, runs next after `now` (OPS-010)."""
    hours, minutes = (int(part) for part in at.split(":"))
    candidate = datetime.combine(now.date(), time(hours, minutes), tzinfo=UTC)
    return candidate if candidate > now else candidate + timedelta(days=1)


def prune_archives(folder: Path, keep: int) -> None:
    """Delete all but the newest `keep` archives of the folder, and nothing else in it."""
    archives = sorted(
        path for path in folder.iterdir() if path.name.startswith(ARCHIVE_PREFIX) and path.name.endswith(ARCHIVE_SUFFIX)
    )
    for path in archives[: max(0, len(archives) - keep)]:
        path.unlink(missing_ok=True)


def _temporary_folder(prefix: str, parent: Path | None) -> Path:
    return Path(tempfile.mkdtemp(prefix=prefix, dir=parent))


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _read_status(folder: Path) -> dict[str, Any]:
    try:
        status: object = json.loads((folder / STATUS_FILE).read_text())
    except (OSError, ValueError):
        return {}
    return cast(dict[str, Any], status) if isinstance(status, dict) else {}


def _write_status(folder: Path, **changes: Any) -> None:
    """Update `status.json` atomically, keeping what the change does not name (OPS-011)."""
    keys = ("started", "last_attempt", "last_success", "outcome", "archive", "error")
    status = dict.fromkeys(keys) | {key: value for key, value in _read_status(folder).items() if key in keys}
    status |= changes
    partial = folder / f".{STATUS_FILE}.partial"
    partial.write_text(json.dumps(status, indent=2) + "\n")
    partial.chmod(0o644)
    partial.replace(folder / STATUS_FILE)


# --- external programs ---


def _tool(argv: Sequence[str], *, environment: dict[str, str] | None = None) -> None:
    """Run `pg_dump`, `pg_restore` or `age` on the backup's own files; fail with what it said."""
    result = subprocess.run(  # noqa: S603 - fixed programs, arguments of the backup's own
        list(argv),
        env={**os.environ, **(environment or {})},
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise BackupError(f"{argv[0]} failed: {result.stderr.strip()[-500:]}")


def _libpq(url: str) -> str:
    """The database URL as libpq reads it."""
    scheme, separator, rest = url.partition("://")
    return f"postgresql://{rest}" if separator and scheme.startswith("postgres") else url


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


# --- backup ---


async def _wait_until_quiet(engine: AsyncEngine) -> None:
    """Wait until no run is queued or running, so that the database and the workspaces match (ADR-0077)."""
    deadline = asyncio.get_running_loop().time() + QUIET_TIMEOUT_SECONDS
    while True:
        async with engine.connect() as connection:
            active = (
                await connection.execute(text("SELECT count(*) FROM runs WHERE status IN ('queued', 'running')"))
            ).scalar_one()
        if active == 0:
            return
        if asyncio.get_running_loop().time() > deadline:
            raise BackupError(f"{active} runs were still active after {QUIET_TIMEOUT_SECONDS} seconds")
        await asyncio.sleep(QUIET_POLL_SECONDS)


async def _users(engine: AsyncEngine) -> list[tuple[str, str]]:
    async with engine.connect() as connection:
        rows = (await connection.execute(text("SELECT tenant_id, id FROM users ORDER BY tenant_id, id"))).all()
    return [(str(row[0]), str(row[1])) for row in rows]


async def _export_workspace(configuration: BackupConfiguration, tenant: str, user: str, destination: Path) -> None:
    headers = {"Authorization": f"Bearer {configuration.sandboxd_token}"}
    url = f"{configuration.sandboxd_url}/sandboxes/{tenant}/{user}/workspace"
    async with (
        httpx.AsyncClient(timeout=DRIVER_TIMEOUT_SECONDS) as client,
        client.stream("GET", url, headers=headers) as response,
    ):
        if response.status_code != 200:
            raise BackupError(f"the sandbox driver did not export a workspace ({response.status_code})")
        with destination.open("wb") as file:
            async for chunk in response.aiter_bytes(CHUNK_BYTES):
                await asyncio.to_thread(file.write, chunk)


async def make_backup(configuration: BackupConfiguration) -> Path:
    """Write one encrypted archive of the instance into the backup folder; its path (OPS-006)."""
    folder = configuration.backup_dir
    target = recipient(configuration.backup_key)
    engine = create_engine(configuration.database_url)
    staging = await asyncio.to_thread(_temporary_folder, ".backup-", folder)
    try:
        await _wait_until_quiet(engine)
        created = datetime.now(UTC)
        contents = staging / "contents"
        (contents / "workspaces").mkdir(parents=True)
        await asyncio.to_thread(
            _tool, ["pg_dump", "--format=custom", f"--file={contents / DATABASE}", _libpq(configuration.database_url)]
        )
        database_taken = _now()
        (contents / SECRET_KEY).write_text(configuration.secret_key)
        for tenant, user in await _users(engine):
            (contents / "workspaces" / tenant).mkdir(exist_ok=True)
            await _export_workspace(configuration, tenant, user, contents / "workspaces" / tenant / f"{user}.tar")
        entries = sorted(path for path in contents.rglob("*") if path.is_file())
        checksums = {path: await asyncio.to_thread(_sha256, path) for path in entries}
        manifest = {
            "version": APPLICATION_VERSION,
            "created": created.isoformat(timespec="seconds"),
            "database_taken": database_taken,
            "workspaces_taken": _now(),
            "entries": {
                path.relative_to(contents).as_posix(): {"size": path.stat().st_size, "sha256": checksum}
                for path, checksum in checksums.items()
            },
        }
        (contents / MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n")
        plain = staging / "archive.tar"

        def pack() -> None:
            with tarfile.open(plain, "w") as archive:
                for path in [contents / MANIFEST, *entries]:
                    archive.add(path, arcname=path.relative_to(contents).as_posix(), recursive=False)

        await asyncio.to_thread(pack)
        name = f"{ARCHIVE_PREFIX}{created.strftime('%Y%m%dT%H%M%SZ')}{ARCHIVE_SUFFIX}"
        encrypted = staging / name
        encrypt = ["age", "--encrypt", "--recipient", target, "--output", str(encrypted), str(plain)]
        await asyncio.to_thread(_tool, encrypt)
        encrypted.chmod(0o600)
        final = folder / name
        encrypted.replace(final)
        return final
    finally:
        await engine.dispose()
        await asyncio.to_thread(shutil.rmtree, staging, True)


async def backup_once(configuration: BackupConfiguration) -> Path:
    """Make an archive, record the outcome in `status.json`, and keep only the newest archives (OPS-010)."""
    attempt = _now()
    try:
        archive = await make_backup(configuration)
    except Exception as error:
        _write_status(configuration.backup_dir, last_attempt=attempt, outcome="failed", error=str(error)[:500])
        raise
    _write_status(
        configuration.backup_dir,
        last_attempt=attempt,
        last_success=_now(),
        outcome="succeeded",
        archive=archive.name,
        error=None,
    )
    prune_archives(configuration.backup_dir, configuration.keep)
    return archive


async def schedule(configuration: BackupConfiguration) -> None:
    """Back up every day at the chosen time, until stopped (OPS-010)."""
    _write_status(configuration.backup_dir, started=_now())
    while True:
        when = next_backup(datetime.now(UTC), configuration.backup_time)
        await asyncio.sleep(max(0.0, (when - datetime.now(UTC)).total_seconds()))
        try:
            archive = await backup_once(configuration)
            logger.info("backup written: %s", archive.name)
        except Exception:
            logger.exception("the backup failed")


# --- restore ---


def _unpack(configuration: BackupConfiguration, archive: Path, folder: Path) -> Path:
    """Decrypt and unpack `archive` into `folder`, checking every entry against the manifest; the contents."""
    identity = folder / "identity"
    identity.write_text(configuration.backup_key.strip() + "\n")
    identity.chmod(0o600)
    plain = folder / "archive.tar"
    _tool(["age", "--decrypt", "--identity", str(identity), "--output", str(plain), str(archive)])
    identity.unlink()
    contents = folder / "contents"
    with tarfile.open(plain, "r") as tar:
        tar.extractall(contents, filter="data")
    plain.unlink()
    try:
        manifest = json.loads((contents / MANIFEST).read_text())
    except (OSError, ValueError) as error:
        raise BackupError("the archive has no manifest") from error
    if manifest.get("version") != APPLICATION_VERSION:
        raise BackupError(
            f"the archive was made by Mazzamurello {manifest.get('version')}, and this is {APPLICATION_VERSION}"
        )
    for name, entry in manifest.get("entries", {}).items():
        path = contents / name
        if not path.is_file() or path.stat().st_size != entry["size"] or _sha256(path) != entry["sha256"]:
            raise BackupError(f"the archive's {name} does not match its manifest")
    return contents


async def _import_workspace(configuration: BackupConfiguration, tenant: str, user: str, source: Path) -> None:
    headers = {"Authorization": f"Bearer {configuration.sandboxd_token}", "Content-Type": "application/x-tar"}
    async with httpx.AsyncClient(timeout=DRIVER_TIMEOUT_SECONDS) as client:
        response = await client.put(
            f"{configuration.sandboxd_url}/sandboxes/{tenant}/{user}/workspace",
            content=await asyncio.to_thread(source.read_bytes),
            headers=headers,
        )
    if response.status_code != 204:
        raise BackupError(f"the sandbox driver refused a workspace ({response.status_code}): {response.text[:300]}")


def _set_secret_key(env_file: Path, secret_key: str) -> None:
    """Write the archive's secret key into the deployment's `.env`, changing nothing else."""
    lines = env_file.read_text().splitlines()
    replaced = [f"MZM_SECRET_KEY={secret_key}" if line.startswith("MZM_SECRET_KEY=") else line for line in lines]
    if replaced == lines and not any(line.startswith("MZM_SECRET_KEY=") for line in lines):
        replaced.append(f"MZM_SECRET_KEY={secret_key}")
    env_file.write_text("\n".join(replaced) + "\n")


async def restore(configuration: BackupConfiguration, archive: Path, env_file: Path | None) -> None:
    """Restore a whole instance into a fresh installation (OPS-006)."""
    folder = await asyncio.to_thread(_temporary_folder, ".restore-", configuration.backup_dir)
    engine = create_engine(configuration.database_url)
    try:
        contents = await asyncio.to_thread(_unpack, configuration, archive, folder)
        async with engine.connect() as connection:
            users = (await connection.execute(text("SELECT count(*) FROM users"))).scalar_one()
        if users:
            raise BackupError("the database has users: restore only into a fresh installation")
        await asyncio.to_thread(
            _tool,
            [
                "pg_restore",
                "--clean",
                "--if-exists",
                "--single-transaction",
                f"--dbname={_libpq(configuration.database_url)}",
                str(contents / DATABASE),
            ],
        )
        for path in sorted((contents / "workspaces").glob("*/*.tar")):
            await _import_workspace(configuration, path.parent.name, path.stem, path)
        if env_file is not None:
            await asyncio.to_thread(_set_secret_key, env_file, (contents / SECRET_KEY).read_text().strip())
    finally:
        await engine.dispose()
        await asyncio.to_thread(shutil.rmtree, folder, True)


async def restore_workspace(configuration: BackupConfiguration, archive: Path, username: str) -> None:
    """Replace one user's workspace with the one in an archive, in a running instance (OPS-006, T-33)."""
    folder = await asyncio.to_thread(_temporary_folder, ".restore-", configuration.backup_dir)
    engine = create_engine(configuration.database_url)
    try:
        contents = await asyncio.to_thread(_unpack, configuration, archive, folder)
        async with engine.connect() as connection:
            row = (
                await connection.execute(
                    text("SELECT tenant_id, id FROM users WHERE lower(username) = lower(:username)"),
                    {"username": username},
                )
            ).one_or_none()
        if row is None:
            raise BackupError(f"there is no user {username}")
        source = contents / "workspaces" / str(row[0]) / f"{row[1]}.tar"
        if not source.is_file():
            raise BackupError(f"the archive has no workspace of {username}")
        await _import_workspace(configuration, str(row[0]), str(row[1]), source)
    finally:
        await engine.dispose()
        with contextlib.suppress(OSError):
            await asyncio.to_thread(shutil.rmtree, folder, True)
