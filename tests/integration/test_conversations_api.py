"""Conversations through the API: create, list, open, rename, archive and delete (API-003)."""

from __future__ import annotations

import datetime
from typing import Any

import pytest

from tests.support.accounts import assert_problem, body, create_account, create_tenant, login
from tests.support.database import Database, uuid7
from tests.support.runs import create_conversation
from tests.support.server import Server


@pytest.fixture
def token(database: Database, server: Server) -> str:
    return login(server, create_account(database, create_tenant(database)))


def _list(server: Server, token: str, **params: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    cursor: str | None = None
    with server.client(token) as client:
        for _ in range(100):
            page = body(client.get("/conversations", params=params | ({"cursor": cursor} if cursor else {})))
            items += page["items"]
            cursor = page.get("next_cursor")
            if cursor is None:
                return items
    raise AssertionError("pagination does not end")


@pytest.mark.spec("API-003")
def test_conversations_are_created_untitled_or_with_a_title(server: Server, token: str) -> None:
    untitled = create_conversation(server, token)
    titled = create_conversation(server, token, "Holiday plans")
    assert untitled["title"] == ""
    assert titled["title"] == "Holiday plans"
    for conversation in (untitled, titled):
        assert conversation["archived"] is False
        assert conversation["active_run_id"] is None
        created = datetime.datetime.fromisoformat(conversation["created_at"])
        assert created.tzinfo is not None
        assert conversation["updated_at"] == conversation["created_at"]


@pytest.mark.spec("API-003")
def test_a_conversation_is_opened_by_its_id(server: Server, token: str) -> None:
    conversation = create_conversation(server, token, "Recipes")
    with server.client(token) as client:
        response = client.get(f"/conversations/{conversation['id']}")
    assert response.status_code == 200, response.text
    assert body(response) == conversation


@pytest.mark.spec("API-003")
def test_conversations_are_listed_most_recently_updated_first(server: Server, token: str) -> None:
    created = [create_conversation(server, token, f"Conversation {index}") for index in range(5)]
    with server.client(token) as client:
        renamed = body(client.patch(f"/conversations/{created[0]['id']}", json={"title": "Renamed"}))
    listed = _list(server, token, limit=2)
    assert [c["id"] for c in listed] == [renamed["id"], *[c["id"] for c in reversed(created[1:])]]


@pytest.mark.spec("API-003")
def test_conversations_are_renamed(server: Server, token: str) -> None:
    conversation = create_conversation(server, token)
    with server.client(token) as client:
        response = client.patch(f"/conversations/{conversation['id']}", json={"title": "Taxes 2026"})
    assert response.status_code == 200, response.text
    renamed = body(response)
    assert renamed["title"] == "Taxes 2026"
    assert renamed["updated_at"] >= conversation["updated_at"]


@pytest.mark.spec("API-003")
def test_archived_conversations_are_listed_apart(server: Server, token: str) -> None:
    kept, archived = create_conversation(server, token), create_conversation(server, token)
    with server.client(token) as client:
        assert body(client.patch(f"/conversations/{archived['id']}", json={"archived": True}))["archived"] is True
    assert [c["id"] for c in _list(server, token)] == [kept["id"]]
    assert [c["id"] for c in _list(server, token, archived="true")] == [archived["id"]]
    with server.client(token) as client:
        assert body(client.patch(f"/conversations/{archived['id']}", json={"archived": False}))["archived"] is False
    assert {c["id"] for c in _list(server, token)} == {kept["id"], archived["id"]}


@pytest.mark.spec("API-003")
def test_conversations_are_deleted(server: Server, token: str) -> None:
    conversation = create_conversation(server, token)
    with server.client(token) as client:
        assert client.delete(f"/conversations/{conversation['id']}").status_code == 204
        assert_problem(client.get(f"/conversations/{conversation['id']}"), 404, "resource.not_found")
        assert_problem(client.delete(f"/conversations/{conversation['id']}"), 404, "resource.not_found")
    assert _list(server, token) == []


@pytest.mark.spec("API-003")
def test_unknown_conversations_are_not_found(server: Server, token: str) -> None:
    unknown = uuid7()
    with server.client(token) as client:
        assert_problem(client.get(f"/conversations/{unknown}"), 404, "resource.not_found")
        assert_problem(client.patch(f"/conversations/{unknown}", json={"title": "x"}), 404, "resource.not_found")
        assert_problem(client.get(f"/conversations/{unknown}/messages"), 404, "resource.not_found")


@pytest.mark.spec("API-003")
@pytest.mark.parametrize(
    ("method", "payload"),
    [
        ("POST", {"title": ""}),
        ("POST", {"title": "x" * 201}),
        ("POST", {"owner_id": "someone"}),
        ("PATCH", {}),
        ("PATCH", {"title": 7}),
    ],
    ids=["empty-title", "long-title", "unknown-field", "empty-change", "non-string-title"],
)
def test_invalid_conversation_requests_are_rejected(
    server: Server, token: str, method: str, payload: dict[str, Any]
) -> None:
    conversation = create_conversation(server, token)
    path = "/conversations" if method == "POST" else f"/conversations/{conversation['id']}"
    with server.client(token) as client:
        assert_problem(client.request(method, path, json=payload), 422, "request.validation_failed")


@pytest.mark.spec("API-003")
def test_a_new_conversation_has_no_messages(server: Server, token: str) -> None:
    conversation = create_conversation(server, token)
    with server.client(token) as client:
        page = body(client.get(f"/conversations/{conversation['id']}/messages"))
    assert (page["items"], page["runs"], page.get("next_cursor")) == ([], [], None)
