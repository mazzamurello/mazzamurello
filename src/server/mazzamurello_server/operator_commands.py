"""The operator's commands: `init`, `setup`, `backup` and `restore` (AUTH-007, OPS-006, ADR-0054, ADR-0077).

Nothing is shipped with a default: `init` generates every secret of a
deployment, and `setup` creates the first administrator with the password
the operator types.
"""

from __future__ import annotations

import asyncio
import getpass
import os
import re
import secrets
import sys
from collections.abc import Mapping
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from mazzamurello_server import backup
from mazzamurello_server.config import PREFIX, BackupConfiguration, ConfigurationError, load_backup_configuration
from mazzamurello_server.credentials import hash_password
from mazzamurello_server.database import create_engine, sqlstate

SECRETS = ("MZM_POSTGRES_PASSWORD", "MZM_OWNER_PASSWORD", "MZM_APP_PASSWORD", "MZM_SECRET_KEY", "MZM_SANDBOXD_TOKEN")
SECRET_BYTES = 32
USERNAME = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")
MINIMUM_PASSWORD_LENGTH = 12
# Raised by bootstrap_instance when users exist.
ALREADY_SET_UP = "55000"


def _fresh_secrets() -> dict[str, str]:
    values = {name: secrets.token_urlsafe(SECRET_BYTES) for name in SECRETS}
    # The backup key is an age identity; keep a copy away from the server (ADR-0077).
    values["MZM_BACKUP_KEY"] = backup.new_backup_key()
    return values


def init(output: Path) -> int:
    """Write a deployment's `.env` with fresh secrets, or add the secrets an existing one lacks."""
    values = _fresh_secrets()
    if output.exists():
        existing = output.read_text()
        named = {line.split("=", 1)[0] for line in existing.splitlines() if "=" in line and not line.startswith("#")}
        missing = [f"{name}={value}" for name, value in values.items() if name not in named]
        if missing:
            with output.open("a") as file:
                file.write(("" if existing.endswith("\n") or not existing else "\n") + "\n".join(missing) + "\n")
            print(f"mazzamurello: added {', '.join(line.split('=')[0] for line in missing)} to {output}")
        else:
            print(f"mazzamurello: {output} has every secret; it was not changed")
        return 0
    lines = [
        "# Mazzamurello deployment settings, written by `init` (ADR-0054).",
        "# Keep this file private: it holds the instance's secrets.",
        "# Keep a copy of MZM_BACKUP_KEY away from the server: without it, no backup can be restored.",
        *(f"{name}={value}" for name, value in values.items()),
        "",
    ]
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as file:
        file.write("\n".join(lines))
    if os.geteuid() == 0:
        # Run in a container as root: the file belongs to whoever owns the directory.
        directory = output.parent.stat()
        os.chown(output, directory.st_uid, directory.st_gid)
    print(f"mazzamurello: wrote {output}")
    return 0


def _answers() -> tuple[str, str, str, str]:
    """The tenant's name, the username, the display name and the password."""
    if sys.stdin.isatty():
        tenant = input("Name of the household (tenant): ").strip()
        username = input("Username of the first administrator: ").strip()
        display_name = input("Their display name: ").strip()
        password = getpass.getpass("Password: ")
        if getpass.getpass("Password again: ") != password:
            raise ValueError("the passwords differ")
        return tenant, username, display_name, password
    lines = [line.rstrip("\n") for line in sys.stdin.readlines()]
    if len(lines) < 4:
        raise ValueError("expected four lines: tenant name, username, display name, password")
    return lines[0].strip(), lines[1].strip(), lines[2].strip(), lines[3]


async def _bootstrap(database_url: str, answers: tuple[str, str, str, str]) -> None:
    tenant, username, display_name, password = answers
    engine = create_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text("SELECT * FROM bootstrap_instance(:tenant, :username, :display_name, :password_hash)"),
                {
                    "tenant": tenant,
                    "username": username,
                    "display_name": display_name,
                    "password_hash": await hash_password(password),
                },
            )
    finally:
        await engine.dispose()


def setup(environment: Mapping[str, str]) -> int:
    """Create the first tenant and its first administrator, once."""
    unknown = sorted(name for name in environment if name.startswith(PREFIX) and name != "MZM_DATABASE_URL")
    try:
        if unknown:
            raise ConfigurationError(f"unknown configuration variable {unknown[0]}")
        database_url = environment.get("MZM_DATABASE_URL", "")
        if not database_url.startswith(("postgresql://", "postgres://")):
            raise ConfigurationError("MZM_DATABASE_URL must be a postgresql:// URL, for mzm_owner")
        answers = _answers()
    except (ConfigurationError, ValueError, EOFError) as error:
        print(f"mazzamurello: setup: {error}", file=sys.stderr)
        return 2
    tenant, username, display_name, password = answers
    problems = [
        message
        for failed, message in (
            (not tenant, "the tenant's name is empty"),
            (not USERNAME.match(username), "the username must be 2 to 64 lowercase letters, digits, '.', '_' or '-'"),
            (not display_name, "the display name is empty"),
            (len(password) < MINIMUM_PASSWORD_LENGTH, f"the password needs {MINIMUM_PASSWORD_LENGTH} characters"),
        )
        if failed
    ]
    if problems:
        print(f"mazzamurello: setup: {'; '.join(problems)}", file=sys.stderr)
        return 2
    try:
        asyncio.run(_bootstrap(database_url, answers))
    except DBAPIError as error:
        if sqlstate(error) == ALREADY_SET_UP:
            print("mazzamurello: setup: the instance already has users; nothing was changed", file=sys.stderr)
            return 1
        raise
    print(f"mazzamurello: created the tenant {tenant!r} and its administrator {username!r}")
    return 0


def _backup_configuration(environment: Mapping[str, str]) -> BackupConfiguration | None:
    try:
        return load_backup_configuration(environment)
    except ConfigurationError as error:
        print(f"mazzamurello: configuration error: {error}", file=sys.stderr)
        return None


def run_backup(environment: Mapping[str, str], *, scheduled: bool) -> int:
    """Back the instance up once, or every day (OPS-006, OPS-010)."""
    configuration = _backup_configuration(environment)
    if configuration is None:
        return 2
    if scheduled:
        asyncio.run(backup.schedule(configuration))
        return 0
    try:
        archive = asyncio.run(backup.backup_once(configuration))
    except (backup.BackupError, OSError) as error:
        print(f"mazzamurello: the backup failed: {error}", file=sys.stderr)
        return 1
    print(f"mazzamurello: wrote {archive}")
    return 0


def run_restore(environment: Mapping[str, str], archive: Path, env_file: Path | None, username: str | None) -> int:
    """Restore an instance into a fresh installation, or one user's workspace (OPS-006)."""
    configuration = _backup_configuration(environment)
    if configuration is None:
        return 2
    try:
        if username is not None:
            asyncio.run(backup.restore_workspace(configuration, archive, username))
            print(f"mazzamurello: restored the workspace of {username}")
            return 0
        asyncio.run(backup.restore(configuration, archive, env_file))
    except (backup.BackupError, OSError) as error:
        print(f"mazzamurello: the restore failed: {error}", file=sys.stderr)
        return 1
    print("mazzamurello: restored; run `docker compose up --detach --wait` to restart with the restored secret key")
    return 0
