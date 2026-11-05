"""The models of a household and the model of a conversation (MOD-010, MOD-011, MOD-012, MOD-014, MOD-015, ADR-0069).

Each household reaches the model the tests serve through two connections: a
server with an OpenAI-compatible API, whose models say nothing about tools,
and OpenRouter, as its documentation describes it (tests/support/model.py).
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import pytest

from tests.support.accounts import Account, assert_problem, body, create_account, create_tenant, login
from tests.support.database import Database
from tests.support.fixtures import HarnessModel, HouseholdModel
from tests.support.model import OPENROUTER_MODELS, REFUSAL, SERVER_MODELS
from tests.support.runs import create_conversation, run_input, start_run, text_of, wait_for_run
from tests.support.server import Server


@dataclass(frozen=True)
class Household:
    member: Account
    token: str
    model: HouseholdModel
    openrouter_id: str


@pytest.fixture
def household(database: Database, server: Server, default_model: HarnessModel) -> Household:
    member = create_account(database, create_tenant(database))
    model = default_model.connect(member.tenant_id)
    with server.client(model.admin_token) as client:
        response = client.post(
            "/tenant/connections",
            json={
                "name": "OpenRouter",
                "kind": "openrouter",
                "base_url": model.endpoint.openrouter_url,
                "api_key": f"sk-or-v1-{secrets.token_hex(8)}",
            },
        )
    assert response.status_code == 201, response.text
    return Household(member, login(server, member), model, body(response)["id"])


def _models(server: Server, token: str) -> dict[str, Any]:
    with server.client(token) as client:
        response = client.get("/models")
    assert response.status_code == 200, response.text
    return body(response)


def _choose(server: Server, token: str, conversation_id: str, connection_id: str, model: str) -> None:
    with server.client(token) as client:
        response = client.patch(
            f"/conversations/{conversation_id}", json={"model": {"connection_id": connection_id, "model": model}}
        )
    assert response.status_code == 200, response.text


@pytest.mark.spec("MOD-011", "MOD-010")
def test_every_member_sees_every_model_of_the_household(server: Server, household: Household) -> None:
    models = _models(server, household.token)
    assert models["default"] == {"connection_id": household.model.connection_id, "model": "test-model"}
    by_connection: dict[str, list[dict[str, Any]]] = {}
    for item in models["items"]:
        by_connection.setdefault(item["connection_id"], []).append(item)
    local = by_connection[household.model.connection_id]
    assert [m["model"] for m in local] == list(SERVER_MODELS)
    assert {(m["location"], m["tools"], m["connection_name"]) for m in local} == {("local", None, "Test server")}
    remote = by_connection[household.openrouter_id]
    # Most used in the past week first, as OpenRouter ordered them when asked.
    assert [m["model"] for m in remote] == [model[0] for model in OPENROUTER_MODELS]
    assert {m["location"] for m in remote} == {"remote"}
    assert [m["tools"] for m in remote] == [model[5] for model in OPENROUTER_MODELS]
    popular = remote[0]
    assert (popular["name"], popular["context_window"]) == ("Test: Popular", 131072)
    prices = popular["prices"]
    assert (Decimal(prices["input"]), Decimal(prices["output"]), prices["currency"]) == (
        Decimal("0.27"),
        Decimal("0.41"),
        "USD",
    )
    assert all(m["prices"] is None for m in local), "a local server costs nothing"
    # A price that depends on the model a router picks is not known.
    (router,) = [m for m in remote if m["model"] == "test/router"]
    assert router["prices"] is None


@pytest.mark.spec("MOD-011")
def test_openrouter_is_asked_for_its_most_used_models(server: Server, household: Household) -> None:
    reads = household.model.endpoint.reads("/openrouter/api/v1/models")
    assert reads, "the server never listed OpenRouter's models"
    assert all("sort=top-weekly" in read.path.split("?", 1)[-1].split("&") for read in reads)


@pytest.mark.spec("MOD-012")
def test_a_new_conversation_starts_with_the_default_model(server: Server, household: Household) -> None:
    conversation = create_conversation(server, household.token)
    assert conversation["model"] == {"connection_id": household.model.connection_id, "model": "test-model"}
    # Changing the default later leaves existing conversations as they are.
    with server.client(household.model.admin_token) as client:
        default = {"connection_id": household.openrouter_id, "model": "test/second"}
        assert client.put("/tenant/default-model", json=default).status_code == 200
    with server.client(household.token) as client:
        assert body(client.get(f"/conversations/{conversation['id']}"))["model"] == conversation["model"]
    assert create_conversation(server, household.token)["model"] == default
    with server.client(household.token) as client:
        chosen = {"connection_id": household.openrouter_id, "model": "test/another"}
        created = client.post("/conversations", json={"model": chosen})
    assert created.status_code == 201, created.text
    assert body(created)["model"] == chosen


@pytest.mark.spec("MOD-012")
def test_the_chosen_model_answers_from_the_next_run(server: Server, household: Household) -> None:
    conversation = create_conversation(server, household.token)
    before = f"before {secrets.token_hex(4)}"
    start_run(server, household.token, conversation["id"], before)
    _choose(server, household.token, conversation["id"], household.openrouter_id, "test/popular")
    after = f"after {secrets.token_hex(4)}"
    run_id, _ = start_run(server, household.token, conversation["id"], after)
    run = wait_for_run(server, household.token, run_id)
    assert run["model"]["connection_id"] == household.openrouter_id
    assert run["model"]["model"] == "test/popular"
    (earlier,) = household.model.endpoint.requests_with(before)
    assert (earlier.openrouter, earlier.body["model"]) == (False, "test-model")
    (request,) = household.model.endpoint.requests_with(after)
    assert (request.openrouter, request.body["model"]) == (True, "test/popular")


@pytest.mark.spec("MOD-012")
def test_only_models_of_the_household_can_be_chosen(
    database: Database, server: Server, household: Household, default_model: HarnessModel
) -> None:
    conversation = create_conversation(server, household.token)
    elsewhere = default_model.connect(create_tenant(database))
    with server.client(household.token) as client:
        for choice in (
            {"connection_id": household.openrouter_id, "model": "test/unknown"},
            {"connection_id": elsewhere.connection_id, "model": "test-model"},
        ):
            refused = client.patch(f"/conversations/{conversation['id']}", json={"model": choice})
            assert_problem(refused, 422, "request.validation_failed")


@pytest.mark.spec("MOD-012")
def test_a_conversation_whose_model_is_gone_does_not_switch_models(server: Server, household: Household) -> None:
    conversation = create_conversation(server, household.token)
    _choose(server, household.token, conversation["id"], household.openrouter_id, "test/popular")
    with server.client(household.model.admin_token) as client:
        assert client.delete(f"/tenant/connections/{household.openrouter_id}").status_code == 204
    text = f"orphaned {secrets.token_hex(4)}"
    with server.client(household.token) as client:
        response = client.post(f"/conversations/{conversation['id']}/runs", json=run_input(conversation["id"], text))
    assert_problem(response, 409, "model.unavailable")
    assert household.model.endpoint.requests_with(text) == [], "another model answered instead"


@pytest.mark.spec("MOD-014")
def test_a_model_without_tools_answers_without_tools(server: Server, household: Household) -> None:
    conversation = create_conversation(server, household.token)
    _choose(server, household.token, conversation["id"], household.openrouter_id, "test/chat-only")
    text = f"chat only {secrets.token_hex(4)}"
    run_id, events = start_run(server, household.token, conversation["id"], text)
    assert wait_for_run(server, household.token, run_id)["status"] == "completed"
    assert text_of(events) == f"Echo: {text}"
    requests = household.model.endpoint.requests_with(text)
    assert requests
    assert all(not request.body.get("tools") for request in requests)


@pytest.mark.spec("MOD-014")
def test_a_server_that_refuses_tools_fails_the_run(server: Server, household: Household) -> None:
    conversation = create_conversation(server, household.token)
    _choose(server, household.token, conversation["id"], household.model.connection_id, "refuses-tools")
    text = f"refused {secrets.token_hex(4)}"
    run_id, events = start_run(server, household.token, conversation["id"], text)
    run = wait_for_run(server, household.token, run_id)
    assert run["status"] == "failed"
    assert run["error_code"] == "model.request_failed"
    assert events[-1].type == "RUN_ERROR"
    assert "does not support tools" in str(events[-1].data.get("message", ""))
    # Never retried without the tools.
    assert all(request.body.get("tools") for request in household.model.endpoint.requests_with(text))


@pytest.mark.spec("MOD-015")
@pytest.mark.parametrize("through", ["server", "openrouter"])
def test_a_refused_request_fails_the_run_with_the_reason(server: Server, household: Household, through: str) -> None:
    conversation = create_conversation(server, household.token)
    if through == "openrouter":
        _choose(server, household.token, conversation["id"], household.openrouter_id, "test/popular")
    run_id, events = start_run(server, household.token, conversation["id"], "refuse")
    run = wait_for_run(server, household.token, run_id)
    assert run["status"] == "failed"
    assert run["error_code"] == "model.refused"
    assert events[-1].type == "RUN_ERROR"
    assert events[-1].data.get("code") == "model.refused"
    assert REFUSAL in str(events[-1].data.get("message", ""))
    # The conversation stays usable: the user can rephrase.
    text = f"rephrased {secrets.token_hex(4)}"
    run_id, events = start_run(server, household.token, conversation["id"], text, parent_run_id=run_id)
    assert wait_for_run(server, household.token, run_id)["status"] == "completed"
    assert text_of(events) == f"Echo: {text}"


def _admin_without_models(database: Database, server: Server) -> str:
    """A tenant admin, also the instance admin, of a household with no connection yet."""
    return login(server, create_account(database, create_tenant(database), "tenant_admin", instance_admin=True))


@pytest.mark.spec("MOD-012")
def test_openrouter_brings_a_free_default_model(
    database: Database, server: Server, harness_model: HarnessModel
) -> None:
    token = _admin_without_models(database, server)
    with server.client(token) as client:
        response = client.post(
            "/tenant/connections",
            json={
                "name": "OpenRouter",
                "kind": "openrouter",
                "base_url": harness_model.endpoint.openrouter_url,
                "api_key": "sk-or-v1-a",
            },
        )
        assert response.status_code == 201, response.text
        openrouter = body(response)["id"]
        # The most used free model that can call tools.
        assert body(client.get("/models"))["default"] == {"connection_id": openrouter, "model": "test/free"}
        # A later connection leaves the default as it is.
        other = client.post(
            "/tenant/connections",
            json={"name": "Server", "kind": "openai", "base_url": harness_model.endpoint.url, "location": "local"},
        )
        assert other.status_code == 201, other.text
        assert body(client.get("/models"))["default"] == {"connection_id": openrouter, "model": "test/free"}
    conversation = create_conversation(server, token)
    assert conversation["model"] == {"connection_id": openrouter, "model": "test/free"}


@pytest.mark.spec("MOD-012")
def test_a_server_brings_its_first_model_as_default(
    database: Database, server: Server, harness_model: HarnessModel
) -> None:
    token = _admin_without_models(database, server)
    with server.client(token) as client:
        response = client.post(
            "/tenant/connections",
            json={"name": "Server", "kind": "openai", "base_url": harness_model.endpoint.url, "location": "local"},
        )
        assert response.status_code == 201, response.text
        assert body(client.get("/models"))["default"] == {
            "connection_id": body(response)["id"],
            "model": SERVER_MODELS[0],
        }
