"""Login, device sessions and logout through the public API.

AUTH-001, AUTH-004, AUTH-006 and AUTH-009; responses as in
specs/contracts/openapi.yaml, session lifetime as in ADR-0049.
"""

from __future__ import annotations

import datetime
from typing import Any

import pytest

from tests.support.accounts import (
    Account,
    assert_problem,
    body,
    create_account,
    create_tenant,
    disable_account,
    login,
)
from tests.support.database import Database
from tests.support.server import Server, fresh_source

SESSION_LIFETIME = datetime.timedelta(days=90)


@pytest.fixture
def account(database: Database) -> Account:
    return create_account(database, create_tenant(database))


def _timestamp(value: object) -> datetime.datetime:
    assert isinstance(value, str)
    parsed = datetime.datetime.fromisoformat(value)
    assert parsed.tzinfo is not None
    return parsed


def _login_response(server: Server, username: str, password: str, source: str | None = None) -> dict[str, Any]:
    with server.client(source=source) as client:
        response = client.post("/auth/login", json={"username": username, "password": password, "device_name": "Phone"})
    assert response.status_code == 201, response.text
    return body(response)


@pytest.mark.spec("AUTH-001", "AUTH-004")
def test_login_creates_a_device_session(server: Server, account: Account) -> None:
    created = _login_response(server, account.username, account.password)
    token, session, user = created["token"], created["session"], created["user"]
    assert isinstance(token, str)
    assert len(token) >= 43  # 256 bits, encoded
    assert session["device_name"] == "Phone"
    assert session["current"] is True
    assert _timestamp(session["expires_at"]) - _timestamp(session["created_at"]) == SESSION_LIFETIME
    assert user == {
        "id": str(account.id),
        "tenant_id": str(account.tenant_id),
        "username": account.username,
        "display_name": "Test user",
        "role": "member",
        "instance_admin": False,
        "created_at": user["created_at"],
    }


@pytest.mark.spec("AUTH-001")
def test_login_ignores_the_case_of_the_username(server: Server, account: Account) -> None:
    user = _login_response(server, account.username.upper(), account.password)["user"]
    assert user["id"] == str(account.id)


@pytest.mark.spec("AUTH-001")
@pytest.mark.parametrize("wrong", ["password", "username"])
def test_wrong_credentials_are_refused_alike(server: Server, account: Account, wrong: str) -> None:
    username = account.username if wrong == "password" else f"nobody-{account.id}"
    password = "not the password" if wrong == "password" else account.password
    with server.client() as client:
        response = client.post("/auth/login", json={"username": username, "password": password, "device_name": "x"})
    assert_problem(response, 401, "auth.invalid_credentials")


@pytest.mark.spec("AUTH-001", "AUTH-009")
def test_disabled_accounts_cannot_sign_in(database: Database, server: Server, account: Account) -> None:
    disable_account(database, account)
    with server.client() as client:
        response = client.post(
            "/auth/login", json={"username": account.username, "password": account.password, "device_name": "x"}
        )
    assert_problem(response, 401, "auth.invalid_credentials")


@pytest.mark.spec("AUTH-001")
@pytest.mark.parametrize(
    "payload",
    [
        {"username": "someone", "password": "secret"},
        {"username": "", "password": "secret", "device_name": "x"},
        {"username": "someone", "password": "secret", "device_name": "x", "extra": True},
    ],
    ids=["missing-device-name", "empty-username", "unknown-field"],
)
def test_invalid_login_requests_are_rejected(server: Server, payload: dict[str, object]) -> None:
    with server.client() as client:
        response = client.post("/auth/login", json=payload)
    problem = assert_problem(response, 422, "request.validation_failed")
    assert problem["errors"]


@pytest.mark.spec("AUTH-006")
def test_failed_logins_for_one_username_are_rate_limited(server: Server, account: Account) -> None:
    for _ in range(5):
        with server.client() as client:
            response = client.post(
                "/auth/login", json={"username": account.username, "password": "wrong", "device_name": "x"}
            )
        assert_problem(response, 401, "auth.invalid_credentials")
    # Refused even with the right password, from a new address.
    with server.client() as client:
        response = client.post(
            "/auth/login", json={"username": account.username, "password": account.password, "device_name": "x"}
        )
    assert_problem(response, 429, "auth.rate_limited")
    assert 1 <= int(response.headers["Retry-After"]) <= 900


@pytest.mark.spec("AUTH-006")
def test_failed_logins_from_one_source_are_rate_limited(server: Server, account: Account) -> None:
    source = fresh_source()
    with server.client(source=source) as client:
        for attempt in range(20):
            response = client.post(
                "/auth/login",
                json={"username": f"nobody-{attempt}-{account.id}", "password": "wrong", "device_name": "x"},
            )
            assert_problem(response, 401, "auth.invalid_credentials")
        response = client.post(
            "/auth/login", json={"username": account.username, "password": account.password, "device_name": "x"}
        )
    assert_problem(response, 429, "auth.rate_limited")
    # The account itself is not limited from elsewhere.
    _login_response(server, account.username, account.password)


@pytest.mark.spec("AUTH-004")
def test_the_token_authenticates_requests(server: Server, account: Account) -> None:
    with server.client(login(server, account)) as client:
        response = client.get("/me")
    assert response.status_code == 200, response.text
    assert body(response)["id"] == str(account.id)


@pytest.mark.spec("AUTH-004")
@pytest.mark.parametrize(
    "authorization",
    [None, "Bearer not-a-token", "Bearer", "Basic dXNlcjpwYXNzd29yZA=="],
    ids=["missing", "unknown-token", "no-token", "other-scheme"],
)
def test_requests_without_a_valid_token_are_refused(server: Server, authorization: str | None) -> None:
    headers = {} if authorization is None else {"Authorization": authorization}
    with server.client() as client:
        response = client.get("/me", headers=headers)
    assert_problem(response, 401, "auth.unauthenticated")


@pytest.mark.spec("AUTH-004")
def test_logout_revokes_the_current_session(server: Server, account: Account) -> None:
    with server.client(login(server, account)) as client:
        assert client.post("/auth/logout").status_code == 204
        assert_problem(client.get("/me"), 401, "auth.unauthenticated")


@pytest.mark.spec("AUTH-004")
def test_users_list_their_active_sessions(server: Server, account: Account) -> None:
    phone, laptop = login(server, account, "Phone"), login(server, account, "Laptop")
    revoked = login(server, account, "Old tablet")
    with server.client(revoked) as client:
        assert client.post("/auth/logout").status_code == 204
    with server.client(phone) as client:
        response = client.get("/me/sessions")
    assert response.status_code == 200, response.text
    sessions = body(response)["items"]
    assert sorted((s["device_name"], s["current"]) for s in sessions) == [("Laptop", False), ("Phone", True)]
    for session in sessions:
        assert set(session) == {"id", "device_name", "created_at", "last_used_at", "expires_at", "current"}
    assert laptop not in response.text


@pytest.mark.spec("AUTH-004")
def test_users_revoke_another_of_their_sessions(server: Server, account: Account) -> None:
    phone, laptop = login(server, account, "Phone"), login(server, account, "Laptop")
    with server.client(laptop) as client:
        laptop_id = next(s["id"] for s in body(client.get("/me/sessions"))["items"] if s["current"])
    with server.client(phone) as client:
        assert client.delete(f"/me/sessions/{laptop_id}").status_code == 204
        remaining = [s["device_name"] for s in body(client.get("/me/sessions"))["items"]]
    assert remaining == ["Phone"]
    with server.client(laptop) as client:
        assert_problem(client.get("/me"), 401, "auth.unauthenticated")


@pytest.mark.spec("AUTH-004")
def test_revoking_an_unknown_session_is_not_found(server: Server, account: Account) -> None:
    with server.client(login(server, account)) as client:
        response = client.delete(f"/me/sessions/{account.id}")
    assert_problem(response, 404, "resource.not_found")


@pytest.mark.spec("AUTH-004")
def test_expired_sessions_are_refused_and_not_listed(database: Database, server: Server, account: Account) -> None:
    current, expired = login(server, account, "Phone"), login(server, account, "Old phone")
    with database.superuser() as conn:
        conn.execute(
            "UPDATE device_sessions SET expires_at = now() - interval '1 second'"
            " WHERE user_id = %s AND device_name = 'Old phone'",
            (account.id,),
        )
    with server.client(expired) as client:
        assert_problem(client.get("/me"), 401, "auth.unauthenticated")
    with server.client(current) as client:
        assert [s["device_name"] for s in body(client.get("/me/sessions"))["items"]] == ["Phone"]


@pytest.mark.spec("AUTH-004")
def test_each_use_renews_the_session(database: Database, server: Server, account: Account) -> None:
    token = login(server, account)
    with database.superuser() as conn:
        conn.execute(
            "UPDATE device_sessions SET last_used_at = now() - interval '30 days',"
            " expires_at = now() + interval '60 days' WHERE user_id = %s",
            (account.id,),
        )
    with server.client(token) as client:
        assert client.get("/me").status_code == 200
    with database.superuser() as conn:
        row = conn.execute(
            "SELECT now() - last_used_at < interval '1 minute',"
            " abs(extract(epoch FROM expires_at - (now() + interval '90 days'))) < 60"
            " FROM device_sessions WHERE user_id = %s",
            (account.id,),
        ).fetchone()
    assert row == (True, True)


@pytest.mark.spec("AUTH-009")
def test_disabling_an_account_ends_its_sessions(database: Database, server: Server, account: Account) -> None:
    token = login(server, account)
    disable_account(database, account)
    with server.client(token) as client:
        assert_problem(client.get("/me"), 401, "auth.unauthenticated")
