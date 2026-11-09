"""The models of a household and the settings of a conversation.

MOD-010, MOD-011, MOD-012, MOD-014, MOD-015, CNV-013, CNV-014, ADR-0069 and
ADR-0081. Each household reaches the model the tests serve through two
connections: a server with an OpenAI-compatible API, whose models say nothing
about tools or reasoning, and OpenRouter, as its documentation describes it
(tests/support/model.py).
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
from tests.support.model import OPENROUTER_MODELS, REFUSAL, SERVER_MODELS, ModelRequest
from tests.support.runs import create_conversation, messages, run_input, start_run, text_of, wait_for_run
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
    assert [m["reasoning"] for m in remote] == [model[6] for model in OPENROUTER_MODELS]
    assert {m["reasoning"] for m in local} == {None}
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


@pytest.mark.spec("MOD-015", "UX-014")
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
    refused_id = run_id
    run_id, events = start_run(server, household.token, conversation["id"], text, parent_run_id=run_id)
    assert wait_for_run(server, household.token, run_id)["status"] == "completed"
    assert text_of(events) == f"Echo: {text}"
    # The history keeps the refusal and its reason (UX-014).
    runs = {run["run_id"]: run for run in messages(server, household.token, conversation["id"])["runs"]}
    error = runs[refused_id]["error"]
    assert error["code"] == "model.refused"
    assert REFUSAL in error["reason"]
    assert runs[run_id]["error"] is None


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


# Every tool of the assistant, each a user can switch off by its name (ADR-0081, ADR-0087).
TOOLS = frozenset(
    {
        "web_search",
        "read_page",
        "run_command",
        "start_command",
        "check_command",
        "stop_command",
        "read_file",
        "write_file",
        "edit_file",
        "create_directory",
        "list_directory",
        "find_files",
        "search_files",
        "file_info",
        "offer_download",
        "ask_user_question",
        "write_plan",
        "read_plan",
        "add_task",
        "update_task_status",
        "update_task_statuses",
        "remove_task",
    }
)
NO_DEFAULTS: dict[str, Any] = {
    "model": None,
    "reasoning": None,
    "disabled_tools": [],
    "base_instructions": None,
    "additional_instructions": None,
}


def _defaults(response: Any) -> dict[str, Any]:
    """The user's defaults in a response, without the built-in base instructions that come with them."""
    defaults = body(response)
    assert isinstance(defaults.pop("built_in_base_instructions"), str)
    return defaults


def _settings(server: Server, token: str, **changes: Any) -> dict[str, Any]:
    """Set the user's defaults: those given, and none of the others."""
    with server.client(token) as client:
        response = client.put("/me/settings", json=NO_DEFAULTS | changes)
    assert response.status_code == 200, response.text
    return _defaults(response)


def _change(server: Server, token: str, conversation_id: str, **changes: Any) -> dict[str, Any]:
    with server.client(token) as client:
        response = client.patch(f"/conversations/{conversation_id}", json=changes)
    assert response.status_code == 200, response.text
    return body(response)


def _request(server: Server, household: Household, conversation_id: str, text: str) -> ModelRequest:
    """Run `text` in the conversation, and the first request it made to the model."""
    run_id, _ = start_run(server, household.token, conversation_id, text)
    assert wait_for_run(server, household.token, run_id)["status"] == "completed"
    return household.model.endpoint.requests_with(text)[0]


@pytest.mark.spec("CNV-013", "CNV-014")
def test_a_user_has_no_defaults_until_they_set_them(database: Database, server: Server, household: Household) -> None:
    with server.client(household.token) as client:
        response = client.get("/me/settings")
    assert response.status_code == 200, response.text
    assert _defaults(response) == NO_DEFAULTS
    chosen = {
        "model": {"connection_id": household.openrouter_id, "model": "test/popular"},
        "reasoning": "deep",
        "disabled_tools": ["web_search", "run_command"],
        "base_instructions": "You are Ada, a patient helper.",
        "additional_instructions": "Answer in French.",
    }
    assert _settings(server, household.token, **chosen) == chosen
    with server.client(household.token) as client:
        assert _defaults(client.get("/me/settings")) == chosen
    # Defaults are the user's alone, even within their household.
    other = login(server, create_account(database, household.member.tenant_id))
    with server.client(other) as client:
        assert _defaults(client.get("/me/settings")) == NO_DEFAULTS


@pytest.mark.spec("CNV-013")
def test_defaults_take_only_models_and_tools_that_exist(server: Server, household: Household) -> None:
    with server.client(household.token) as client:
        for invalid in (
            {"model": {"connection_id": household.openrouter_id, "model": "test/unknown"}},
            {"reasoning": "maximum"},
            {"disabled_tools": ["teleport"]},
            # The names of the tool groups before ADR-0087 are no tools.
            {"disabled_tools": ["shell"]},
        ):
            assert_problem(client.put("/me/settings", json=NO_DEFAULTS | invalid), 422, "request.validation_failed")
        conversation = create_conversation(server, household.token)
        refused = client.patch(f"/conversations/{conversation['id']}", json={"disabled_tools": ["teleport"]})
        assert_problem(refused, 422, "request.validation_failed")


@pytest.mark.spec("CNV-013", "CNV-014")
def test_without_defaults_a_conversation_starts_well_configured(server: Server, household: Household) -> None:
    conversation = create_conversation(server, household.token)
    assert conversation["model"] == {"connection_id": household.model.connection_id, "model": "test-model"}
    assert (conversation["reasoning"], conversation["disabled_tools"]) == ("on", [])
    assert (conversation["base_instructions"], conversation["additional_instructions"]) == (None, None)
    request = _request(server, household, conversation["id"], f"configured {secrets.token_hex(4)}")
    assert request.tool_names() == TOOLS


@pytest.mark.spec("CNV-013", "MOD-012")
def test_a_new_conversation_copies_the_users_defaults(server: Server, household: Household) -> None:
    popular = {"connection_id": household.openrouter_id, "model": "test/popular"}
    _settings(server, household.token, model=popular, reasoning="deep", disabled_tools=["web_search"])
    conversation = create_conversation(server, household.token)
    assert (conversation["model"], conversation["reasoning"], conversation["disabled_tools"]) == (
        popular,
        "deep",
        ["web_search"],
    )
    # A copy: changing the defaults later leaves the conversation as it is.
    _settings(server, household.token, reasoning="off")
    with server.client(household.token) as client:
        kept = body(client.get(f"/conversations/{conversation['id']}"))
        assert (kept["model"], kept["reasoning"], kept["disabled_tools"]) == (popular, "deep", ["web_search"])
        # What the request gives wins over the defaults.
        created = client.post("/conversations", json={"reasoning": "deep", "disabled_tools": ["run_command"]})
    assert created.status_code == 201, created.text
    assert (body(created)["reasoning"], body(created)["disabled_tools"]) == ("deep", ["run_command"])


@pytest.mark.spec("CNV-013", "MOD-012")
def test_a_default_model_no_longer_offered_gives_way_to_the_tenants(server: Server, household: Household) -> None:
    _settings(server, household.token, model={"connection_id": household.openrouter_id, "model": "test/popular"})
    with server.client(household.model.admin_token) as client:
        assert client.delete(f"/tenant/connections/{household.openrouter_id}").status_code == 204
    conversation = create_conversation(server, household.token)
    assert conversation["model"] == {"connection_id": household.model.connection_id, "model": "test-model"}


@pytest.mark.spec("CNV-013")
@pytest.mark.parametrize("through", ["server", "openrouter"])
def test_the_reasoning_level_reaches_the_model_from_the_next_run(
    server: Server, household: Household, through: str
) -> None:
    conversation = create_conversation(server, household.token)
    if through == "openrouter":
        _choose(server, household.token, conversation["id"], household.openrouter_id, "test/popular")
    efforts: dict[str, str | None] = {}
    for level in ("off", "deep", "on"):
        assert _change(server, household.token, conversation["id"], reasoning=level)["reasoning"] == level
        efforts[level] = _request(
            server, household, conversation["id"], f"{level} {secrets.token_hex(4)}"
        ).reasoning_effort()
    assert (efforts["off"], efforts["deep"]) == ("none", "high")
    # The provider's own default effort, neither off nor deep.
    assert efforts["on"] not in ("none", "high")


@pytest.mark.spec("CNV-013")
def test_a_model_known_not_to_reason_runs_without_reasoning(server: Server, household: Household) -> None:
    conversation = create_conversation(server, household.token)
    _choose(server, household.token, conversation["id"], household.openrouter_id, "test/second")
    _change(server, household.token, conversation["id"], reasoning="deep")
    request = _request(server, household, conversation["id"], f"no reasoning {secrets.token_hex(4)}")
    assert "reasoning" not in request.body
    assert "reasoning_effort" not in request.body


@pytest.mark.spec("CNV-013")
def test_the_models_reasoning_is_streamed_and_kept(server: Server, household: Household) -> None:
    conversation = create_conversation(server, household.token)
    _choose(server, household.token, conversation["id"], household.openrouter_id, "test/popular")
    text = f"think:{secrets.token_hex(4)}"
    run_id, events = start_run(server, household.token, conversation["id"], text)
    assert wait_for_run(server, household.token, run_id)["status"] == "completed"
    reasoning = "".join(str(e.data.get("delta", "")) for e in events if e.type == "REASONING_MESSAGE_CONTENT")
    assert reasoning == f"Thinking: {text.removeprefix('think:')}"
    assert text_of(events) == f"Echo: {text}"
    kept = [m for m in messages(server, household.token, conversation["id"])["items"] if m["role"] == "reasoning"]
    assert [m["content"] for m in kept] == [reasoning]


@pytest.mark.spec("CNV-013")
def test_tools_that_are_off_are_not_offered_to_the_model(server: Server, household: Household) -> None:
    conversation = create_conversation(server, household.token)
    # Every tool has a switch, and is offered while it is on (ADR-0087).
    assert set(_request(server, household, conversation["id"], f"all {secrets.token_hex(4)}").tool_names()) == TOOLS
    for off in (
        ["run_command", "web_search", "ask_user_question", "write_plan"],
        ["write_file", "edit_file", "offer_download", "read_page", "remove_task"],
    ):
        assert _change(server, household.token, conversation["id"], disabled_tools=off)["disabled_tools"] == off
        offered = set(_request(server, household, conversation["id"], f"tools {secrets.token_hex(4)}").tool_names())
        assert offered == TOOLS - set(off)


def _working_instructions_follow(system: str, base: str, additional: str) -> None:
    """The base instructions come first, then the working instructions, then the additional ones."""
    assert system.index(base) < system.index("/workspace") < system.index(additional)


@pytest.mark.spec("CNV-014")
def test_default_instructions_reach_every_conversation_from_its_next_run(server: Server, household: Household) -> None:
    conversation = create_conversation(server, household.token)
    default = _request(server, household, conversation["id"], f"built in {secrets.token_hex(4)}").system_text()
    assert "Mazzamurello" in default
    # Set after the conversation started, and used by it all the same.
    base, additional = f"You are Ada {secrets.token_hex(4)}.", f"Sign as Ada {secrets.token_hex(4)}."
    _settings(server, household.token, base_instructions=base, additional_instructions=additional)
    system = _request(server, household, conversation["id"], f"tailored {secrets.token_hex(4)}").system_text()
    assert "You are Mazzamurello" not in system
    _working_instructions_follow(system, base, additional)
    # Restoring the default brings back the built-in base instructions.
    _settings(server, household.token, additional_instructions=additional)
    system = _request(server, household, conversation["id"], f"restored {secrets.token_hex(4)}").system_text()
    assert base not in system
    _working_instructions_follow(system, "You are Mazzamurello", additional)


@pytest.mark.spec("CNV-014")
def test_the_built_in_base_instructions_come_with_the_defaults(server: Server, household: Household) -> None:
    with server.client(household.token) as client:
        built_in = body(client.get("/me/settings"))["built_in_base_instructions"]
    assert "Mazzamurello" in built_in
    conversation = create_conversation(server, household.token)
    assert built_in in _request(server, household, conversation["id"], f"shown {secrets.token_hex(4)}").system_text()
    # The same when the user replaced them, so a client can show what restoring brings back.
    with server.client(household.token) as client:
        response = client.put("/me/settings", json=NO_DEFAULTS | {"base_instructions": "You are Ada."})
    assert response.status_code == 200, response.text
    assert body(response)["built_in_base_instructions"] == built_in


@pytest.mark.spec("CNV-014")
def test_a_conversations_own_instructions_win_until_restored(server: Server, household: Household) -> None:
    default = f"Sign as Ada {secrets.token_hex(4)}."
    _settings(server, household.token, additional_instructions=default)
    conversation = create_conversation(server, household.token)
    base, own = f"You are Bea {secrets.token_hex(4)}.", f"Sign as Bea {secrets.token_hex(4)}."
    changed = _change(server, household.token, conversation["id"], base_instructions=base, additional_instructions=own)
    assert (changed["base_instructions"], changed["additional_instructions"]) == (base, own)
    system = _request(server, household, conversation["id"], f"own {secrets.token_hex(4)}").system_text()
    assert default not in system
    _working_instructions_follow(system, base, own)
    # An empty text is a choice of nothing; the base instructions come back with null.
    _change(server, household.token, conversation["id"], base_instructions=None, additional_instructions="")
    system = _request(server, household, conversation["id"], f"none {secrets.token_hex(4)}").system_text()
    assert base not in system
    assert own not in system
    assert default not in system
    assert "You are Mazzamurello" in system


@pytest.mark.spec("CNV-014")
def test_the_working_instructions_describe_only_the_enabled_tools(server: Server, household: Household) -> None:
    conversation = create_conversation(server, household.token)
    _settings(server, household.token, base_instructions="Say nothing of tools.")
    system = _request(server, household, conversation["id"], f"all tools {secrets.token_hex(4)}").system_text()
    for phrase in ("/workspace", "pdftotext", "offer_download"):
        assert phrase in system, f"the working instructions lost {phrase}"
    for phrase in ("ask_user_question", "write_plan"):
        assert phrase in system, f"the instructions of the harness lost {phrase}"
    off = ["run_command", "start_command", "offer_download", "ask_user_question", "add_task"]
    _change(server, household.token, conversation["id"], disabled_tools=off)
    system = _request(server, household, conversation["id"], f"fewer tools {secrets.token_hex(4)}").system_text()
    assert "pdftotext" not in system, "the toolbox is described without commands to run it"
    assert "offer_download" not in system
    assert "ask_user_question" not in system
    assert "write_plan" not in system, "the task list is described without all of its tools"
    assert "/workspace" in system, "the workspace is described while its file tools are on"
