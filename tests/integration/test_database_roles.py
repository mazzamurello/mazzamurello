"""The application role is unprivileged (TEN-004, specs/contracts/database.md)."""

from __future__ import annotations

import pytest
from psycopg import errors

from tests.support.database import CONTRACT_TABLES, SECURITY_DEFINER_FUNCTIONS, SYSTEM_SCHEMAS, Database
from tests.support.world import World

# Security-definer functions mzm_app may call: the pre-authentication ones, and
# the retention lookup of the worker (ADR-0052).
PRE_AUTHENTICATION_FUNCTIONS = (
    *(name for name in SECURITY_DEFINER_FUNCTIONS if name.startswith("auth_")),
    "retention_expired_runs",
    "instance_default_model_configured",
)


def _assert_contract_tables_exist(database: Database) -> None:
    with database.superuser() as conn:
        found = {
            name
            for (name,) in conn.execute(
                "SELECT relname FROM pg_class WHERE relnamespace = 'public'::regnamespace AND relkind IN ('r', 'p')"
            ).fetchall()
        }
    missing = set(CONTRACT_TABLES) - found
    assert not missing, f"tables of the database contract are missing: {sorted(missing)}"


@pytest.mark.spec("TEN-004")
def test_application_role_has_no_elevated_attributes(database: Database) -> None:
    _assert_contract_tables_exist(database)
    with database.superuser() as conn:
        row = conn.execute(
            "SELECT rolsuper, rolbypassrls, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname = 'mzm_app'"
        ).fetchone()
        memberships = conn.execute(
            "SELECT roleid::regrole::text FROM pg_auth_members WHERE member = 'mzm_app'::regrole"
        ).fetchall()
    assert row == (False, False, False, False)
    assert memberships == [], "mzm_app must not be a member of any role"


@pytest.mark.spec("TEN-004")
def test_application_role_owns_nothing(database: Database) -> None:
    _assert_contract_tables_exist(database)
    with database.superuser() as conn:
        owned = conn.execute(
            """
            SELECT 'relation ' || oid::regclass::text FROM pg_class WHERE relowner = 'mzm_app'::regrole
            UNION ALL SELECT 'function ' || oid::regprocedure::text FROM pg_proc WHERE proowner = 'mzm_app'::regrole
            UNION ALL SELECT 'schema ' || nspname FROM pg_namespace WHERE nspowner = 'mzm_app'::regrole
            UNION ALL SELECT 'type ' || oid::regtype::text FROM pg_type WHERE typowner = 'mzm_app'::regrole
            """
        ).fetchall()
    assert owned == []


@pytest.mark.spec("TEN-004")
def test_migrations_run_with_the_owner_role(database: Database) -> None:
    _assert_contract_tables_exist(database)
    with database.superuser() as conn:
        owners = dict(
            conn.execute(
                "SELECT relname, relowner::regrole::text FROM pg_class"
                " WHERE relnamespace = 'public'::regnamespace AND relname = ANY(%s)",
                (list(CONTRACT_TABLES),),
            ).fetchall()
        )
    assert owners == dict.fromkeys(CONTRACT_TABLES, "mzm_owner")


@pytest.mark.spec("TEN-004")
def test_application_cannot_switch_to_the_owner_role(database: Database) -> None:
    _assert_contract_tables_exist(database)
    with database.app() as conn, pytest.raises(errors.InsufficientPrivilege):
        conn.execute("SET ROLE mzm_owner")


@pytest.mark.spec("TEN-004")
def test_application_cannot_read_password_hashes(database: Database, world: World) -> None:
    with database.app() as conn:
        conn.execute(
            "SELECT set_config('app.tenant_id', %s, true), set_config('app.user_id', %s, true)",
            (str(world.alice.tenant_id), str(world.alice.id)),
        )
        with pytest.raises(errors.InsufficientPrivilege):
            conn.execute("SELECT password_hash FROM users")


@pytest.mark.spec("TEN-004")
def test_application_cannot_touch_login_attempts_directly(database: Database) -> None:
    _assert_contract_tables_exist(database)
    with database.superuser() as conn:
        row = conn.execute(
            "SELECT has_table_privilege('mzm_app', 'public.login_attempts',"
            " 'SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER'),"
            " has_any_column_privilege('mzm_app', 'public.login_attempts', 'SELECT, INSERT, UPDATE, REFERENCES')"
        ).fetchone()
    assert row == (False, False)


@pytest.mark.spec("TEN-004")
def test_security_definer_functions_are_only_those_of_the_contract(database: Database) -> None:
    with database.superuser() as conn:
        rows = conn.execute(
            """
            SELECT p.proname, p.proowner::regrole::text,
                   EXISTS (SELECT 1 FROM unnest(coalesce(p.proconfig, '{}')) s WHERE s LIKE 'search\\_path=%%'),
                   has_function_privilege('mzm_app', p.oid, 'EXECUTE')
            FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
            WHERE p.prosecdef AND n.nspname <> ALL(%s)
            """,
            (list(SYSTEM_SCHEMAS),),
        ).fetchall()
    functions = {name: (owner, fixed_path, app_may_execute) for name, owner, fixed_path, app_may_execute in rows}
    assert set(functions) == set(SECURITY_DEFINER_FUNCTIONS)
    for name, (owner, fixed_path, app_may_execute) in functions.items():
        assert owner == "mzm_owner", f"{name} is owned by {owner}"
        assert fixed_path, f"{name} has no fixed search_path"
        assert app_may_execute == (name in PRE_AUTHENTICATION_FUNCTIONS), f"{name}: wrong EXECUTE grant for mzm_app"
