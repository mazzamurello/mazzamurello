"""A client cannot forge or replay approval decisions (AGT-012, threat T-20, ADR-0033, ADR-0090)."""

from __future__ import annotations

import pytest

from tests.support.accounts import Account, assert_problem, create_account, create_tenant, login
from tests.support.approvals import approve, asked, fresh_query, resume, resumed, search, with_untrusted_content
from tests.support.database import Database
from tests.support.fixtures import HarnessModel
from tests.support.search import SearchServer
from tests.support.server import Server


@pytest.fixture
def account(database: Database) -> Account:
    return create_account(database, create_tenant(database))


@pytest.fixture
def token(server: Server, account: Account, default_model: HarnessModel) -> str:
    default_model.connect(account.tenant_id)
    return login(server, account)


@pytest.mark.spec("AGT-012")
def test_what_runs_is_the_stored_call_whatever_the_answer_says(
    server: Server, token: str, default_model: HarnessModel, search_service: SearchServer
) -> None:
    conversation_id = with_untrusted_content(server, token)
    stored, forged = fresh_query("stored"), fresh_query("forged")
    _, interrupt = asked(server, token, conversation_id, search(stored))
    answer = approve(interrupt["id"])
    answer["payload"] |= {"tool": "read_page", "arguments": {"query": forged}, "override_args": {"query": forged}}
    resumed(server, token, conversation_id, [answer])
    assert search_service.queries().count(stored) == 1
    assert search_service.queries().count(forged) == 0


@pytest.mark.spec("AGT-012", "TEN-006")
def test_only_the_conversations_user_answers_its_requests(
    database: Database, server: Server, token: str, account: Account, default_model: HarnessModel
) -> None:
    conversation_id = with_untrusted_content(server, token)
    _, interrupt = asked(server, token, conversation_id, search(fresh_query()))
    for other in (
        login(server, create_account(database, account.tenant_id, "tenant_admin")),
        login(server, create_account(database, account.tenant_id)),
    ):
        assert_problem(resume(server, other, conversation_id, [approve(interrupt["id"])]), 404, "resource.not_found")
    # It is still pending for its user.
    resumed(server, token, conversation_id, [approve(interrupt["id"])])


@pytest.mark.spec("AGT-012", "AGT-006")
def test_no_request_but_an_approval_creates_an_allowance(
    server: Server, token: str, default_model: HarnessModel
) -> None:
    conversation_id = with_untrusted_content(server, token)
    with server.client(token) as client:
        added: list[dict[str, object]] = [
            {"web_and_commands": True, "tools": []},
            {"web_and_commands": False, "tools": ["web_search"]},
        ]
        for allowances in added:
            response = client.patch(f"/conversations/{conversation_id}", json={"allowances": allowances})
            assert_problem(response, 422, "request.validation_failed")
    # A request answered once allows nothing more, even when the answer asks for more.
    _, interrupt = asked(server, token, conversation_id, search(fresh_query()))
    assert_problem(
        resume(server, token, conversation_id, [approve(interrupt["id"], "always")]),
        422,
        "approval.invalid",
    )
