"""Fixtures for end-to-end tests: none of the session's database, server or sandboxes (ADR-0054).

Each module installs a deployment of its own, so that CI can run modules
in parts of their own (ADR-0059).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from tests.support import deployment as installation
from tests.support.deployment import Deployment
from tests.support.model import ModelServer


@pytest.fixture(scope="module")
def deployment(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Deployment]:
    with installation.installed(tmp_path_factory.mktemp("deployment")) as installed:
        yield installed


@pytest.fixture(scope="module")
def reachable_model(deployment: Deployment) -> Iterator[ModelServer]:
    with installation.reachable_model(deployment) as model:
        yield model
