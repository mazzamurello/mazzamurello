"""Device sessions last 90 days from their last use (AUTH-004, ADR-0049).

Revision ID: 0003
Revises: 0002
"""

from __future__ import annotations

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

UPGRADE = [
    # A revoked or expired session is never renewed.
    """
    CREATE OR REPLACE FUNCTION auth_touch_session(session_id uuid) RETURNS void
    LANGUAGE sql SECURITY DEFINER
    SET search_path = pg_catalog, pg_temp
    AS $$
      UPDATE public.device_sessions SET last_used_at = now(), expires_at = now() + interval '90 days'
      WHERE id = $1 AND revoked_at IS NULL AND expires_at > now()
    $$
    """,
]

DOWNGRADE = [
    """
    CREATE OR REPLACE FUNCTION auth_touch_session(session_id uuid) RETURNS void
    LANGUAGE sql SECURITY DEFINER
    SET search_path = pg_catalog, pg_temp
    AS $$ UPDATE public.device_sessions SET last_used_at = now() WHERE id = $1 $$
    """,
]


def _execute(statements: list[str]) -> None:
    connection = op.get_bind()
    for statement in statements:
        connection.exec_driver_sql(statement)


def upgrade() -> None:
    _execute(UPGRADE)


def downgrade() -> None:
    _execute(DOWNGRADE)
