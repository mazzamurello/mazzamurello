"""Attempts to reach another user's conversations, runs and events through the API (TEN-006, TEN-009)."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from tests.support.accounts import Account, assert_problem, body, create_account, create_tenant, login
from tests.support.database import Context, Database, app_transaction
from tests.support.fixtures import HarnessModel
from tests.support.runs import create_conversation, run_input, start_run, wait_for_run
from tests.support.server import Server


@dataclass(frozen=True)
class Victim:
    token: str
    conversation_id: str
    run_id: str


@pytest.fixture
def victim(database: Database, server: Server, default_model: HarnessModel) -> Victim:
    owner = create_account(database, create_tenant(database))
    token = login(server, owner)
    conversation = create_conversation(server, token, "Private")
    run_id, _ = start_run(server, token, conversation["id"], "private words")
    wait_for_run(server, token, run_id)
    return Victim(token, conversation["id"], run_id)


def _actors(database: Database) -> list[Account]:
    other_tenant = create_tenant(database)
    return [
        create_account(database, other_tenant, "tenant_admin", instance_admin=True),
        create_account(database, other_tenant),
    ]


def _same_tenant_actors(database: Database, server: Server, victim: Victim) -> list[Account]:
    with server.client(victim.token) as client:
        tenant_id = body(client.get("/me"))["tenant_id"]
    return [create_account(database, tenant_id, "tenant_admin"), create_account(database, tenant_id)]


@pytest.mark.spec("TEN-006")
@pytest.mark.parametrize("where", ["same-tenant", "other-tenant"])
def test_conversations_of_others_are_out_of_reach(
    database: Database, server: Server, victim: Victim, where: str
) -> None:
    actors = _same_tenant_actors(database, server, victim) if where == "same-tenant" else _actors(database)
    conversation, run = f"/conversations/{victim.conversation_id}", f"/runs/{victim.run_id}"
    for actor in actors:
        with server.client(login(server, actor)) as client:
            assert victim.conversation_id not in [c["id"] for c in body(client.get("/conversations"))["items"]]
            for response in (
                client.get(conversation),
                client.patch(conversation, json={"title": "Mine"}),
                client.get(f"{conversation}/messages"),
                client.post(f"{conversation}/runs", json=run_input(victim.conversation_id, "intrude")),
                client.get(run),
                client.post(f"{run}/cancel"),
                client.get(f"{run}/events"),
                client.delete(conversation),
            ):
                assert_problem(response, 404, "resource.not_found")
    # Nothing changed for the owner.
    with server.client(victim.token) as client:
        owned = body(client.get(conversation))
        history = body(client.get(f"{conversation}/messages"))["items"]
    assert owned["title"] == "Private"
    assert [m.get("content") for m in history] == ["private words", "Echo: private words"]


@pytest.mark.spec("TEN-006", "TEN-009")
def test_runs_cannot_be_started_under_another_conversation_id(
    database: Database, server: Server, victim: Victim
) -> None:
    intruder = create_account(database, create_tenant(database))
    token = login(server, intruder)
    own = create_conversation(server, token)
    # The path names the intruder's conversation; the input names the victim's.
    payload = run_input(victim.conversation_id, "intrude")
    with server.client(token) as client:
        assert_problem(client.post(f"/conversations/{own['id']}/runs", json=payload), 422, "request.validation_failed")
        # Reusing the victim's run ID never returns the victim's stream.
        replay_attempt = client.post(
            f"/conversations/{own['id']}/runs", json=run_input(own["id"], "intrude") | {"runId": victim.run_id}
        )
    assert replay_attempt.status_code in {404, 409, 422}
    assert "private words" not in replay_attempt.text


@pytest.mark.spec("TEN-006", "MOD-008")
def test_model_configurations_need_a_request_context(database: Database, server: Server, victim: Victim) -> None:
    with app_transaction(database, None) as conn:
        assert conn.execute("SELECT id FROM instance_models").fetchall() == []
        assert conn.execute("SELECT id FROM tenant_models").fetchall() == []
    with database.superuser() as conn:
        assert conn.execute("SELECT 1 FROM instance_models LIMIT 1").fetchall()


@pytest.mark.spec("TEN-006", "MOD-008")
def test_tenant_models_are_visible_only_in_their_tenant(database: Database, server: Server) -> None:
    owner = create_account(database, create_tenant(database), "tenant_admin")
    with server.client(login(server, owner)) as client:
        created = client.post(
            "/tenant/models",
            json={"name": "Ours", "base_url": "https://1.1.1.1/v1", "model": "m", "paid": False},
        )
    assert created.status_code == 201, created.text
    stranger = create_account(database, create_tenant(database), "tenant_admin", instance_admin=True)
    with app_transaction(database, Context(stranger.tenant_id, stranger.id, "tenant_admin", True)) as conn:
        assert conn.execute("SELECT id FROM tenant_models WHERE tenant_id = %s", (owner.tenant_id,)).fetchall() == []
