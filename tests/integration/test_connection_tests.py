"""Testing a connection, step by step (MOD-013, MOD-011, ADR-0069).

The tests reach servers on the loopback address, so the admin is also the
instance admin (MOD-009). A refused port, a name under `.invalid`, a path
that is not an API and a web page stand in for the failures a household
meets. Untrusted certificates and timeouts are not served here.
"""

from __future__ import annotations

import socket
from typing import Any

import pytest

from tests.support.accounts import assert_problem, body, create_account, create_tenant, login
from tests.support.database import Database, uuid7
from tests.support.fixtures import HarnessModel
from tests.support.model import OPENROUTER_MODELS, REJECTED_KEY, SERVER_MODELS
from tests.support.server import Server


@pytest.fixture
def token(database: Database, server: Server) -> str:
    return login(server, create_account(database, create_tenant(database), "tenant_admin", instance_admin=True))


def _closed_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _test(server: Server, token: str, connection: dict[str, Any]) -> dict[str, Any]:
    with server.client(token) as client:
        response = client.post("/tenant/connection-tests", json=connection)
    assert response.status_code == 200, response.text
    return body(response)


def _openai(base_url: str) -> dict[str, Any]:
    return {"name": f"Server {uuid7()}", "kind": "openai", "base_url": base_url, "location": "local"}


def _steps(result: dict[str, Any]) -> list[tuple[str, str]]:
    return [(step["step"], step["outcome"]) for step in result["steps"]]


@pytest.mark.spec("MOD-013")
def test_a_working_server_passes_every_step(server: Server, token: str, harness_model: HarnessModel) -> None:
    result = _test(server, token, _openai(harness_model.endpoint.url))
    assert result["passed"] is True
    assert (result["reason"], result["http_status"], result["technical_detail"]) == (None, None, None)
    assert result["model_count"] == len(SERVER_MODELS)
    # Plain http has no secure connection to make.
    assert _steps(result) == [("resolve", "passed"), ("connect", "passed"), ("list_models", "passed")]
    assert all(isinstance(step["duration_ms"], int) and step["duration_ms"] >= 0 for step in result["steps"])
    assert all(step["detail"] for step in result["steps"])


@pytest.mark.spec("MOD-013")
def test_openrouter_checks_the_key(server: Server, token: str, harness_model: HarnessModel) -> None:
    connection = {"name": "OpenRouter", "kind": "openrouter", "base_url": harness_model.endpoint.openrouter_url}
    passed = _test(server, token, connection | {"api_key": "sk-or-v1-accepted"})
    assert passed["passed"] is True
    assert passed["model_count"] == len(OPENROUTER_MODELS)
    assert [step for step, _ in _steps(passed)] == ["resolve", "connect", "authenticate", "list_models"]
    failed = _test(server, token, connection | {"api_key": REJECTED_KEY})
    assert failed["passed"] is False
    assert (failed["reason"], failed["http_status"]) == ("unauthorized", 401)
    assert _steps(failed)[-2:] == [("authenticate", "failed"), ("list_models", "skipped")]
    assert failed["steps"][-1]["duration_ms"] is None
    assert REJECTED_KEY not in str(failed), "the result repeats the key"


@pytest.mark.spec("MOD-013")
@pytest.mark.parametrize(
    "case",
    ["connection_refused", "name_not_found", "http_error", "not_a_model_server"],
)
def test_a_failure_names_its_step_and_reason(
    server: Server, token: str, harness_model: HarnessModel, case: str
) -> None:
    root = harness_model.endpoint.url.removesuffix("/v1")
    base_url, failed_step = {
        "connection_refused": (f"http://127.0.0.1:{_closed_port()}/v1", "connect"),
        "name_not_found": ("http://mazzamurello-test.invalid:11434/v1", "resolve"),
        # The server answers, but not at this path: most servers want `/v1`.
        "http_error": (root, "list_models"),
        "not_a_model_server": (f"{root}/html", "list_models"),
    }[case]
    result = _test(server, token, _openai(base_url))
    assert result["passed"] is False
    assert result["reason"] == case
    assert result["model_count"] is None
    steps = _steps(result)
    failed_at = [step for step, _ in steps].index(failed_step)
    assert steps[failed_at] == (failed_step, "failed")
    assert all(outcome == "passed" for _, outcome in steps[:failed_at])
    assert all(outcome == "skipped" for _, outcome in steps[failed_at + 1 :])
    assert result["technical_detail"]
    assert len(result["technical_detail"]) <= 2000
    if case == "http_error":
        assert result["http_status"] == 404
        assert "404" in result["steps"][failed_at]["detail"]
    if case == "not_a_model_server":
        # Up to 500 characters of the answer help to recognize what answered.
        assert "Welcome to your router" in result["technical_detail"]


@pytest.mark.spec("MOD-013", "MOD-008")
def test_a_connection_that_fails_its_test_is_not_saved(server: Server, token: str, harness_model: HarnessModel) -> None:
    broken = _openai(f"http://127.0.0.1:{_closed_port()}/v1")
    with server.client(token) as client:
        refused = client.post("/tenant/connections", json=broken)
        problem = assert_problem(refused, 422, "connection.test_failed")
        assert problem["test"]["reason"] == "connection_refused"
        assert broken["name"] not in [c["name"] for c in body(client.get("/tenant/connections"))["items"]]
        working = body(client.post("/tenant/connections", json=_openai(harness_model.endpoint.url)))
        path = f"/tenant/connections/{working['id']}"
        changed = client.patch(path, json={"base_url": broken["base_url"]})
        assert_problem(changed, 422, "connection.test_failed")
        kept = [c for c in body(client.get("/tenant/connections"))["items"] if c["id"] == working["id"]]
    assert [c["base_url"] for c in kept] == [harness_model.endpoint.url]


@pytest.mark.spec("MOD-013", "MOD-011")
def test_testing_a_saved_connection_refreshes_its_models(
    server: Server, token: str, harness_model: HarnessModel
) -> None:
    with server.client(token) as client:
        connection = body(client.post("/tenant/connections", json=_openai(harness_model.endpoint.url)))
        response = client.post(f"/tenant/connections/{connection['id']}/test")
        assert response.status_code == 200, response.text
        assert body(response)["passed"] is True
        (after,) = [c for c in body(client.get("/tenant/connections"))["items"] if c["id"] == connection["id"]]
    assert after["models_refreshed_at"] > connection["models_refreshed_at"]


@pytest.mark.spec("MOD-013")
def test_tests_are_rate_limited_per_household(server: Server, token: str) -> None:
    refused = _openai(f"http://127.0.0.1:{_closed_port()}/v1")
    with server.client(token) as client:
        statuses = [client.post("/tenant/connection-tests", json=refused).status_code for _ in range(21)]
        limited = client.post("/tenant/connection-tests", json=refused)
    assert statuses[:20] == [200] * 20
    assert_problem(limited, 429, "auth.rate_limited")
