"""Disabling an account ends its sessions (AUTH-009, ADR-0048).

The tenant admin disables the account as `mzm_app`; whether a session is
revoked is read as the server reads it on every request, through
`auth_find_session`.
"""

from __future__ import annotations

import datetime

import psycopg
import pytest

from tests.support.database import Context, Database, app_transaction, uuid7
from tests.support.world import User, World

A_TIME = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)


def _tenant_admin(world: World) -> Context:
    return Context(world.tenant_a, world.anna.id, "tenant_admin")


def _add_session(database: Database, user: User) -> bytes:
    """Open another session for the user; return its token hash."""
    token_hash = uuid7().bytes * 2
    with database.superuser() as conn:
        conn.execute(
            "INSERT INTO device_sessions (id, tenant_id, user_id, token_hash, device_name, created_at, last_used_at,"
            " expires_at) VALUES (%s, %s, %s, %s, 'second device', now(), now(), now() + interval '1 day')",
            (uuid7(), user.tenant_id, user.id, token_hash),
        )
    return token_hash


def _revoked(conn: psycopg.Connection, token_hash: bytes) -> bool:
    rows = conn.execute("SELECT revoked FROM auth_find_session(%s)", (token_hash,)).fetchall()
    assert len(rows) == 1
    return rows[0][0]


def _set_disabled(conn: psycopg.Connection, user: User, *, disabled: bool) -> None:
    query = (
        "UPDATE users SET disabled_at = now() WHERE id = %s"
        if disabled
        else ("UPDATE users SET disabled_at = NULL WHERE id = %s")
    )
    assert conn.execute(query, (user.id,)).rowcount == 1


@pytest.mark.spec("AUTH-009")
def test_disabling_an_account_revokes_every_session(database: Database, world: World) -> None:
    second = _add_session(database, world.alice)
    with app_transaction(database, _tenant_admin(world)) as conn:
        assert not _revoked(conn, world.alice.token_hash)
        _set_disabled(conn, world.alice, disabled=True)
        # In the same transaction as the change.
        assert _revoked(conn, world.alice.token_hash)
        assert _revoked(conn, second)


@pytest.mark.spec("AUTH-009")
def test_disabling_an_account_leaves_other_sessions_alone(database: Database, world: World) -> None:
    with app_transaction(database, _tenant_admin(world)) as conn:
        _set_disabled(conn, world.alice, disabled=True)
        assert not _revoked(conn, world.anna.token_hash)
        assert not _revoked(conn, world.bob.token_hash)


@pytest.mark.spec("AUTH-009")
def test_re_enabling_an_account_restores_no_session(database: Database, world: World) -> None:
    with app_transaction(database, _tenant_admin(world)) as conn:
        _set_disabled(conn, world.alice, disabled=True)
        _set_disabled(conn, world.alice, disabled=False)
        assert _revoked(conn, world.alice.token_hash)


@pytest.mark.spec("AUTH-009")
def test_other_changes_to_an_account_revoke_nothing(database: Database, world: World) -> None:
    with app_transaction(database, _tenant_admin(world)) as conn:
        conn.execute("UPDATE users SET display_name = 'Alice', role = 'tenant_admin' WHERE id = %s", (world.alice.id,))
        assert not _revoked(conn, world.alice.token_hash)


@pytest.mark.spec("AUTH-009")
def test_earlier_revocations_keep_their_time(database: Database, world: World) -> None:
    second = _add_session(database, world.alice)
    with database.superuser() as conn:
        conn.execute("UPDATE device_sessions SET revoked_at = %s WHERE token_hash = %s", (A_TIME, second))
    with database.app() as conn:
        context = _tenant_admin(world)
        conn.execute(
            "SELECT set_config('app.tenant_id', %s, true), set_config('app.user_id', %s, true),"
            " set_config('app.role', %s, true)",
            (str(context.tenant_id), str(context.user_id), context.role),
        )
        _set_disabled(conn, world.alice, disabled=True)
        conn.commit()
    with database.superuser() as conn:
        revoked_at = dict(
            conn.execute(
                "SELECT token_hash, revoked_at FROM device_sessions WHERE user_id = %s", (world.alice.id,)
            ).fetchall()
        )
    assert revoked_at[second] == A_TIME
    assert revoked_at[world.alice.token_hash] is not None
