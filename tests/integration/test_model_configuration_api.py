"""Model configurations through the API (MOD-008, MOD-002, ADR-0051)."""

from __future__ import annotations

from typing import Any

import pytest

from tests.support.accounts import Account, assert_problem, body, create_account, create_tenant, login
from tests.support.database import Database, uuid7
from tests.support.fixtures import HarnessModel
from tests.support.server import Server

PUBLIC_ENDPOINT = "https://1.1.1.1/v1"
KEY_VALUE = "sk-test-secret-value"


def _configuration(**changes: Any) -> dict[str, Any]:
    return {"name": f"Model {uuid7()}", "base_url": PUBLIC_ENDPOINT, "model": "some-model", "paid": False} | changes


@pytest.fixture
def instance_admin(database: Database) -> Account:
    return create_account(database, create_tenant(database), "tenant_admin", instance_admin=True)


@pytest.fixture
def tenant_admin(database: Database) -> Account:
    return create_account(database, create_tenant(database), "tenant_admin")


@pytest.mark.spec("MOD-008", "MOD-002")
@pytest.mark.parametrize("scope", ["instance", "tenant"])
def test_admins_configure_models_with_write_only_keys(
    server: Server, instance_admin: Account, tenant_admin: Account, scope: str
) -> None:
    admin = instance_admin if scope == "instance" else tenant_admin
    prices = {"input": "0.15", "cached_input": "0.075", "output": "0.6", "currency": "USD"}
    with server.client(login(server, admin)) as client:
        created = client.post(f"/{scope}/models", json=_configuration(api_key=KEY_VALUE, paid=True, prices=prices))
        assert created.status_code == 201, created.text
        configuration = body(created)
        listed = body(client.get(f"/{scope}/models"))["items"]
    assert configuration["has_api_key"] is True
    assert configuration["prices"] == prices
    assert configuration["paid"] is True
    assert configuration["is_default"] is False
    assert configuration in listed
    for response in (created.text, str(listed)):
        assert KEY_VALUE not in response
    assert "api_key" not in configuration


@pytest.mark.spec("MOD-008", "MOD-002")
def test_api_keys_are_stored_encrypted(database: Database, server: Server, instance_admin: Account) -> None:
    with server.client(login(server, instance_admin)) as client:
        configuration = body(client.post("/instance/models", json=_configuration(api_key=KEY_VALUE)))
    with database.superuser() as conn:
        row = conn.execute(
            "SELECT api_key_ciphertext FROM instance_models WHERE id = %s", (configuration["id"],)
        ).fetchone()
    assert row is not None
    ciphertext = bytes(row[0])
    assert KEY_VALUE.encode() not in ciphertext
    assert len(ciphertext) > len(KEY_VALUE)


@pytest.mark.spec("MOD-008")
def test_keys_and_prices_can_be_changed_and_removed(server: Server, tenant_admin: Account) -> None:
    with server.client(login(server, tenant_admin)) as client:
        configuration = body(client.post("/tenant/models", json=_configuration(api_key=KEY_VALUE)))
        path = f"/tenant/models/{configuration['id']}"
        changed = body(client.patch(path, json={"api_key": None, "name": "Renamed", "model": "other-model"}))
    assert (changed["has_api_key"], changed["name"], changed["model"]) == (False, "Renamed", "other-model")


@pytest.mark.spec("MOD-008")
@pytest.mark.parametrize("scope", ["instance", "tenant"])
def test_each_scope_has_at_most_one_default(
    server: Server, instance_admin: Account, tenant_admin: Account, harness_model: HarnessModel, scope: str
) -> None:
    admin = instance_admin if scope == "instance" else tenant_admin
    with server.client(login(server, admin)) as client:
        first = body(client.post(f"/{scope}/models", json=_configuration(is_default=True)))
        second = body(client.post(f"/{scope}/models", json=_configuration(is_default=True)))
        defaults = [c["id"] for c in body(client.get(f"/{scope}/models"))["items"] if c["is_default"]]
        if scope == "instance":
            # Leave the harness model as the default for other tests.
            client.delete(f"/instance/models/{first['id']}")
            client.delete(f"/instance/models/{second['id']}")
    assert defaults == [second["id"]]


@pytest.mark.spec("MOD-008")
def test_removing_a_configuration(server: Server, tenant_admin: Account) -> None:
    with server.client(login(server, tenant_admin)) as client:
        configuration = body(client.post("/tenant/models", json=_configuration()))
        assert client.delete(f"/tenant/models/{configuration['id']}").status_code == 204
        assert configuration["id"] not in [c["id"] for c in body(client.get("/tenant/models"))["items"]]
        assert_problem(client.delete(f"/tenant/models/{configuration['id']}"), 404, "resource.not_found")


@pytest.mark.spec("MOD-008")
def test_names_are_unique_per_scope(server: Server, tenant_admin: Account) -> None:
    with server.client(login(server, tenant_admin)) as client:
        configuration = body(client.post("/tenant/models", json=_configuration()))
        duplicate = client.post("/tenant/models", json=_configuration(name=configuration["name"]))
    assert_problem(duplicate, 409, "resource.conflict")


@pytest.mark.spec("MOD-008")
@pytest.mark.parametrize(
    "base_url",
    ["http://1.1.1.1/v1", "https://127.0.0.1/v1", "https://10.0.0.1/v1", "https://[::1]/v1", "https://localhost/v1"],
    ids=["plain-http", "loopback", "private", "loopback-v6", "localhost"],
)
def test_tenant_models_reach_only_public_https_endpoints(server: Server, tenant_admin: Account, base_url: str) -> None:
    with server.client(login(server, tenant_admin)) as client:
        response = client.post("/tenant/models", json=_configuration(base_url=base_url))
        configuration = body(client.post("/tenant/models", json=_configuration()))
        changed = client.patch(f"/tenant/models/{configuration['id']}", json={"base_url": base_url})
    for refused in (response, changed):
        problem = assert_problem(refused, 422, "request.validation_failed")
        assert [error["location"] for error in problem["errors"]] == ["/base_url"]


@pytest.mark.spec("MOD-008")
def test_instance_models_may_reach_local_endpoints(
    server: Server, instance_admin: Account, harness_model: HarnessModel
) -> None:
    with server.client(login(server, instance_admin)) as client:
        response = client.post("/instance/models", json=_configuration(base_url="http://192.168.1.10:11434/v1"))
        assert response.status_code == 201, response.text
        client.delete(f"/instance/models/{body(response)['id']}")


@pytest.mark.spec("MOD-008")
@pytest.mark.parametrize(
    "change",
    [
        {"prices": {"input": "-1", "output": "1", "currency": "USD"}},
        {"prices": {"input": "1", "output": "1", "currency": "dollars"}},
        {"name": ""},
        {"base_url": "not a url"},
        {"provider": "x"},
    ],
    ids=["negative-price", "invalid-currency", "empty-name", "invalid-url", "unknown-field"],
)
def test_invalid_configurations_are_rejected(server: Server, tenant_admin: Account, change: dict[str, Any]) -> None:
    with server.client(login(server, tenant_admin)) as client:
        assert_problem(client.post("/tenant/models", json=_configuration(**change)), 422, "request.validation_failed")


@pytest.mark.spec("MOD-008")
def test_only_admins_configure_models(database: Database, server: Server, tenant_admin: Account) -> None:
    member = create_account(database, tenant_admin.tenant_id)
    with server.client(login(server, member)) as client:
        assert_problem(client.post("/tenant/models", json=_configuration()), 403, "permission.denied")
        assert_problem(client.get("/tenant/models"), 403, "permission.denied")
    with server.client(login(server, tenant_admin)) as client:
        assert_problem(client.post("/instance/models", json=_configuration()), 403, "permission.denied")
        assert_problem(client.get("/instance/models"), 403, "permission.denied")


@pytest.mark.spec("MOD-008", "TEN-006")
def test_tenant_models_of_other_tenants_are_out_of_reach(
    database: Database, server: Server, tenant_admin: Account
) -> None:
    other = create_account(database, create_tenant(database), "tenant_admin")
    with server.client(login(server, other)) as client:
        theirs = body(client.post("/tenant/models", json=_configuration(api_key=KEY_VALUE)))
    with server.client(login(server, tenant_admin)) as client:
        assert theirs["id"] not in [c["id"] for c in body(client.get("/tenant/models"))["items"]]
        path = f"/tenant/models/{theirs['id']}"
        assert_problem(client.patch(path, json={"name": "Mine"}), 404, "resource.not_found")
        assert_problem(client.delete(path), 404, "resource.not_found")
