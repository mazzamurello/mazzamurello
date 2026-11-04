"""OpenRouter, the first remote provider (MOD-001, MOD-006, ADR-0057, ADR-0069).

The model the tests serve answers as OpenRouter's documentation describes
under `/openrouter/api/v1` (tests/support/model.py); tests never reach
OpenRouter itself.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from decimal import Decimal

import pytest

from tests.support.accounts import Account, assert_problem, body, create_account, create_tenant, login
from tests.support.database import Database, uuid7
from tests.support.fixtures import HarnessModel, HouseholdModel
from tests.support.model import OPENROUTER_COST
from tests.support.runs import create_conversation, start_run, text_of, wait_for_run
from tests.support.server import Server

ATTRIBUTION_HEADERS = ("http-referer", "x-title", "x-openrouter-title", "x-openrouter-categories")


@dataclass(frozen=True)
class OpenRouterModel:
    connection_id: str
    api_key: str


@pytest.fixture
def account(database: Database) -> Account:
    return create_account(database, create_tenant(database))


@pytest.fixture
def household(account: Account, default_model: HarnessModel) -> HouseholdModel:
    return default_model.connect(account.tenant_id)


@pytest.fixture
def token(server: Server, account: Account) -> str:
    return login(server, account)


@pytest.fixture
def openrouter(server: Server, household: HouseholdModel) -> OpenRouterModel:
    """An OpenRouter connection of the household, whose most used model is its default."""
    api_key = f"sk-or-v1-{secrets.token_hex(16)}"
    with server.client(household.admin_token) as client:
        response = client.post(
            "/tenant/connections",
            json={
                "name": "OpenRouter",
                "kind": "openrouter",
                "base_url": household.endpoint.openrouter_url,
                "api_key": api_key,
            },
        )
        assert response.status_code == 201, response.text
        connection = body(response)
        default = {"connection_id": connection["id"], "model": "test/popular"}
        assert client.put("/tenant/default-model", json=default).status_code == 200
    return OpenRouterModel(connection["id"], api_key)


@pytest.mark.spec("MOD-001", "MOD-008", "MOD-010")
def test_openrouter_connections_are_remote(server: Server, household: HouseholdModel) -> None:
    connection = {"name": "OpenRouter", "kind": "openrouter", "base_url": household.endpoint.openrouter_url}
    with server.client(household.admin_token) as client:
        created = client.post("/tenant/connections", json=connection | {"name": "Remote", "api_key": "sk-or-v1-a"})
        assert created.status_code == 201, created.text
        assert (body(created)["kind"], body(created)["location"]) == ("openrouter", "remote")
        for invalid in ({"location": "local"}, {"kind": "anthropic"}):
            assert_problem(
                client.post("/tenant/connections", json=connection | {"api_key": "sk-or-v1-b"} | invalid),
                422,
                "request.validation_failed",
            )
        # OpenRouter needs a key.
        assert_problem(client.post("/tenant/connections", json=connection), 422, "request.validation_failed")


@pytest.mark.spec("MOD-001", "MOD-002", "OBS-001")
def test_openrouter_answers_through_the_gateway(
    server: Server, token: str, household: HouseholdModel, openrouter: OpenRouterModel
) -> None:
    conversation = create_conversation(server, token)
    text = f"hello {uuid7()}"
    run_id, events = start_run(server, token, conversation["id"], text)
    assert wait_for_run(server, token, run_id)["status"] == "completed"
    assert text_of(events) == f"Echo: {text}"
    requests = household.endpoint.requests_with(text)
    assert requests
    assert all(request.openrouter for request in requests)
    assert {request.authorization for request in requests} == {f"Bearer {openrouter.api_key}"}
    assert [name for request in requests for name in ATTRIBUTION_HEADERS if name in request.headers] == []


@pytest.mark.spec("MOD-001")
def test_the_ledger_records_the_cost_openrouter_reports(
    database: Database, server: Server, token: str, openrouter: OpenRouterModel
) -> None:
    conversation = create_conversation(server, token)
    run_id, _ = start_run(server, token, conversation["id"], "priced by the provider")
    with database.superuser() as conn:
        rows = conn.execute(
            "SELECT model, cost, currency, price_source FROM usage_ledger WHERE run_id = %s AND purpose = 'run'",
            (run_id,),
        ).fetchall()
    assert rows == [("test/popular", Decimal(str(OPENROUTER_COST)), "USD", "provider")]


@pytest.mark.spec("MOD-001")
def test_tools_work_through_openrouter(server: Server, token: str, openrouter: OpenRouterModel) -> None:
    conversation = create_conversation(server, token)
    run_id, events = start_run(server, token, conversation["id"], "run:echo $((6*7))")
    assert wait_for_run(server, token, run_id)["status"] == "completed"
    assert "Tool said:" in text_of(events)
    assert "42" in text_of(events)


@pytest.mark.spec("MOD-001")
@pytest.mark.parametrize("script", ["status:402", "status:429", "error-midstream"])
def test_openrouter_errors_fail_the_run(server: Server, token: str, openrouter: OpenRouterModel, script: str) -> None:
    conversation = create_conversation(server, token)
    run_id, events = start_run(server, token, conversation["id"], script)
    run = wait_for_run(server, token, run_id)
    assert run["status"] == "failed"
    assert run["error_code"] in {"model.request_failed", "model.unavailable"}
    assert events[-1].type == "RUN_ERROR"
    assert events[-1].data.get("code") == run["error_code"]
