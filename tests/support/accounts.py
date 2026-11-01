"""Accounts with known passwords, and the API calls tests make with them.

Accounts are arranged in the database as superuser, as the test harness
contract allows, with Argon2id password hashes (AUTH-001). Everything else
goes through the API.
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from typing import Any, cast

import httpx
from argon2 import PasswordHasher

from tests.support.database import Database, uuid7
from tests.support.server import Server

_HASHER = PasswordHasher()


@dataclass(frozen=True)
class Account:
    id: uuid.UUID
    tenant_id: uuid.UUID
    username: str
    password: str
    role: str
    instance_admin: bool


def create_tenant(database: Database) -> uuid.UUID:
    tenant_id = uuid7()
    with database.superuser() as conn:
        conn.execute(
            "INSERT INTO tenants (id, name, created_at) VALUES (%s, %s, now())", (tenant_id, f"tenant-{tenant_id}")
        )
    return tenant_id


def create_account(
    database: Database, tenant_id: uuid.UUID, role: str = "member", *, instance_admin: bool = False
) -> Account:
    user_id, password = uuid7(), secrets.token_urlsafe(16)
    username = f"user-{user_id}"
    with database.superuser() as conn:
        conn.execute(
            "INSERT INTO users (id, tenant_id, username, display_name, password_hash, role, instance_admin,"
            " created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, now())",
            (user_id, tenant_id, username, "Test user", _HASHER.hash(password), role, instance_admin),
        )
    return Account(user_id, tenant_id, username, password, role, instance_admin)


def disable_account(database: Database, account: Account) -> None:
    """Disable an account as a tenant admin would, so that its triggers run (AUTH-009)."""
    with database.superuser() as conn, conn.transaction():
        conn.execute("SELECT set_config('app.role', 'tenant_admin', true)")
        conn.execute("UPDATE users SET disabled_at = now() WHERE id = %s", (account.id,))


def body(response: httpx.Response) -> dict[str, Any]:
    """The JSON object of a response."""
    payload = response.json()
    assert isinstance(payload, dict), payload
    return cast(dict[str, Any], payload)


def login(server: Server, account: Account, device_name: str = "test device") -> str:
    """Sign in and return the session token."""
    with server.client() as client:
        response = client.post(
            "/auth/login",
            json={"username": account.username, "password": account.password, "device_name": device_name},
        )
    assert response.status_code == 201, response.text
    token = body(response)["token"]
    assert isinstance(token, str)
    return token


def assert_problem(response: httpx.Response, status: int, code: str) -> dict[str, Any]:
    """The response is an RFC 9457 problem with the given status and stable code (API-007)."""
    assert response.status_code == status, response.text
    assert response.headers["content-type"].startswith("application/problem+json")
    problem = body(response)
    assert problem["status"] == status
    assert problem["code"] == code
    assert isinstance(problem["title"], str)
    assert isinstance(problem["type"], str)
    return problem
