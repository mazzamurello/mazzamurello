"""Forking a conversation at a turn (CNV-005, ADR-0073)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from tests.support.accounts import assert_problem, body
from tests.support.database import Database
from tests.support.fixtures import HarnessModel
from tests.support.households import Member, new_member
from tests.support.runs import create_conversation, messages, start_run, wait_for_run
from tests.support.server import Server


@pytest.fixture
def member(database: Database, server: Server, harness_model: HarnessModel) -> Member:
    return new_member(database, server, harness_model)


def _fork(server: Server, token: str, conversation_id: str, run_id: str) -> httpx.Response:
    with server.client(token) as client:
        return client.post(f"/conversations/{conversation_id}/fork", json={"run_id": run_id})


def _contents(page: dict[str, Any]) -> list[str]:
    return [str(message.get("content")) for message in page["items"]]


@pytest.mark.spec("CNV-005")
def test_a_fork_copies_the_history_up_to_a_turn(database: Database, server: Server, member: Member) -> None:
    with server.client(member.token) as client:
        folder = body(client.post("/folders", json={"name": "Trips"}))
    original = create_conversation(server, member.token, "Urbino")
    with server.client(member.token) as client:
        assert client.patch(f"/conversations/{original['id']}", json={"folder_id": folder["id"]}).is_success
    first, _ = start_run(server, member.token, original["id"], "fork one")
    start_run(server, member.token, original["id"], "fork two")
    response = _fork(server, member.token, original["id"], first)
    assert response.status_code == 201, response.text
    fork = body(response)
    assert fork["id"] != original["id"]
    assert fork["forked_from"] == {"conversation_id": original["id"], "run_id": first}
    assert (fork["title"], fork["folder_id"], fork["model"]) == ("Urbino", folder["id"], original["model"])
    page = messages(server, member.token, fork["id"])
    assert _contents(page) == ["fork one", "Echo: fork one"]
    # Copies, under identifiers of their own.
    assert page["runs"][0]["run_id"] != first
    # The original's spending happened once: the ledger is not copied.
    with database.superuser() as conn:
        copied = conn.execute("SELECT count(*) FROM usage_ledger WHERE conversation_id = %s", (fork["id"],)).fetchone()
    assert copied == (0,)
    assert _contents(messages(server, member.token, original["id"]))[-1] == "Echo: fork two"


@pytest.mark.spec("CNV-005", "CNV-002")
def test_a_fork_goes_its_own_way(server: Server, member: Member, harness_model: HarnessModel) -> None:
    original = create_conversation(server, member.token)
    first, _ = start_run(server, member.token, original["id"], "own one")
    start_run(server, member.token, original["id"], "own two")
    fork = body(_fork(server, member.token, original["id"], first))
    run_id, _ = start_run(server, member.token, fork["id"], "own two, elsewhere")
    assert wait_for_run(server, member.token, run_id)["status"] == "completed"
    (request,) = harness_model.endpoint.requests_with("own two, elsewhere")
    assert request.user_texts() == ["own one", "own two, elsewhere"]
    # Rewinding or deleting the original leaves the fork whole.
    with server.client(member.token) as client:
        assert client.post(f"/conversations/{original['id']}/rewind", json={"run_id": None}).is_success
        assert client.delete(f"/conversations/{original['id']}").status_code == 204
        kept = body(client.get(f"/conversations/{fork['id']}"))
    assert kept["forked_from"]["conversation_id"] is None
    assert _contents(messages(server, member.token, fork["id"])) == [
        "own one",
        "Echo: own one",
        "own two, elsewhere",
        "Echo: own two, elsewhere",
    ]


@pytest.mark.spec("CNV-005", "TEN-006")
def test_forking_needs_an_idle_conversation_its_own_run_and_its_owner(
    database: Database, server: Server, member: Member, harness_model: HarnessModel
) -> None:
    conversation, other = create_conversation(server, member.token), create_conversation(server, member.token)
    first, _ = start_run(server, member.token, conversation["id"], "idle")
    foreign, _ = start_run(server, member.token, other["id"], "elsewhere")
    assert_problem(_fork(server, member.token, conversation["id"], foreign), 422, "request.validation_failed")
    running, _ = start_run(server, member.token, conversation["id"], "slow:6", stop_after=1)
    assert_problem(_fork(server, member.token, conversation["id"], first), 409, "run.in_progress")
    wait_for_run(server, member.token, running)
    stranger = new_member(database, server, harness_model)
    assert_problem(_fork(server, stranger.token, conversation["id"], first), 404, "resource.not_found")
