"""Tool permissions: what a household's admin allows, asks or denies to each user (AGT-002, AGT-005, AGT-006,
CNV-013, ADR-0090).

The model the tests serve answers `No tool <name>` when the request does not
offer the tool it is asked to call (tests/support/model.py).
"""

from __future__ import annotations

import json
import secrets
from typing import Any

import pytest

from tests.support.accounts import Account, assert_problem, body, create_account, create_tenant, login
from tests.support.approvals import (
    DECLARED,
    approve,
    asked,
    completed,
    conversation_of,
    fresh_query,
    resumed,
    search,
    with_untrusted_content,
)
from tests.support.contract import contract
from tests.support.database import Database, uuid7
from tests.support.fixtures import HarnessModel
from tests.support.runs import create_conversation, start_run, text_of, wait_for_run
from tests.support.server import Server

WEB_AND_COMMANDS = {"web_search", "read_page", "run_command", "start_command"}


@pytest.fixture
def household(database: Database, server: Server, default_model: HarnessModel) -> tuple[str, Account, str]:
    """A household's admin, signed in, and one of its members, signed in."""
    tenant_id = create_tenant(database)
    default_model.connect(tenant_id)
    admin = create_account(database, tenant_id, "tenant_admin")
    member = create_account(database, tenant_id)
    return login(server, admin), member, login(server, member)


def set_permissions(server: Server, admin_token: str, user: Account, **permissions: dict[str, str]) -> dict[str, Any]:
    with server.client(admin_token) as client:
        response = client.put(
            f"/tenant/users/{user.id}/tool-permissions",
            json={"tools": permissions.get("tools", {}), "classes": permissions.get("classes", {})},
        )
    assert response.status_code == 200, response.text
    return body(response)


def tools_of(server: Server, token: str) -> dict[str, dict[str, Any]]:
    with server.client(token) as client:
        response = client.get("/tools")
    assert response.status_code == 200, response.text
    return {item["name"]: item for item in body(response)["items"]}


def offered(server: Server, token: str, model: HarnessModel) -> set[str]:
    """The tools the model is offered in a new conversation of the user."""
    marker = f"offered {uuid7()}"
    run_id, _ = start_run(server, token, create_conversation(server, token)["id"], marker)
    wait_for_run(server, token, run_id)
    (request,) = model.endpoint.requests_with(marker)
    return request.tool_names()


@pytest.mark.spec("AGT-002")
def test_only_a_tenant_admin_sets_a_users_tool_permissions(
    database: Database, server: Server, household: tuple[str, Account, str]
) -> None:
    admin_token, member, member_token = household
    with server.client(admin_token) as client:
        response = client.get(f"/tenant/users/{member.id}/tool-permissions")
        assert response.status_code == 200, response.text
        assert body(response) == {"tools": {}, "classes": {}}
    stored = set_permissions(
        server, admin_token, member, tools={"web_search": "deny"}, classes={"external_communication": "ask"}
    )
    assert stored == {"tools": {"web_search": "deny"}, "classes": {"external_communication": "ask"}}
    with server.client(admin_token) as client:
        assert body(client.get(f"/tenant/users/{member.id}/tool-permissions")) == stored
        for wrong in (
            {"tools": {"no_such_tool": "deny"}, "classes": {}},
            {"tools": {}, "classes": {"no_such_class": "deny"}},
            {"tools": {"web_search": "maybe"}, "classes": {}},
        ):
            assert_problem(
                client.put(f"/tenant/users/{member.id}/tool-permissions", json=wrong), 422, "request.validation_failed"
            )
    # A member reads and sets no one's, not even their own.
    with server.client(member_token) as client:
        assert_problem(client.get(f"/tenant/users/{member.id}/tool-permissions"), 403, "permission.denied")
        assert_problem(
            client.put(f"/tenant/users/{member.id}/tool-permissions", json={"tools": {}, "classes": {}}),
            403,
            "permission.denied",
        )
    # Another household's admin does not find the user.
    stranger = login(server, create_account(database, create_tenant(database), "tenant_admin"))
    with server.client(stranger) as client:
        assert_problem(client.get(f"/tenant/users/{member.id}/tool-permissions"), 404, "resource.not_found")


@pytest.mark.spec("AGT-005", "AGT-006", "CNV-013")
def test_every_tool_is_listed_with_its_classes_and_approval_default(
    server: Server, household: tuple[str, Account, str]
) -> None:
    _, _, member_token = household
    with server.client(member_token) as client:
        items = body(client.get("/tools"))["items"]
    names: list[str] = contract()["components"]["schemas"]["ToolName"]["enum"]
    assert [item["name"] for item in items] == names
    for item in items:
        classes, default = DECLARED[item["name"]]
        assert (set(item["classes"]), item["approval_default"]) == (classes, default), item
        assert (item["effective"], item["permission"]) == (default, None)


@pytest.mark.spec("AGT-002", "CNV-013")
def test_a_denied_tool_is_never_offered_to_the_model(
    server: Server, household: tuple[str, Account, str], default_model: HarnessModel
) -> None:
    admin_token, member, member_token = household
    set_permissions(server, admin_token, member, tools={"web_search": "deny"})
    tools = tools_of(server, member_token)
    assert (tools["web_search"]["effective"], tools["web_search"]["permission"]) == (
        "deny",
        {"setting": "deny", "subject": "web_search"},
    )
    assert "web_search" not in offered(server, member_token, default_model)
    # Asked for it, the model does not have it.
    conversation_id = create_conversation(server, member_token)["id"]
    events = completed(server, member_token, conversation_id, search(fresh_query()))
    assert text_of(events) == "No tool web_search"
    # The user's own settings cannot switch it back on.
    with server.client(member_token) as client:
        response = client.patch(f"/conversations/{conversation_id}", json={"disabled_tools": []})
        assert response.status_code == 200, response.text
    assert "web_search" not in offered(server, member_token, default_model)


@pytest.mark.spec("AGT-002")
def test_a_tools_setting_wins_over_its_classes_and_the_strictest_class_wins(
    server: Server, household: tuple[str, Account, str], default_model: HarnessModel
) -> None:
    admin_token, member, member_token = household
    set_permissions(server, admin_token, member, classes={"external_communication": "deny"})
    assert not WEB_AND_COMMANDS & offered(server, member_token, default_model)
    assert "read_file" in offered(server, member_token, default_model)
    set_permissions(
        server, admin_token, member, tools={"web_search": "allow"}, classes={"external_communication": "deny"}
    )
    tools = tools_of(server, member_token)
    assert tools["web_search"]["effective"] == "allow"
    assert tools["read_page"]["permission"] == {"setting": "deny", "subject": "external_communication"}
    assert "web_search" in offered(server, member_token, default_model)
    assert "read_page" not in offered(server, member_token, default_model)
    set_permissions(
        server, admin_token, member, classes={"external_communication": "allow", "ingests_untrusted": "ask"}
    )
    tools = tools_of(server, member_token)
    assert tools["web_search"]["effective"] == "ask"
    assert tools["web_search"]["permission"] == {"setting": "ask", "subject": "ingests_untrusted"}
    assert tools["write_file"]["effective"] == "allow"


@pytest.mark.spec("AGT-002", "AGT-006")
def test_an_asked_tool_asks_on_every_call_unless_allowed_in_the_conversation(
    server: Server, household: tuple[str, Account, str], default_model: HarnessModel
) -> None:
    admin_token, member, member_token = household
    set_permissions(server, admin_token, member, tools={"web_search": "ask"})
    conversation_id = create_conversation(server, member_token)["id"]
    # Asked even without untrusted content, for its permission; not for a turn.
    _, interrupt = asked(server, member_token, conversation_id, search(fresh_query()))
    request = interrupt["metadata"]["approval"]
    assert (request["reason"], request["scopes"]) == ("permission", ["once", "conversation"])
    resumed(server, member_token, conversation_id, [approve(interrupt["id"], "conversation")])
    assert conversation_of(server, member_token, conversation_id)["allowances"] == {
        "web_and_commands": False,
        "tools": ["web_search"],
    }
    # Its permission is satisfied in this conversation, but the trifecta rule still asks.
    _, interrupt = asked(server, member_token, conversation_id, search(fresh_query("after")))
    assert interrupt["metadata"]["approval"]["reason"] == "untrusted_content"


@pytest.mark.spec("AGT-002", "AGT-004")
def test_an_allowed_tool_still_asks_after_untrusted_content(
    server: Server, household: tuple[str, Account, str], default_model: HarnessModel
) -> None:
    admin_token, member, member_token = household
    set_permissions(server, admin_token, member, tools={"web_search": "allow", "read_page": "allow"})
    conversation_id = with_untrusted_content(server, member_token)
    _, interrupt = asked(server, member_token, conversation_id, search(fresh_query()))
    assert interrupt["metadata"]["approval"]["reason"] == "untrusted_content"


@pytest.mark.spec("AGT-002")
def test_permissions_apply_from_the_next_run(
    server: Server, household: tuple[str, Account, str], default_model: HarnessModel
) -> None:
    admin_token, member, member_token = household
    conversation_id = create_conversation(server, member_token)["id"]
    marker = f"before {secrets.token_hex(4)}"
    completed(server, member_token, conversation_id, marker)
    set_permissions(server, admin_token, member, tools={"web_search": "deny"})
    after = f"tool:web_search {json.dumps({'query': 'x'})}"
    events = completed(server, member_token, conversation_id, after)
    assert text_of(events) == "No tool web_search"
