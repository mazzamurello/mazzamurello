"""Connections reach the household's network only when the instance admin set them (MOD-009, MOD-013, T-27, T-31).

A tenant admin who is not the instance admin may only use public `https`
addresses. Their connection tests report any other address as not allowed,
without connecting to it, so the test is no tool to probe the network.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.support.accounts import Account, assert_problem, body, create_account, create_tenant, login
from tests.support.database import Database, uuid7
from tests.support.fixtures import HarnessModel
from tests.support.server import Server

ADDRESSES = [
    "http://1.1.1.1/v1",
    "https://127.0.0.1/v1",
    "https://10.0.0.1/v1",
    "https://192.168.1.10:11434/v1",
    "https://[::1]/v1",
    "https://localhost/v1",
    "https://[::ffff:127.0.0.1]/v1",
    "https://[64:ff9b::a00:1]/v1",
]
ADDRESS_IDS = ["plain-http", "loopback", "private", "home-network", "loopback-v6", "localhost", "mapped", "nat64"]


@pytest.fixture
def tenant_admin(database: Database) -> Account:
    return create_account(database, create_tenant(database), "tenant_admin")


def _openai(base_url: str) -> dict[str, Any]:
    return {"name": f"Server {uuid7()}", "kind": "openai", "base_url": base_url, "location": "local"}


@pytest.mark.spec("MOD-009", "MOD-013")
@pytest.mark.parametrize("base_url", ADDRESSES, ids=ADDRESS_IDS)
def test_other_admins_cannot_reach_private_addresses(server: Server, tenant_admin: Account, base_url: str) -> None:
    with server.client(login(server, tenant_admin)) as client:
        tested = client.post("/tenant/connection-tests", json=_openai(base_url))
        added = client.post("/tenant/connections", json=_openai(base_url))
    assert tested.status_code == 200, tested.text
    assert (body(tested)["passed"], body(tested)["reason"]) == (False, "address_not_allowed")
    problem = assert_problem(added, 422, "connection.test_failed")
    assert problem["test"]["reason"] == "address_not_allowed"


@pytest.mark.spec("MOD-009", "MOD-013")
def test_a_refused_address_is_never_contacted(
    server: Server, tenant_admin: Account, harness_model: HarnessModel
) -> None:
    probe = f"probe-{uuid7()}"
    base_url = harness_model.endpoint.url.removesuffix("/v1") + f"/{probe}/v1"
    with server.client(login(server, tenant_admin)) as client:
        result = body(client.post("/tenant/connection-tests", json=_openai(base_url)))
    assert result["reason"] == "address_not_allowed"
    assert [step["outcome"] for step in result["steps"] if step["step"] in ("connect", "list_models")] in (
        [],
        ["failed", "skipped"],
        ["skipped", "skipped"],
    )
    assert [r for r in harness_model.endpoint.requests if probe in r.path] == []


@pytest.mark.spec("MOD-009")
def test_another_admin_keeps_a_private_connection_but_cannot_move_it(
    database: Database, server: Server, harness_model: HarnessModel
) -> None:
    tenant = create_tenant(database)
    household = harness_model.connect(tenant)
    other_admin = create_account(database, tenant, "tenant_admin")
    path = f"/tenant/connections/{household.connection_id}"
    moved = harness_model.endpoint.url.removesuffix("/v1") + "/elsewhere/v1"
    with server.client(login(server, other_admin)) as client:
        renamed = client.patch(path, json={"name": "Renamed"})
        assert renamed.status_code == 200, renamed.text
        assert body(renamed)["private_network"] is True
        refused = client.patch(path, json={"base_url": moved})
        problem = assert_problem(refused, 422, "connection.test_failed")
        assert problem["test"]["reason"] == "address_not_allowed"
        (kept,) = [c for c in body(client.get("/tenant/connections"))["items"] if c["id"] == household.connection_id]
    assert (kept["base_url"], kept["private_network"]) == (harness_model.endpoint.url, True)
