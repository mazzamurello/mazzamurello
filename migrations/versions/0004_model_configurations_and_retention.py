"""Model configurations and the retention lookup (MOD-008, ADR-0051, TEN-009, ADR-0052).

Revision ID: 0004
Revises: 0003
"""

from __future__ import annotations

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

MODEL_COLUMNS = """
      name text NOT NULL CHECK (name <> ''),
      base_url text NOT NULL,
      model text NOT NULL CHECK (model <> ''),
      api_key_ciphertext bytea,
      paid boolean NOT NULL,
      input_price numeric(20, 10) CHECK (input_price >= 0),
      cached_input_price numeric(20, 10) CHECK (cached_input_price >= 0),
      output_price numeric(20, 10) CHECK (output_price >= 0),
      currency text CHECK (currency ~ '^[A-Z]{3}$'),
      is_default boolean NOT NULL DEFAULT false,
      created_at timestamptz NOT NULL,
      updated_at timestamptz NOT NULL,
      -- A currency exactly when a price is set.
      CHECK ((currency IS NULL) = (input_price IS NULL AND cached_input_price IS NULL AND output_price IS NULL))
"""

UPGRADE = [
    f"""
    CREATE TABLE instance_models (
      id uuid PRIMARY KEY,
      {MODEL_COLUMNS},
      UNIQUE (name)
    )
    """,
    "CREATE UNIQUE INDEX instance_models_one_default ON instance_models (is_default) WHERE is_default",
    f"""
    CREATE TABLE tenant_models (
      id uuid PRIMARY KEY,
      tenant_id uuid NOT NULL REFERENCES tenants (id),
      {MODEL_COLUMNS},
      UNIQUE (tenant_id, name)
    )
    """,
    "CREATE UNIQUE INDEX tenant_models_one_default ON tenant_models (tenant_id) WHERE is_default",
    *(
        statement
        for table in ("instance_models", "tenant_models")
        for statement in (
            f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
            f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
        )
    ),
    # Any signed-in user may read the instance's configurations.
    """
    CREATE POLICY instance_models_app_select ON instance_models FOR SELECT TO mzm_app
    USING (app_user_id() IS NOT NULL)
    """,
    *(
        f"CREATE POLICY instance_models_app_{operation.lower()} ON instance_models FOR {operation} TO mzm_app {clause}"
        for operation, clause in (
            ("INSERT", "WITH CHECK (app_is_instance_admin())"),
            ("UPDATE", "USING (app_is_instance_admin())"),
            ("DELETE", "USING (app_is_instance_admin())"),
        )
    ),
    "CREATE POLICY tenant_models_app_select ON tenant_models FOR SELECT TO mzm_app USING (tenant_id = app_tenant_id())",
    *(
        f"CREATE POLICY tenant_models_app_{operation.lower()} ON tenant_models FOR {operation} TO mzm_app {clause}"
        for operation, clause in (
            ("INSERT", "WITH CHECK (tenant_id = app_tenant_id() AND app_is_tenant_admin())"),
            ("UPDATE", "USING (tenant_id = app_tenant_id() AND app_is_tenant_admin())"),
            ("DELETE", "USING (tenant_id = app_tenant_id() AND app_is_tenant_admin())"),
        )
    ),
    "GRANT SELECT, INSERT, UPDATE, DELETE ON instance_models, tenant_models TO mzm_app",
    # Retention of durable workflows (ADR-0052): identifiers only, across
    # tenants, through an owner policy on runs.
    "CREATE POLICY runs_owner_select ON runs FOR SELECT TO mzm_owner USING (true)",
    """
    CREATE FUNCTION retention_expired_runs(days integer) RETURNS SETOF uuid
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path = pg_catalog, pg_temp
    AS $$ SELECT r.id FROM public.runs r WHERE r.finished_at < now() - make_interval(days => $1) $$
    """,
    "REVOKE EXECUTE ON FUNCTION retention_expired_runs(integer) FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION retention_expired_runs(integer) TO mzm_app",
]

DOWNGRADE = [
    "DROP FUNCTION retention_expired_runs(integer)",
    "DROP POLICY runs_owner_select ON runs",
    "DROP TABLE tenant_models",
    "DROP TABLE instance_models",
]


def _execute(statements: list[str]) -> None:
    connection = op.get_bind()
    for statement in statements:
        connection.exec_driver_sql(statement)


def upgrade() -> None:
    _execute(UPGRADE)


def downgrade() -> None:
    _execute(DOWNGRADE)
