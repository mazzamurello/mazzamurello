"""Conversations and runs through the API: AG-UI inputs and Server-Sent Events (ADR-0032)."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from typing import Any, cast

import httpx

from tests.support.accounts import body
from tests.support.contract import check_event
from tests.support.database import uuid7
from tests.support.server import Server

RUN_TIMEOUT_SECONDS = 60
FINAL_STATUSES = frozenset({"completed", "failed", "cancelled", "interrupted"})


@dataclass(frozen=True)
class Event:
    """One SSE message: its `id` (the sequence number), `event` and JSON `data`."""

    seq: int
    type: str
    data: dict[str, Any]


def parse_events(lines: list[str]) -> list[Event]:
    events: list[Event] = []
    fields: dict[str, str] = {}
    for line in [*lines, ""]:
        if line == "":
            if "data" in fields:
                data = cast(dict[str, Any], json.loads(fields["data"]))
                check_event(data, f"event {fields.get('id')} ({fields.get('event', '')})")
                events.append(Event(int(fields["id"]), fields.get("event", ""), data))
            fields = {}
        elif not line.startswith(":"):
            name, _, value = line.partition(":")
            fields[name] = fields.get(name, "") + value.removeprefix(" ")
    return events


def _read(response: httpx.Response, stop_after: int | None) -> list[Event]:
    assert response.status_code == 200, response.read().decode()
    assert response.headers["content-type"].startswith("text/event-stream")
    lines: list[str] = []
    for line in response.iter_lines():
        lines.append(line)
        if stop_after is not None and line == "" and len(parse_events(lines)) >= stop_after:
            break
    return parse_events(lines)


def create_conversation(server: Server, token: str, title: str | None = None) -> dict[str, Any]:
    with server.client(token) as client:
        response = client.post("/conversations", json={} if title is None else {"title": title})
    assert response.status_code == 201, response.text
    return body(response)


def run_input(
    conversation_id: str, text: str, run_id: uuid.UUID | None = None, parent_run_id: str | None = None
) -> dict[str, Any]:
    """A minimal AG-UI `RunAgentInput` with one user message."""
    payload: dict[str, Any] = {
        "threadId": conversation_id,
        "runId": str(run_id or uuid7()),
        "messages": [{"id": str(uuid7()), "role": "user", "content": text}],
    }
    if parent_run_id is not None:
        payload["parentRunId"] = parent_run_id
    return payload


def start_run(
    server: Server,
    token: str,
    conversation_id: str,
    text: str,
    *,
    run_id: uuid.UUID | None = None,
    parent_run_id: str | None = None,
    stop_after: int | None = None,
) -> tuple[str, list[Event]]:
    """Start a run and read its events, until the stream ends or `stop_after` events arrived."""
    payload = run_input(conversation_id, text, run_id, parent_run_id)
    with (
        server.client(token) as client,
        client.stream(
            "POST", f"/conversations/{conversation_id}/runs", json=payload, timeout=RUN_TIMEOUT_SECONDS
        ) as response,
    ):
        return payload["runId"], _read(response, stop_after)


def replay(
    server: Server, token: str, run_id: str, *, after: int | None = None, last_event_id: int | None = None
) -> list[Event]:
    headers = {} if last_event_id is None else {"Last-Event-ID": str(last_event_id)}
    params = {} if after is None else {"after": after}
    with (
        server.client(token) as client,
        client.stream(
            "GET", f"/runs/{run_id}/events", headers=headers, params=params, timeout=RUN_TIMEOUT_SECONDS
        ) as response,
    ):
        return _read(response, None)


def get_run(server: Server, token: str, run_id: str) -> dict[str, Any]:
    with server.client(token) as client:
        response = client.get(f"/runs/{run_id}")
    assert response.status_code == 200, response.text
    return body(response)


def wait_for_run(server: Server, token: str, run_id: str, timeout: float = RUN_TIMEOUT_SECONDS) -> dict[str, Any]:
    """The run, once it has reached a final status."""
    deadline = time.monotonic() + timeout
    while True:
        run = get_run(server, token, run_id)
        if run["status"] in FINAL_STATUSES or time.monotonic() > deadline:
            return run
        time.sleep(0.2)


def messages(server: Server, token: str, conversation_id: str, **params: str) -> dict[str, Any]:
    with server.client(token) as client:
        response = client.get(f"/conversations/{conversation_id}/messages", params=params)
    assert response.status_code == 200, response.text
    return body(response)


def text_of(events: list[Event]) -> str:
    """The text of the assistant's messages in a run's events."""
    return "".join(str(event.data.get("delta", "")) for event in events if event.type == "TEXT_MESSAGE_CONTENT")
