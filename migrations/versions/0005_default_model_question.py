"""Whether the instance has a default model, for /health before any sign-in (OPS-002, ADR-0054).

Revision ID: 0005
Revises: 0004
"""

from __future__ import annotations

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

UPGRADE = [
    "CREATE POLICY instance_models_owner_select ON instance_models FOR SELECT TO mzm_owner USING (true)",
    # Only a yes or a no: nothing about the configuration itself.
    """
    CREATE FUNCTION instance_default_model_configured() RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path = pg_catalog, pg_temp
    AS $$ SELECT EXISTS (SELECT 1 FROM public.instance_models WHERE is_default) $$
    """,
    "REVOKE EXECUTE ON FUNCTION instance_default_model_configured() FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION instance_default_model_configured() TO mzm_app",
]

DOWNGRADE = [
    "DROP FUNCTION instance_default_model_configured()",
    "DROP POLICY instance_models_owner_select ON instance_models",
]


def _execute(statements: list[str]) -> None:
    connection = op.get_bind()
    for statement in statements:
        connection.exec_driver_sql(statement)


def upgrade() -> None:
    _execute(UPGRADE)


def downgrade() -> None:
    _execute(DOWNGRADE)
