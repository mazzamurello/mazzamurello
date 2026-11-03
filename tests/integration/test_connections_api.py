"""Connections of a household through the API (MOD-008, MOD-002, ADR-0069).

Connections in these tests reach the model the tests serve, on the loopback
address, so they are added by a user who is the instance admin as well as a
tenant admin (MOD-009); the address rules are tested in
tests/security/test_connection_addresses.py.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.support.accounts import Account, assert_problem, body, create_account, create_tenant, login
from tests.support.database import Database, uuid7
from tests.support.fixtures import HarnessModel
from tests.support.model import SERVER_MODELS
from tests.support.server import Server

KEY_VALUE = "sk-test-secret-value"


@pytest.fixture
def admin(database: Database) -> Account:
    """A tenant admin of a new household who is also the instance admin."""
    return create_account(database, create_tenant(database), "tenant_admin", instance_admin=True)


def _server(model: HarnessModel, **changes: Any) -> dict[str, Any]:
    connection = {"name": f"Server {uuid7()}", "kind": "openai", "base_url": model.endpoint.url, "location": "local"}
    return connection | changes


@pytest.mark.spec("MOD-008", "MOD-002", "MOD-010")
def test_admins_add_connections_with_write_only_keys(
    server: Server, admin: Account, harness_model: HarnessModel
) -> None:
    with server.client(login(server, admin)) as client:
        created = client.post("/tenant/connections", json=_server(harness_model, api_key=KEY_VALUE))
        assert created.status_code == 201, created.text
        connection = body(created)
        listed = body(client.get("/tenant/connections"))["items"]
    assert connection["kind"] == "openai"
    assert connection["location"] == "local"
    assert connection["has_api_key"] is True
    assert connection["private_network"] is True
    assert connection["model_count"] == len(SERVER_MODELS)
    assert connection["models_refreshed_at"] is not None
    assert "api_key" not in connection
    assert connection in listed
    for response in (created.text, str(listed)):
        assert KEY_VALUE not in response


@pytest.mark.spec("MOD-008", "MOD-002")
def test_api_keys_are_stored_encrypted(
    database: Database, server: Server, admin: Account, harness_model: HarnessModel
) -> None:
    with server.client(login(server, admin)) as client:
        connection = body(client.post("/tenant/connections", json=_server(harness_model, api_key=KEY_VALUE)))
    with database.superuser() as conn:
        row = conn.execute("SELECT api_key_ciphertext FROM connections WHERE id = %s", (connection["id"],)).fetchone()
    assert row is not None
    ciphertext = bytes(row[0])
    assert KEY_VALUE.encode() not in ciphertext
    assert len(ciphertext) > len(KEY_VALUE)


@pytest.mark.spec("MOD-008")
def test_connections_can_be_renamed_and_their_key_removed(
    server: Server, admin: Account, harness_model: HarnessModel
) -> None:
    with server.client(login(server, admin)) as client:
        connection = body(client.post("/tenant/connections", json=_server(harness_model, api_key=KEY_VALUE)))
        path = f"/tenant/connections/{connection['id']}"
        changed = client.patch(path, json={"api_key": None, "name": "Renamed", "location": "remote"})
    assert changed.status_code == 200, changed.text
    assert (body(changed)["has_api_key"], body(changed)["name"], body(changed)["location"]) == (
        False,
        "Renamed",
        "remote",
    )


@pytest.mark.spec("MOD-008")
def test_names_are_unique_in_a_household(server: Server, admin: Account, harness_model: HarnessModel) -> None:
    with server.client(login(server, admin)) as client:
        connection = body(client.post("/tenant/connections", json=_server(harness_model)))
        duplicate = client.post("/tenant/connections", json=_server(harness_model, name=connection["name"]))
    assert_problem(duplicate, 409, "resource.conflict")


@pytest.mark.spec("MOD-008")
def test_removing_a_connection(server: Server, admin: Account, harness_model: HarnessModel) -> None:
    with server.client(login(server, admin)) as client:
        connection = body(client.post("/tenant/connections", json=_server(harness_model)))
        assert client.delete(f"/tenant/connections/{connection['id']}").status_code == 204
        assert connection["id"] not in [c["id"] for c in body(client.get("/tenant/connections"))["items"]]
        assert connection["id"] not in [m["connection_id"] for m in body(client.get("/models"))["items"]]
        assert_problem(client.delete(f"/tenant/connections/{connection['id']}"), 404, "resource.not_found")


@pytest.mark.spec("MOD-008")
@pytest.mark.parametrize(
    "change",
    [
        {"name": ""},
        {"base_url": "not a url"},
        {"base_url": None},
        {"location": None},
        {"location": "somewhere"},
        {"kind": "anthropic"},
        {"model": "test-model"},
    ],
    ids=["empty-name", "invalid-url", "no-address", "no-location", "unknown-location", "unknown-kind", "unknown-field"],
)
def test_invalid_connections_are_rejected(
    server: Server, admin: Account, harness_model: HarnessModel, change: dict[str, Any]
) -> None:
    connection = {key: value for key, value in (_server(harness_model) | change).items() if value is not None}
    with server.client(login(server, admin)) as client:
        assert_problem(client.post("/tenant/connections", json=connection), 422, "request.validation_failed")


@pytest.mark.spec("MOD-008")
def test_only_tenant_admins_manage_connections(
    database: Database, server: Server, admin: Account, harness_model: HarnessModel
) -> None:
    with server.client(login(server, admin)) as client:
        connection = body(client.post("/tenant/connections", json=_server(harness_model)))
    path = f"/tenant/connections/{connection['id']}"
    member = create_account(database, admin.tenant_id)
    with server.client(login(server, member)) as client:
        for response in (
            client.post("/tenant/connections", json=_server(harness_model)),
            client.get("/tenant/connections"),
            client.patch(path, json={"name": "Mine"}),
            client.delete(path),
            client.post(f"{path}/test"),
            client.post("/tenant/connection-tests", json=_server(harness_model)),
            client.put("/tenant/default-model", json={"connection_id": connection["id"], "model": "test-model"}),
        ):
            assert_problem(response, 403, "permission.denied")


@pytest.mark.spec("MOD-008", "TEN-006")
def test_connections_of_other_households_are_out_of_reach(
    database: Database, server: Server, admin: Account, harness_model: HarnessModel
) -> None:
    other = create_account(database, create_tenant(database), "tenant_admin", instance_admin=True)
    with server.client(login(server, other)) as client:
        theirs = body(client.post("/tenant/connections", json=_server(harness_model, api_key=KEY_VALUE)))
    path = f"/tenant/connections/{theirs['id']}"
    with server.client(login(server, admin)) as client:
        assert theirs["id"] not in [c["id"] for c in body(client.get("/tenant/connections"))["items"]]
        assert theirs["id"] not in [m["connection_id"] for m in body(client.get("/models"))["items"]]
        assert_problem(client.patch(path, json={"name": "Mine"}), 404, "resource.not_found")
        assert_problem(client.delete(path), 404, "resource.not_found")
        assert_problem(client.post(f"{path}/test"), 404, "resource.not_found")
        refused = client.put("/tenant/default-model", json={"connection_id": theirs["id"], "model": "test-model"})
        assert_problem(refused, 422, "request.validation_failed")


@pytest.mark.spec("MOD-008")
def test_the_instance_has_no_models_of_its_own(server: Server, admin: Account) -> None:
    with server.client(login(server, admin)) as client:
        assert_problem(client.get("/instance/models"), 404, "resource.not_found")
        assert_problem(client.get("/tenant/models"), 404, "resource.not_found")
