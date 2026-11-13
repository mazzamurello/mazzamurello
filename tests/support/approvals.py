"""Approval requests, and how tests answer them (AGT-004, AGT-006, AGT-007, AGT-012, ADR-0090).

The model the tests serve calls a tool by name when the user's message is
`tool:<name> <arguments>` (tests/support/model.py). Searches reach the search
service the tests serve, whose results are untrusted content.
"""

from __future__ import annotations

import json
import secrets
from typing import Any

import httpx

from tests.support.accounts import body
from tests.support.database import uuid7
from tests.support.runs import Event, create_conversation, parse_events, start_run, wait_for_run
from tests.support.server import Server

# The classes and approval defaults of ADR-0090.
DECLARED: dict[str, tuple[set[str], str]] = {
    "web_search": ({"ingests_untrusted", "external_communication"}, "allow"),
    "read_page": ({"ingests_untrusted", "external_communication"}, "allow"),
    "run_command": ({"reads_private_data", "ingests_untrusted", "external_communication"}, "allow"),
    "start_command": ({"reads_private_data", "ingests_untrusted", "external_communication"}, "allow"),
    **{
        name: ({"reads_private_data", "ingests_untrusted"}, "allow")
        for name in (
            "check_command",
            "read_file",
            "list_directory",
            "find_files",
            "search_files",
            "file_info",
            "read_tool_result",
        )
    },
    **{
        name: ({"reads_private_data"}, "allow")
        for name in ("stop_command", "write_file", "edit_file", "create_directory", "offer_download")
    },
    **{
        name: (set[str](), "allow")
        for name in (
            "ask_user_question",
            "write_plan",
            "read_plan",
            "add_task",
            "update_task_status",
            "update_task_statuses",
            "remove_task",
        )
    },
}


def search(query: str) -> str:
    return f"tool:web_search {json.dumps({'query': query})}"


def fresh_query(label: str = "query") -> str:
    return f"{label} {secrets.token_hex(4)}"


def interrupts(events: list[Event]) -> list[dict[str, Any]]:
    """The interrupts the run finished with; none when it finished otherwise."""
    (finished,) = [event for event in events if event.type == "RUN_FINISHED"]
    outcome: dict[str, Any] = finished.data.get("outcome") or {}
    found: list[dict[str, Any]] = outcome.get("interrupts", [])
    return found if outcome.get("type") == "interrupt" else []


def approval_of(events: list[Event]) -> dict[str, Any]:
    """The one approval request the run ended with."""
    (interrupt,) = interrupts(events)
    assert interrupt["reason"] == "approval", interrupt
    return interrupt


def approve(interrupt_id: str, scope: str = "once") -> dict[str, Any]:
    return {"interruptId": interrupt_id, "status": "resolved", "payload": {"approved": True, "scope": scope}}


def deny(interrupt_id: str) -> dict[str, Any]:
    return {"interruptId": interrupt_id, "status": "resolved", "payload": {"approved": False}}


def resume(server: Server, token: str, conversation_id: str, entries: list[dict[str, Any]]) -> httpx.Response:
    """Answer the pending interrupts: the response, streamed in full."""
    payload = {"threadId": conversation_id, "runId": str(uuid7()), "messages": [], "resume": entries}
    with server.client(token) as client:
        return client.post(f"/conversations/{conversation_id}/runs", json=payload, timeout=60)


def resumed(server: Server, token: str, conversation_id: str, entries: list[dict[str, Any]]) -> list[Event]:
    """Answer the pending interrupts, and wait for the run that continues: its events."""
    response = resume(server, token, conversation_id, entries)
    assert response.status_code == 200, response.text
    events = parse_events(response.text.splitlines())
    wait_for_run(server, token, events[0].data["runId"])
    return events


def conversation_of(server: Server, token: str, conversation_id: str) -> dict[str, Any]:
    with server.client(token) as client:
        return body(client.get(f"/conversations/{conversation_id}"))


def completed(server: Server, token: str, conversation_id: str, text: str) -> list[Event]:
    """Run `text`, which needs no approval, to completion: its events."""
    run_id, events = start_run(server, token, conversation_id, text)
    assert wait_for_run(server, token, run_id)["status"] == "completed", interrupts(events)
    return events


def with_untrusted_content(server: Server, token: str) -> str:
    """A new conversation whose first turn searched the web: it has untrusted content from then on."""
    conversation_id = create_conversation(server, token)["id"]
    completed(server, token, conversation_id, search(fresh_query("first")))
    return conversation_id


def asked(server: Server, token: str, conversation_id: str, text: str) -> tuple[str, dict[str, Any]]:
    """Run `text`, which ends asking for approval: the run and its request."""
    run_id, events = start_run(server, token, conversation_id, text)
    # Its status follows its last event.
    assert wait_for_run(server, token, run_id)["status"] == "interrupted"
    return run_id, approval_of(events)


def activity(server: Server, token: str, **params: str) -> list[dict[str, Any]]:
    with server.client(token) as client:
        response = client.get("/me/activity", params=params)
    assert response.status_code == 200, response.text
    items: list[dict[str, Any]] = body(response)["items"]
    return items


def approving(server: Server, token: str, conversation_id: str, text: str) -> tuple[str, list[Event], str]:
    """Run `text`, approving for the turn every request it makes (ADR-0090): its first run, every event, its last run.

    For tests of other things that need more than one command or search in a conversation, which,
    from the second on, ask for approval.
    """
    run_id, events = start_run(server, token, conversation_id, text)
    seen = list(events)
    last = run_id
    while wait_for_run(server, token, last)["status"] == "interrupted":
        pending = [interrupt["id"] for interrupt in interrupts(events) if interrupt["reason"] == "approval"]
        assert pending, "the run asks a question, not for approval"
        events = resumed(server, token, conversation_id, [approve(interrupt_id, "turn") for interrupt_id in pending])
        seen += events
        last = events[0].data["runId"]
    return run_id, seen, last
