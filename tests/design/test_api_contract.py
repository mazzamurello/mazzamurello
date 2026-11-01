"""The server serves exactly the contract's operations, with documented error codes (ADR-0056)."""

from __future__ import annotations

import ast
import base64
import re
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.routing import APIRoute, iter_route_contexts

from mazzamurello_server.app import create_app
from mazzamurello_server.config import ApiConfiguration, load_api_configuration
from tests.support.contract import contract
from tests.support.database import ROOT

SERVER = ROOT / "src" / "server" / "mazzamurello_server"
HTTP_METHODS = ("get", "put", "post", "delete", "patch")
# Dotted names in the server that are not error codes.
NOT_ERROR_CODES = re.compile(r"^mazzamurello\.")
DOTTED = re.compile(r"^[a-z]+\.[a-z_]+$")


def _configuration() -> ApiConfiguration:
    return load_api_configuration(
        {
            "MZM_DATABASE_URL": "postgresql://mzm_app:unused@127.0.0.1:1/unused",
            "MZM_SECRET_KEY": base64.urlsafe_b64encode(bytes(32)).decode(),
            "MZM_SANDBOXD_URL": "http://127.0.0.1:1/v1",
            "MZM_SANDBOXD_TOKEN": "t" * 43,
        }
    )


def _server_operations() -> set[tuple[str, str]]:
    base = str(contract()["servers"][0]["url"]).rstrip("/")
    operations: set[tuple[str, str]] = set()
    for route in iter_route_contexts(create_app(_configuration()).routes):
        path = route.path or ""
        assert isinstance(route.original_route, APIRoute), f"{path}: every route is an operation of the contract"
        assert path.startswith(f"{base}/"), f"{path}: outside {base}"
        operations.update((method.lower(), path.removeprefix(base)) for method in route.methods or ())
    return operations


def _contract_operations() -> set[tuple[str, str]]:
    paths = cast(dict[str, dict[str, Any]], contract()["paths"])
    return {(method, path) for path, item in paths.items() for method in item if method in HTTP_METHODS}


@pytest.mark.spec("API-001", "API-002")
def test_the_server_serves_exactly_the_contracts_operations() -> None:
    server, documented = _server_operations(), _contract_operations()
    assert sorted(server - documented) == [], "operations the contract does not describe (API-001)"
    assert sorted(documented - server) == [], "operations of the contract the server lacks"


def _string_constants(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    return {node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)}


@pytest.mark.spec("API-007")
def test_every_error_code_the_server_produces_is_documented() -> None:
    documented = set(cast(list[str], contract()["components"]["schemas"]["ErrorCode"]["enum"]))
    produced = {
        value
        for path in sorted(SERVER.rglob("*.py"))
        for value in _string_constants(path)
        if DOTTED.match(value) and not NOT_ERROR_CODES.match(value)
    }
    assert produced, "no error codes found: the pattern no longer matches the server's codes"
    assert sorted(produced - documented) == []
