"""Database under test, set up as the test harness contract prescribes.

See specs/contracts/test-harness.md: PostgreSQL 17 in a container, the
initialization of the database contract run as superuser, migrations run as
`mzm_owner`, assertions made as `mzm_app`.
"""

from __future__ import annotations

import os
import secrets
import subprocess
import sys
import time
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import psycopg
import pytest
from psycopg import sql

ROOT = Path(__file__).resolve().parents[2]
POSTGRES_IMAGE = "postgres:17.6"
DATABASE_NAME = "mazzamurello"
MIGRATION_TIMEOUT_SECONDS = 300

# Tables of the database contract, by kind.
PRIVATE_TABLES = ("device_sessions", "conversations", "conversation_messages", "runs", "usage_ledger")
CONTRACT_TABLES = ("tenants", "users", "login_attempts", *PRIVATE_TABLES)
# Column holding the owning user of each private table.
OWNER_COLUMN = {table: "user_id" if table == "device_sessions" else "owner_id" for table in PRIVATE_TABLES}
# Schemas that are not part of the application schema.
SYSTEM_SCHEMAS = ("pg_catalog", "information_schema", "pg_toast")
DURABLE_EXECUTION_SCHEMA = "dbos"

SECURITY_DEFINER_FUNCTIONS = (
    "auth_find_login",
    "auth_find_session",
    "auth_touch_session",
    "auth_record_login_attempt",
    "bootstrap_instance",
)


@dataclass(frozen=True)
class Database:
    host: str
    port: int
    superuser_url: str
    app_url: str

    def superuser(self) -> psycopg.Connection:
        """Connection for catalog inspection and arranging data, never for assertions on `mzm_app`."""
        return psycopg.connect(self.superuser_url, autocommit=True)

    def app(self) -> psycopg.Connection:
        """Connection as the application role, in a transaction."""
        return psycopg.connect(self.app_url)


def uuid7() -> uuid.UUID:
    """A version 7 UUID, as the database contract prescribes for identifiers."""
    value = (time.time_ns() // 1_000_000) << 80 | secrets.randbits(80)
    value = (value & ~(0xF << 76)) | (0x7 << 76)
    value = (value & ~(0x3 << 62)) | (0x2 << 62)
    return uuid.UUID(int=value)


def _initialize(superuser_url: str, owner_password: str, app_password: str) -> None:
    # The initialization of specs/contracts/database.md, with test passwords.
    with psycopg.connect(superuser_url, autocommit=True) as conn:
        conn.execute(
            sql.SQL("CREATE ROLE mzm_owner LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE").format(
                sql.Literal(owner_password)
            )
        )
        conn.execute(
            sql.SQL(
                "CREATE ROLE mzm_app LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOINHERIT"
            ).format(sql.Literal(app_password))
        )
        conn.execute(f"CREATE DATABASE {DATABASE_NAME} OWNER mzm_owner")
        conn.execute(f"REVOKE ALL ON DATABASE {DATABASE_NAME} FROM PUBLIC")
        conn.execute(f"GRANT CONNECT ON DATABASE {DATABASE_NAME} TO mzm_app")


def _migrate(owner_url: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "migrations/alembic.ini", "upgrade", "head"],
        cwd=ROOT,
        env={**os.environ, "MZM_DATABASE_URL": owner_url},
        capture_output=True,
        text=True,
        timeout=MIGRATION_TIMEOUT_SECONDS,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"migrations failed (exit {result.returncode}):\n{result.stdout}\n{result.stderr}")


_DATABASE = pytest.StashKey[Database | BaseException]()


def start_database(config: pytest.Config) -> Database:
    """Start the database once per test session; later calls return the same one."""
    cached = config.stash.get(_DATABASE, None)
    if isinstance(cached, BaseException):
        raise cached
    if cached is not None:
        return cached

    from testcontainers.community.postgres import PostgresContainer

    container = PostgresContainer(POSTGRES_IMAGE, password=secrets.token_hex(16), driver=None)
    try:
        container.start()
        config.add_cleanup(container.stop)
        host = container.get_container_host_ip()
        port = int(container.get_exposed_port(5432))
        superuser_url = container.get_connection_url()
        owner_password, app_password = secrets.token_hex(16), secrets.token_hex(16)
        _initialize(superuser_url, owner_password, app_password)
        _migrate(f"postgresql://mzm_owner:{owner_password}@{host}:{port}/{DATABASE_NAME}")
        database = Database(
            host=host,
            port=port,
            superuser_url=f"postgresql://{container.username}:{container.password}@{host}:{port}/{DATABASE_NAME}",
            app_url=f"postgresql://mzm_app:{app_password}@{host}:{port}/{DATABASE_NAME}",
        )
    except BaseException as exc:
        config.stash[_DATABASE] = exc
        raise
    config.stash[_DATABASE] = database
    return database


@dataclass(frozen=True)
class Context:
    """The request context of the database contract."""

    tenant_id: uuid.UUID
    user_id: uuid.UUID
    role: str = "member"
    instance_admin: bool = False


@contextmanager
def app_transaction(database: Database, context: Context | None) -> Generator[psycopg.Connection]:
    """A transaction as `mzm_app` with the given request context, rolled back at the end."""
    with database.app() as conn:
        if context is not None:
            conn.execute(
                "SELECT set_config('app.tenant_id', %s, true), set_config('app.user_id', %s, true),"
                " set_config('app.role', %s, true), set_config('app.instance_admin', %s, true)",
                (str(context.tenant_id), str(context.user_id), context.role, str(context.instance_admin).lower()),
            )
        try:
            yield conn
        finally:
            conn.rollback()
