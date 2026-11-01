"""The instance's health, as the API reports it (OPS-002, ADR-0054)."""

from __future__ import annotations

import pytest

from tests.support.accounts import Account, create_account, create_tenant, login
from tests.support.database import Database
from tests.support.fixtures import HarnessModel
from tests.support.server import Server

CHECKS = ("database", "platform", "sandbox_driver", "isolation_runtime", "egress_table", "model_gateway")


@pytest.fixture
def instance_admin(database: Database) -> Account:
    return create_account(database, create_tenant(database), "tenant_admin", instance_admin=True)


@pytest.mark.spec("OPS-002")
def test_anonymous_callers_see_only_the_status(server: Server, default_model: HarnessModel) -> None:
    with server.client() as client:
        response = client.get("/health")
    assert response.status_code == 200, response.text
    assert response.json() == {"status": "ok"}


@pytest.mark.spec("OPS-002")
def test_members_see_only_the_status(database: Database, server: Server, default_model: HarnessModel) -> None:
    member = create_account(database, create_tenant(database))
    with server.client(login(server, member)) as client:
        assert client.get("/health").json() == {"status": "ok"}


@pytest.mark.spec("OPS-002", "SBX-003", "SBX-015")
def test_instance_admins_see_every_check(server: Server, instance_admin: Account, default_model: HarnessModel) -> None:
    with server.client(login(server, instance_admin)) as client:
        health = client.get("/health").json()
    assert health["status"] == "ok"
    assert {name: health["checks"][name] for name in CHECKS} == dict.fromkeys(CHECKS, "ok")


@pytest.mark.spec("OPS-002", "MOD-008")
def test_an_instance_without_a_default_model_is_degraded(
    server: Server, instance_admin: Account, default_model: HarnessModel
) -> None:
    with server.client(default_model.admin_token) as client:
        client.patch(f"/instance/models/{default_model.id}", json={"is_default": False})
    try:
        with server.client() as client:
            anonymous = client.get("/health")
        with server.client(login(server, instance_admin)) as client:
            detailed = client.get("/health").json()
        assert (anonymous.status_code, anonymous.json()) == (200, {"status": "degraded"})
        assert detailed["checks"]["model_gateway"] == "degraded"
    finally:
        with server.client(default_model.admin_token) as client:
            client.patch(f"/instance/models/{default_model.id}", json={"is_default": True})
