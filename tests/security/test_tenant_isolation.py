"""Attempts to reach another user's or another tenant's rows as `mzm_app`.

These tests act on the database directly, with the request context of the
database contract; tests through the API endpoints come with the server
application's test interface.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, LiteralString

import pytest
from psycopg import sql
from psycopg.types.json import Jsonb

from tests.support.assertions import assert_changes_nothing, assert_denied
from tests.support.database import (
    CONTRACT_TABLES,
    OWNER_COLUMN,
    PRIVATE_TABLES,
    Context,
    Database,
    app_transaction,
    uuid7,
)
from tests.support.world import KEY_COLUMNS, MESSAGE, User, World


@dataclass(frozen=True)
class Attempt:
    """An actor trying to reach a victim's rows."""

    id: str
    actor: Callable[[World], Context]
    victim: Callable[[World], User]


def _as(user: Callable[[World], User], *, instance_admin: bool = False) -> Callable[[World], Context]:
    def context(world: World) -> Context:
        actor = user(world)
        return Context(actor.tenant_id, actor.id, actor.role, instance_admin)

    return context


ATTEMPTS = (
    Attempt("member-reads-same-tenant-user", _as(lambda w: w.alice), lambda w: w.anna),
    Attempt("member-reads-other-tenant", _as(lambda w: w.alice), lambda w: w.bob),
    Attempt("tenant-admin-reads-own-member", _as(lambda w: w.anna), lambda w: w.alice),
    Attempt("tenant-admin-reads-other-tenant", _as(lambda w: w.anna), lambda w: w.bob),
    Attempt("instance-admin-reads-other-tenant", _as(lambda w: w.bob, instance_admin=True), lambda w: w.alice),
)


def _key_filter(table: str) -> sql.Composable:
    return sql.SQL(" AND ").join(sql.SQL("{} = %s").format(sql.Identifier(column)) for column in KEY_COLUMNS[table])


def _actor_user(world: World, context: Context) -> User:
    return next(user for user in world.users() if user.id == context.user_id)


def _new_row(table: str, owner: User) -> tuple[LiteralString, tuple[Any, ...]]:
    """An INSERT of a fresh row in `table` claiming to belong to `owner`."""
    tenant, user = owner.tenant_id, owner.id
    match table:
        case "device_sessions":
            return (
                "INSERT INTO device_sessions (id, tenant_id, user_id, token_hash, device_name, created_at,"
                " last_used_at, expires_at) VALUES (%s, %s, %s, %s, 'intruder', now(), now(), now())",
                (uuid7(), tenant, user, uuid.uuid4().bytes * 2),
            )
        case "conversations":
            return (
                "INSERT INTO conversations (id, tenant_id, owner_id, title, created_at, updated_at)"
                " VALUES (%s, %s, %s, 'intruder', now(), now())",
                (uuid7(), tenant, user),
            )
        case "runs":
            return (
                "INSERT INTO runs (id, tenant_id, owner_id, conversation_id, parent_run_id, kind, status, created_at)"
                " VALUES (%s, %s, %s, %s, %s, 'message', 'completed', now())",
                (uuid7(), tenant, user, owner.conversation_id, owner.run_id),
            )
        case "conversation_messages":
            return (
                "INSERT INTO conversation_messages (run_id, seq, tenant_id, owner_id, conversation_id, message,"
                " created_at) VALUES (%s, 2, %s, %s, %s, %s, now())",
                (owner.run_id, tenant, user, owner.conversation_id, Jsonb(MESSAGE)),
            )
        case "usage_ledger":
            return (
                "INSERT INTO usage_ledger (id, tenant_id, owner_id, purpose, provider, model, price_source,"
                " created_at) VALUES (%s, %s, %s, 'run', 'test', 'test-model', 'free', now())",
                (uuid7(), tenant, user),
            )
        case _:
            raise AssertionError(f"no row builder for {table}")


@pytest.mark.spec("TEN-006")
@pytest.mark.parametrize("table", PRIVATE_TABLES)
@pytest.mark.parametrize("attempt", ATTEMPTS, ids=lambda attempt: attempt.id)
def test_private_rows_of_others_are_invisible(database: Database, world: World, table: str, attempt: Attempt) -> None:
    context, victim = attempt.actor(world), attempt.victim(world)
    actor = _actor_user(world, context)
    owner = OWNER_COLUMN[table]
    with app_transaction(database, context) as conn:
        select_victim = sql.SQL("SELECT 1 FROM {} WHERE {}").format(sql.Identifier(table), _key_filter(table))
        assert conn.execute(select_victim, victim.rows[table]).fetchall() == []
        select_all = sql.SQL("SELECT tenant_id, {} FROM {}").format(sql.Identifier(owner), sql.Identifier(table))
        visible = conn.execute(select_all).fetchall()
    # Not vacuous: the actor sees its own row, and only its own rows.
    assert (actor.tenant_id, actor.id) in visible
    assert set(visible) == {(actor.tenant_id, actor.id)}


@pytest.mark.spec("TEN-006")
@pytest.mark.parametrize("table", PRIVATE_TABLES)
@pytest.mark.parametrize("attempt", ATTEMPTS, ids=lambda attempt: attempt.id)
def test_private_rows_of_others_cannot_be_modified(
    database: Database, world: World, table: str, attempt: Attempt
) -> None:
    context, victim = attempt.actor(world), attempt.victim(world)
    owner, key = sql.Identifier(OWNER_COLUMN[table]), _key_filter(table)
    update = sql.SQL("UPDATE {} SET {} = {} WHERE {}").format(sql.Identifier(table), owner, owner, key)
    delete = sql.SQL("DELETE FROM {} WHERE {}").format(sql.Identifier(table), key)
    with app_transaction(database, context) as conn:
        assert_changes_nothing(conn, update, victim.rows[table])
        assert_changes_nothing(conn, delete, victim.rows[table])


@pytest.mark.spec("TEN-006")
@pytest.mark.parametrize("table", PRIVATE_TABLES)
@pytest.mark.parametrize("attempt", ATTEMPTS, ids=lambda attempt: attempt.id)
def test_private_rows_cannot_be_created_for_others(
    database: Database, world: World, table: str, attempt: Attempt
) -> None:
    context, victim = attempt.actor(world), attempt.victim(world)
    query, params = _new_row(table, victim)
    with app_transaction(database, context) as conn:
        assert_denied(conn, query, params)


@pytest.mark.spec("TEN-006")
@pytest.mark.parametrize("table", PRIVATE_TABLES)
@pytest.mark.parametrize("attempt", ATTEMPTS, ids=lambda attempt: attempt.id)
def test_own_private_rows_cannot_be_given_to_others(
    database: Database, world: World, table: str, attempt: Attempt
) -> None:
    context, victim = attempt.actor(world), attempt.victim(world)
    actor = _actor_user(world, context)
    owner = OWNER_COLUMN[table]
    with app_transaction(database, context) as conn:
        assert_denied(
            conn,
            sql.SQL("UPDATE {} SET tenant_id = %s, {} = %s WHERE {}").format(
                sql.Identifier(table), sql.Identifier(owner), _key_filter(table)
            ),
            (victim.tenant_id, victim.id, *actor.rows[table]),
        )


@pytest.mark.spec("TEN-003", "TEN-006")
# Model configurations are checked with the API tests, which create them.
@pytest.mark.parametrize(
    "table", [table for table in CONTRACT_TABLES if table not in ("login_attempts", "instance_models", "tenant_models")]
)
def test_nothing_is_visible_without_a_request_context(database: Database, world: World, table: str) -> None:
    # `users` is read through a column mzm_app may select; the others whole.
    column = "id" if table in ("tenants", "users") else "tenant_id"
    with app_transaction(database, None) as conn:
        select = sql.SQL("SELECT {} FROM {}").format(sql.Identifier(column), sql.Identifier(table))
        assert conn.execute(select).fetchall() == []
    with database.superuser() as conn:
        assert conn.execute(sql.SQL("SELECT 1 FROM {} LIMIT 1").format(sql.Identifier(table))).fetchall()


@pytest.mark.spec("TEN-006")
def test_tenants_of_others_are_invisible(database: Database, world: World) -> None:
    with app_transaction(database, Context(world.tenant_a, world.alice.id)) as conn:
        assert conn.execute("SELECT id FROM tenants").fetchall() == [(world.tenant_a,)]


@pytest.mark.spec("TEN-006")
def test_users_of_other_tenants_are_invisible(database: Database, world: World) -> None:
    with app_transaction(database, Context(world.tenant_a, world.alice.id)) as conn:
        visible = {user_id for (user_id,) in conn.execute("SELECT id FROM users").fetchall()}
    assert {world.alice.id, world.anna.id} <= visible
    assert world.bob.id not in visible


@pytest.mark.spec("TEN-006")
def test_members_cannot_change_other_users(database: Database, world: World) -> None:
    with app_transaction(database, Context(world.tenant_a, world.alice.id)) as conn:
        for victim in (world.anna, world.bob):
            assert_changes_nothing(conn, "UPDATE users SET display_name = 'changed' WHERE id = %s", (victim.id,))


@pytest.mark.spec("TEN-006")
def test_tenant_admins_cannot_change_users_of_other_tenants(database: Database, world: World) -> None:
    with app_transaction(database, Context(world.tenant_a, world.anna.id, "tenant_admin")) as conn:
        assert_changes_nothing(conn, "UPDATE users SET display_name = 'changed' WHERE id = %s", (world.bob.id,))


@pytest.mark.spec("TEN-006")
def test_users_can_be_created_only_in_ones_own_tenant_by_its_admin(database: Database, world: World) -> None:
    insert = (
        "INSERT INTO users (id, tenant_id, username, display_name, password_hash, role, instance_admin, created_at)"
        " VALUES (%s, %s, %s, 'intruder', 'x', 'member', false, now())"
    )
    with app_transaction(database, Context(world.tenant_a, world.alice.id)) as conn:
        user_id = uuid7()
        assert_denied(conn, insert, (user_id, world.tenant_a, f"user-{user_id}"))
    with app_transaction(database, Context(world.tenant_a, world.anna.id, "tenant_admin")) as conn:
        user_id = uuid7()
        assert_denied(conn, insert, (user_id, world.tenant_b, f"user-{user_id}"))


@pytest.mark.spec("TEN-006")
def test_only_instance_admins_create_tenants(database: Database, world: World) -> None:
    with app_transaction(database, Context(world.tenant_a, world.anna.id, "tenant_admin")) as conn:
        tenant_id = uuid7()
        assert_denied(
            conn, "INSERT INTO tenants (id, name, created_at) VALUES (%s, %s, now())", (tenant_id, f"t-{tenant_id}")
        )


@pytest.mark.spec("TEN-006")
def test_tenants_cannot_be_changed_or_deleted(database: Database, world: World) -> None:
    with app_transaction(database, Context(world.tenant_a, world.anna.id, "tenant_admin")) as conn:
        assert_changes_nothing(conn, "UPDATE tenants SET name = 'changed' WHERE id = %s", (world.tenant_a,))
        assert_changes_nothing(conn, "DELETE FROM tenants WHERE id = %s", (world.tenant_a,))
