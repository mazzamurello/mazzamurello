"""Fixtures shared by the test directories that need the database or the API."""

from __future__ import annotations

import pytest

from tests.support.database import Database, start_database
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
