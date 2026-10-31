"""Fixtures shared by the test directories that need the database or the API."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

import pytest

from tests.support.accounts import body, create_account, create_tenant, login
from tests.support.database import Database, start_database, uuid7
from tests.support.model import ModelServer, start_model_server
from tests.support.server import Server, start_server
from tests.support.world import World, create_world


@pytest.fixture(scope="session")
def database(request: pytest.FixtureRequest) -> Database:
    return start_database(request.config)


@pytest.fixture
def world(database: Database) -> World:
    return create_world(database)


@pytest.fixture(scope="session")
def server(request: pytest.FixtureRequest, database: Database) -> Server:
    return start_server(request.config, database)


@dataclass(frozen=True)
class HarnessModel:
    """The instance model served by the tests, and an instance admin who manages it."""

    id: str
    admin_token: str
    endpoint: ModelServer


@pytest.fixture(scope="session")
def model_server() -> Iterator[ModelServer]:
    model, http = start_model_server()
    yield model
    http.shutdown()


@pytest.fixture(scope="session")
def harness_model(database: Database, server: Server, model_server: ModelServer) -> HarnessModel:
    admin = create_account(database, create_tenant(database), "tenant_admin", instance_admin=True)
    token = login(server, admin)
    with server.client(token) as client:
        response = client.post(
            "/instance/models",
            json={
                "name": f"Test model {uuid7()}",
                "base_url": model_server.url,
                "model": "test-model",
                "paid": False,
                "is_default": True,
            },
        )
    assert response.status_code == 201, response.text
    return HarnessModel(body(response)["id"], token, model_server)


@pytest.fixture
def default_model(server: Server, harness_model: HarnessModel) -> HarnessModel:
    """The harness model, made the instance default again in case a test changed it."""
    with server.client(harness_model.admin_token) as client:
        response = client.patch(f"/instance/models/{harness_model.id}", json={"is_default": True})
    assert response.status_code == 200, response.text
    return harness_model
