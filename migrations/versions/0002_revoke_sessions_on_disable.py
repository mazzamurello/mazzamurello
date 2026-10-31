"""Disabling an account revokes its sessions (AUTH-009, ADR-0048).

Revision ID: 0002
Revises: 0001
"""

from __future__ import annotations

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

UPGRADE = [
    # Runs as mzm_owner: row-level security keeps a tenant admin from reaching
    # other users' sessions, so the function works through the owner policies
    # on device_sessions (ADR-0046). It is not executable by mzm_app; triggers
    # call it whatever the caller's privileges.
    """
    CREATE FUNCTION revoke_sessions_of_disabled_user() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path = pg_catalog, pg_temp
    AS $$
    BEGIN
      UPDATE public.device_sessions s SET revoked_at = now()
      WHERE s.tenant_id = NEW.tenant_id AND s.user_id = NEW.id AND s.revoked_at IS NULL;
      RETURN NULL;
    END
    $$
    """,
    "REVOKE EXECUTE ON FUNCTION revoke_sessions_of_disabled_user() FROM PUBLIC",
    """
    CREATE TRIGGER revoke_sessions_of_disabled_user AFTER UPDATE OF disabled_at ON users
    FOR EACH ROW WHEN (OLD.disabled_at IS NULL AND NEW.disabled_at IS NOT NULL)
    EXECUTE FUNCTION revoke_sessions_of_disabled_user()
    """,
]

DOWNGRADE = [
    "DROP TRIGGER revoke_sessions_of_disabled_user ON users",
    "DROP FUNCTION revoke_sessions_of_disabled_user()",
]


def _execute(statements: list[str]) -> None:
    connection = op.get_bind()
    for statement in statements:
        connection.exec_driver_sql(statement)


def upgrade() -> None:
    _execute(UPGRADE)


def downgrade() -> None:
    _execute(DOWNGRADE)
