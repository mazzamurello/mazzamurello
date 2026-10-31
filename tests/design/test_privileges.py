"""Privileges and policies on the live schema, exactly as specs/contracts/database.md lists them."""

from __future__ import annotations

from dataclasses import dataclass

import psycopg
import pytest

from tests.support.database import CONTRACT_TABLES, DURABLE_EXECUTION_SCHEMA, SYSTEM_SCHEMAS, Database

EXCLUDED_SCHEMAS = (*SYSTEM_SCHEMAS, DURABLE_EXECUTION_SCHEMA)
COLUMN_PRIVILEGES = ("SELECT", "INSERT", "UPDATE", "REFERENCES")
TABLE_PRIVILEGES = ("DELETE", "TRUNCATE", "TRIGGER", "MAINTAIN")
SEQUENCE_PRIVILEGES = ("USAGE", "SELECT", "UPDATE")


@dataclass(frozen=True)
class Columns:
    """The columns a privilege covers: every column, only some, or every column but some."""

    only: tuple[str, ...] = ()
    excluding: tuple[str, ...] = ()

    def of(self, table_columns: set[str]) -> set[str]:
        return set(self.only) if self.only else table_columns - set(self.excluding)


EVERY = Columns()

# "Privileges of mzm_app" in the database contract. Table privileges such as
# DELETE cover the whole table and are listed with EVERY.
GRANTS: dict[str, dict[str, Columns]] = {
    "tenants": {"SELECT": EVERY, "INSERT": EVERY},
    "users": {
        "SELECT": Columns(excluding=("password_hash",)),
        "INSERT": EVERY,
        "UPDATE": Columns(only=("display_name", "password_hash", "role", "disabled_at")),
    },
    "device_sessions": {"SELECT": EVERY, "INSERT": EVERY, "DELETE": EVERY, "UPDATE": Columns(only=("revoked_at",))},
    "login_attempts": {},
    "conversations": {"SELECT": EVERY, "INSERT": EVERY, "UPDATE": EVERY, "DELETE": EVERY},
    "conversation_messages": {"SELECT": EVERY, "INSERT": EVERY},
    "runs": {"SELECT": EVERY, "INSERT": EVERY, "UPDATE": EVERY},
    "usage_ledger": {"SELECT": EVERY, "INSERT": EVERY},
}
EXECUTABLE_FUNCTIONS = {
    "app_tenant_id()",
    "app_user_id()",
    "app_is_tenant_admin()",
    "app_is_instance_admin()",
    "auth_find_login(text)",
    "auth_find_session(bytea)",
    "auth_touch_session(uuid)",
    "auth_record_login_attempt(text, inet, boolean)",
}

# Owner policies of the pre-authentication functions: table -> operations.
OWNER_POLICIES = {
    "tenants": {"SELECT", "INSERT"},
    "users": {"SELECT", "INSERT"},
    "device_sessions": {"SELECT", "UPDATE"},
    "login_attempts": {"SELECT", "INSERT", "DELETE"},
}


def _columns(conn: psycopg.Connection) -> dict[str, set[str]]:
    rows = conn.execute(
        """
        SELECT c.relname, a.attname FROM pg_class c
        JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
        WHERE c.relnamespace = 'public'::regnamespace AND c.relname = ANY(%s)
        """,
        (list(CONTRACT_TABLES),),
    ).fetchall()
    columns: dict[str, set[str]] = {}
    for table, column in rows:
        columns.setdefault(table, set()).add(column)
    missing = set(CONTRACT_TABLES) - set(columns)
    assert not missing, f"tables of the database contract are missing: {sorted(missing)}"
    return columns


def _expected_privileges(columns: dict[str, set[str]]) -> set[str]:
    expected: set[str] = set()
    for table, grants in GRANTS.items():
        for privilege, covered in grants.items():
            if privilege in TABLE_PRIVILEGES:
                assert covered == EVERY
                expected.add(f"{table}: {privilege}")
            else:
                expected |= {f"{table}.{column}: {privilege}" for column in covered.of(columns[table])}
    return expected | {f"function {signature}: EXECUTE" for signature in EXECUTABLE_FUNCTIONS}


def _effective_privileges(conn: psycopg.Connection) -> set[str]:
    """Every privilege mzm_app holds in the application schema, granted to it or to PUBLIC."""
    granted: set[str] = set()
    excluded = list(EXCLUDED_SCHEMAS)
    for privilege in COLUMN_PRIVILEGES:
        rows = conn.execute(
            """
            SELECT n.nspname, c.relname, a.attname FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
            WHERE c.relkind IN ('r', 'p', 'v', 'm', 'f') AND n.nspname <> ALL(%s)
              AND n.nspname NOT LIKE 'pg\\_temp\\_%%' AND n.nspname NOT LIKE 'pg\\_toast%%'
              AND has_column_privilege('mzm_app', c.oid, a.attnum, %s)
            """,
            (excluded, privilege),
        ).fetchall()
        granted |= {f"{_name(schema, table)}.{column}: {privilege}" for schema, table, column in rows}
    for privilege in TABLE_PRIVILEGES:
        rows = conn.execute(
            """
            SELECT n.nspname, c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relkind IN ('r', 'p', 'v', 'm', 'f') AND n.nspname <> ALL(%s)
              AND n.nspname NOT LIKE 'pg\\_temp\\_%%' AND n.nspname NOT LIKE 'pg\\_toast%%'
              AND has_table_privilege('mzm_app', c.oid, %s)
            """,
            (excluded, privilege),
        ).fetchall()
        granted |= {f"{_name(schema, table)}: {privilege}" for schema, table in rows}
    for privilege in SEQUENCE_PRIVILEGES:
        rows = conn.execute(
            """
            SELECT n.nspname, c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relkind = 'S' AND n.nspname <> ALL(%s)
              AND CASE WHEN c.relkind = 'S' THEN has_sequence_privilege('mzm_app', c.oid, %s) END
            """,
            (excluded, privilege),
        ).fetchall()
        granted |= {f"sequence {_name(schema, sequence)}: {privilege}" for schema, sequence in rows}
    rows = conn.execute(
        """
        SELECT n.nspname, p.proname || '(' || oidvectortypes(p.proargtypes) || ')' FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname <> ALL(%s) AND has_function_privilege('mzm_app', p.oid, 'EXECUTE')
        """,
        (excluded,),
    ).fetchall()
    granted |= {f"function {_name(schema, signature)}: EXECUTE" for schema, signature in rows}
    rows = conn.execute(
        "SELECT nspname FROM pg_namespace WHERE has_schema_privilege('mzm_app', oid, 'CREATE')"
    ).fetchall()
    granted |= {f"schema {schema}: CREATE" for (schema,) in rows}
    return granted


def _name(schema: str, name: str) -> str:
    return name if schema == "public" else f"{schema}.{name}"


@pytest.mark.spec("TEN-004")
def test_application_role_holds_exactly_the_listed_privileges(database: Database) -> None:
    with database.superuser() as conn:
        expected = _expected_privileges(_columns(conn))
        granted = _effective_privileges(conn)
    missing, extra = sorted(expected - granted), sorted(granted - expected)
    assert not extra, f"mzm_app holds privileges the database contract does not list: {extra}"
    assert not missing, f"mzm_app lacks privileges the database contract lists: {missing}"


@pytest.mark.spec("TEN-003", "TEN-004")
def test_policies_are_for_the_application_except_the_owner_policies(database: Database) -> None:
    with database.superuser() as conn:
        _columns(conn)
        rows = conn.execute(
            "SELECT schemaname, tablename, policyname, cmd, roles::text[], qual, with_check FROM pg_policies"
            " WHERE schemaname <> ALL(%s)",
            (list(EXCLUDED_SCHEMAS),),
        ).fetchall()
    owner_policies: dict[str, set[str]] = {}
    for schema, table, policy, command, roles, qual, with_check in rows:
        name = f"{_name(schema, table)}.{policy}"
        assert roles in (["mzm_app"], ["mzm_owner"]), f"{name} applies to {roles}, not to mzm_app or mzm_owner alone"
        if roles == ["mzm_owner"]:
            owner_policies.setdefault(_name(schema, table), set()).add(command)
            assert qual in (None, "true"), f"{name} has a condition"
            assert with_check in (None, "true"), f"{name} has a condition"
    assert owner_policies == OWNER_POLICIES
