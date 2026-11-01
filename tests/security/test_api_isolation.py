"""Attempts to reach other users' and other tenants' data through the API endpoints.

TEN-006 for the endpoints of the authentication and administration
milestone, and TEN-005: the request context comes only from the token and
never outlives its request, even on pooled database connections.
"""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import pytest

from tests.support.accounts import Account, assert_problem, body, create_account, create_tenant, login
from tests.support.database import Database
from tests.support.server import Server

# Every endpoint of the milestone that needs a session.
AUTHENTICATED_ENDPOINTS = (
    ("POST", "/auth/logout"),
    ("GET", "/me"),
    ("GET", "/me/sessions"),
    ("DELETE", f"/me/sessions/{uuid.UUID(int=1)}"),
    ("GET", "/tenant/users"),
    ("POST", "/tenant/users"),
    ("GET", "/instance/tenants"),
    ("POST", "/instance/tenants"),
)


@dataclass(frozen=True)
class People:
    alice: Account  # member of tenant A
    anna: Account  # tenant admin of tenant A
    bob: Account  # tenant admin of tenant B


@pytest.fixture
def people(database: Database) -> People:
    tenant_a, tenant_b = create_tenant(database), create_tenant(database)
    return People(
        alice=create_account(database, tenant_a),
        anna=create_account(database, tenant_a, "tenant_admin"),
        bob=create_account(database, tenant_b, "tenant_admin"),
    )


def _current_session_id(server: Server, token: str) -> str:
    with server.client(token) as client:
        return next(s["id"] for s in body(client.get("/me/sessions"))["items"] if s["current"])


@pytest.mark.spec("TEN-006")
@pytest.mark.parametrize(("method", "path"), AUTHENTICATED_ENDPOINTS)
def test_endpoints_refuse_requests_without_a_session(server: Server, method: str, path: str) -> None:
    with server.client() as client:
        assert_problem(client.request(method, path, json={}), 401, "auth.unauthenticated")


@pytest.mark.spec("TEN-006")
@pytest.mark.parametrize("victim", ["anna", "bob"], ids=["same-tenant", "other-tenant"])
def test_sessions_of_others_cannot_be_revoked(server: Server, people: People, victim: str) -> None:
    target: Account = getattr(people, victim)
    target_token = login(server, target)
    target_session = _current_session_id(server, target_token)
    # Even by a tenant admin of the same tenant.
    for actor in (people.alice, people.anna) if victim == "bob" else (people.alice,):
        with server.client(login(server, actor)) as client:
            assert_problem(client.delete(f"/me/sessions/{target_session}"), 404, "resource.not_found")
    with server.client(target_token) as client:
        assert client.get("/me").status_code == 200


@pytest.mark.spec("TEN-006")
def test_sessions_of_others_are_not_listed(server: Server, people: People) -> None:
    login(server, people.anna, "Anna's phone")
    login(server, people.bob, "Bob's phone")
    with server.client(login(server, people.alice, "Alice's phone")) as client:
        listed = [s["device_name"] for s in body(client.get("/me/sessions"))["items"]]
    assert listed == ["Alice's phone"]


@pytest.mark.spec("TEN-006")
def test_users_of_other_tenants_are_not_listed(server: Server, people: People) -> None:
    with server.client(login(server, people.alice)) as client:
        response = client.get("/tenant/users", params={"limit": 100})
    listed = {user["id"] for user in body(response)["items"]}
    assert {str(people.alice.id), str(people.anna.id)} <= listed
    assert str(people.bob.id) not in listed


@pytest.mark.spec("TEN-006")
def test_tenant_admins_create_users_only_in_their_tenant(server: Server, people: People) -> None:
    with server.client(login(server, people.anna)) as client:
        response = client.post(
            "/tenant/users",
            json={
                "username": f"new-{people.alice.id}",
                "display_name": "New user",
                "password": "a long enough password",
                "role": "member",
                # Not part of the request: the tenant comes from the session.
                "tenant_id": str(people.bob.tenant_id),
            },
        )
    assert_problem(response, 422, "request.validation_failed")


@pytest.mark.spec("TEN-005")
def test_the_context_comes_from_the_token_and_ends_with_the_request(server: Server, people: People) -> None:
    tokens = {account.id: login(server, account) for account in (people.alice, people.anna, people.bob)}
    accounts = {account.id: account for account in (people.alice, people.anna, people.bob)}

    def check(user_id: uuid.UUID) -> None:
        account = accounts[user_id]
        with server.client(tokens[user_id]) as client:
            me = body(client.get("/me"))
            users = {user["tenant_id"] for user in body(client.get("/tenant/users", params={"limit": 100}))["items"]}
            unauthenticated = client.get("/me", headers={"Authorization": ""})
        assert (me["id"], me["tenant_id"]) == (str(account.id), str(account.tenant_id))
        assert users == {str(account.tenant_id)}
        assert unauthenticated.status_code == 401

    # Interleaved and concurrent requests of different tenants share the
    # server's pooled connections.
    order = [account_id for _ in range(15) for account_id in tokens]
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(check, order))
