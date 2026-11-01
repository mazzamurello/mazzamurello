"""OpenRouter, the first remote provider (MOD-001, MOD-006, ADR-0057).

The model the tests serve answers as OpenRouter's documentation describes
under `/openrouter/api/v1` (tests/support/model.py); tests never reach
OpenRouter itself.
"""

from __future__ import annotations

import secrets
from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal

import pytest

from tests.support.accounts import Account, assert_problem, body, create_account, create_tenant, login
from tests.support.database import Database, uuid7
from tests.support.fixtures import HarnessModel
from tests.support.model import OPENROUTER_COST
from tests.support.runs import create_conversation, start_run, text_of, wait_for_run
from tests.support.server import Server

ATTRIBUTION_HEADERS = ("http-referer", "x-title", "x-openrouter-title", "x-openrouter-categories")


@dataclass(frozen=True)
class OpenRouterModel:
    id: str
    api_key: str


@pytest.fixture
def account(database: Database) -> Account:
    return create_account(database, create_tenant(database))


@pytest.fixture
def token(server: Server, account: Account) -> str:
    return login(server, account)


@pytest.fixture
def openrouter(server: Server, default_model: HarnessModel) -> Iterator[OpenRouterModel]:
    """An OpenRouter model as the instance's default, for the duration of a test."""
    api_key = f"sk-or-v1-{secrets.token_hex(16)}"
    with server.client(default_model.admin_token) as client:
        response = client.post(
            "/instance/models",
            json={
                "name": f"OpenRouter {uuid7()}",
                "api": "openrouter",
                "base_url": default_model.endpoint.openrouter_url,
                "model": "openai/gpt-4o-mini",
                "api_key": api_key,
                "paid": True,
                "is_default": True,
            },
        )
    assert response.status_code == 201, response.text
    model = OpenRouterModel(body(response)["id"], api_key)
    try:
        yield model
    finally:
        with server.client(default_model.admin_token) as client:
            client.patch(f"/instance/models/{default_model.id}", json={"is_default": True})
            client.delete(f"/instance/models/{model.id}")


@pytest.mark.spec("MOD-001", "MOD-008")
def test_model_configurations_name_their_api(server: Server, default_model: HarnessModel) -> None:
    with server.client(default_model.admin_token) as client:
        plain = client.post(
            "/instance/models",
            json={"name": f"Plain {uuid7()}", "base_url": "http://10.0.0.5:11434/v1", "model": "m", "paid": False},
        )
        assert plain.status_code == 201, plain.text
        assert body(plain)["api"] == "openai"
        changed = client.patch(f"/instance/models/{body(plain)['id']}", json={"api": "openrouter"})
        assert changed.status_code == 200, changed.text
        assert body(changed)["api"] == "openrouter"
        assert_problem(
            client.patch(f"/instance/models/{body(plain)['id']}", json={"api": "anthropic"}),
            422,
            "request.validation_failed",
        )
        assert client.delete(f"/instance/models/{body(plain)['id']}").status_code == 204


@pytest.mark.spec("MOD-001", "MOD-002", "OBS-001")
def test_openrouter_answers_through_the_gateway(
    server: Server, token: str, default_model: HarnessModel, openrouter: OpenRouterModel
) -> None:
    conversation = create_conversation(server, token)
    text = f"hello {uuid7()}"
    run_id, events = start_run(server, token, conversation["id"], text)
    assert wait_for_run(server, token, run_id)["status"] == "completed"
    assert text_of(events) == f"Echo: {text}"
    requests = default_model.endpoint.requests_with(text)
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
            "SELECT model, cost, currency, price_source FROM usage_ledger WHERE run_id = %s", (run_id,)
        ).fetchall()
    assert rows == [("openai/gpt-4o-mini", Decimal(str(OPENROUTER_COST)), "USD", "provider")]


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
