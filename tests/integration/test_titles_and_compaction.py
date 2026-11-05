"""Automatic titles and compaction, by the conversation's own model (CNV-006, AGT-016, ADR-0041, ADR-0073)."""

from __future__ import annotations

import secrets
import time
from typing import Any

import pytest

from tests.support.accounts import body
from tests.support.database import Database
from tests.support.fixtures import HarnessModel
from tests.support.households import Member, new_member
from tests.support.runs import create_conversation, messages, start_run, wait_for_run
from tests.support.server import Server

TITLE_SECONDS = 30
# A window small enough that a few long turns exceed 80% of it.
SMALL_WINDOW = 1200


@pytest.fixture
def member(database: Database, server: Server, harness_model: HarnessModel) -> Member:
    return new_member(database, server, harness_model)


def _conversation(server: Server, token: str, conversation_id: str) -> dict[str, Any]:
    with server.client(token) as client:
        return body(client.get(f"/conversations/{conversation_id}"))


def _purposes(database: Database, conversation_id: str) -> list[str]:
    with database.superuser() as conn:
        rows = conn.execute(
            "SELECT purpose FROM usage_ledger WHERE conversation_id = %s ORDER BY created_at", (conversation_id,)
        ).fetchall()
    return [str(purpose) for (purpose,) in rows]


@pytest.mark.spec("CNV-006", "MOD-006")
def test_a_new_conversation_gets_a_title_from_its_model(database: Database, server: Server, member: Member) -> None:
    conversation = create_conversation(server, member.token)
    assert conversation["title"] == ""
    run_id, events = start_run(server, member.token, conversation["id"], f"plan a trip {secrets.token_hex(3)}")
    assert wait_for_run(server, member.token, run_id)["status"] == "completed"
    deadline = time.monotonic() + TITLE_SECONDS
    while not (title := _conversation(server, member.token, conversation["id"])["title"]):
        assert time.monotonic() < deadline, "the conversation got no title"
        time.sleep(0.3)
    assert 0 < len(title) <= 200
    # The run announces the title before it finishes, so clients show it while it is answered.
    (announced,) = [e for e in events if e.type == "CUSTOM" and e.data.get("name") == "mzm.title"]
    assert announced.data["value"] == {"title": title}
    finished = next(index for index, e in enumerate(events) if e.type == "RUN_FINISHED")
    assert events.index(announced) < finished
    # The title is a model request of the conversation's own model, in the ledger; it is made
    # alongside the answer, so either may be recorded first.
    assert sorted(_purposes(database, conversation["id"])) == ["run", "title"]
    with database.superuser() as conn:
        models = conn.execute(
            "SELECT DISTINCT model FROM usage_ledger WHERE conversation_id = %s", (conversation["id"],)
        ).fetchall()
    assert models == [("test-model",)]
    # Later runs leave the title alone.
    run_id, _ = start_run(server, member.token, conversation["id"], "and another thing")
    wait_for_run(server, member.token, run_id)
    time.sleep(1)
    assert _conversation(server, member.token, conversation["id"])["title"] == title
    assert _purposes(database, conversation["id"]).count("title") == 1


@pytest.mark.spec("CNV-006")
def test_a_named_conversation_keeps_its_name(database: Database, server: Server, member: Member) -> None:
    conversation = create_conversation(server, member.token, "Our holidays")
    run_id, _ = start_run(server, member.token, conversation["id"], "hello")
    wait_for_run(server, member.token, run_id)
    time.sleep(1)
    assert _conversation(server, member.token, conversation["id"])["title"] == "Our holidays"
    assert "title" not in _purposes(database, conversation["id"])


@pytest.mark.spec("AGT-016", "MOD-008")
def test_connections_to_own_servers_carry_a_context_window(server: Server, member: Member) -> None:
    path = f"/tenant/connections/{member.model.connection_id}"
    with server.client(member.model.admin_token) as client:
        (connection,) = [
            c for c in body(client.get("/tenant/connections"))["items"] if c["id"] == member.model.connection_id
        ]
        assert connection["context_window"] == 8192
        changed = client.patch(path, json={"context_window": 32768})
        assert changed.status_code == 200, changed.text
        assert body(changed)["context_window"] == 32768
        windows = {
            m["context_window"]
            for m in body(client.get("/models"))["items"]
            if m["connection_id"] == member.model.connection_id
        }
        assert windows == {32768}
        assert client.patch(path, json={"context_window": 100}).status_code == 422


@pytest.mark.spec("AGT-016", "MOD-006")
def test_a_long_conversation_is_compacted_for_the_model_only(
    database: Database, server: Server, member: Member, harness_model: HarnessModel
) -> None:
    with server.client(member.model.admin_token) as client:
        path = f"/tenant/connections/{member.model.connection_id}"
        assert client.patch(path, json={"context_window": SMALL_WINDOW}).status_code == 200
    conversation = create_conversation(server, member.token)
    mark = secrets.token_hex(4)
    # Each turn is a long message and its echo; four of them exceed 80% of the window.
    texts = [f"turn {n} {mark} " + "lorem ipsum dolor sit amet " * 30 for n in range(1, 6)]
    for text in texts:
        run_id, _ = start_run(server, member.token, conversation["id"], text)
        assert wait_for_run(server, member.token, run_id)["status"] == "completed"
    with database.superuser() as conn:
        checkpoints = conn.execute(
            "SELECT count(*) FROM compaction_checkpoints WHERE conversation_id = %s", (conversation["id"],)
        ).fetchone()
    assert checkpoints is not None
    assert checkpoints[0] >= 1, "the conversation was never compacted"
    assert "compaction" in _purposes(database, conversation["id"])
    # The model no longer receives the first turn as it was...
    (last,) = harness_model.endpoint.requests_with(texts[-1])
    assert texts[0] not in last.user_texts()
    # ...while the stored conversation keeps every message.
    stored = [
        m.get("content") for m in messages(server, member.token, conversation["id"])["items"] if m["role"] == "user"
    ]
    assert stored == texts
