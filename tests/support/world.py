"""Test data: two tenants and their users, each user with one row in every private table.

Rows are arranged as superuser, which bypasses row-level security, with the
columns of specs/contracts/database.md. Every call creates fresh identifiers,
so tests never share data.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import psycopg
from psycopg.types.json import Jsonb

from tests.support.database import PRIVATE_TABLES, Database, uuid7

# A serialized Pydantic AI user message; its content does not matter here.
MESSAGE = {"kind": "request", "parts": [{"part_kind": "user-prompt", "content": "hello"}]}
# An Argon2id encoded hash; no password matches it.
ARGON2_HASH = "$argon2id$v=19$m=65536,t=3,p=4$c2FsdA$aGFzaA"
# Primary key columns of each private table.
KEY_COLUMNS: dict[str, tuple[str, ...]] = {
    "device_sessions": ("id",),
    "conversations": ("id",),
    "runs": ("id",),
    "conversation_messages": ("run_id", "seq"),
    "usage_ledger": ("id",),
}


@dataclass(frozen=True)
class User:
    id: uuid.UUID
    tenant_id: uuid.UUID
    username: str
    role: str
    # Hash of the token of the user's device session.
    token_hash: bytes
    conversation_id: uuid.UUID
    run_id: uuid.UUID
    # Primary key value of the user's row in each private table, as a tuple.
    rows: dict[str, tuple[object, ...]]


@dataclass(frozen=True)
class World:
    tenant_a: uuid.UUID
    tenant_b: uuid.UUID
    alice: User  # member of tenant A
    anna: User  # tenant admin of tenant A
    bob: User  # member of tenant B

    def users(self) -> tuple[User, ...]:
        return (self.alice, self.anna, self.bob)


def create_tenant(conn: psycopg.Connection) -> uuid.UUID:
    tenant_id = uuid7()
    conn.execute(
        "INSERT INTO tenants (id, name, created_at) VALUES (%s, %s, now())",
        (tenant_id, f"tenant-{tenant_id}"),
    )
    return tenant_id


def create_user(conn: psycopg.Connection, tenant_id: uuid.UUID, role: str) -> User:
    user_id, conversation_id, run_id, session_id, ledger_id = (uuid7() for _ in range(5))
    username, token_hash = f"user-{user_id}", user_id.bytes * 2
    conn.execute(
        "INSERT INTO users (id, tenant_id, username, display_name, password_hash, role, instance_admin, created_at)"
        " VALUES (%s, %s, %s, %s, %s, %s, false, now())",
        (user_id, tenant_id, username, "Test user", ARGON2_HASH, role),
    )
    conn.execute(
        "INSERT INTO device_sessions (id, tenant_id, user_id, token_hash, device_name, created_at, last_used_at,"
        " expires_at) VALUES (%s, %s, %s, %s, %s, now(), now(), now() + interval '1 day')",
        (session_id, tenant_id, user_id, token_hash, "test device"),
    )
    conn.execute(
        "INSERT INTO conversations (id, tenant_id, owner_id, title, created_at, updated_at)"
        " VALUES (%s, %s, %s, %s, now(), now())",
        (conversation_id, tenant_id, user_id, "Test conversation"),
    )
    conn.execute(
        "INSERT INTO runs (id, tenant_id, owner_id, conversation_id, parent_run_id, kind, status, created_at)"
        " VALUES (%s, %s, %s, %s, NULL, 'message', 'completed', now())",
        (run_id, tenant_id, user_id, conversation_id),
    )
    conn.execute(
        "INSERT INTO conversation_messages (run_id, seq, tenant_id, owner_id, conversation_id, message, created_at)"
        " VALUES (%s, 1, %s, %s, %s, %s, now())",
        (run_id, tenant_id, user_id, conversation_id, Jsonb(MESSAGE)),
    )
    conn.execute(
        "INSERT INTO usage_ledger (id, tenant_id, owner_id, conversation_id, run_id, purpose, provider, model,"
        " price_source, created_at) VALUES (%s, %s, %s, %s, %s, 'run', 'test', 'test-model', 'free', now())",
        (ledger_id, tenant_id, user_id, conversation_id, run_id),
    )
    rows: dict[str, tuple[object, ...]] = {
        "device_sessions": (session_id,),
        "conversations": (conversation_id,),
        "runs": (run_id,),
        "conversation_messages": (run_id, 1),
        "usage_ledger": (ledger_id,),
    }
    assert set(rows) == set(PRIVATE_TABLES)
    return User(user_id, tenant_id, username, role, token_hash, conversation_id, run_id, rows)


def disable_user(database: Database, user: User) -> None:
    """Mark a user disabled, as a tenant admin would."""
    with database.superuser() as conn:
        # Triggers enforce the application's rules on changes to users, and
        # arranging data is not subject to them.
        conn.execute("SET session_replication_role = replica")
        conn.execute("UPDATE users SET disabled_at = now() WHERE id = %s", (user.id,))


def create_world(database: Database) -> World:
    with database.superuser() as conn:
        tenant_a, tenant_b = create_tenant(conn), create_tenant(conn)
        return World(
            tenant_a=tenant_a,
            tenant_b=tenant_b,
            alice=create_user(conn, tenant_a, "member"),
            anna=create_user(conn, tenant_a, "tenant_admin"),
            bob=create_user(conn, tenant_b, "member"),
        )
