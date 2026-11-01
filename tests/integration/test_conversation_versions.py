"""Message versions, rewinding and continuity across devices (CNV-001, CNV-004, CNV-015, ADR-0037).

A run whose `parentRunId` is the parent of an earlier run is another version
of that turn; setting a conversation's `active_run_id` switches versions or
rewinds to an earlier turn.
"""

from __future__ import annotations

import secrets
from typing import Any

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
    return login(server, account)


def _contents(page: dict[str, Any]) -> list[str]:
    return [str(message.get("content")) for message in page["items"]]


def _switch(server: Server, token: str, conversation_id: str, run_id: str) -> dict[str, Any]:
    with server.client(token) as client:
        response = client.patch(f"/conversations/{conversation_id}", json={"active_run_id": run_id})
    assert response.status_code == 200, response.text
    return body(response)


@pytest.mark.spec("CNV-001")
def test_editing_a_message_keeps_the_earlier_version(server: Server, token: str) -> None:
    conversation = create_conversation(server, token)
    first, _ = start_run(server, token, conversation["id"], "edit one")
    original, _ = start_run(server, token, conversation["id"], "edit two")
    # Editing the second message starts a run whose parent is the first run.
    edited, _ = start_run(server, token, conversation["id"], "edit two, edited", parent_run_id=first)
    page = messages(server, token, conversation["id"])
    assert _contents(page) == ["edit one", "Echo: edit one", "edit two, edited", "Echo: edit two, edited"]
    assert [run["versions"] for run in page["runs"]] == [[first], [original, edited]]
    earlier = messages(server, token, conversation["id"], run_id=original)
    assert _contents(earlier) == ["edit one", "Echo: edit one", "edit two", "Echo: edit two"]


@pytest.mark.spec("CNV-001")
def test_asking_for_a_new_answer_keeps_both_answers(server: Server, token: str) -> None:
    conversation = create_conversation(server, token)
    first, _ = start_run(server, token, conversation["id"], "answer one")
    old_answer, _ = start_run(server, token, conversation["id"], "answer two")
    new_answer, _ = start_run(server, token, conversation["id"], "answer two", parent_run_id=first)
    page = messages(server, token, conversation["id"])
    assert page["runs"][-1]["versions"] == [old_answer, new_answer]
    old_ids = {item["id"] for item in messages(server, token, conversation["id"], run_id=old_answer)["items"]}
    new_ids = {item["id"] for item in page["items"]}
    assert len(old_ids - new_ids) == 2, "the earlier question and answer are kept as their own messages"


@pytest.mark.spec("CNV-001", "CNV-002")
def test_switching_versions_and_continuing_from_any(server: Server, token: str, default_model: HarnessModel) -> None:
    conversation = create_conversation(server, token)
    first, _ = start_run(server, token, conversation["id"], "switch one")
    original, _ = start_run(server, token, conversation["id"], "switch two")
    start_run(server, token, conversation["id"], "switch two, edited", parent_run_id=first)
    assert _switch(server, token, conversation["id"], original)["active_run_id"] == original
    assert _contents(messages(server, token, conversation["id"]))[-1] == "Echo: switch two"
    later, _ = start_run(server, token, conversation["id"], "switch three")
    page = messages(server, token, conversation["id"])
    assert [run["run_id"] for run in page["runs"]] == [first, original, later]
    (request,) = default_model.endpoint.requests_with("switch three")
    assert request.user_texts() == ["switch one", "switch two", "switch three"]


@pytest.mark.spec("CNV-004")
def test_rewinding_keeps_what_followed_as_a_version(server: Server, token: str) -> None:
    conversation = create_conversation(server, token)
    first, _ = start_run(server, token, conversation["id"], "rewind one")
    second, _ = start_run(server, token, conversation["id"], "rewind two")
    third, _ = start_run(server, token, conversation["id"], "rewind three")
    _switch(server, token, conversation["id"], first)
    assert _contents(messages(server, token, conversation["id"])) == ["rewind one", "Echo: rewind one"]
    again, _ = start_run(server, token, conversation["id"], "rewind two, again")
    page = messages(server, token, conversation["id"])
    assert [run["run_id"] for run in page["runs"]] == [first, again]
    assert page["runs"][1]["versions"] == [second, again]
    kept = messages(server, token, conversation["id"], run_id=third)
    assert [run["run_id"] for run in kept["runs"]] == [first, second, third]


@pytest.mark.spec("CNV-004")
def test_rewinding_leaves_the_workspace_alone(server: Server, token: str) -> None:
    conversation = create_conversation(server, token)
    name, before, after = f"rewind-{secrets.token_hex(4)}.txt", secrets.token_hex(6), secrets.token_hex(6)
    first, _ = start_run(server, token, conversation["id"], f"run:echo {before} > {name}")
    start_run(server, token, conversation["id"], f"run:echo {after} > {name}")
    _switch(server, token, conversation["id"], first)
    run_id, events = start_run(server, token, conversation["id"], f"run:cat {name}")
    assert wait_for_run(server, token, run_id)["status"] == "completed"
    assert after in text_of(events), "rewinding changed a file of the workspace"


@pytest.mark.spec("CNV-001", "CNV-004")
def test_switching_needs_an_idle_conversation_and_one_of_its_runs(server: Server, token: str) -> None:
    conversation, other = create_conversation(server, token), create_conversation(server, token)
    first, _ = start_run(server, token, conversation["id"], "idle one")
    foreign, _ = start_run(server, token, other["id"], "idle elsewhere")
    running, _ = start_run(server, token, conversation["id"], "slow:6", stop_after=1)
    with server.client(token) as client:
        assert_problem(
            client.patch(f"/conversations/{conversation['id']}", json={"active_run_id": first}), 409, "run.in_progress"
        )
    wait_for_run(server, token, running)
    with server.client(token) as client:
        assert_problem(
            client.patch(f"/conversations/{conversation['id']}", json={"active_run_id": foreign}),
            422,
            "request.validation_failed",
        )


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


@pytest.mark.spec("CNV-001")
def test_message_ids_are_stable_across_reads_and_versions(server: Server, token: str) -> None:
    conversation = create_conversation(server, token)
    first, _ = start_run(server, token, conversation["id"], "stable one")
    original, _ = start_run(server, token, conversation["id"], "stable two")
    start_run(server, token, conversation["id"], "stable two, edited", parent_run_id=first)
    once, twice = messages(server, token, conversation["id"]), messages(server, token, conversation["id"])
    assert [item["id"] for item in once["items"]] == [item["id"] for item in twice["items"]]
    other = messages(server, token, conversation["id"], run_id=original)
    # The first turn is shared by both versions, with the same IDs.
    assert once["runs"][0]["message_ids"] == other["runs"][0]["message_ids"]
