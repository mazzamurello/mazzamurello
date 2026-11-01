"""Creating and listing users and tenants through the public API (AUTH-001, AUTH-002, TEN-001)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from tests.support.accounts import Account, assert_problem, body, create_account, create_tenant, login
from tests.support.database import Database, uuid7
from tests.support.server import Server


def _new_user(role: str = "member") -> dict[str, Any]:
    name = f"new-{uuid7()}"
    return {"username": name, "display_name": "New user", "password": f"pw-{uuid7()}", "role": role}


def _pages(server: Server, token: str, path: str, limit: int) -> list[dict[str, Any]]:
    """Every item of a paginated list, following the cursors."""
    items: list[dict[str, Any]] = []
    cursor: str | None = None
    with server.client(token) as client:
        for _ in range(1000):
            params: dict[str, str | int] = {"limit": limit} | ({"cursor": cursor} if cursor else {})
            response = client.get(path, params=params)
            assert response.status_code == 200, response.text
            page = body(response)
            assert len(page["items"]) <= limit
            items += page["items"]
            cursor = page.get("next_cursor")
            if cursor is None:
                return items
    raise AssertionError("pagination does not end")


@pytest.fixture
def tenant(database: Database) -> uuid.UUID:
    return create_tenant(database)


@pytest.fixture
def admin(database: Database, tenant: uuid.UUID) -> Account:
    return create_account(database, tenant, "tenant_admin")


@pytest.fixture
def instance_admin(database: Database) -> Account:
    return create_account(database, create_tenant(database), "tenant_admin", instance_admin=True)


@pytest.mark.spec("AUTH-001", "AUTH-002")
def test_tenant_admins_create_users_who_can_sign_in(server: Server, admin: Account) -> None:
    request = _new_user()
    with server.client(login(server, admin)) as client:
        response = client.post("/tenant/users", json=request)
    assert response.status_code == 201, response.text
    user = body(response)
    assert {key: user[key] for key in ("tenant_id", "username", "display_name", "role", "instance_admin")} == {
        "tenant_id": str(admin.tenant_id),
        "username": request["username"],
        "display_name": "New user",
        "role": "member",
        "instance_admin": False,
    }
    with server.client() as client:
        signed_in = client.post(
            "/auth/login",
            json={"username": request["username"], "password": request["password"], "device_name": "x"},
        )
    assert signed_in.status_code == 201, signed_in.text


@pytest.mark.spec("AUTH-001")
def test_passwords_are_stored_as_argon2id_hashes(database: Database, server: Server, admin: Account) -> None:
    request = _new_user()
    with server.client(login(server, admin)) as client:
        user = body(client.post("/tenant/users", json=request))
    assert "password" not in user
    assert "password_hash" not in user
    with database.superuser() as conn:
        row = conn.execute("SELECT password_hash FROM users WHERE id = %s", (user["id"],)).fetchone()
    assert row is not None
    assert row[0].startswith("$argon2id$")
    assert request["password"] not in row[0]


@pytest.mark.spec("AUTH-002")
def test_tenant_admins_create_tenant_admins(server: Server, admin: Account) -> None:
    with server.client(login(server, admin)) as client:
        response = client.post("/tenant/users", json=_new_user("tenant_admin"))
    assert response.status_code == 201, response.text
    assert body(response)["role"] == "tenant_admin"


@pytest.mark.spec("AUTH-002")
def test_members_cannot_create_users(database: Database, server: Server, tenant: uuid.UUID) -> None:
    member = create_account(database, tenant)
    with server.client(login(server, member)) as client:
        assert_problem(client.post("/tenant/users", json=_new_user()), 403, "permission.denied")


@pytest.mark.spec("AUTH-002")
def test_usernames_are_unique_across_the_instance(database: Database, server: Server, admin: Account) -> None:
    elsewhere = create_account(database, create_tenant(database))
    with server.client(login(server, admin)) as client:
        response = client.post("/tenant/users", json=_new_user() | {"username": elsewhere.username})
    assert_problem(response, 409, "resource.conflict")


@pytest.mark.spec("AUTH-002")
@pytest.mark.parametrize(
    "change",
    [{"password": "short"}, {"username": "Not Valid"}, {"role": "owner"}, {"instance_admin": True}],
    ids=["short-password", "invalid-username", "unknown-role", "unknown-field"],
)
def test_invalid_users_are_rejected(server: Server, admin: Account, change: dict[str, Any]) -> None:
    with server.client(login(server, admin)) as client:
        response = client.post("/tenant/users", json=_new_user() | change)
    assert_problem(response, 422, "request.validation_failed")


@pytest.mark.spec("TEN-001")
def test_users_are_listed_per_tenant_page_by_page(database: Database, server: Server, admin: Account) -> None:
    members = [create_account(database, admin.tenant_id) for _ in range(4)]
    create_account(database, create_tenant(database))
    listed = _pages(server, login(server, admin), "/tenant/users", limit=2)
    assert sorted(user["id"] for user in listed) == sorted(str(a.id) for a in [admin, *members])
    assert {user["tenant_id"] for user in listed} == {str(admin.tenant_id)}


@pytest.mark.spec("TEN-001", "AUTH-002")
def test_instance_admins_create_tenants_with_their_first_admin(server: Server, instance_admin: Account) -> None:
    first_admin = _new_user("tenant_admin")
    name = f"Family {uuid7()}"
    with server.client(login(server, instance_admin)) as client:
        response = client.post("/instance/tenants", json={"name": name, "admin": first_admin})
    assert response.status_code == 201, response.text
    tenant = body(response)
    assert tenant["name"] == name
    with server.client() as client:
        signed_in = client.post(
            "/auth/login",
            json={"username": first_admin["username"], "password": first_admin["password"], "device_name": "x"},
        )
    assert signed_in.status_code == 201, signed_in.text
    user = body(signed_in)["user"]
    assert (user["tenant_id"], user["role"], user["instance_admin"]) == (tenant["id"], "tenant_admin", False)


@pytest.mark.spec("TEN-001", "AUTH-002")
def test_only_instance_admins_create_tenants(server: Server, admin: Account) -> None:
    with server.client(login(server, admin)) as client:
        response = client.post(
            "/instance/tenants", json={"name": f"Family {uuid7()}", "admin": _new_user("tenant_admin")}
        )
        assert_problem(response, 403, "permission.denied")
        assert_problem(client.get("/instance/tenants"), 403, "permission.denied")


@pytest.mark.spec("TEN-001")
def test_tenant_names_are_unique(database: Database, server: Server, instance_admin: Account) -> None:
    with database.superuser() as conn:
        row = conn.execute("SELECT name FROM tenants WHERE id = %s", (instance_admin.tenant_id,)).fetchone()
    assert row is not None
    with server.client(login(server, instance_admin)) as client:
        response = client.post("/instance/tenants", json={"name": row[0], "admin": _new_user("tenant_admin")})
    assert_problem(response, 409, "resource.conflict")


@pytest.mark.spec("TEN-001")
def test_a_failed_tenant_creation_leaves_nothing_behind(
    database: Database, server: Server, instance_admin: Account
) -> None:
    taken = create_account(database, create_tenant(database))
    name = f"Family {uuid7()}"
    with server.client(login(server, instance_admin)) as client:
        first_admin = _new_user("tenant_admin") | {"username": taken.username}
        response = client.post("/instance/tenants", json={"name": name, "admin": first_admin})
    assert_problem(response, 409, "resource.conflict")
    with database.superuser() as conn:
        assert conn.execute("SELECT 1 FROM tenants WHERE name = %s", (name,)).fetchall() == []


@pytest.mark.spec("TEN-001")
def test_instance_admins_list_every_tenant(database: Database, server: Server, instance_admin: Account) -> None:
    created = {str(create_tenant(database)) for _ in range(3)}
    listed = {tenant["id"] for tenant in _pages(server, login(server, instance_admin), "/instance/tenants", limit=100)}
    assert created | {str(instance_admin.tenant_id)} <= listed


@pytest.mark.spec("TEN-001", "AUTH-002")
def test_the_first_admin_of_a_tenant_must_be_a_tenant_admin(server: Server, instance_admin: Account) -> None:
    with server.client(login(server, instance_admin)) as client:
        response = client.post("/instance/tenants", json={"name": f"Family {uuid7()}", "admin": _new_user("member")})
    assert_problem(response, 422, "request.validation_failed")
