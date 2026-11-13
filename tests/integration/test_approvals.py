"""Approvals: the lethal trifecta rule, what an approval covers, and requests that expire (AGT-004, AGT-006,
AGT-007, AGT-008, AGT-012, ADR-0033, ADR-0090).

The model the tests serve calls a tool by name when the user's message is
`tool:<name> <arguments>`, and several tools in turn with `chain:`
(tests/support/model.py). Searches reach the search service the tests serve,
whose results are untrusted content: after the first one, the conversation
has untrusted content, and the web and command tools ask.
"""

from __future__ import annotations

import datetime
import json
import time
from typing import Any

import pytest

from tests.support.accounts import Account, assert_problem, body, create_account, create_tenant, login
from tests.support.approvals import (
    activity,
    approve,
    asked,
    completed,
    conversation_of,
    deny,
    fresh_query,
    interrupts,
    resume,
    resumed,
    search,
    with_untrusted_content,
)
from tests.support.database import Database
from tests.support.fixtures import HarnessModel
from tests.support.runs import create_conversation, get_run, run_input, text_of, wait_for_run
from tests.support.search import SearchServer
from tests.support.server import Server

ALL_SCOPES = ["once", "turn", "conversation"]


@pytest.fixture
def account(database: Database) -> Account:
    return create_account(database, create_tenant(database))


@pytest.fixture
def token(server: Server, account: Account, default_model: HarnessModel) -> str:
    default_model.connect(account.tenant_id)
    return login(server, account)


@pytest.mark.spec("AGT-004", "AGT-007")
def test_untrusted_content_makes_the_web_ask_until_approved(
    server: Server, token: str, default_model: HarnessModel, search_service: SearchServer
) -> None:
    conversation_id = create_conversation(server, token)["id"]
    # Nothing untrusted yet: the first search runs without asking.
    first = fresh_query("first")
    assert interrupts(completed(server, token, conversation_id, search(first))) == []
    assert search_service.queries().count(first) == 1
    # Its results are now part of the conversation: the next search asks.
    second = fresh_query("second")
    before = datetime.datetime.now(datetime.UTC)
    run_id, interrupt = asked(server, token, conversation_id, search(second))
    assert interrupt["id"] == f"apr-{interrupt['toolCallId']}"
    expires = datetime.datetime.fromisoformat(interrupt["expiresAt"])
    assert datetime.timedelta(hours=23, minutes=59) < expires - before < datetime.timedelta(hours=24, minutes=1)
    request = interrupt["metadata"]["approval"]
    assert request["tool"] == "web_search"
    assert request["arguments"] == {"query": second}
    assert second in request["data"]
    assert request["action"].strip()
    assert request["destination"].strip()
    assert request["reason"] == "untrusted_content"
    assert request["scopes"] == ALL_SCOPES
    # Nothing ran: the query has not left.
    assert search_service.queries().count(second) == 0
    # The conversation keeps the request, and takes nothing else until it is answered.
    assert conversation_of(server, token, conversation_id)["interrupts"] == [interrupt]
    with server.client(token) as client:
        another = client.post(f"/conversations/{conversation_id}/runs", json=run_input(conversation_id, "hello"))
    assert_problem(another, 409, "run.interrupt_pending")
    # Approved once: the call runs, and the run goes on.
    events = resumed(server, token, conversation_id, [approve(interrupt["id"])])
    run = get_run(server, token, events[0].data["runId"])
    assert (run["kind"], run["parent_run_id"], run["status"]) == ("resume", run_id, "completed")
    assert search_service.queries().count(second) == 1
    assert text_of(events).startswith("Tool said:")
    assert conversation_of(server, token, conversation_id)["interrupts"] == []
    # Once covered only that call: the next turn asks again.
    asked(server, token, conversation_id, search(fresh_query("third")))


@pytest.mark.spec("AGT-007")
@pytest.mark.parametrize("how", ["denied", "cancelled"])
def test_a_denied_call_does_not_run_and_the_model_is_told(
    server: Server, token: str, default_model: HarnessModel, search_service: SearchServer, how: str
) -> None:
    conversation_id = with_untrusted_content(server, token)
    query = fresh_query("denied")
    text = search(query)
    _, interrupt = asked(server, token, conversation_id, text)
    entry = deny(interrupt["id"]) if how == "denied" else {"interruptId": interrupt["id"], "status": "cancelled"}
    events = resumed(server, token, conversation_id, [entry])
    assert get_run(server, token, events[0].data["runId"])["status"] == "completed"
    assert search_service.queries().count(query) == 0
    results = [
        str(message.get("content", ""))
        for request in default_model.endpoint.requests_with(text)
        for message in request.body.get("messages", [])
        if message.get("role") == "tool"
    ]
    assert any("denied" in result.lower() for result in results), results


@pytest.mark.spec("AGT-004", "AGT-006")
def test_the_web_and_commands_are_allowed_in_a_conversation_until_withdrawn(
    server: Server, token: str, default_model: HarnessModel, search_service: SearchServer
) -> None:
    conversation_id = with_untrusted_content(server, token)
    assert conversation_of(server, token, conversation_id)["allowances"] == {"web_and_commands": False, "tools": []}
    run_id, interrupt = asked(server, token, conversation_id, search(fresh_query()))
    resumed(server, token, conversation_id, [approve(interrupt["id"], "conversation")])
    conversation = conversation_of(server, token, conversation_id)
    assert conversation["allowances"] == {"web_and_commands": True, "tools": []}
    # Later turns no longer ask: neither a search nor a page.
    later = fresh_query("later")
    completed(server, token, conversation_id, search(later))
    assert search_service.queries().count(later) == 1
    completed(server, token, conversation_id, 'tool:read_page {"url": "ftp://example.org/file"}')
    # A fork does not copy what was allowed, and no setting can allow it.
    with server.client(token) as client:
        response = client.post(f"/conversations/{conversation_id}/fork", json={"run_id": run_id})
        assert response.status_code == 201, response.text
        fork = body(response)
        assert fork["allowances"] == {"web_and_commands": False, "tools": []}
        added = client.patch(
            f"/conversations/{fork['id']}", json={"allowances": {"web_and_commands": True, "tools": []}}
        )
        assert_problem(added, 422, "request.validation_failed")
        # Its user withdraws it, and the web asks again.
        withdrawn = client.patch(
            f"/conversations/{conversation_id}", json={"allowances": {"web_and_commands": False, "tools": []}}
        )
        assert withdrawn.status_code == 200, withdrawn.text
        assert body(withdrawn)["allowances"] == {"web_and_commands": False, "tools": []}
    asked(server, token, conversation_id, search(fresh_query("again")))


@pytest.mark.spec("AGT-004")
def test_one_approval_covers_the_web_and_commands_for_the_rest_of_the_turn(
    server: Server, token: str, default_model: HarnessModel, search_service: SearchServer
) -> None:
    conversation_id = with_untrusted_content(server, token)
    first, second = fresh_query("one"), fresh_query("two")
    chain = (
        f"chain:web_search {json.dumps({'query': first})}"
        f" >>> web_search {json.dumps({'query': second})}"
        ' >>> read_page {"url": "ftp://example.org/file"}'
    )
    _, interrupt = asked(server, token, conversation_id, chain)
    assert interrupt["metadata"]["approval"]["arguments"] == {"query": first}
    events = resumed(server, token, conversation_id, [approve(interrupt["id"], "turn")])
    # The second search and the page needed no other approval.
    assert get_run(server, token, events[0].data["runId"])["status"] == "completed"
    assert interrupts(events) == []
    assert (search_service.queries().count(first), search_service.queries().count(second)) == (1, 1)
    # The turn is over: nothing is allowed in the conversation, and the next turn asks.
    assert conversation_of(server, token, conversation_id)["allowances"] == {"web_and_commands": False, "tools": []}
    asked(server, token, conversation_id, search(fresh_query("next turn")))


@pytest.mark.spec("AGT-012")
def test_answers_must_fit_the_stored_request(server: Server, token: str, default_model: HarnessModel) -> None:
    conversation_id = with_untrusted_content(server, token)
    _, interrupt = asked(server, token, conversation_id, search(fresh_query()))
    wrong: list[list[dict[str, Any]]] = [
        [approve("apr-unknown")],
        [approve(interrupt["id"], "forever")],
        [{"interruptId": interrupt["id"], "status": "resolved", "payload": {"approved": True}}],
        [{"interruptId": interrupt["id"], "status": "resolved", "payload": {}}],
        [approve(interrupt["id"]), approve("apr-unknown")],
        [],
    ]
    for entries in wrong:
        assert_problem(resume(server, token, conversation_id, entries), 422, "approval.invalid")
    resumed(server, token, conversation_id, [approve(interrupt["id"])])
    # Once resolved, the same answer is refused.
    assert_problem(resume(server, token, conversation_id, [approve(interrupt["id"])]), 422, "approval.invalid")


@pytest.mark.spec("AGT-012", "AGT-007")
def test_an_expired_request_cannot_be_approved(
    database: Database, server: Server, token: str, default_model: HarnessModel, search_service: SearchServer
) -> None:
    conversation_id = with_untrusted_content(server, token)
    query = fresh_query("expired")
    _, interrupt = asked(server, token, conversation_id, search(query))
    with database.superuser() as conn:
        conn.execute(
            "UPDATE conversations SET approvals_expire_at = now() - interval '1 second' WHERE id = %s",
            (conversation_id,),
        )
    # Whether the sweep has denied it yet or not, it is no longer pending.
    assert_problem(resume(server, token, conversation_id, [approve(interrupt["id"])]), 422, "approval.invalid")
    assert search_service.queries().count(query) == 0


@pytest.mark.spec("AGT-007", "AGT-008")
def test_an_unanswered_request_is_denied_when_it_expires(
    database: Database, server: Server, token: str, default_model: HarnessModel, search_service: SearchServer
) -> None:
    conversation_id = with_untrusted_content(server, token)
    query = fresh_query("unanswered")
    text = search(query)
    run_id, interrupt = asked(server, token, conversation_id, text)
    with database.superuser() as conn:
        conn.execute(
            "UPDATE conversations SET approvals_expire_at = now() - interval '1 second' WHERE id = %s",
            (conversation_id,),
        )
    # The worker's sweep resumes the conversation, with the call denied.
    deadline = time.monotonic() + 20
    conversation = conversation_of(server, token, conversation_id)
    while conversation["active_run_id"] == run_id and time.monotonic() < deadline:
        time.sleep(0.2)
        conversation = conversation_of(server, token, conversation_id)
    run = wait_for_run(server, token, conversation["active_run_id"])
    assert (run["kind"], run["parent_run_id"], run["status"]) == ("resume", run_id, "completed")
    assert conversation_of(server, token, conversation_id)["interrupts"] == []
    assert search_service.queries().count(query) == 0
    results = [
        str(message.get("content", ""))
        for request in default_model.endpoint.requests_with(text)
        for message in request.body.get("messages", [])
        if message.get("role") == "tool"
    ]
    assert any("denied" in result.lower() for result in results), results
    (event,) = [e for e in activity(server, token, conversation_id=conversation_id) if e["run_id"] == run_id]
    assert (event["outcome"], event["reason"], event["scope"]) == ("expired", "untrusted_content", None)
    assert event["tool_call_id"] == interrupt["toolCallId"]


@pytest.mark.spec("AGT-008")
def test_every_tool_call_leaves_an_audit_event_without_its_content(
    server: Server, token: str, default_model: HarnessModel
) -> None:
    conversation_id = create_conversation(server, token, title="Audited")["id"]
    first, second, third = fresh_query("free"), fresh_query("approved"), fresh_query("denied")
    completed(server, token, conversation_id, search(first))
    _, approved = asked(server, token, conversation_id, search(second))
    resumed(server, token, conversation_id, [approve(approved["id"])])
    _, denied = asked(server, token, conversation_id, search(third))
    resumed(server, token, conversation_id, [deny(denied["id"])])
    with server.client(token) as client:
        response = client.get("/me/activity", params={"conversation_id": conversation_id})
    assert response.status_code == 200, response.text
    # Content-free: neither the queries nor the results.
    for query in (first, second, third):
        assert query not in response.text
    events = body(response)["items"]
    # Newest first.
    assert [(e["tool"], e["outcome"], e["scope"], e["reason"]) for e in events] == [
        ("web_search", "denied", None, "untrusted_content"),
        ("web_search", "approved", "once", "untrusted_content"),
        ("web_search", "not_needed", None, None),
    ]
    assert all(e["conversation_id"] == conversation_id for e in events)
    assert all(e["conversation_title"] == "Audited" for e in events)
    assert not any(e["repeated"] for e in events)
    assert [e["tool_call_id"] for e in events[:2]] == [denied["toolCallId"], approved["toolCallId"]]
    # The history says, on each call, how it was decided (UX-023).
    with server.client(token) as client:
        page = body(client.get(f"/conversations/{conversation_id}/messages"))
    decided = {
        item["tool_call_id"]: (item["outcome"], item["scope"], item["reason"])
        for run in page["runs"]
        for item in run["approvals"]
    }
    assert decided[approved["toolCallId"]] == ("approved", "once", "untrusted_content")
    assert decided[denied["toolCallId"]] == ("denied", None, "untrusted_content")
    # Filtered by tool, and kept once the conversation is deleted.
    assert activity(server, token, tool="read_page", conversation_id=conversation_id) == []
    with server.client(token) as client:
        assert client.delete(f"/conversations/{conversation_id}").status_code == 204
    kept = activity(server, token, conversation_id=conversation_id)
    assert [e["id"] for e in kept] == [e["id"] for e in events]
    assert all(e["conversation_title"] is None for e in kept)


@pytest.mark.spec("AGT-008", "TEN-006")
def test_audit_events_are_visible_only_to_the_user_they_acted_for(
    database: Database, server: Server, token: str, account: Account, default_model: HarnessModel
) -> None:
    conversation_id = create_conversation(server, token)["id"]
    completed(server, token, conversation_id, search(fresh_query()))
    assert activity(server, token, conversation_id=conversation_id)
    # Not to another member of the household, nor to its admin.
    for role in ("member", "tenant_admin"):
        other = login(server, create_account(database, account.tenant_id, role))
        assert activity(server, other, conversation_id=conversation_id) == []
