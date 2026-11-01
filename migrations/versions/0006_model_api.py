"""The API of each model configuration: OpenAI-compatible or OpenRouter (MOD-001, ADR-0057).

Revision ID: 0006
Revises: 0005
"""

from __future__ import annotations

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

TABLES = ("instance_models", "tenant_models")

UPGRADE = [
    f"ALTER TABLE {table} ADD COLUMN api text NOT NULL DEFAULT 'openai' CHECK (api IN ('openai', 'openrouter'))"
    for table in TABLES
]

DOWNGRADE = [f"ALTER TABLE {table} DROP COLUMN api" for table in TABLES]


def _execute(statements: list[str]) -> None:
    connection = op.get_bind()
    for statement in statements:
        connection.exec_driver_sql(statement)


def upgrade() -> None:
    _execute(UPGRADE)


def downgrade() -> None:
    _execute(DOWNGRADE)
