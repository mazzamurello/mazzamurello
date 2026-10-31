"""Design tests on the live schema (specs/contracts/database.md)."""

from __future__ import annotations

from dataclasses import dataclass

import psycopg
import pytest

from tests.support.database import (
    CONTRACT_TABLES,
    DURABLE_EXECUTION_SCHEMA,
    OWNER_COLUMN,
    PRIVATE_TABLES,
    SYSTEM_SCHEMAS,
    Database,
)

EXCLUDED_SCHEMAS = (*SYSTEM_SCHEMAS, DURABLE_EXECUTION_SCHEMA)
# Foreign keys between tenant-scoped tables in the contract: users, device
# sessions, conversations, messages, runs and ledger entries reference each
# other through ten of them.
CONTRACT_TENANT_FOREIGN_KEYS = 10


@dataclass(frozen=True)
class Table:
    schema: str
    name: str
    row_security: bool
    forced_row_security: bool
    reachable_by_app: bool
    # Column name -> NOT NULL.
    columns: dict[str, bool]


def _tables(conn: psycopg.Connection) -> dict[str, Table]:
    rows = conn.execute(
        """
        SELECT n.nspname, c.relname, c.relrowsecurity, c.relforcerowsecurity,
               has_table_privilege('mzm_app', c.oid, 'SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER')
               OR has_any_column_privilege('mzm_app', c.oid, 'SELECT, INSERT, UPDATE, REFERENCES'),
               coalesce(
                 (SELECT jsonb_object_agg(a.attname, a.attnotnull) FROM pg_attribute a
                  WHERE a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped),
                 '{}'::jsonb)
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relkind IN ('r', 'p')
          AND n.nspname <> ALL(%s) AND n.nspname NOT LIKE 'pg\\_temp\\_%%' AND n.nspname NOT LIKE 'pg\\_toast%%'
        """,
        (list(EXCLUDED_SCHEMAS),),
    ).fetchall()
    tables = [
        Table(schema, name, rls, forced, reachable, dict(columns))
        for schema, name, rls, forced, reachable, columns in rows
    ]
    return {table.name if table.schema == "public" else f"{table.schema}.{table.name}": table for table in tables}


@pytest.fixture
def tables(database: Database) -> dict[str, Table]:
    with database.superuser() as conn:
        tables = _tables(conn)
    missing = set(CONTRACT_TABLES) - set(tables)
    assert not missing, f"tables of the database contract are missing: {sorted(missing)}"
    return tables


@pytest.mark.spec("TEN-001")
def test_every_user_belongs_to_exactly_one_tenant(database: Database, tables: dict[str, Table]) -> None:
    assert tables["users"].columns.get("tenant_id") is True
    with database.superuser() as conn:
        references = conn.execute(
            """
            SELECT 1 FROM pg_constraint con
            JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = con.conkey[1]
            WHERE con.contype = 'f' AND con.conrelid = 'public.users'::regclass
              AND con.confrelid = 'public.tenants'::regclass AND cardinality(con.conkey) = 1
              AND a.attname = 'tenant_id'
            """
        ).fetchall()
    assert references, "users.tenant_id must reference tenants"


@pytest.mark.spec("TEN-002")
def test_contract_tables_carry_ownership_columns(tables: dict[str, Table]) -> None:
    for name in ("users", *PRIVATE_TABLES):
        assert tables[name].columns.get("tenant_id") is True, f"{name}.tenant_id must be NOT NULL"
    for name in PRIVATE_TABLES:
        owner = OWNER_COLUMN[name]
        assert tables[name].columns.get(owner) is True, f"{name}.{owner} must be NOT NULL"


@pytest.mark.spec("TEN-002")
def test_every_table_the_application_reaches_carries_its_tenant(tables: dict[str, Table]) -> None:
    # `tenants` is the tenant itself; every other reachable table is tenant-scoped.
    reachable = {name: table for name, table in tables.items() if table.reachable_by_app and name != "tenants"}
    assert set(PRIVATE_TABLES) <= set(reachable)
    offenders = sorted(name for name, table in reachable.items() if table.columns.get("tenant_id") is not True)
    assert not offenders, f"tables reachable by mzm_app without a NOT NULL tenant_id: {offenders}"


@pytest.mark.spec("TEN-002")
def test_foreign_keys_between_tenant_scoped_tables_include_the_tenant(database: Database) -> None:
    with database.superuser() as conn:
        rows = conn.execute(
            """
            SELECT con.conname, src.relname, dst.relname,
                   array_agg(sa.attname ORDER BY k.ord), array_agg(da.attname ORDER BY k.ord)
            FROM pg_constraint con
            JOIN pg_class src ON src.oid = con.conrelid
            JOIN pg_class dst ON dst.oid = con.confrelid
            JOIN pg_namespace n ON n.oid = src.relnamespace
            CROSS JOIN LATERAL unnest(con.conkey, con.confkey) WITH ORDINALITY AS k(src_col, dst_col, ord)
            JOIN pg_attribute sa ON sa.attrelid = con.conrelid AND sa.attnum = k.src_col
            JOIN pg_attribute da ON da.attrelid = con.confrelid AND da.attnum = k.dst_col
            WHERE con.contype = 'f' AND n.nspname = 'public'
              AND EXISTS (SELECT 1 FROM pg_attribute WHERE attrelid = con.conrelid AND attname = 'tenant_id')
              AND EXISTS (SELECT 1 FROM pg_attribute WHERE attrelid = con.confrelid AND attname = 'tenant_id')
            GROUP BY con.conname, src.relname, dst.relname
            """
        ).fetchall()
    assert len(rows) >= CONTRACT_TENANT_FOREIGN_KEYS
    offenders = sorted(
        f"{source}.{name} -> {target}"
        for name, source, target, source_columns, target_columns in rows
        if ("tenant_id", "tenant_id") not in zip(source_columns, target_columns, strict=True)
    )
    assert not offenders, f"foreign keys that do not pair tenant_id with tenant_id: {offenders}"


@pytest.mark.spec("TEN-003")
def test_contract_tables_have_forced_row_level_security(tables: dict[str, Table]) -> None:
    for name in CONTRACT_TABLES:
        assert tables[name].row_security, f"{name}: row-level security is not enabled"
        assert tables[name].forced_row_security, f"{name}: row-level security is not forced"


@pytest.mark.spec("TEN-003")
def test_every_tenant_scoped_table_has_forced_row_level_security(tables: dict[str, Table]) -> None:
    scoped = {name: table for name, table in tables.items() if "tenant_id" in table.columns}
    assert set(PRIVATE_TABLES) <= set(scoped)
    offenders = sorted(name for name, table in scoped.items() if not (table.row_security and table.forced_row_security))
    assert not offenders, f"tenant-scoped tables without enabled and forced row-level security: {offenders}"


@pytest.mark.spec("TEN-003")
def test_every_table_the_application_reaches_has_forced_row_level_security(tables: dict[str, Table]) -> None:
    reachable = {name: table for name, table in tables.items() if table.reachable_by_app}
    assert set(PRIVATE_TABLES) <= set(reachable)
    offenders = sorted(
        name for name, table in reachable.items() if not (table.row_security and table.forced_row_security)
    )
    assert not offenders, f"tables reachable by mzm_app without enabled and forced row-level security: {offenders}"
