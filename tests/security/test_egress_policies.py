"""Who reads and changes data egress policies, below the API (MOD-003, ADR-0091, specs/contracts/database.md).

A user's own choice is theirs: a tenant admin neither reads nor changes it,
and a member changes no policy but their own. Every user of the world has
chosen local models only for themself (tests/support/world.py); other rows
are arranged as superuser, and each check runs as `sibillo_app` with a
request context.
"""

from __future__ import annotations

import uuid

import psycopg
import pytest
from psycopg.abc import QueryNoTemplate

from tests.support.database import Context, Database, app_transaction
from tests.support.world import World


def _arrange(database: Database, tenant_id: uuid.UUID, user_id: uuid.UUID | None, set_by: str) -> None:
    with database.superuser() as conn:
        conn.execute(
            "INSERT INTO egress_policies (tenant_id, user_id, set_by, policy, updated_at)"
            " VALUES (%s, %s, %s, 'local_only', now())",
            (tenant_id, user_id, set_by),
        )


def _visible(conn: psycopg.Connection, user_id: uuid.UUID | None, set_by: str) -> bool:
    row = conn.execute(
        "SELECT count(*) FROM egress_policies WHERE user_id IS NOT DISTINCT FROM %s AND set_by = %s",
        (user_id, set_by),
    ).fetchone()
    return row is not None and row[0] > 0


def _applies(conn: psycopg.Connection, query: QueryNoTemplate, params: tuple[object, ...]) -> bool:
    """Run a statement in a savepoint; return whether it changed at least one row."""
    try:
        with conn.transaction():
            return conn.execute(query, params).rowcount > 0
    except psycopg.DatabaseError:
        return False


def _insert(conn: psycopg.Connection, tenant_id: uuid.UUID, user_id: uuid.UUID | None, set_by: str) -> bool:
    return _applies(
        conn,
        "INSERT INTO egress_policies (tenant_id, user_id, set_by, policy, updated_at)"
        " VALUES (%s, %s, %s, 'local_only', now())",
        (tenant_id, user_id, set_by),
    )


def _delete(conn: psycopg.Connection, user_id: uuid.UUID | None, set_by: str) -> bool:
    return _applies(
        conn,
        "DELETE FROM egress_policies WHERE user_id IS NOT DISTINCT FROM %s AND set_by = %s",
        (user_id, set_by),
    )


def _member(world: World) -> Context:
    return Context(world.tenant_a, world.alice.id)


def _tenant_admin(world: World) -> Context:
    return Context(world.tenant_a, world.anna.id, "tenant_admin")


@pytest.mark.spec("MOD-003", "TEN-003")
def test_a_tenant_admin_neither_reads_nor_changes_a_users_own_choice(database: Database, world: World) -> None:
    with app_transaction(database, _tenant_admin(world)) as conn:
        assert not _visible(conn, world.alice.id, "user")
        assert not _delete(conn, world.alice.id, "user")
        assert not _applies(
            conn, "UPDATE egress_policies SET policy = 'any' WHERE user_id = %s AND set_by = 'user'", (world.alice.id,)
        )
    with app_transaction(database, _member(world)) as conn:
        assert _visible(conn, world.alice.id, "user")
        # Control: the user removes their own.
        assert _delete(conn, world.alice.id, "user")
    # Nor does the admin make one for them.
    with database.superuser() as conn:
        conn.execute("DELETE FROM egress_policies WHERE user_id = %s AND set_by = 'user'", (world.alice.id,))
    with app_transaction(database, _tenant_admin(world)) as conn:
        assert not _insert(conn, world.tenant_a, world.alice.id, "user")


@pytest.mark.spec("MOD-003", "TEN-003")
def test_a_member_changes_only_their_own_choice(database: Database, world: World) -> None:
    _arrange(database, world.tenant_a, None, "admin")
    _arrange(database, world.tenant_a, world.alice.id, "admin")
    with app_transaction(database, _member(world)) as conn:
        # They read what applies to them: the household's and their admin's.
        assert _visible(conn, None, "admin")
        assert _visible(conn, world.alice.id, "admin")
        # They loosen neither, and set nothing for the household or another user.
        assert not _delete(conn, None, "admin")
        assert not _delete(conn, world.alice.id, "admin")
        assert not _insert(conn, world.tenant_a, None, "admin")
        assert not _delete(conn, world.anna.id, "user")
        assert not _insert(conn, world.tenant_a, world.anna.id, "admin")
        # Control: their own choice.
        assert _delete(conn, world.alice.id, "user")
        assert _insert(conn, world.tenant_a, world.alice.id, "user")
    with app_transaction(database, _tenant_admin(world)) as conn:
        # Control: the admin changes what they set.
        assert _delete(conn, world.alice.id, "admin")
        assert _insert(conn, world.tenant_a, world.anna.id, "admin")


@pytest.mark.spec("MOD-003", "TEN-002")
def test_policies_stay_in_their_household(database: Database, world: World) -> None:
    _arrange(database, world.tenant_a, None, "admin")
    with app_transaction(database, Context(world.tenant_b, world.bob.id, "tenant_admin")) as conn:
        assert not _visible(conn, None, "admin")
        assert not _delete(conn, None, "admin")
        assert not _insert(conn, world.tenant_a, world.alice.id, "admin")
