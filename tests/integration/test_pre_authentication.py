"""The pre-authentication functions work before any request context exists.

They run as `mzm_owner` under forced row-level security, through the owner
policies of specs/contracts/database.md (ADR-0046). Each call is made as
`mzm_app` with no request context, as the server makes it at login and on
every request.
"""

from __future__ import annotations

import datetime

import psycopg
import pytest

from tests.support.database import Context, Database, app_transaction, uuid7
from tests.support.world import ARGON2_HASH, World, disable_user


@pytest.mark.spec("AUTH-001")
def test_login_lookup_finds_the_user(database: Database, world: World) -> None:
    alice = world.alice
    with database.app() as conn:
        rows = conn.execute(
            "SELECT user_id, tenant_id, password_hash, role, instance_admin, disabled FROM auth_find_login(%s)",
            (alice.username,),
        ).fetchall()
    assert rows == [(alice.id, alice.tenant_id, ARGON2_HASH, "member", False, False)]


@pytest.mark.spec("AUTH-001")
def test_login_lookup_ignores_the_case_of_the_username(database: Database, world: World) -> None:
    with database.app() as conn:
        for spelling in (world.alice.username.upper(), world.alice.username.capitalize()):
            rows = conn.execute("SELECT user_id FROM auth_find_login(%s)", (spelling,)).fetchall()
            assert rows == [(world.alice.id,)]


@pytest.mark.spec("AUTH-001")
def test_usernames_are_unique_ignoring_case(database: Database, world: World) -> None:
    insert = (
        "INSERT INTO users (id, tenant_id, username, display_name, password_hash, role, instance_admin, created_at)"
        " VALUES (%s, %s, %s, 'New user', %s, 'member', false, now())"
    )
    with app_transaction(database, Context(world.tenant_a, world.anna.id, "tenant_admin")) as conn:
        # Control: a new username is accepted.
        with conn.transaction():
            conn.execute(insert, (uuid7(), world.tenant_a, f"user-{uuid7()}", ARGON2_HASH))
        with pytest.raises(psycopg.errors.UniqueViolation), conn.transaction():
            conn.execute(insert, (uuid7(), world.tenant_a, world.alice.username.upper(), ARGON2_HASH))


@pytest.mark.spec("AUTH-001")
def test_login_lookup_reports_disabled_users(database: Database, world: World) -> None:
    disable_user(database, world.alice)
    with database.app() as conn:
        rows = conn.execute("SELECT disabled FROM auth_find_login(%s)", (world.alice.username,)).fetchall()
    assert rows == [(True,)]


@pytest.mark.spec("AUTH-004")
def test_token_lookup_finds_the_session(database: Database, world: World) -> None:
    anna = world.anna
    with database.app() as conn:
        rows = conn.execute(
            "SELECT session_id, user_id, tenant_id, role, instance_admin, expires_at > now(), revoked"
            " FROM auth_find_session(%s)",
            (anna.token_hash,),
        ).fetchall()
    assert rows == [(anna.rows["device_sessions"][0], anna.id, anna.tenant_id, "tenant_admin", False, True, False)]


@pytest.mark.spec("AUTH-004")
def test_token_lookup_reports_revoked_sessions(database: Database, world: World) -> None:
    with database.superuser() as conn:
        conn.execute("UPDATE device_sessions SET revoked_at = now() WHERE user_id = %s", (world.alice.id,))
    with database.app() as conn:
        rows = conn.execute("SELECT revoked FROM auth_find_session(%s)", (world.alice.token_hash,)).fetchall()
    assert rows == [(True,)]


@pytest.mark.spec("AUTH-004")
def test_touching_a_session_records_its_use(database: Database, world: World) -> None:
    (session_id,) = world.alice.rows["device_sessions"]
    long_ago = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    with database.superuser() as conn:
        conn.execute("UPDATE device_sessions SET last_used_at = %s WHERE id = %s", (long_ago, session_id))
    with database.app() as conn:
        conn.execute("SELECT auth_touch_session(%s)", (session_id,))
        conn.commit()
    with database.superuser() as conn:
        row = conn.execute("SELECT last_used_at FROM device_sessions WHERE id = %s", (session_id,)).fetchone()
    assert row is not None
    assert row[0] > long_ago


@pytest.mark.spec("AUTH-006")
def test_login_attempts_are_recorded(database: Database) -> None:
    username = f"user-{uuid7()}"
    with database.app() as conn:
        rows = conn.execute(
            "SELECT allowed FROM auth_record_login_attempt(%s, %s::inet, %s)", (username, "192.0.2.1", False)
        ).fetchall()
        conn.commit()
    # A first attempt for an unknown username is never rate-limited.
    assert rows == [(True,)]
    with database.superuser() as conn:
        recorded = conn.execute(
            "SELECT host(source), success FROM login_attempts WHERE username = %s", (username,)
        ).fetchall()
    assert recorded == [("192.0.2.1", False)]
