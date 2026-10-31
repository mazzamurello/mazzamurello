"""Changes the application must refuse although the row is visible to the actor.

Row-level security decides which rows a user reaches; these tests cover what
a user may do to rows they reach: change their own role or account state, or
attach their rows to another user's data (specs/contracts/database.md,
ADR-0046). A refusal may come from privileges, policies, triggers or
constraints; each test checks the outcome, and a control shows that the same
statement works where the contract allows it.
"""

from __future__ import annotations

import datetime
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, LiteralString

import psycopg
import pytest
from psycopg import sql
from psycopg.abc import QueryNoTemplate
from psycopg.types.json import Jsonb

from tests.support.database import Context, Database, app_transaction, uuid7
from tests.support.world import ARGON2_HASH, MESSAGE, User, World, disable_user

A_TIME = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)


def _applies(conn: psycopg.Connection, query: QueryNoTemplate, params: tuple[Any, ...]) -> bool:
    """Run a statement in a savepoint; return whether it changed at least one row."""
    try:
        with conn.transaction():
            return conn.execute(query, params).rowcount > 0
    except psycopg.DatabaseError:
        return False


def _update_applies(conn: psycopg.Connection, user: User, column: str, value: object) -> bool:
    """Set one column of a user; return whether the user now has that value, as the actor sees it.

    Reading the value back, rather than counting rows, also catches a trigger
    that silently keeps the old value.
    """
    _applies(
        conn,
        sql.SQL("UPDATE users SET {} = %s WHERE id = %s").format(sql.Identifier(column)),
        (value, user.id),
    )
    row = conn.execute(
        sql.SQL("SELECT {} IS NOT DISTINCT FROM %s FROM users WHERE id = %s").format(sql.Identifier(column)),
        (value, user.id),
    ).fetchone()
    return row == (True,)


def _member(world: World) -> Context:
    return Context(world.tenant_a, world.alice.id)


def _tenant_admin(world: World, *, instance_admin: bool = False) -> Context:
    return Context(world.tenant_a, world.anna.id, "tenant_admin", instance_admin)


GUARDED_COLUMNS = (
    ("role", "tenant_admin"),
    ("instance_admin", True),
    ("disabled_at", A_TIME),
)


@pytest.mark.spec("AUTH-002", "TEN-006")
@pytest.mark.parametrize(("column", "value"), GUARDED_COLUMNS, ids=[column for column, _ in GUARDED_COLUMNS])
def test_members_cannot_change_their_own_role_or_account_state(
    database: Database, world: World, column: str, value: object
) -> None:
    with app_transaction(database, _member(world)) as conn:
        assert not _update_applies(conn, world.alice, column, value)


@pytest.mark.spec("AUTH-002", "TEN-006")
def test_disabled_members_cannot_enable_themselves(database: Database, world: World) -> None:
    disable_user(database, world.alice)
    with app_transaction(database, _member(world)) as conn:
        assert not _update_applies(conn, world.alice, "disabled_at", None)


@pytest.mark.spec("AUTH-002", "TEN-006")
def test_members_change_their_own_name_and_password(database: Database, world: World) -> None:
    with app_transaction(database, _member(world)) as conn:
        assert _update_applies(conn, world.alice, "display_name", "Alice")
        # The password hash cannot be read back by the application.
        assert _applies(conn, "UPDATE users SET password_hash = %s WHERE id = %s", (ARGON2_HASH, world.alice.id))


@pytest.mark.spec("AUTH-002", "TEN-006")
@pytest.mark.parametrize(("column", "value"), [("role", "tenant_admin"), ("disabled_at", A_TIME)])
def test_tenant_admins_change_role_and_account_state_of_their_members(
    database: Database, world: World, column: str, value: object
) -> None:
    with app_transaction(database, _tenant_admin(world)) as conn:
        assert _update_applies(conn, world.alice, column, value)


IMMUTABLE_COLUMNS: tuple[tuple[str, Callable[[World], object]], ...] = (
    ("instance_admin", lambda world: True),
    ("username", lambda world: f"renamed-{uuid7()}"),
    ("id", lambda world: uuid7()),
    ("tenant_id", lambda world: world.tenant_b),
    ("created_at", lambda world: A_TIME),
)


@pytest.mark.spec("AUTH-002", "TEN-006")
@pytest.mark.parametrize(("column", "value"), IMMUTABLE_COLUMNS, ids=[column for column, _ in IMMUTABLE_COLUMNS])
def test_identity_columns_never_change_through_the_application(
    database: Database, world: World, column: str, value: Callable[[World], object]
) -> None:
    # Even with the most privileged request context. Column privileges deny
    # these updates, so the update itself reports whether it was applied.
    update = sql.SQL("UPDATE users SET {} = %s WHERE id = %s").format(sql.Identifier(column))
    with app_transaction(database, _tenant_admin(world, instance_admin=True)) as conn:
        assert not _applies(conn, update, (value(world), world.alice.id))


def _new_user(conn: psycopg.Connection, tenant_id: uuid.UUID, *, instance_admin: bool) -> bool:
    """Create a user and return whether the actor sees it afterwards."""
    user_id = uuid7()
    _applies(
        conn,
        "INSERT INTO users (id, tenant_id, username, display_name, password_hash, role, instance_admin, created_at)"
        " VALUES (%s, %s, %s, 'New user', %s, 'member', %s, now())",
        (user_id, tenant_id, f"user-{user_id}", ARGON2_HASH, instance_admin),
    )
    return conn.execute("SELECT 1 FROM users WHERE id = %s", (user_id,)).fetchone() is not None


@pytest.mark.spec("AUTH-002", "TEN-006")
def test_tenant_admins_create_users_but_not_instance_admins(database: Database, world: World) -> None:
    with app_transaction(database, _tenant_admin(world)) as conn:
        assert _new_user(conn, world.tenant_a, instance_admin=False)
        assert not _new_user(conn, world.tenant_a, instance_admin=True)


@pytest.mark.spec("AUTH-002", "TEN-006")
def test_members_create_no_users(database: Database, world: World) -> None:
    with app_transaction(database, _member(world)) as conn:
        assert not _new_user(conn, world.tenant_a, instance_admin=False)
        assert not _new_user(conn, world.tenant_a, instance_admin=True)


@pytest.mark.spec("AUTH-002", "TEN-006")
def test_instance_admins_create_instance_admins(database: Database, world: World) -> None:
    with app_transaction(database, Context(world.tenant_b, world.bob.id, instance_admin=True)) as conn:
        assert _new_user(conn, world.tenant_b, instance_admin=True)


@dataclass(frozen=True)
class Attachment:
    """A write by the actor that references a row of `target`, the actor's own or another user's."""

    id: str
    statement: Callable[[User, User], tuple[LiteralString, tuple[Any, ...]]]


def _run(actor: User, target: User) -> tuple[LiteralString, tuple[Any, ...]]:
    return (
        "INSERT INTO runs (id, tenant_id, owner_id, conversation_id, parent_run_id, kind, status, created_at)"
        " VALUES (%s, %s, %s, %s, NULL, 'message', 'completed', now())",
        (uuid7(), actor.tenant_id, actor.id, target.conversation_id),
    )


def _child_run(actor: User, target: User) -> tuple[LiteralString, tuple[Any, ...]]:
    return (
        "INSERT INTO runs (id, tenant_id, owner_id, conversation_id, parent_run_id, kind, status, created_at)"
        " VALUES (%s, %s, %s, %s, %s, 'message', 'completed', now())",
        (uuid7(), actor.tenant_id, actor.id, actor.conversation_id, target.run_id),
    )


def _message(actor: User, target: User) -> tuple[LiteralString, tuple[Any, ...]]:
    return (
        "INSERT INTO conversation_messages (run_id, seq, tenant_id, owner_id, conversation_id, message, created_at)"
        " VALUES (%s, 2, %s, %s, %s, %s, now())",
        (target.run_id, actor.tenant_id, actor.id, actor.conversation_id, Jsonb(MESSAGE)),
    )


def _ledger_conversation(actor: User, target: User) -> tuple[LiteralString, tuple[Any, ...]]:
    return (
        "INSERT INTO usage_ledger (id, tenant_id, owner_id, conversation_id, purpose, provider, model, price_source,"
        " created_at) VALUES (%s, %s, %s, %s, 'title', 'test', 'test-model', 'free', now())",
        (uuid7(), actor.tenant_id, actor.id, target.conversation_id),
    )


def _ledger_run(actor: User, target: User) -> tuple[LiteralString, tuple[Any, ...]]:
    return (
        "INSERT INTO usage_ledger (id, tenant_id, owner_id, run_id, purpose, provider, model, price_source,"
        " created_at) VALUES (%s, %s, %s, %s, 'run', 'test', 'test-model', 'free', now())",
        (uuid7(), actor.tenant_id, actor.id, target.run_id),
    )


def _active_run(actor: User, target: User) -> tuple[LiteralString, tuple[Any, ...]]:
    return ("UPDATE conversations SET active_run_id = %s WHERE id = %s", (target.run_id, actor.conversation_id))


ATTACHMENTS = (
    Attachment("run-in-conversation", _run),
    Attachment("run-continuing-run", _child_run),
    Attachment("message-of-run", _message),
    Attachment("ledger-entry-of-conversation", _ledger_conversation),
    Attachment("ledger-entry-of-run", _ledger_run),
    Attachment("active-run-of-conversation", _active_run),
)


@pytest.mark.spec("TEN-002", "TEN-006")
@pytest.mark.parametrize("attachment", ATTACHMENTS, ids=lambda attachment: attachment.id)
def test_own_rows_cannot_reference_another_users_rows(database: Database, world: World, attachment: Attachment) -> None:
    alice = world.alice
    with app_transaction(database, _member(world)) as conn:
        # Control: the same write referencing alice's own rows is accepted.
        assert _applies(conn, *attachment.statement(alice, alice))
        # The victim is in the same tenant, so only the owner tells the rows apart.
        assert not _applies(conn, *attachment.statement(alice, world.anna))
