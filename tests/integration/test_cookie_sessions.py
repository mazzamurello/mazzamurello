"""Cookie sessions for the web app (AUTH-005, ADR-0025, ADR-0067).

With `session_delivery: cookie`, sign-in sets the session as an `HttpOnly`,
`Secure`, `SameSite=Lax` cookie instead of returning the token, and every
state-changing request authenticated by that cookie needs the header
`X-Sibillo-Request`.
"""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest

from tests.support.accounts import Account, assert_problem, body, create_account, create_tenant, login
from tests.support.contract import response_hook
from tests.support.database import Database
from tests.support.server import Server, fresh_source

COOKIE = "sibillo_session"
REQUEST_HEADER = "X-Sibillo-Request"


@pytest.fixture
def account(database: Database) -> Account:
    return create_account(database, create_tenant(database))


@pytest.fixture
def browser(server: Server) -> Iterator[httpx.Client]:
    """A client that keeps cookies like a browser, without any Authorization header.

    The test server is plain HTTP on 127.0.0.1, so the `Secure` cookie is sent
    back by hand, as browsers do for loopback addresses.
    """
    with httpx.Client(
        base_url=server.base_url,
        headers={"X-Forwarded-For": fresh_source()},
        timeout=30,
        event_hooks={"response": [response_hook]},
    ) as client:
        yield client


def _sign_in(browser: httpx.Client, account: Account) -> httpx.Response:
    response = browser.post(
        "/auth/login",
        json={
            "username": account.username,
            "password": account.password,
            "device_name": "browser",
            "session_delivery": "cookie",
        },
    )
    assert response.status_code == 201, response.text
    cookie = response.cookies.get(COOKIE)
    assert cookie
    browser.cookies.clear()
    browser.cookies.set(COOKIE, cookie)
    return response


@pytest.mark.spec("AUTH-005")
def test_sign_in_sets_a_protected_cookie_and_returns_no_token(browser: httpx.Client, account: Account) -> None:
    response = _sign_in(browser, account)
    assert "token" not in body(response)
    header = response.headers["set-cookie"]
    attributes = {part.strip().split("=", 1)[0].lower() for part in header.split(";")}
    assert {"httponly", "secure", "samesite", "path"} <= attributes
    assert "samesite=lax" in header.lower()
    assert browser.get("/me").status_code == 200


@pytest.mark.spec("AUTH-005")
def test_changes_need_the_request_header(browser: httpx.Client, account: Account) -> None:
    _sign_in(browser, account)
    assert_problem(browser.post("/conversations", json={}), 401, "auth.unauthenticated")
    created = browser.post("/conversations", json={}, headers={REQUEST_HEADER: "1"})
    assert created.status_code == 201, created.text


@pytest.mark.spec("AUTH-005", "AUTH-004")
def test_bearer_tokens_need_no_request_header(server: Server, account: Account) -> None:
    with server.client(login(server, account)) as client:
        assert client.post("/conversations", json={}).status_code == 201


@pytest.mark.spec("AUTH-005", "AUTH-004")
def test_sign_out_clears_the_cookie_and_ends_the_session(browser: httpx.Client, account: Account) -> None:
    _sign_in(browser, account)
    cookie = browser.cookies.get(COOKIE)
    response = browser.post("/auth/logout", headers={REQUEST_HEADER: "1"})
    assert response.status_code == 204
    cleared = response.headers.get("set-cookie", "").lower()
    assert cleared.startswith(f"{COOKIE}=")
    assert "max-age=0" in cleared or "expires=" in cleared
    # The old cookie, sent again: its session is over.
    browser.cookies.clear()
    browser.cookies.set(COOKIE, cookie or "")
    assert_problem(browser.get("/me"), 401, "auth.unauthenticated")


@pytest.mark.spec("AUTH-005")
def test_a_token_sign_in_sets_no_cookie(server: Server, account: Account) -> None:
    with server.client() as client:
        response = client.post(
            "/auth/login",
            json={"username": account.username, "password": account.password, "device_name": "script"},
        )
    assert response.status_code == 201, response.text
    assert body(response)["token"]
    assert "set-cookie" not in response.headers
