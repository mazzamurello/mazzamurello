"""Assertions about what `mzm_app` may do."""

from __future__ import annotations

from typing import Any

import psycopg
import pytest
from psycopg import errors
from psycopg.abc import QueryNoTemplate


def rows_changed_or_denied(conn: psycopg.Connection, query: QueryNoTemplate, params: tuple[Any, ...]) -> int | None:
    """Run a write in a savepoint; return the rows it changed, or None when it was denied.

    Denied means the role lacks the privilege or a row-level security policy
    rejected the new row; both are reported by PostgreSQL as insufficient
    privilege.
    """
    try:
        with conn.transaction():
            return conn.execute(query, params).rowcount
    except errors.InsufficientPrivilege:
        return None


def assert_changes_nothing(conn: psycopg.Connection, query: QueryNoTemplate, params: tuple[Any, ...]) -> None:
    """The write is denied or matches no row."""
    assert rows_changed_or_denied(conn, query, params) in (None, 0)


def assert_denied(conn: psycopg.Connection, query: QueryNoTemplate, params: tuple[Any, ...]) -> None:
    """The write is rejected by privileges or by a row-level security policy."""
    with pytest.raises(errors.InsufficientPrivilege), conn.transaction():
        conn.execute(query, params)
