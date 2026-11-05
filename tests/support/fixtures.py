"""Fixtures shared by the test directories that need the database or the API."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field

import pytest

from tests.support.accounts import body, create_account, login
from tests.support.database import Database, start_database
from tests.support.model import ModelServer, start_model_server
from tests.support.sandbox import Driver, start_sandboxes
from tests.support.search import SearchServer, start_search_server
from tests.support.server import Server, start_server
from tests.support.world import World, create_world


@pytest.fixture(scope="session")
def database(request: pytest.FixtureRequest) -> Database:
    return start_database(request.config)


@pytest.fixture
def world(database: Database) -> World:
    return create_world(database)


@pytest.fixture(scope="session")
def sandboxes(request: pytest.FixtureRequest) -> Driver:
    return start_sandboxes(request.config)


@pytest.fixture(scope="session")
def search_service() -> Iterator[SearchServer]:
    search, http = start_search_server()
    yield search
    http.shutdown()


@pytest.fixture(scope="session")
def server(
    request: pytest.FixtureRequest, database: Database, sandboxes: Driver, search_service: SearchServer
) -> Server:
    return start_server(request.config, database, (sandboxes.url, sandboxes.token), search_service.url)


@dataclass(frozen=True)
class HouseholdModel:
    """The harness model as one household reaches it: its connection and default model (ADR-0069)."""

    connection_id: str
    # A user of the household who is its tenant admin and the instance admin.
    admin_token: str
    endpoint: ModelServer


@dataclass(frozen=True)
class HarnessModel:
    """The model served by the tests, which households reach through a connection of their own."""

    endpoint: ModelServer
    database: Database
    server: Server
    households: dict[uuid.UUID, HouseholdModel] = field(default_factory=dict[uuid.UUID, HouseholdModel])

    def connect(self, tenant_id: uuid.UUID) -> HouseholdModel:
        """Give the tenant a connection to the harness model and make `test-model` its default model.

        The connection is added by a user who is also the instance admin, since
        only such a connection may use the loopback address (MOD-009).
        """
        household = self.households.get(tenant_id)
        if household is None:
            admin = create_account(self.database, tenant_id, "tenant_admin", instance_admin=True)
            token = login(self.server, admin)
            with self.server.client(token) as client:
                response = client.post(
                    "/tenant/connections",
                    json={"name": "Test server", "kind": "openai", "base_url": self.endpoint.url, "location": "local"},
                )
            assert response.status_code == 201, response.text
            household = HouseholdModel(body(response)["id"], token, self.endpoint)
            self.households[tenant_id] = household
        with self.server.client(household.admin_token) as client:
            response = client.put(
                "/tenant/default-model", json={"connection_id": household.connection_id, "model": "test-model"}
            )
        assert response.status_code == 200, response.text
        return household


@pytest.fixture(scope="session")
def model_server() -> Iterator[ModelServer]:
    model, http = start_model_server()
    yield model
    http.shutdown()


@pytest.fixture(scope="session")
def harness_model(database: Database, server: Server, model_server: ModelServer) -> HarnessModel:
    return HarnessModel(model_server, database, server)


@pytest.fixture
def default_model(harness_model: HarnessModel) -> HarnessModel:
    """The harness model; tests connect the households that need a model with `connect`."""
    return harness_model
