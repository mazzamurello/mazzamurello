"""Live usage, and costs per answer, conversation and period (MOD-007, MOD-006, ADR-0042, ADR-0073)."""

from __future__ import annotations

import secrets
from decimal import Decimal
from typing import Any

import pytest

from tests.support.accounts import body
from tests.support.database import Database, uuid7
from tests.support.fixtures import HarnessModel
from tests.support.households import Member, new_member
from tests.support.model import OPENROUTER_COST
from tests.support.runs import create_conversation, messages, start_run, wait_for_run
from tests.support.server import Server


@pytest.fixture
def member(database: Database, server: Server, harness_model: HarnessModel) -> Member:
    return new_member(database, server, harness_model)


def _openrouter(server: Server, member: Member) -> str:
    """Add OpenRouter to the household and make its most used model the default."""
    with server.client(member.model.admin_token) as client:
        response = client.post(
            "/tenant/connections",
            json={
                "name": "OpenRouter",
                "kind": "openrouter",
                "base_url": member.model.endpoint.openrouter_url,
                "api_key": f"sk-or-v1-{secrets.token_hex(8)}",
            },
        )
        assert response.status_code == 201, response.text
        connection_id = str(body(response)["id"])
        assert client.put(
            "/tenant/default-model", json={"connection_id": connection_id, "model": "test/popular"}
        ).is_success
    return connection_id


def _total(amounts: list[dict[str, Any]], currency: str = "USD") -> Decimal:
    return sum((Decimal(item["amount"]) for item in amounts if item["currency"] == currency), Decimal(0))


@pytest.mark.spec("MOD-007")
def test_each_model_response_reports_the_context_and_the_cost_so_far(server: Server, member: Member) -> None:
    conversation = create_conversation(server, member.token)
    run_id, events = start_run(server, member.token, conversation["id"], "run:echo $((6*7))")
    assert wait_for_run(server, member.token, run_id)["status"] == "completed"
    usage = [
        event.data["value"] for event in events if event.type == "CUSTOM" and event.data.get("name") == "mzm.usage"
    ]
    # One after each model response: the tool call, then the answer.
    assert len(usage) == 2
    first, last = usage
    assert first["context_window"] == 8192
    assert 0 < first["context_tokens"] <= first["context_window"]
    assert last["input_tokens"] > first["input_tokens"]
    assert last["output_tokens"] > first["output_tokens"]
    # A local model costs nothing.
    assert Decimal(last["cost"]["amount"]) == 0


@pytest.mark.spec("MOD-007", "UX-008")
def test_costs_of_answers_conversations_and_periods(database: Database, server: Server, member: Member) -> None:
    _openrouter(server, member)
    # Named, so that no title request adds to its cost (CNV-006).
    conversation = create_conversation(server, member.token, "Priced")
    run_id, events = start_run(server, member.token, conversation["id"], "priced")
    assert wait_for_run(server, member.token, run_id)["status"] == "completed"
    usage = [
        event.data["value"] for event in events if event.type == "CUSTOM" and event.data.get("name") == "mzm.usage"
    ]
    assert Decimal(usage[-1]["cost"]["amount"]) == Decimal(str(OPENROUTER_COST))
    page = messages(server, member.token, conversation["id"])
    assert _total(page["runs"][0]["cost"]) == Decimal(str(OPENROUTER_COST))
    with server.client(member.token) as client:
        assert _total(body(client.get(f"/conversations/{conversation['id']}"))["cost"]) == Decimal(str(OPENROUTER_COST))
    # Earlier spending, arranged in the ledger: two days ago and forty days ago.
    with database.superuser() as conn:
        for days, cost in ((2, "1.5"), (40, "7")):
            conn.execute(
                "INSERT INTO usage_ledger (id, tenant_id, owner_id, purpose, provider, model, cost, currency,"
                " price_source, created_at) VALUES (%s, %s, %s, 'run', 'test', 'test', %s, 'USD', 'provider',"
                " now() - make_interval(days => %s))",
                (uuid7(), member.account.tenant_id, member.account.id, Decimal(cost), days),
            )
    with server.client(member.token) as client:
        usage_now = body(client.get("/me/usage"))
    assert _total(usage_now["last_24_hours"]) == Decimal(str(OPENROUTER_COST))
    assert _total(usage_now["last_30_days"]) == Decimal(str(OPENROUTER_COST)) + Decimal("1.5")
    assert usage_now["unpriced_requests"] == 0


@pytest.mark.spec("MOD-007", "TEN-006")
def test_usage_is_the_users_own(
    database: Database, server: Server, member: Member, harness_model: HarnessModel
) -> None:
    _openrouter(server, member)
    conversation = create_conversation(server, member.token, "Mine")
    run_id, _ = start_run(server, member.token, conversation["id"], "mine")
    wait_for_run(server, member.token, run_id)
    other = new_member(database, server, harness_model)
    with server.client(other.token) as client:
        usage = body(client.get("/me/usage"))
    assert _total(usage["last_30_days"]) == 0
