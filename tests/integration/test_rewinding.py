"""Rewinding, editing a message and continuity across devices (CNV-004, CNV-016, CNV-015, ADR-0068).

A conversation has one chain of runs. Rewinding names the run that becomes
the last and deletes the runs after it; editing a message is rewinding to
the turn before it, then sending the edited text.
"""

from __future__ import annotations

import secrets
from typing import Any

import httpx
import pytest

from tests.support.accounts import Account, assert_problem, body, create_account, create_tenant, login
from tests.support.database import Database
from tests.support.fixtures import HarnessModel
from tests.support.runs import create_conversation, messages, replay, start_run, text_of, wait_for_run
from tests.support.server import Server


@pytest.fixture
def account(database: Database) -> Account:
    return create_account(database, create_tenant(database))


@pytest.fixture
def token(server: Server, account: Account, default_model: HarnessModel) -> str:
    default_model.connect(account.tenant_id)
    return login(server, account)


def _contents(page: dict[str, Any]) -> list[str]:
    return [str(message.get("content")) for message in page["items"]]


def _rewind(server: Server, token: str, conversation_id: str, run_id: str | None) -> httpx.Response:
    with server.client(token) as client:
        return client.post(f"/conversations/{conversation_id}/rewind", json={"run_id": run_id})


@pytest.mark.spec("CNV-004")
def test_rewinding_deletes_what_followed(database: Database, server: Server, token: str) -> None:
    conversation = create_conversation(server, token)
    first, _ = start_run(server, token, conversation["id"], "rewind one")
    second, _ = start_run(server, token, conversation["id"], "rewind two")
    third, _ = start_run(server, token, conversation["id"], "rewind three")
    response = _rewind(server, token, conversation["id"], first)
    assert response.status_code == 200, response.text
    assert body(response)["active_run_id"] == first
    assert _contents(messages(server, token, conversation["id"])) == ["rewind one", "Echo: rewind one"]
    with server.client(token) as client:
        for deleted in (second, third):
            assert_problem(client.get(f"/runs/{deleted}"), 404, "resource.not_found")
            assert_problem(client.get(f"/runs/{deleted}/events"), 404, "resource.not_found")
    with database.superuser() as conn:
        rows = conn.execute("SELECT count(*) FROM conversation_messages WHERE run_id = ANY(%s)", ([second, third],))
        workflows = conn.execute(
            "SELECT count(*) FROM dbos.workflow_status WHERE workflow_uuid = ANY(%s)", ([second, third],)
        )
        assert (rows.fetchone(), workflows.fetchone()) == ((0,), (0,))
        # Spending stays in the ledger, detached from the deleted runs (ADR-0042).
        ledger = conn.execute(
            "SELECT run_id FROM usage_ledger WHERE conversation_id = %s AND purpose = 'run' ORDER BY created_at",
            (conversation["id"],),
        ).fetchall()
    assert [str(run) if run else None for (run,) in ledger] == [first, None, None]
    again, _ = start_run(server, token, conversation["id"], "rewind two, again")
    page = messages(server, token, conversation["id"])
    assert [run["run_id"] for run in page["runs"]] == [first, again]


@pytest.mark.spec("CNV-004")
def test_rewinding_leaves_the_workspace_alone(server: Server, token: str) -> None:
    conversation = create_conversation(server, token)
    name, before, after = f"rewind-{secrets.token_hex(4)}.txt", secrets.token_hex(6), secrets.token_hex(6)
    first, _ = start_run(server, token, conversation["id"], f"run:echo {before} > {name}")
    start_run(server, token, conversation["id"], f"run:echo {after} > {name}")
    assert _rewind(server, token, conversation["id"], first).status_code == 200
    run_id, events = start_run(server, token, conversation["id"], f"run:cat {name}")
    assert wait_for_run(server, token, run_id)["status"] == "completed"
    assert after in text_of(events), "rewinding changed a file of the workspace"


@pytest.mark.spec("CNV-004")
def test_rewinding_needs_an_idle_conversation_and_one_of_its_runs(server: Server, token: str) -> None:
    conversation, other = create_conversation(server, token), create_conversation(server, token)
    first, _ = start_run(server, token, conversation["id"], "idle one")
    foreign, _ = start_run(server, token, other["id"], "idle elsewhere")
    running, _ = start_run(server, token, conversation["id"], "slow:6", stop_after=1)
    assert_problem(_rewind(server, token, conversation["id"], first), 409, "run.in_progress")
    wait_for_run(server, token, running)
    assert_problem(_rewind(server, token, conversation["id"], foreign), 422, "request.validation_failed")
    # Nothing was deleted by the refused attempts.
    assert [run["run_id"] for run in messages(server, token, conversation["id"])["runs"]] == [first, running]


@pytest.mark.spec("CNV-016", "CNV-004")
def test_editing_a_message_rewinds_to_the_turn_before_it(
    server: Server, token: str, default_model: HarnessModel
) -> None:
    conversation = create_conversation(server, token)
    first, _ = start_run(server, token, conversation["id"], "edit one")
    start_run(server, token, conversation["id"], "edit two")
    start_run(server, token, conversation["id"], "edit three")
    # The client rewinds to the parent of the run that holds the edited message.
    held_by = messages(server, token, conversation["id"])["runs"][1]
    assert held_by["parent_run_id"] == first
    assert _rewind(server, token, conversation["id"], held_by["parent_run_id"]).status_code == 200
    edited, _ = start_run(server, token, conversation["id"], "edit two, edited")
    page = messages(server, token, conversation["id"])
    assert _contents(page) == ["edit one", "Echo: edit one", "edit two, edited", "Echo: edit two, edited"]
    assert [run["run_id"] for run in page["runs"]] == [first, edited]
    (request,) = default_model.endpoint.requests_with("edit two, edited")
    assert request.user_texts() == ["edit one", "edit two, edited"]


@pytest.mark.spec("CNV-016", "CNV-004")
def test_the_first_message_can_be_edited(server: Server, token: str, default_model: HarnessModel) -> None:
    conversation = create_conversation(server, token)
    first, _ = start_run(server, token, conversation["id"], "first, original")
    start_run(server, token, conversation["id"], "second")
    response = _rewind(server, token, conversation["id"], None)
    assert response.status_code == 200, response.text
    assert body(response)["active_run_id"] is None
    assert messages(server, token, conversation["id"])["items"] == []
    with server.client(token) as client:
        assert_problem(client.get(f"/runs/{first}"), 404, "resource.not_found")
    edited, _ = start_run(server, token, conversation["id"], "first, edited")
    assert [run["run_id"] for run in messages(server, token, conversation["id"])["runs"]] == [edited]
    (request,) = default_model.endpoint.requests_with("first, edited")
    assert request.user_texts() == ["first, edited"]


@pytest.mark.spec("CNV-004", "API-003")
def test_history_no_longer_describes_versions(server: Server, token: str) -> None:
    conversation = create_conversation(server, token)
    start_run(server, token, conversation["id"], "plain")
    (run,) = messages(server, token, conversation["id"])["runs"]
    assert set(run) == {"run_id", "parent_run_id", "kind", "message_ids", "cost"}
    # The active run is no longer set by updating the conversation.
    with server.client(token) as client:
        response = client.patch(f"/conversations/{conversation['id']}", json={"active_run_id": None})
    assert_problem(response, 422, "request.validation_failed")


@pytest.mark.spec("CNV-015", "API-004")
def test_another_device_follows_and_continues_a_conversation(server: Server, account: Account, token: str) -> None:
    phone = login(server, account)
    assert phone != token, "each sign-in is a device session of its own"
    conversation = create_conversation(server, token)
    running, _ = start_run(server, token, conversation["id"], "slow:4", stop_after=1)
    with server.client(phone) as client:
        response = client.get(f"/conversations/{conversation['id']}")
    assert response.status_code == 200, response.text
    assert body(response)["active_run_id"] == running
    followed = replay(server, phone, running)
    assert followed[0].type == "RUN_STARTED"
    assert followed[-1].type == "RUN_FINISHED"
    continued, _ = start_run(server, phone, conversation["id"], "from the phone")
    page = messages(server, token, conversation["id"])
    assert [run["run_id"] for run in page["runs"]] == [running, continued]
    assert _contents(page)[-2:] == ["from the phone", "Echo: from the phone"]


@pytest.mark.spec("API-003")
def test_message_ids_are_stable_across_reads(server: Server, token: str) -> None:
    conversation = create_conversation(server, token)
    start_run(server, token, conversation["id"], "stable one")
    start_run(server, token, conversation["id"], "stable two")
    once, twice = messages(server, token, conversation["id"]), messages(server, token, conversation["id"])
    assert [item["id"] for item in once["items"]] == [item["id"] for item in twice["items"]]
    assert [run["message_ids"] for run in once["runs"]] == [run["message_ids"] for run in twice["runs"]]
