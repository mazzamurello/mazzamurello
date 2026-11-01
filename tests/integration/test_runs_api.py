"""Runs through the API: AG-UI events over SSE, durable execution, history and the cost ledger.

API-004, AGT-009, AGT-010, CNV-002, CNV-003, MOD-001, MOD-002, MOD-005,
MOD-006 and TEN-009, as in ADR-0032, ADR-0034, ADR-0037 and ADR-0052. The
model is the one the tests serve (specs/contracts/test-harness.md).
"""

from __future__ import annotations

import time
import urllib.parse
from decimal import Decimal

import pytest

from tests.support.accounts import Account, assert_problem, body, create_account, create_tenant, login
from tests.support.database import Database, uuid7
from tests.support.fixtures import HarnessModel
from tests.support.model import COMPLETION_TOKENS, PROMPT_TOKENS
from tests.support.runs import (
    create_conversation,
    get_run,
    messages,
    replay,
    run_input,
    start_run,
    text_of,
    wait_for_run,
)
from tests.support.server import Server

LIFECYCLE = {"RUN_STARTED", "RUN_FINISHED", "RUN_ERROR"}


@pytest.fixture
def account(database: Database) -> Account:
    return create_account(database, create_tenant(database))


@pytest.fixture
def token(server: Server, account: Account, default_model: HarnessModel) -> str:
    return login(server, account)


def _endpoint_host(model: HarnessModel) -> str:
    return urllib.parse.urlsplit(model.endpoint.url).netloc


@pytest.mark.spec("API-004", "AGT-009")
def test_a_run_streams_ag_ui_events_with_sequence_numbers(server: Server, token: str) -> None:
    conversation = create_conversation(server, token)
    run_id, events = start_run(server, token, conversation["id"], "hello")
    assert [event.seq for event in events] == list(range(1, len(events) + 1))
    assert events[0].type == "RUN_STARTED"
    assert (events[0].data["threadId"], events[0].data["runId"]) == (conversation["id"], run_id)
    assert events[-1].type == "RUN_FINISHED"
    assert all(event.type == event.data["type"] for event in events)
    assert {"TEXT_MESSAGE_START", "TEXT_MESSAGE_CONTENT", "TEXT_MESSAGE_END"} <= {event.type for event in events}
    assert text_of(events) == "Echo: hello"


@pytest.mark.spec("API-004", "AGT-009", "MOD-005")
def test_a_finished_run_records_its_outcome(server: Server, token: str, default_model: HarnessModel) -> None:
    conversation = create_conversation(server, token)
    run_id, events = start_run(server, token, conversation["id"], "hello")
    run = wait_for_run(server, token, run_id)
    assert run["status"] == "completed"
    assert (run["id"], run["conversation_id"], run["parent_run_id"], run["kind"]) == (
        run_id,
        conversation["id"],
        None,
        "message",
    )
    assert run["error_code"] is None
    assert run["model"] == {"provider": _endpoint_host(default_model), "model": "test-model"}
    assert run["last_event_seq"] == len(events)
    assert run["created_at"] <= run["started_at"] <= run["finished_at"]
    with server.client(token) as client:
        updated = body(client.get(f"/conversations/{conversation['id']}"))
    assert updated["active_run_id"] == run_id
    assert updated["updated_at"] > conversation["updated_at"]


@pytest.mark.spec("API-004")
def test_history_is_served_as_ag_ui_messages(server: Server, token: str) -> None:
    conversation = create_conversation(server, token)
    run_id, _ = start_run(server, token, conversation["id"], "hello")
    page = messages(server, token, conversation["id"])
    assert [(m["role"], m.get("content")) for m in page["items"]] == [("user", "hello"), ("assistant", "Echo: hello")]
    assert len({m["id"] for m in page["items"]}) == 2
    assert page["runs"] == [
        {
            "run_id": run_id,
            "parent_run_id": None,
            "kind": "message",
            "message_ids": [m["id"] for m in page["items"]],
            "versions": [run_id],
        }
    ]


@pytest.mark.spec("API-004", "AGT-009")
@pytest.mark.parametrize("how", ["last-event-id", "after"])
def test_events_are_replayed_after_a_sequence_number(server: Server, token: str, how: str) -> None:
    conversation = create_conversation(server, token)
    run_id, events = start_run(server, token, conversation["id"], "hello")
    for after in (0, 2, len(events)):
        replayed = (
            replay(server, token, run_id, last_event_id=after)
            if how == "last-event-id"
            else replay(server, token, run_id, after=after)
        )
        assert replayed == events[after:]


@pytest.mark.spec("AGT-009")
def test_a_run_continues_when_the_client_disconnects(server: Server, token: str) -> None:
    conversation = create_conversation(server, token)
    run_id, first = start_run(server, token, conversation["id"], "slow:6", stop_after=2)
    assert len(first) == 2
    assert wait_for_run(server, token, run_id)["status"] == "completed"
    everything = replay(server, token, run_id)
    assert everything[:2] == first
    assert everything[-1].type == "RUN_FINISHED"
    assert text_of(everything) == "".join(f"piece {index} " for index in range(6))


@pytest.mark.spec("API-004", "AGT-009")
def test_a_second_client_follows_a_run_in_progress(server: Server, token: str) -> None:
    conversation = create_conversation(server, token)
    run_id, _ = start_run(server, token, conversation["id"], "slow:6", stop_after=1)
    # Another device, signed in as the same user, from the start of the run.
    followed = replay(server, token, run_id)
    assert followed[0].type == "RUN_STARTED"
    assert followed[-1].type == "RUN_FINISHED"


@pytest.mark.spec("API-004")
def test_a_retried_request_returns_the_same_run(server: Server, token: str, default_model: HarnessModel) -> None:
    conversation = create_conversation(server, token)
    run_id = uuid7()
    _, first = start_run(server, token, conversation["id"], "once", run_id=run_id)
    _, again = start_run(server, token, conversation["id"], "once", run_id=run_id)
    assert again == first
    assert len(default_model.endpoint.requests_with("once")) == 1
    assert len(messages(server, token, conversation["id"])["runs"]) == 1


@pytest.mark.spec("CNV-002")
def test_runs_continue_the_active_path(server: Server, token: str, default_model: HarnessModel) -> None:
    conversation = create_conversation(server, token)
    first, _ = start_run(server, token, conversation["id"], "first message")
    second, _ = start_run(server, token, conversation["id"], "second message")
    assert get_run(server, token, second)["parent_run_id"] == first
    (request,) = default_model.endpoint.requests_with("second message")
    assert request.user_texts() == ["first message", "second message"]
    page = messages(server, token, conversation["id"])
    assert [m.get("content") for m in page["items"]] == [
        "first message",
        "Echo: first message",
        "second message",
        "Echo: second message",
    ]


@pytest.mark.spec("CNV-002")
def test_only_the_path_of_a_run_reaches_the_model(server: Server, token: str, default_model: HarnessModel) -> None:
    conversation = create_conversation(server, token)
    first, _ = start_run(server, token, conversation["id"], "path a1")
    start_run(server, token, conversation["id"], "path a2")
    # A new version of the second turn: it continues the first run.
    other, _ = start_run(server, token, conversation["id"], "path b2", parent_run_id=first)
    (request,) = default_model.endpoint.requests_with("path b2")
    assert request.user_texts() == ["path a1", "path b2"]
    third, _ = start_run(server, token, conversation["id"], "path b3")
    (request,) = default_model.endpoint.requests_with("path b3")
    assert request.user_texts() == ["path a1", "path b2", "path b3"]
    assert get_run(server, token, third)["parent_run_id"] == other


@pytest.mark.spec("API-004")
def test_one_run_at_a_time_per_conversation(server: Server, token: str) -> None:
    conversation = create_conversation(server, token)
    run_id, _ = start_run(server, token, conversation["id"], "slow:6", stop_after=1)
    with server.client(token) as client:
        response = client.post(f"/conversations/{conversation['id']}/runs", json=run_input(conversation["id"], "next"))
        assert_problem(response, 409, "run.in_progress")
        assert_problem(client.delete(f"/conversations/{conversation['id']}"), 409, "run.in_progress")
    wait_for_run(server, token, run_id)


@pytest.mark.spec("API-004")
@pytest.mark.parametrize("problem", ["other-thread", "assistant-message", "no-messages", "unknown-parent"])
def test_invalid_run_inputs_are_rejected(server: Server, token: str, problem: str) -> None:
    conversation = create_conversation(server, token)
    payload = run_input(conversation["id"], "hello")
    expected = (422, "request.validation_failed")
    match problem:
        case "other-thread":
            payload["threadId"] = str(uuid7())
        case "assistant-message":
            payload["messages"][-1]["role"] = "assistant"
        case "no-messages":
            payload["messages"] = []
        case _:
            payload["parentRunId"] = str(uuid7())
            expected = (404, "resource.not_found")
    with server.client(token) as client:
        assert_problem(client.post(f"/conversations/{conversation['id']}/runs", json=payload), *expected)


@pytest.mark.spec("MOD-008")
def test_runs_need_a_default_model(server: Server, token: str, default_model: HarnessModel) -> None:
    conversation = create_conversation(server, token)
    with server.client(default_model.admin_token) as client:
        client.patch(f"/instance/models/{default_model.id}", json={"is_default": False})
    try:
        with server.client(token) as client:
            response = client.post(
                f"/conversations/{conversation['id']}/runs", json=run_input(conversation["id"], "hello")
            )
        assert_problem(response, 409, "model.unavailable")
    finally:
        with server.client(default_model.admin_token) as client:
            client.patch(f"/instance/models/{default_model.id}", json={"is_default": True})


@pytest.mark.spec("CNV-003")
def test_a_run_is_stopped(server: Server, token: str, default_model: HarnessModel) -> None:
    conversation = create_conversation(server, token)
    run_id, _ = start_run(server, token, conversation["id"], "slow:20", stop_after=3)
    with server.client(token) as client:
        response = client.post(f"/runs/{run_id}/cancel")
    assert response.status_code == 200, response.text
    run = wait_for_run(server, token, run_id)
    assert run["status"] == "cancelled"
    events = replay(server, token, run_id)
    assert (events[-1].type, events[-1].data.get("code")) == ("RUN_ERROR", "run.cancelled")
    requests = len(default_model.endpoint.requests_with("slow:20"))
    time.sleep(1)
    assert len(default_model.endpoint.requests_with("slow:20")) == requests
    # What the run produced before stopping is kept.
    assert [m.get("content") for m in messages(server, token, conversation["id"])["items"]][:1] == ["slow:20"]
    with server.client(token) as client:
        again = body(client.post(f"/runs/{run_id}/cancel"))
    assert again == get_run(server, token, run_id)


@pytest.mark.spec("CNV-003")
def test_cancelling_a_finished_run_changes_nothing(server: Server, token: str) -> None:
    conversation = create_conversation(server, token)
    run_id, _ = start_run(server, token, conversation["id"], "hello")
    finished = wait_for_run(server, token, run_id)
    with server.client(token) as client:
        assert body(client.post(f"/runs/{run_id}/cancel")) == finished


@pytest.mark.spec("API-004", "MOD-001")
def test_a_failing_model_fails_the_run_visibly(server: Server, token: str) -> None:
    conversation = create_conversation(server, token)
    run_id, events = start_run(server, token, conversation["id"], "fail")
    assert events[-1].type == "RUN_ERROR"
    run = wait_for_run(server, token, run_id)
    assert run["status"] == "failed"
    assert run["error_code"] in {"model.request_failed", "model.unavailable"}
    assert events[-1].data.get("code") == run["error_code"]


@pytest.mark.spec("MOD-002", "MOD-008")
def test_the_api_key_reaches_only_the_model(server: Server, token: str, default_model: HarnessModel) -> None:
    secret = f"sk-{uuid7()}"
    with server.client(default_model.admin_token) as client:
        client.patch(f"/instance/models/{default_model.id}", json={"api_key": secret})
    try:
        conversation = create_conversation(server, token)
        run_id, events = start_run(server, token, conversation["id"], "with key")
        (request,) = default_model.endpoint.requests_with("with key")
        assert request.authorization == f"Bearer {secret}"
        visible = str(events) + str(get_run(server, token, run_id)) + str(messages(server, token, conversation["id"]))
        assert secret not in visible
    finally:
        with server.client(default_model.admin_token) as client:
            client.patch(f"/instance/models/{default_model.id}", json={"api_key": None})


@pytest.mark.spec("MOD-006", "MOD-005")
def test_every_model_request_is_in_the_cost_ledger(
    database: Database, server: Server, account: Account, token: str, default_model: HarnessModel
) -> None:
    conversation = create_conversation(server, token)
    run_id, _ = start_run(server, token, conversation["id"], "hello")
    with database.superuser() as conn:
        rows = conn.execute(
            "SELECT tenant_id, owner_id, conversation_id, run_id, purpose, provider, model, input_tokens,"
            " output_tokens, cost, price_source FROM usage_ledger WHERE run_id = %s",
            (run_id,),
        ).fetchall()
    assert [tuple(map(str, row[:7])) + tuple(row[7:]) for row in rows] == [
        (
            str(account.tenant_id),
            str(account.id),
            conversation["id"],
            run_id,
            "run",
            _endpoint_host(default_model),
            "test-model",
            PROMPT_TOKENS,
            COMPLETION_TOKENS,
            Decimal(0),
            "free",
        )
    ]


@pytest.mark.spec("MOD-006")
def test_paid_models_are_priced_from_the_configuration(
    database: Database, server: Server, token: str, default_model: HarnessModel
) -> None:
    prices = {"input": "2", "output": "8", "currency": "EUR"}
    with server.client(default_model.admin_token) as client:
        client.patch(f"/instance/models/{default_model.id}", json={"paid": True, "prices": prices})
    try:
        conversation = create_conversation(server, token)
        run_id, _ = start_run(server, token, conversation["id"], "priced")
    finally:
        with server.client(default_model.admin_token) as client:
            client.patch(f"/instance/models/{default_model.id}", json={"paid": False, "prices": None})
    with database.superuser() as conn:
        row = conn.execute(
            "SELECT cost, currency, price_source FROM usage_ledger WHERE run_id = %s", (run_id,)
        ).fetchone()
    expected = (Decimal(PROMPT_TOKENS) * 2 + Decimal(COMPLETION_TOKENS) * 8) / 1_000_000
    assert row == (expected, "EUR", "admin")


@pytest.mark.spec("API-003", "TEN-009", "MOD-006")
def test_deleting_a_conversation_removes_its_runs_and_workflows(
    database: Database, server: Server, account: Account, token: str
) -> None:
    conversation = create_conversation(server, token)
    run_id, _ = start_run(server, token, conversation["id"], "hello")
    with server.client(token) as client:
        assert client.delete(f"/conversations/{conversation['id']}").status_code == 204
        assert_problem(client.get(f"/runs/{run_id}"), 404, "resource.not_found")
        assert_problem(client.get(f"/runs/{run_id}/events"), 404, "resource.not_found")
    with database.superuser() as conn:
        workflows = conn.execute("SELECT 1 FROM dbos.workflow_status WHERE workflow_uuid = %s", (run_id,)).fetchall()
        ledger = conn.execute(
            "SELECT conversation_id, run_id FROM usage_ledger WHERE owner_id = %s", (account.id,)
        ).fetchall()
    assert workflows == []
    # Spending stays in the ledger, detached from what was deleted (ADR-0042).
    assert ledger == [(None, None)]


@pytest.mark.spec("TEN-009")
def test_workflows_of_old_runs_are_deleted(database: Database, server: Server, token: str) -> None:
    conversation = create_conversation(server, token)
    run_id, _ = start_run(server, token, conversation["id"], "hello")
    with database.superuser() as conn:
        conn.execute("UPDATE runs SET finished_at = now() - interval '31 days' WHERE id = %s", (run_id,))
    # Retention runs when the worker starts (ADR-0052).
    server.crash_and_restart_worker()
    deadline = time.monotonic() + 60
    with database.superuser() as conn:
        while conn.execute("SELECT 1 FROM dbos.workflow_status WHERE workflow_uuid = %s", (run_id,)).fetchall():
            assert time.monotonic() < deadline, "the workflow of an old run was not deleted"
            time.sleep(0.5)
    # The run and its history stay; its events do not.
    assert get_run(server, token, run_id)["status"] == "completed"
    assert len(messages(server, token, conversation["id"])["items"]) == 2
    with server.client(token) as client:
        assert_problem(client.get(f"/runs/{run_id}/events"), 404, "resource.not_found")


@pytest.mark.spec("AGT-010")
def test_a_run_survives_a_crash_of_the_worker(server: Server, token: str) -> None:
    conversation = create_conversation(server, token)
    run_id, _ = start_run(server, token, conversation["id"], "slow:8", stop_after=3)
    server.crash_and_restart_worker()
    run = wait_for_run(server, token, run_id, timeout=120)
    events = replay(server, token, run_id)
    # Resumed, retried or failed, but never silently lost.
    assert run["status"] in {"completed", "failed"}
    assert events[-1].type == ("RUN_FINISHED" if run["status"] == "completed" else "RUN_ERROR")
    assert [event.seq for event in events] == list(range(1, len(events) + 1))
